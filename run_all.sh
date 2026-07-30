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
#
# X signal (optional):
#   Set X_BEARER_TOKEN in .env to use the official API (pay-per-use).
#   Otherwise x_scan.py falls back to x_manual_log.csv.
#   Skip entirely: SKIP_X=1 ./run_all.sh
#
# Search volume (DataForSEO Google Ads — primary demand signal):
#   Set DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD in .env.
#   Cached weekly by default. Skip: SKIP_SEARCH_VOLUME=1 ./run_all.sh
#   Estimate first: python3 search_volume_scan.py --estimate
#
# Reddit is optional / unreliable — skip with SKIP_REDDIT=1.
set -e
cd "$(dirname "$0")"

REDDIT_BACKEND="${REDDIT_BACKEND:-pullpush}"
STEP=0
total=6

step() {
  STEP=$((STEP + 1))
  echo "== ${STEP}/${total} $1 =="
}

if [[ "${WAIT_FOR_PULLPUSH:-0}" == "1" && "${REDDIT_BACKEND}" == "pullpush" && "${SKIP_REDDIT:-0}" != "1" ]]; then
  step "Waiting for PullPush to be healthy"
  python3 wait_for_pullpush.py --wait-only
fi

if [[ "${SKIP_SEARCH_VOLUME:-0}" != "1" ]]; then
  step "Search volume (DataForSEO Google Ads)"
  if [[ -n "${DATAFORSEO_LOGIN:-}" || -f .env ]]; then
    # shellcheck disable=SC1091
    set -a
    [[ -f .env ]] && source .env || true
    set +a
  fi
  if [[ -n "${DATAFORSEO_LOGIN:-}" && -n "${DATAFORSEO_PASSWORD:-}" ]]; then
    python3 search_volume_scan.py
  else
    echo "  skipped (no DATAFORSEO_LOGIN/PASSWORD — set in .env)"
  fi
else
  step "Search volume (DataForSEO Google Ads)"
  echo "  skipped (SKIP_SEARCH_VOLUME=1)"
fi

if [[ "${SKIP_REDDIT:-0}" != "1" ]]; then
  step "Reddit scan (backend: ${REDDIT_BACKEND}) [optional]"
  if [[ "${REDDIT_BACKEND}" == "pullpush" ]]; then
    python3 reddit_scan.py --backend pullpush --delay "${REDDIT_DELAY:-5}" || {
      echo "  [warn] reddit scan failed — continuing (Reddit is optional)"
    }
  else
    python3 reddit_scan.py --backend "${REDDIT_BACKEND}" || {
      echo "  [warn] reddit scan failed — continuing (Reddit is optional)"
    }
  fi
else
  step "Reddit scan"
  echo "  skipped (SKIP_REDDIT=1)"
fi

step "Google Trends scan"
python3 trends_scan.py || echo "  [warn] trends scan failed — continuing"

step "Marketplace listing scan"
python3 marketplace_scan.py

if [[ "${SKIP_X:-0}" != "1" ]]; then
  step "X (Twitter) scan"
  python3 x_scan.py || echo "  [warn] X scan failed — continuing"
else
  step "X (Twitter) scan"
  echo "  skipped (SKIP_X=1)"
fi

step "Scoring & ranking"
python3 score_demand.py

echo
echo "Done. See out/demand_report.csv for the full ranked list."
