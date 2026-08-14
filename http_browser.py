"""
Optional Chrome-impersonated GET for Cloudflare *fingerprint* challenges.

Printables HTML search and Thangs HTML search are often blocked for the
stock Python TLS fingerprint (JA3). curl_cffi can impersonate Chrome and
sometimes recovers those pages without browser automation.

Usage:
  - Prefer http_get_browser() for challenged HTML endpoints only.
  - Keep GraphQL / JSON APIs on plain requests (they are usually not challenged).
  - If curl_cffi is missing or still challenged → caller soft-fails (no invent).

Does not claim a permanent bypass; Turnstile/managed challenges may still win.
"""
from __future__ import annotations

import time
from typing import Any

import requests

# Impersonation profiles supported by curl_cffi vary by version; try a short list.
# "chrome" tracks the package default (e.g. chrome146). Older pins as fallback.
_CHROME_PROFILES = (
    "chrome",
    "chrome136",
    "chrome131",
    "chrome124",
    "chrome120",
)

try:
    from curl_cffi import requests as cffi_requests  # type: ignore

    _HAS_CURL_CFFI = True
except ImportError:  # pragma: no cover
    cffi_requests = None  # type: ignore
    _HAS_CURL_CFFI = False


def has_curl_cffi() -> bool:
    return bool(_HAS_CURL_CFFI)


def is_cloudflare_challenge(
    status_code: int,
    text: str | None,
    headers: dict | None = None,
) -> bool:
    """Detect Cloudflare managed challenge / interstitial pages."""
    # Strong signal from CF response headers (case-insensitive).
    if headers:
        for k, v in headers.items():
            if str(k).lower() == "cf-mitigated" and "challenge" in str(v).lower():
                return True

    body = (text or "")[:3000].lower()
    if status_code in (403, 503):
        if any(
            s in body
            for s in (
                "just a moment",
                "cf-browser-verification",
                "cf-mitigated",
                "cloudflare",
                "enable javascript and cookies",
                "checking your browser",
            )
        ):
            return True
    if "just a moment" in body and (
        "enable javascript" in body or "cloudflare" in body
    ):
        return True
    return False


class BrowserResponse:
    """Minimal response shim so callers can use .status_code / .text uniformly."""

    def __init__(self, status_code: int, text: str, headers: dict | None = None):
        self.status_code = status_code
        self.text = text or ""
        self.headers = headers or {}

    @classmethod
    def from_requests(cls, resp: requests.Response) -> "BrowserResponse":
        return cls(
            resp.status_code,
            resp.text or "",
            dict(resp.headers) if resp.headers else {},
        )


def _cffi_get(
    url: str,
    *,
    headers: dict | None,
    timeout: float,
    impersonate: str,
) -> BrowserResponse:
    assert cffi_requests is not None
    resp = cffi_requests.get(
        url,
        headers=headers or {},
        timeout=timeout,
        impersonate=impersonate,
    )
    return BrowserResponse(
        resp.status_code,
        getattr(resp, "text", None) or "",
        dict(getattr(resp, "headers", {}) or {}),
    )


def http_get_browser(
    url: str,
    *,
    headers: dict | None = None,
    timeout: float = 25.0,
    retries: int = 2,
    session: requests.Session | None = None,
) -> BrowserResponse:
    """
    GET HTML with optional Chrome TLS impersonation.

    Order:
      1) curl_cffi Chrome impersonation (if installed)
      2) plain requests (session or module) as fallback

    Retries only transient 429/5xx. A Cloudflare challenge (403/503 interstitial)
    is returned immediately — callers soft-fail; do not spin forever.
    """
    last_err: Exception | None = None

    # --- Prefer curl_cffi when available ---------------------------------
    if _HAS_CURL_CFFI:
        last_challenge: BrowserResponse | None = None
        for profile in _CHROME_PROFILES:
            for attempt in range(max(1, retries)):
                try:
                    br = _cffi_get(
                        url,
                        headers=headers,
                        timeout=timeout,
                        impersonate=profile,
                    )
                    if is_cloudflare_challenge(br.status_code, br.text, br.headers):
                        # Managed CF: fingerprint can differ by profile —
                        # try next once each. Do not spin forever.
                        last_challenge = br
                        break
                    if br.status_code == 403:
                        # Non-CF 403 — no multi-profile storm
                        return br
                    if br.status_code in (429, 502, 503, 504):
                        sleep_s = min(45.0, (2**attempt) * 2.0)
                        time.sleep(sleep_s)
                        last_err = RuntimeError(f"HTTP {br.status_code}")
                        continue
                    # Success (or non-retryable non-CF error) — return to caller
                    return br
                except Exception as e:  # network / curl errors
                    last_err = e
                    time.sleep(min(20.0, (2**attempt) * 1.5))
            # try next impersonation profile
        if last_challenge is not None:
            return last_challenge
        # Fall through to requests if all cffi attempts failed hard

    # --- Fallback: stock requests ----------------------------------------
    getter = session.get if session is not None else requests.get
    for attempt in range(max(1, retries)):
        try:
            resp = getter(url, headers=headers or {}, timeout=timeout)
            br = BrowserResponse.from_requests(resp)
            if br.status_code in (429, 502, 503, 504) and not is_cloudflare_challenge(
                br.status_code, br.text, br.headers
            ):
                sleep_s = min(45.0, (2**attempt) * 2.0)
                time.sleep(sleep_s)
                last_err = RuntimeError(f"HTTP {br.status_code}")
                continue
            return br
        except requests.RequestException as e:
            last_err = e
            time.sleep(min(20.0, (2**attempt) * 1.5))

    raise RuntimeError(f"browser GET failed after retries: {last_err}")


def cloudflare_softfail_message(site: str, *, used_cffi: bool | None = None) -> str:
    """Consistent note text for soft-fail paths."""
    cffi = has_curl_cffi() if used_cffi is None else used_cffi
    if cffi:
        return (
            f"{site} HTTP 403/challenge (Cloudflare — still blocked with "
            f"curl_cffi Chrome impersonation; soft-fail this source)"
        )
    return (
        f"{site} HTTP 403/challenge (Cloudflare fingerprint — install "
        f"curl_cffi for optional Chrome impersonation; soft-fail this source)"
    )
