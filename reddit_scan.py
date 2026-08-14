#!/usr/bin/env python3
"""
reddit_scan.py
---------------
Scans configured subreddits for mentions of each candidate product's keywords
and produces a demand signal: number of matching posts, total upvotes, and
total comment count over the configured lookback window.

BACKENDS
  pullpush  (default) — free historical Reddit search via https://pullpush.io
                        No Reddit OAuth / API approval required.
  praw      — official Reddit API via PRAW. Requires approved credentials.

USAGE:
  python3 reddit_scan.py
  python3 reddit_scan.py --backend pullpush
  python3 reddit_scan.py --backend praw
  python3 reddit_scan.py --write-empty   # zeros only (weekly pipeline default)
  python3 reddit_scan.py --backend pullpush --config config/products.yaml \\
      --out out/reddit_signal.csv

  Weekly pipeline: Reddit is OFF by default. Opt in with:
    INCLUDE_REDDIT=1 ./run_all.sh

SETUP — pullpush (manual / opt-in, no credentials):
  Uses the public PullPush submission search API. Often flaky (429 / lag).
  CAVEATS:
    - Volunteer archive; uptime and freshness vary. The index can lag live
      Reddit by weeks or months. This script probes the archive tip and, if
      the tip is older than your lookback window, scores the most recent
      lookback_days of *indexed* data instead so relative rankings still work.
    - Rate-limit politely (default ~1.2s between requests). Not for tight loops.
    - Not an official Reddit product; research stopgap only.

SETUP — praw (official Reddit API — approval-gated, not self-serve):
  Unauthenticated reddit.com/.json endpoints are effectively dead for bulk use.
  Official API access requires Reddit approval under the Responsible Builder
  Policy (manual review; not a quick self-serve signup). After approval:
  1. Create a "script" app at https://www.reddit.com/prefs/apps
  2. Redirect URI: http://localhost:8080 (required field, unused)
  3. Copy .env.example to .env and fill in:
       REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET / REDDIT_USER_AGENT
  4. Run: python3 reddit_scan.py --backend praw

NOTES ON REDDIT'S TERMS (read before scaling this up):
  - Reddit's free API tier is ~100 queries/minute (OAuth) and is intended for
    non-commercial / personal use. This script runs well within that limit if
    you run it on a schedule (e.g. weekly) rather than continuously polling.
  - Reddit's terms state commercial use of its Data API requires a paid
    contract. Using this script to privately inform YOUR OWN sourcing
    decisions (not reselling Reddit data, not building a public product on
    top of it) is the common/accepted hobbyist-research pattern, but it is
    not a substitute for legal advice. If you scale to querying many
    subreddits many times a day, budget for Reddit's paid tier
    ($0.24 / 1,000 calls) or switch to manual spot-checks.
  - PullPush is a third-party archive of public posts; its own availability
    and terms apply separately from Reddit's Data API.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests
import yaml

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

PULLPUSH_SUBMISSION_URL = "https://api.pullpush.io/reddit/search/submission/"
# PullPush is a shared volunteer service and 429s aggressively under burst load.
# ~3s between calls keeps a full weekly product scan under the limit in practice.
DEFAULT_REQUEST_DELAY_S = 3.0
PULLPUSH_MAX_RETRIES = 6
# Extra days beyond lookback when the tip probe fails — captures lagged archives
# so client-side re-windowing still has data to work with.
PULLPUSH_LAG_BUFFER_DAYS = 540
USER_AGENT = "printshop-demand-scan/0.2 (+local research; pullpush/praw)"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def load_config(config_path: str) -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


def write_rows(rows: list[dict], out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    fieldnames = [
        "product",
        "category",
        "reddit_matching_posts",
        "reddit_total_upvotes",
        "reddit_total_comments",
        "reddit_example_links",
    ]
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nWrote {len(rows)} rows to {out_path}")


def empty_product_row(name: str, category: str) -> dict:
    return {
        "product": name,
        "category": category,
        "reddit_matching_posts": 0,
        "reddit_total_upvotes": 0,
        "reddit_total_comments": 0,
        "reddit_example_links": "",
    }


def permalink_to_url(permalink: str | None, fallback_id: str | None = None) -> str | None:
    if permalink:
        if permalink.startswith("http"):
            return permalink
        return f"https://www.reddit.com{permalink}"
    if fallback_id:
        return f"https://www.reddit.com/comments/{fallback_id}"
    return None


# ---------------------------------------------------------------------------
# PRAW backend (official Reddit API)
# ---------------------------------------------------------------------------

def get_praw_client():
    try:
        import praw
    except ImportError:
        print("Missing dependency for --backend praw. Run: pip install -r requirements.txt")
        sys.exit(1)

    client_id = os.environ.get("REDDIT_CLIENT_ID")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET")
    user_agent = os.environ.get("REDDIT_USER_AGENT", USER_AGENT)

    if not client_id or not client_secret:
        print(
            "ERROR: --backend praw requires REDDIT_CLIENT_ID and "
            "REDDIT_CLIENT_SECRET. Copy .env.example to .env, or use "
            "--backend pullpush (default) which needs no credentials."
        )
        sys.exit(1)

    return praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=user_agent,
    )


def scan_praw(cfg: dict, max_results_per_query: int, delay_s: float) -> list[dict]:
    reddit = get_praw_client()
    lookback_days = cfg.get("reddit_lookback_days", 180)
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    subreddit_names = cfg["subreddits"]
    combined_sub = "+".join(subreddit_names)

    print(
        f"Backend: praw | lookback: {lookback_days}d | "
        f"subreddits: {len(subreddit_names)} | products: {len(cfg['products'])}"
    )

    rows = []
    for product in cfg["products"]:
        name = product["name"]
        category = product.get("category", "")
        total_posts = 0
        total_score = 0
        total_comments = 0
        example_links: list[str] = []
        seen_ids: set[str] = set()

        for kw in product["keywords"]:
            try:
                subreddit = reddit.subreddit(combined_sub)
                for submission in subreddit.search(
                    kw, sort="new", time_filter="year", limit=max_results_per_query
                ):
                    if submission.id in seen_ids:
                        continue
                    created = datetime.fromtimestamp(
                        submission.created_utc, tz=timezone.utc
                    )
                    if created < cutoff:
                        continue
                    seen_ids.add(submission.id)
                    total_posts += 1
                    total_score += submission.score
                    total_comments += submission.num_comments
                    if len(example_links) < 3:
                        example_links.append(
                            f"https://www.reddit.com{submission.permalink}"
                        )
            except Exception as e:
                print(f"  [warn] praw search failed for '{kw}': {e}")
            time.sleep(delay_s)

        rows.append(
            {
                "product": name,
                "category": category,
                "reddit_matching_posts": total_posts,
                "reddit_total_upvotes": total_score,
                "reddit_total_comments": total_comments,
                "reddit_example_links": " | ".join(example_links),
            }
        )
        print(f"  scanned: {name} -> {total_posts} posts, {total_score} upvotes")

    return rows


# ---------------------------------------------------------------------------
# PullPush backend (no Reddit OAuth)
# ---------------------------------------------------------------------------

def _error_message(resp: requests.Response) -> str:
    ctype = (resp.headers.get("Content-Type") or "").lower()
    text = (resp.text or "").strip()
    if "html" in ctype or text[:15].lower().startswith("<!doctype") or text[:6].lower().startswith("<html"):
        return f"(HTML error page, {len(text)} bytes)"
    try:
        payload = resp.json()
        if isinstance(payload, dict) and payload.get("error"):
            return str(payload["error"])
    except Exception:
        pass
    return text[:200]


def pullpush_get(
    params: dict,
    timeout: int = 30,
    max_retries: int = PULLPUSH_MAX_RETRIES,
) -> list[dict]:
    """
    GET PullPush submission search with retries on 429 / transient 5xx.
    Returns the `data` list, or raises RuntimeError on permanent failure.
    """
    headers = {"User-Agent": USER_AGENT}
    last_err: str | None = None

    for attempt in range(max_retries):
        try:
            resp = requests.get(
                PULLPUSH_SUBMISSION_URL,
                params=params,
                headers=headers,
                timeout=timeout,
            )
        except requests.RequestException as e:
            last_err = str(e)
            sleep_s = min(90.0, (2**attempt) * 3.0)
            print(
                f"  [warn] pullpush network error (attempt {attempt + 1}/"
                f"{max_retries}): {e}; sleeping {sleep_s:.0f}s"
            )
            time.sleep(sleep_s)
            continue

        if resp.status_code in (429, 502, 503, 504):
            # 429 = rate limit; 502/503/504 often mean the shared service is
            # overloaded or fronted by a temporary block. Short sleeps just
            # re-trigger failures — back off hard.
            retry_after = resp.headers.get("Retry-After")
            try:
                sleep_s = float(retry_after) if retry_after else 45.0 * (attempt + 1)
            except ValueError:
                sleep_s = 45.0 * (attempt + 1)
            sleep_s = min(max(sleep_s, 30.0), 180.0)
            last_err = f"HTTP {resp.status_code}: {_error_message(resp)}"
            label = "rate limited" if resp.status_code == 429 else f"HTTP {resp.status_code}"
            print(
                f"  [warn] pullpush {label} (attempt {attempt + 1}/"
                f"{max_retries}); sleeping {sleep_s:.0f}s"
            )
            time.sleep(sleep_s)
            continue

        if resp.status_code >= 500:
            last_err = f"HTTP {resp.status_code}: {_error_message(resp)}"
            sleep_s = min(90.0, (2**attempt) * 5.0)
            print(
                f"  [warn] pullpush HTTP {resp.status_code} (attempt {attempt + 1}/"
                f"{max_retries}); sleeping {sleep_s:.0f}s"
            )
            time.sleep(sleep_s)
            continue

        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {_error_message(resp)}")

        try:
            payload = resp.json()
        except ValueError as e:
            raise RuntimeError(f"non-JSON response: {resp.text[:120]}") from e
        if isinstance(payload, dict) and payload.get("error"):
            raise RuntimeError(str(payload["error"]))
        data = payload.get("data") if isinstance(payload, dict) else None
        return data or []

    raise RuntimeError(f"unavailable after retries: {last_err}")


def probe_pullpush_archive_tip(subreddits: list[str], delay_s: float) -> datetime | None:
    """
    Find the newest created_utc PullPush currently serves for our niche.
    Used to detect archive lag and shift the lookback window if needed.
    """
    # One probe only — keep rate-limit headroom for the real product queries.
    preferred = ("MTB", "ebikes", "fpv", "3Dprinting")
    probe_sub = next((s for s in preferred if s in subreddits), None)
    if probe_sub is None and subreddits:
        probe_sub = subreddits[0]
    if probe_sub is None:
        return None

    try:
        # Few retries: if the shared bucket is empty, fall back quickly and let
        # the product scan recover with longer 429 backoffs.
        data = pullpush_get(
            {
                "q": "bike OR drone OR print",
                "subreddit": probe_sub,
                "size": 5,
                "sort": "desc",
                "sort_type": "created_utc",
            },
            max_retries=2,
        )
        newest: datetime | None = None
        for post in data:
            cu = post.get("created_utc")
            if cu is None:
                continue
            created = datetime.fromtimestamp(float(cu), tz=timezone.utc)
            if newest is None or created > newest:
                newest = created
        time.sleep(delay_s)
        return newest
    except Exception as e:
        print(f"  [warn] archive tip probe failed for r/{probe_sub}: {e}")
        time.sleep(delay_s)
        return None


def resolve_lookback_window(
    lookback_days: int, archive_tip: datetime | None
) -> tuple[datetime, datetime, str]:
    """
    Returns (window_start, window_end, note).
    If the archive tip is older than lookback_days from now, score the most
    recent lookback_days of *indexed* data so rankings stay meaningful.
    If the tip probe failed, open a wide fetch window (lookback + lag buffer)
    ending now; posts are still filtered client-side to lookback_days of the
    newest post actually returned in the run when possible via
    `tighten_window_to_results`.
    """
    now = datetime.now(timezone.utc)
    live_start = now - timedelta(days=lookback_days)

    if archive_tip is None:
        wide_start = now - timedelta(days=lookback_days + PULLPUSH_LAG_BUFFER_DAYS)
        return wide_start, now, (
            f"lookback: wide fetch last {lookback_days + PULLPUSH_LAG_BUFFER_DAYS}d "
            f"(tip probe failed; will re-window to newest {lookback_days}d of hits)"
        )

    lag = now - archive_tip
    lag_days = lag.total_seconds() / 86400

    if archive_tip >= live_start:
        # Archive is fresh enough that live lookback is usable.
        note = (
            f"lookback: last {lookback_days}d ending now | "
            f"archive tip ~{archive_tip.date()} ({lag_days:.0f}d lag)"
        )
        return live_start, now, note

    # Archive is stale: slide the window to end at the tip.
    window_end = archive_tip
    window_start = archive_tip - timedelta(days=lookback_days)
    note = (
        f"lookback: last {lookback_days}d of INDEXED data "
        f"({window_start.date()} → {window_end.date()}) | "
        f"archive lag ~{lag_days:.0f}d — relative rankings still useful; "
        f"switch to --backend praw when API access is approved"
    )
    return window_start, window_end, note


def tighten_window_to_results(
    rows_posts: list[list[dict]],
    lookback_days: int,
    window_start: datetime,
    window_end: datetime,
    tip_known: bool,
) -> tuple[datetime, datetime, list[list[dict]]]:
    """
    When the archive tip was unknown, re-window all collected posts to the
    newest lookback_days relative to the newest post seen in this run.
    `rows_posts` is a list (per product) of raw post dicts with created_utc.
    """
    if tip_known:
        return window_start, window_end, rows_posts

    newest: datetime | None = None
    for posts in rows_posts:
        for post in posts:
            cu = post.get("created_utc")
            if cu is None:
                continue
            created = datetime.fromtimestamp(float(cu), tz=timezone.utc)
            if newest is None or created > newest:
                newest = created

    if newest is None:
        return window_start, window_end, rows_posts

    new_end = newest
    new_start = newest - timedelta(days=lookback_days)
    tightened: list[list[dict]] = []
    for posts in rows_posts:
        kept = []
        for post in posts:
            cu = post.get("created_utc")
            if cu is None:
                continue
            created = datetime.fromtimestamp(float(cu), tz=timezone.utc)
            if new_start <= created <= new_end:
                kept.append(post)
        tightened.append(kept)
    return new_start, new_end, tightened


def _aggregate_posts(posts: list[dict]) -> tuple[int, int, int, list[str]]:
    """Deduped posts → (count, total_score, total_comments, example_links)."""
    seen: set[str] = set()
    total_score = 0
    total_comments = 0
    example_links: list[str] = []
    for post in posts:
        post_id = post.get("id")
        if not post_id or post_id in seen:
            continue
        seen.add(post_id)
        total_score += int(post.get("score") or 0)
        total_comments += int(post.get("num_comments") or 0)
        if len(example_links) < 3:
            url = permalink_to_url(post.get("permalink"), post_id)
            if url:
                example_links.append(url)
    return len(seen), total_score, total_comments, example_links


def scan_pullpush(
    cfg: dict,
    max_results_per_query: int,
    delay_s: float,
    per_subreddit: bool,
) -> list[dict]:
    lookback_days = cfg.get("reddit_lookback_days", 180)
    subreddit_names = list(cfg["subreddits"])
    subreddit_set = {s.lower() for s in subreddit_names}
    products = cfg["products"]

    print(
        f"Backend: pullpush | products: {len(products)} | "
        f"subreddits: {len(subreddit_names)} | "
        f"mode: {'per-subreddit' if per_subreddit else 'global+filter'} | "
        f"delay: {delay_s}s"
    )
    print("Probing PullPush archive tip…")
    archive_tip = probe_pullpush_archive_tip(subreddit_names, delay_s)
    tip_known = archive_tip is not None
    window_start, window_end, window_note = resolve_lookback_window(
        lookback_days, archive_tip
    )
    print(f"  {window_note}")
    after_epoch = int(window_start.timestamp())
    before_epoch = int(window_end.timestamp())

    # Collect raw posts first so we can re-window if the tip probe failed.
    per_product_posts: list[list[dict]] = []
    product_meta: list[tuple[str, str]] = []
    consecutive_failures = 0
    # Bail out if the archive is clearly down rather than burning 20+ minutes
    # on retries that all return 502/429.
    circuit_breaker_limit = 5
    aborted_early = False

    for product in products:
        name = product["name"]
        category = product.get("category", "")
        product_meta.append((name, category))
        collected: list[dict] = []
        seen_ids: set[str] = set()

        if aborted_early:
            per_product_posts.append(collected)
            print(f"  skipped: {name} (PullPush unavailable — circuit open)")
            continue

        for kw in product["keywords"]:
            if aborted_early:
                break

            queries: list[dict] = []
            if per_subreddit:
                for sub in subreddit_names:
                    queries.append(
                        {
                            "q": kw,
                            "subreddit": sub,
                            "size": max_results_per_query,
                            "after": str(after_epoch),
                            "before": str(before_epoch),
                            "sort": "desc",
                            "sort_type": "created_utc",
                        }
                    )
            else:
                # One global query per keyword, then keep only configured subs.
                # Better for specific product keywords; undercounts very generic
                # terms if non-niche hits fill the result page. Use
                # --per-subreddit for thorough (slower) coverage.
                queries.append(
                    {
                        "q": kw,
                        "size": max(max_results_per_query, 100),
                        "after": str(after_epoch),
                        "before": str(before_epoch),
                        "sort": "desc",
                        "sort_type": "created_utc",
                    }
                )

            for params in queries:
                try:
                    data = pullpush_get(params)
                    consecutive_failures = 0
                except Exception as e:
                    consecutive_failures += 1
                    sub_label = params.get("subreddit", "*")
                    print(
                        f"  [warn] pullpush search failed for '{kw}' "
                        f"(r/{sub_label}): {e}"
                    )
                    if consecutive_failures >= circuit_breaker_limit:
                        aborted_early = True
                        print(
                            f"\n[warn] PullPush failed {consecutive_failures} "
                            "queries in a row — opening circuit breaker and "
                            "writing partial results. Wait a few minutes and "
                            "re-run (try --delay 5)."
                        )
                        break
                    time.sleep(delay_s)
                    continue

                for post in data:
                    post_id = post.get("id")
                    if not post_id or post_id in seen_ids:
                        continue

                    sub = (post.get("subreddit") or "").lower()
                    if not per_subreddit and sub not in subreddit_set:
                        continue

                    cu = post.get("created_utc")
                    if cu is not None:
                        created = datetime.fromtimestamp(float(cu), tz=timezone.utc)
                        if created < window_start or created > window_end:
                            continue

                    seen_ids.add(post_id)
                    collected.append(post)

                time.sleep(delay_s)

        per_product_posts.append(collected)
        print(f"  fetched: {name} -> {len(collected)} raw posts (pre-final-window)")

    window_start, window_end, per_product_posts = tighten_window_to_results(
        per_product_posts,
        lookback_days,
        window_start,
        window_end,
        tip_known=tip_known,
    )
    if not tip_known:
        print(
            f"  re-windowed to newest {lookback_days}d of hits: "
            f"{window_start.date()} → {window_end.date()}"
        )

    rows = []
    for (name, category), posts in zip(product_meta, per_product_posts):
        total_posts, total_score, total_comments, example_links = _aggregate_posts(
            posts
        )
        rows.append(
            {
                "product": name,
                "category": category,
                "reddit_matching_posts": total_posts,
                "reddit_total_upvotes": total_score,
                "reddit_total_comments": total_comments,
                "reddit_example_links": " | ".join(example_links),
            }
        )
        print(f"  scanned: {name} -> {total_posts} posts, {total_score} upvotes")

    if rows and all(r["reddit_matching_posts"] == 0 for r in rows):
        print(
            "\n[warn] Every product scored 0 matching posts. Common causes:\n"
            "  - PullPush rate limit / outage (wait a few minutes and re-run)\n"
            "  - Archive lag beyond the fetch buffer\n"
            "  - Keywords too specific for the indexed window\n"
            "  - Configured subreddit names don't match archive names\n"
            "  Try: --delay 5, --per-subreddit, broader keywords, or --backend praw"
        )

    return rows


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

def scan(
    config_path: str,
    out_path: str,
    backend: str = "pullpush",
    max_results_per_query: int = 25,
    delay_s: float = DEFAULT_REQUEST_DELAY_S,
    per_subreddit: bool = False,
) -> None:
    cfg = load_config(config_path)
    if not cfg.get("products"):
        print("ERROR: no products in config")
        sys.exit(1)
    if not cfg.get("subreddits"):
        print("ERROR: no subreddits in config")
        sys.exit(1)

    if backend == "praw":
        rows = scan_praw(cfg, max_results_per_query, delay_s)
    elif backend == "pullpush":
        rows = scan_pullpush(cfg, max_results_per_query, delay_s, per_subreddit)
    else:
        print(f"ERROR: unknown backend '{backend}' (use pullpush or praw)")
        sys.exit(1)

    if not rows:
        # Still write a header-only-ish empty product list for pipeline stability
        rows = [
            empty_product_row(p["name"], p.get("category", ""))
            for p in cfg["products"]
        ]

    write_rows(rows, out_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Scan Reddit demand signals for candidate 3D-printed products."
    )
    parser.add_argument("--config", default="config/products.yaml")
    parser.add_argument("--out", default="out/reddit_signal.csv")
    parser.add_argument(
        "--backend",
        choices=("pullpush", "praw"),
        default="pullpush",
        help="Data source. pullpush needs no credentials (default). "
        "praw uses the official Reddit API when approved.",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=25,
        help="Max results per query (praw) or per subreddit query "
        "(pullpush --per-subreddit). Global pullpush mode uses max(this, 100).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_REQUEST_DELAY_S,
        help=f"Seconds between API requests (default {DEFAULT_REQUEST_DELAY_S}).",
    )
    parser.add_argument(
        "--per-subreddit",
        action="store_true",
        help="PullPush only: query each subreddit separately (slower, more "
        "thorough for generic keywords).",
    )
    parser.add_argument(
        "--write-empty",
        action="store_true",
        help="Write zeroed rows for every product (no network). Used when the "
        "weekly pipeline skips Reddit so scoring redistributes cleanly.",
    )
    args = parser.parse_args()
    if args.write_empty:
        cfg = load_config(args.config)
        products = cfg.get("products") or []
        if not products:
            print("ERROR: no products in config")
            sys.exit(1)
        rows = [
            empty_product_row(p["name"], p.get("category", ""))
            for p in products
        ]
        write_rows(rows, args.out)
        print("Reddit signal empty (skipped / --write-empty); scoring will redistribute.")
        sys.exit(0)
    scan(
        config_path=args.config,
        out_path=args.out,
        backend=args.backend,
        max_results_per_query=args.max_results,
        delay_s=args.delay,
        per_subreddit=args.per_subreddit,
    )
