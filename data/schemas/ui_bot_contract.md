# Demand Monitor UI Bot ingest contract (locked 2026-09-17, flattened)

Sheet columns match `signal.schema.json` / `theme.schema.json` / `source_health.schema.json`.

| Artifact | Path |
| --- | --- |
| Signals (canonical) | `data/signals/YYYY-MM-DD.jsonl` |
| Signals (Sheet) | `data/signals/YYYY-MM-DD.csv` |
| Themes EBR | `data/themes/YYYY-MM-DD_ebr.csv` (+ optional `.json` digest) |
| Themes FB | `data/themes/YYYY-MM-DD_fb.csv` (+ optional `.json` digest) |
| Source Health | `data/source_health/YYYY-MM-DD_weekday.csv` (+ optional `.json`) |
| Scored products | `data/scored/dashboard_run_YYYY-MM-DD.csv` (optional `out/dashboard_run.csv`) |

## CSV headers

**Signals:** `id,ts,source,role,kind,url,product_key,tags,summary,quote,metrics_json,raw_ref`  
(`tags` pipe-separated; `metrics_json` stringified object or blank)

**Themes:** `digest_id,ts,window,sources_readable,sources_failed,nothing_new,label,tag,gist,url,relevance,signal_ids`  
(pipe-separated list fields; `nothing_new` TRUE|FALSE; empty themes still emit one blank theme row)

**Source Health:** `ts,run_id,alert_user,name,status,detail`  
(`status` ∈ OK|STALE|BLOCKED|AUTH|EMPTY_UNEXPECTED|SKIPPED)

**Products:** see `scored_product.columns.md` — config-only / unscored never emit.
