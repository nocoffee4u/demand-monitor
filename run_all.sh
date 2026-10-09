#!/usr/bin/env bash
# Runs the demand-scan pipeline. Reddit is retired (no usable API).
set -e
cd "$(dirname "$0")"

echo "== 1/3 Google Trends scan =="
python3 trends_scan.py || echo "[warn] trends scan failed; continuing"

echo "== 2/3 Marketplace listing scan =="
python3 marketplace_scan.py || echo "[warn] marketplace scan failed; continuing"

echo "== 3/3 Dashboard scoring =="
python3 score_dashboard.py --config config/products.yaml \
  --marketplace out/marketplace_signal.csv \
  --trends out/trends_signal.csv \
  --out out/dashboard_run.csv \
  --fetch-oem || python3 score_demand.py

echo
echo "Done. See out/dashboard_run.csv for dashboard ingest fields."
