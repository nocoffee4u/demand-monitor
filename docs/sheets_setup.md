# Google Sheets export setup

Push weekly demand rankings into a Google Sheet (Service Account auth).
Design source of truth: [`sheets_dashboard_spec.md`](sheets_dashboard_spec.md).

## One-time setup

### 1. Google Cloud project

1. Open [Google Cloud Console](https://console.cloud.google.com/)
2. Create or select a project
3. Enable **Google Sheets API**  
   https://console.cloud.google.com/apis/library/sheets.googleapis.com

### 2. Service account

1. **IAM & Admin → Service Accounts → Create**
2. Name e.g. `demand-monitor-sheets`
3. **Keys → Add key → JSON** — download the file
4. Store it **outside the repo**, e.g.  
   `~/.config/demand-monitor/service-account.json`  
   (never commit this file)

### 3. Spreadsheet

1. Create a blank Google Sheet in your Google account  
   (or use an existing one)
2. Copy the spreadsheet ID from the URL:
   ```
   https://docs.google.com/spreadsheets/d/THIS_IS_THE_ID/edit
   ```
3. Click **Share** → add the service account email  
   (`…@….iam.gserviceaccount.com`) as **Editor**

Least privilege: only this one spreadsheet needs to be shared. No full Drive access required.

### 4. `.env`

```bash
GOOGLE_SERVICE_ACCOUNT_JSON=/Users/YOU/.config/demand-monitor/service-account.json
GOOGLE_SHEETS_SPREADSHEET_ID=paste_id_here
```

### 5. Install Python deps

```bash
source venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
# After scoring exists:
python3 score_demand.py          # writes out/demand_report.csv + out/run_meta.json
python3 export_to_sheets.py --dry-run   # local preview, no Google API
python3 export_to_sheets.py             # live push

# Full pipeline (export is the last step):
./run_all.sh
SKIP_SHEETS=1 ./run_all.sh              # skip export
```

Weekly launchd (`scripts/install_weekly_schedule.sh`) already runs `./run_all.sh`,
so once `.env` is set, Monday automation includes Sheets with no extra steps.

## Tabs created

| Tab | Content |
|---|---|
| Dashboard | Status strip, KPIs, Action This Week, top 10, chart data, charts |
| Product Rankings | Trimmed decision columns + `run_date` |
| Scoring Detail | Full contrib/raw/fit columns for “why” |
| Search Volume | Per-product summary + flat keyword audit |
| Marketplace | Listings + Printables/Cults engagement |
| Local Service (Phoenix) | Keywords, PAA, Maps competitors |
| History | **Append-only** weekly log |
| Config | Read-only mirror of products.yaml + local_service.yaml |

## Troubleshooting

| Symptom | Fix |
|---|---|
| `403` / permission denied | Share the sheet with the service account email as Editor |
| `404` spreadsheet | Wrong `GOOGLE_SHEETS_SPREADSHEET_ID` |
| `File not found` for JSON | Path in `GOOGLE_SERVICE_ACCOUNT_JSON` is wrong or unreadable |
| Charts missing | Data still exported; re-run without `--skip-charts`; check API quotas |
| Export skipped in `run_all.sh` | Both env vars must be set; or remove `SKIP_SHEETS=1` |

## Security

- Service account JSON is gitignored (`*-service-account*.json`, etc.)
- Never paste the private key into the repo or chat logs
- Revoke/rotate the key in Cloud Console if it leaks
