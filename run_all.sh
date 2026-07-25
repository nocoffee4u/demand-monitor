#!/usr/bin/env bash
# Runs the full demand-scan pipeline in order and prints the ranked report.
# Requires REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET env vars to be set first
# (see reddit_scan.py header for how to get them).
set -e
cd "$(dirname "$0")"

echo "== 1/4 Reddit scan =="
python3 reddit_scan.py

echo "== 2/4 Google Trends scan =="
python3 trends_scan.py

echo "== 3/4 Marketplace listing scan =="
python3 marketplace_scan.py

echo "== 4/4 Scoring & ranking =="
python3 score_demand.py

echo
echo "Done. See out/demand_report.csv for the full ranked list."
