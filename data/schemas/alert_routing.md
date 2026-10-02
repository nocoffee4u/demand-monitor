# Alert routing

Prefer **ONE** alert channel: Grok Bot app notify **or** email `somomfg@gmail.com`.  
Do **not** use Meta/Zapier Instagram. No new SMS spend without Grant. Slack only if already connected.

Daily file: `data/alerts/YYYY-MM-DD.json` (schema: `alert.schema.json`).

## Severity

| Condition | severity |
| --- | --- |
| BLOCKED important source | `critical` |
| OEM OOS → in-stock on Path A | `warn` |
| ≥3× 1–2★ same accessory pain in 7d | `warn` |
| STALE important source | `warn` |

## Important sources (always treat BLOCKED/AUTH/STALE seriously)

- `ebr_weekly`
- `facebook_manual` (3 groups)
- `oem_catalog`
- `etsy`
- `makerworld`
- Amazon reviews lanes
- `youtube` (when attempted)
- `google_reviews_*`
- `oem_help_*`
