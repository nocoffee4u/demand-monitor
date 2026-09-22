# Drive weekday auto-push companions

Weekday drops are written to Google Drive parent folder `0AP1Zt35TN43AUk9PVA` using these dated companion names:

- `opportunities_YYYY-MM-DD.csv`
- `alerts_YYYY-MM-DD.json`
- `heat_YYYY-MM-DD.csv`

Existing dated companions continue to use their practiced names:

- `signals_YYYY-MM-DD.csv`
- `themes_YYYY-MM-DD_ebr.csv` and `themes_YYYY-MM-DD_fb.csv`
- `source_health_YYYY-MM-DD_weekday.csv`

The HTTPS webhook remains stubbed. Until the UI pastes an HTTPS URL, Context stays on the poll → CSV + Drive + Pipeline flow.
