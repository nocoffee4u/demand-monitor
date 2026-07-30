#!/usr/bin/env bash
# Runs the full demand-scan pipeline in order and prints the ranked report.
#
# Reddit scan defaults to the PullPush backend (no credentials). To use the
# official Reddit API once approved:
#   REDDIT_BACKEND=praw ./run_all.sh
# and set REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET (see reddit_scan.py).
#
# If PullPush is flaky, wait until healthy first:
#   WAIT_FOR_PULLPUSH=1 ./run_all.sh
#   # or: python3 wait_for_pullpush.py --full-pipeline
set -e
cd "$(dirname "$0")"

REDDIT_BACKEND="${REDDIT_BACKEND:-pullpush}"

if [[ "${WAIT_FOR_PULLPUSH:-0}" == "1" && "${REDDIT_BACKEND}" == "pullpush" ]]; then
  echo "== 0/4 Waiting for PullPush to be healthy =="
  python3 wait_for_pullpush.py --wait-only
fi

echo "== 1/4 Reddit scan (backend: ${REDDIT_BACKEND}) =="
if [[ "${REDDIT_BACKEND}" == "pullpush" ]]; then
  python3 reddit_scan.py --backend pullpush --delay "${REDDIT_DELAY:-5}"
else
  python3 reddit_scan.py --backend "${REDDIT_BACKEND}"
fi

echo "== 2/4 Google Trends scan =="
python3 trends_scan.py

echo "== 3/4 Marketplace listing scan =="
python3 marketplace_scan.py

echo "== 4/4 Scoring & ranking =="
python3 score_demand.py

echo
echo "Done. See out/demand_report.csv for the full ranked list."
