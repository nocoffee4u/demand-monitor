#!/usr/bin/env python3
"""
reddit_scan.py
---------------
Scans configured subreddits for mentions of each candidate product's keywords
and produces a demand signal: number of matching posts, total upvotes, and
total comment count over the configured lookback window.

SETUP (one-time):
  1. Go to https://www.reddit.com/prefs/apps
  2. Click "create another app...", choose type "script"
  3. Set redirect uri to http://localhost:8080 (unused but required)
  4. Copy the client ID (under the app name) and client secret
  5. Copy .env.example to .env and fill in the three values below, or
     export them as environment variables before running:
       export REDDIT_CLIENT_ID=xxxx
       export REDDIT_CLIENT_SECRET=xxxx
       export REDDIT_USER_AGENT="printshop-demand-scan/0.1 by u/yourusername"

USAGE:
  python3 reddit_scan.py --config config/products.yaml --out out/reddit_signal.csv

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
"""
import argparse
import csv
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import yaml

try:
    import praw
except ImportError:
    print("Missing dependency. Run: pip install -r requirements.txt")
    sys.exit(1)

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def get_reddit_client():
    client_id = os.environ.get("REDDIT_CLIENT_ID")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET")
    user_agent = os.environ.get("REDDIT_USER_AGENT", "printshop-demand-scan/0.1")

    if not client_id or not client_secret:
        print(
            "ERROR: Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET environment "
            "variables first. See the setup instructions at the top of this file."
        )
        sys.exit(1)

    return praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=user_agent,
    )


def scan(config_path, out_path, max_results_per_query=25):
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    reddit = get_reddit_client()
    lookback_days = cfg.get("reddit_lookback_days", 180)
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    subreddit_names = cfg["subreddits"]
    combined_sub = "+".join(subreddit_names)

    rows = []
    for product in cfg["products"]:
        name = product["name"]
        category = product.get("category", "")
        total_posts = 0
        total_score = 0
        total_comments = 0
        example_links = []

        for kw in product["keywords"]:
            try:
                subreddit = reddit.subreddit(combined_sub)
                for submission in subreddit.search(
                    kw, sort="new", time_filter="year", limit=max_results_per_query
                ):
                    created = datetime.fromtimestamp(
                        submission.created_utc, tz=timezone.utc
                    )
                    if created < cutoff:
                        continue
                    total_posts += 1
                    total_score += submission.score
                    total_comments += submission.num_comments
                    if len(example_links) < 3:
                        example_links.append(f"https://reddit.com{submission.permalink}")
            except Exception as e:
                print(f"  [warn] search failed for '{kw}': {e}")
            time.sleep(1.1)  # stay comfortably under rate limits

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

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nWrote {len(rows)} rows to {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/products.yaml")
    parser.add_argument("--out", default="out/reddit_signal.csv")
    args = parser.parse_args()
    scan(args.config, args.out)
