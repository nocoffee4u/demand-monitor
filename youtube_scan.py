#!/usr/bin/env python3
"""Scan a small set of YouTube searches and emit demand signals.

The YouTube Data API search.list endpoint costs quota units per search, so this
scanner deliberately makes one small search per keyword and does not request
view counts. Use --out for a JSON array, or --emit-signals to append
schema-shaped JSONL lines for weekday hunt ingest.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


API_URL = "https://www.googleapis.com/youtube/v3/search"
# Tight Rad accessory / pain queries (quota: one search.list per keyword).
KEYWORDS = (
    "Rad Power display cover",
    "Rad e-bike display cover",
    "RadRunner phone mount",
    "Rad Power phone mount",
    "Rad Power charging port plug",
    "RadRunner fender install",
    "RadRunner front basket",
)
# Keep a signal only if title+description hits at least one of these
# (case-insensitive). Drops eyewear/optical glare and unrelated shorts.
RELEVANCE_TERMS = (
    "radrunner",
    "radwagon",
    "radcity",
    "radrover",
    "rad power",
    "ebike",
    "e-bike",
)
# Bare "rad" as a whole word (avoids matching "radar" / "radical" alone).
RELEVANCE_RAD_WORD = re.compile(r"\brad\b", re.IGNORECASE)
COMPLAINT_TERMS = (
    "annoy",
    "bad",
    "broken",
    "can't",
    "cannot",
    "doesn't",
    "difficult",
    "glare",
    "hate",
    "issue",
    "problem",
    "sun",
    "won't",
)
WISH_TERMS = (
    "add",
    "could use",
    "i want",
    "need",
    "should",
    "wish",
    "would like",
    "looking for",
)


def get_api_key():
    """Load .env when python-dotenv is installed, then read the environment."""
    if load_dotenv is not None:
        load_dotenv()
    return os.environ.get("YOUTUBE_API_KEY")


def is_relevant(title, description):
    """True when title+description looks Rad / e-bike related."""
    text = f"{title} {description}".lower()
    if any(term in text for term in RELEVANCE_TERMS):
        return True
    return bool(RELEVANCE_RAD_WORD.search(text))


def classify_kind(title, url):
    text = f"{title} {url}".lower()
    if any(term in text for term in COMPLAINT_TERMS):
        return "complaint"
    if any(term in text for term in WISH_TERMS):
        return "wish"
    return "other"


def keyword_tags(keyword):
    return [
        word
        for word in re.findall(r"[a-z0-9]+", keyword.lower())
        if word not in {"the", "and"}
    ]


def make_signal(item, keyword, observed_at):
    """Build a signal from fields returned by search.list only."""
    item_id = item.get("id") or {}
    snippet = item.get("snippet") or {}
    video_id = item_id.get("videoId")
    title = snippet.get("title")
    if not video_id or not title:
        return None

    channel_title = snippet.get("channelTitle") or ""
    published_at = snippet.get("publishedAt")
    description = snippet.get("description") or ""
    if not is_relevant(title, description):
        return None

    url = f"https://www.youtube.com/watch?v={video_id}"
    signal = {
        "id": f"youtube:{video_id}",
        "ts": observed_at,
        "source": "youtube",
        "role": "demand",
        "kind": classify_kind(title, url),
        "url": url,
        "product_key": None,
        "tags": sorted({"youtube", *keyword_tags(keyword)}),
        "summary": f"{title} ({channel_title})" if channel_title else title,
        "quote": description or title,
        "metrics": {
            "matched_keywords": [keyword],
            "channel_title": channel_title,
            "published_at": published_at,
            "video_id": video_id,
        },
        "raw_ref": url,
    }
    return signal


def scan(api_key, max_results=5):
    if requests is None:
        raise RuntimeError("Missing dependency: requests. Run: pip install -r requirements.txt")

    observed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    signals_by_video = {}
    errors = []
    searches_succeeded = 0
    dropped_irrelevant = 0

    for keyword in KEYWORDS:
        params = {
            "key": api_key,
            "part": "snippet",
            "q": keyword,
            "type": "video",
            "maxResults": max_results,
        }
        try:
            response = requests.get(API_URL, params=params, timeout=20)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            errors.append(f"{keyword}: {exc}")
            continue

        searches_succeeded += 1
        for item in payload.get("items", []):
            snippet = item.get("snippet") or {}
            title = snippet.get("title") or ""
            description = snippet.get("description") or ""
            # Count relevance drops before make_signal returns None for other reasons
            video_id = (item.get("id") or {}).get("videoId")
            if video_id and title and not is_relevant(title, description):
                dropped_irrelevant += 1
                continue
            signal = make_signal(item, keyword, observed_at)
            if signal is None:
                continue
            video_id = signal["metrics"]["video_id"]
            existing = signals_by_video.get(video_id)
            if existing is None:
                signals_by_video[video_id] = signal
                continue
            existing["metrics"]["matched_keywords"].append(keyword)
            existing["tags"] = sorted(set(existing["tags"] + keyword_tags(keyword)))

    signals = list(signals_by_video.values())
    return {
        "source": "youtube",
        "searches_attempted": len(KEYWORDS),
        "searches_succeeded": searches_succeeded,
        "max_results_per_search": max_results,
        "dropped_irrelevant": dropped_irrelevant,
        "signal_count": len(signals),
        "errors": errors,
        "signals": signals,
    }


def append_signals_jsonl(path, signals):
    """Append schema-shaped signal dicts as JSONL (weekday hunt ingest)."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as fh:
        for signal in signals:
            fh.write(json.dumps(signal, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        help="write signal-shaped dictionaries as a JSON array to this path",
    )
    parser.add_argument(
        "--emit-signals",
        metavar="PATH.jsonl",
        help="append schema-shaped signal lines to this JSONL path",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        choices=range(5, 11),
        default=5,
        help="results per search (5-10; default: 5)",
    )
    args = parser.parse_args()

    api_key = get_api_key()
    if not api_key:
        print(
            "ERROR: YOUTUBE_API_KEY is missing. Set it in .env or export it before running.",
            file=sys.stderr,
        )
        return 2

    try:
        summary = scan(api_key, max_results=args.max_results)
        if args.out:
            output_path = Path(args.out)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(summary["signals"], indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            summary["out"] = str(output_path)
        if args.emit_signals:
            append_signals_jsonl(args.emit_signals, summary["signals"])
            summary["emit_signals"] = str(Path(args.emit_signals))
    except (OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["searches_succeeded"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
