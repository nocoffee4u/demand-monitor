#!/usr/bin/env python3
"""
wait_for_pullpush.py
--------------------
Polls the PullPush API until it responds successfully, then runs the Reddit
demand scan (or the full pipeline). Use this when PullPush is rate-limiting
or returning 502s and you don't want to babysit re-runs.

USAGE:
  # Wait until healthy, then run reddit_scan.py (PullPush backend)
  python3 wait_for_pullpush.py

  # Health check only (exit 0 = healthy, 1 = not ready / timed out)
  python3 wait_for_pullpush.py --check-only

  # Wait, then run the full demand pipeline
  python3 wait_for_pullpush.py --full-pipeline

  # Tune polling / timeout
  python3 wait_for_pullpush.py --interval 60 --timeout 3600 --delay 5

  # Pass extra args through to reddit_scan.py (after --)
  python3 wait_for_pullpush.py -- --delay 5 --per-subreddit

  # Skip the scan and only wait (useful in shell scripts)
  python3 wait_for_pullpush.py --wait-only
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

import requests

PULLPUSH_SUBMISSION_URL = "https://api.pullpush.io/reddit/search/submission/"
USER_AGENT = "printshop-demand-scan/0.2 (+wait_for_pullpush)"
# Tiny query — just enough to prove the search endpoint is serving JSON.
PROBE_PARAMS = {
    "q": "bike",
    "subreddit": "MTB",
    "size": 1,
    "sort": "desc",
    "sort_type": "created_utc",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def probe_pullpush(timeout: float = 20.0) -> tuple[bool, str]:
    """
    Returns (healthy, detail). Healthy means HTTP 200 + parseable JSON with a
    `data` list (empty list still counts as healthy — the API is up).
    """
    try:
        resp = requests.get(
            PULLPUSH_SUBMISSION_URL,
            params=PROBE_PARAMS,
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
        )
    except requests.RequestException as e:
        return False, f"network error: {e}"

    if resp.status_code in (429, 502, 503, 504):
        return False, f"HTTP {resp.status_code} (unavailable / rate limited)"

    if resp.status_code != 200:
        body = (resp.text or "")[:120].replace("\n", " ")
        return False, f"HTTP {resp.status_code}: {body}"

    try:
        payload = resp.json()
    except ValueError:
        return False, "HTTP 200 but non-JSON body"

    if not isinstance(payload, dict):
        return False, f"unexpected JSON type: {type(payload).__name__}"

    if "error" in payload and payload["error"]:
        return False, f"API error: {payload['error']}"

    if "data" not in payload:
        return False, f"JSON missing 'data' key (keys={list(payload.keys())[:6]})"

    n = len(payload.get("data") or [])
    return True, f"HTTP 200, data[{n}]"


def wait_until_healthy(
    interval_s: float,
    timeout_s: float,
    max_interval_s: float,
    probe_timeout_s: float,
) -> bool:
    """
    Poll until healthy or timeout. Interval grows after consecutive failures
    (capped at max_interval_s) so we don't hammer a struggling service.
    """
    deadline = time.monotonic() + timeout_s if timeout_s > 0 else None
    attempt = 0
    current_interval = interval_s

    print(f"[{utc_now()}] Probing PullPush at {PULLPUSH_SUBMISSION_URL}")
    if timeout_s > 0:
        print(f"  timeout: {timeout_s:.0f}s | start interval: {interval_s:.0f}s "
              f"(max {max_interval_s:.0f}s)")
    else:
        print(f"  timeout: none (run until healthy) | start interval: {interval_s:.0f}s")

    while True:
        attempt += 1
        healthy, detail = probe_pullpush(timeout=probe_timeout_s)
        if healthy:
            print(f"[{utc_now()}] PullPush healthy on attempt {attempt}: {detail}")
            return True

        remaining = None
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                print(
                    f"[{utc_now()}] Timed out after {attempt} attempts "
                    f"(last: {detail})"
                )
                return False

        sleep_s = current_interval
        if remaining is not None:
            sleep_s = min(sleep_s, max(remaining, 0.0))

        print(
            f"[{utc_now()}] not ready (attempt {attempt}): {detail} — "
            f"retry in {sleep_s:.0f}s"
            + (f" ({remaining:.0f}s left)" if remaining is not None else "")
        )
        time.sleep(sleep_s)

        # Back off gradually so a multi-hour outage doesn't mean a request
        # every 30s forever.
        current_interval = min(current_interval * 1.5, max_interval_s)


def run_command(cmd: list[str], env: dict | None = None) -> int:
    print(f"[{utc_now()}] Running: {' '.join(cmd)}")
    completed = subprocess.run(cmd, env=env)
    return int(completed.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Wait until PullPush is healthy, then run the Reddit demand scan "
            "(or the full pipeline)."
        )
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=45.0,
        help="Seconds between health probes at the start (default 45).",
    )
    parser.add_argument(
        "--max-interval",
        type=float,
        default=300.0,
        help="Cap on backoff between probes in seconds (default 300).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=3600.0,
        help="Give up after this many seconds (default 3600). Use 0 to wait forever.",
    )
    parser.add_argument(
        "--probe-timeout",
        type=float,
        default=20.0,
        help="HTTP timeout for each health probe in seconds (default 20).",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Probe once and exit 0 if healthy, 1 otherwise (no wait loop).",
    )
    parser.add_argument(
        "--wait-only",
        action="store_true",
        help="Wait until healthy, then exit without running a scan.",
    )
    parser.add_argument(
        "--full-pipeline",
        action="store_true",
        help="After healthy, run ./run_all.sh instead of just reddit_scan.py.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=5.0,
        help=(
            "Default --delay passed to reddit_scan.py when not overridden "
            "after -- (default 5 for a safer full scan)."
        ),
    )
    parser.add_argument(
        "scan_args",
        nargs=argparse.REMAINDER,
        help="Args after -- are forwarded to reddit_scan.py "
        "(ignored with --full-pipeline / --wait-only / --check-only).",
    )
    args = parser.parse_args()

    # argparse includes the bare '--' in REMAINDER when present
    scan_args = list(args.scan_args)
    if scan_args and scan_args[0] == "--":
        scan_args = scan_args[1:]

    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    if args.check_only:
        healthy, detail = probe_pullpush(timeout=args.probe_timeout)
        status = "healthy" if healthy else "not ready"
        print(f"[{utc_now()}] PullPush {status}: {detail}")
        return 0 if healthy else 1

    if not wait_until_healthy(
        interval_s=args.interval,
        timeout_s=args.timeout,
        max_interval_s=args.max_interval,
        probe_timeout_s=args.probe_timeout,
    ):
        return 1

    if args.wait_only:
        return 0

    # Brief pause after the successful probe so the health-check request
    # doesn't immediately compete with the scan for the rate-limit bucket.
    cool_down = min(10.0, max(args.interval * 0.25, 3.0))
    print(f"[{utc_now()}] Cooling down {cool_down:.0f}s before scan…")
    time.sleep(cool_down)

    if args.full_pipeline:
        env = os.environ.copy()
        env.setdefault("REDDIT_BACKEND", "pullpush")
        return run_command(["bash", "./run_all.sh"], env=env)

    # Prefer the project venv interpreter when present so cron/scripts work
    # without an activated shell.
    venv_python = os.path.join(script_dir, "venv", "bin", "python3")
    python = venv_python if os.path.isfile(venv_python) else sys.executable

    cmd = [python, "reddit_scan.py", "--backend", "pullpush"]
    # If the caller didn't pass --delay themselves, use a safer default for
    # full product lists after a recovery wait.
    if not any(a == "--delay" or a.startswith("--delay=") for a in scan_args):
        cmd.extend(["--delay", str(args.delay)])
    cmd.extend(scan_args)
    return run_command(cmd)


if __name__ == "__main__":
    sys.exit(main())
