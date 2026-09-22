# Demand Monitor UI Bot ingest contract (locked 2026-09-17, flattened; Opportunity/SLA CONFIRM 2026-09-21)

Sheet columns match `signal.schema.json` / `theme.schema.json` / `source_health.schema.json` / `opportunity.schema.json`.

| Artifact | Path |
| --- | --- |
| Signals (canonical) | `data/signals/YYYY-MM-DD.jsonl` |
| Signals (Sheet) | `data/signals/YYYY-MM-DD.csv` |
| Themes EBR | `data/themes/YYYY-MM-DD_ebr.csv` (+ optional `.json` digest) |
| Themes FB | `data/themes/YYYY-MM-DD_fb.csv` (+ optional `.json` digest) |
| Source Health | `data/source_health/YYYY-MM-DD_weekday.csv` (+ optional `.json`) |
| Opportunities | `data/opportunities/YYYY-MM-DD.csv` (+ jsonl OK) |
| Alerts | `data/alerts/YYYY-MM-DD.json` (see `alert.schema.json`) |
| Heat (interim) | `data/scored/heat_YYYY-MM-DD.csv` |
| Scored products | `data/scored/dashboard_run_YYYY-MM-DD.csv` (optional `out/dashboard_run.csv`) |
| Handoffs (Pulse) | JSON matching `handoff.schema.json` (draft_only always true) |

## Drive companion (interim until HTTPS webhook)

See [`drive_autopush.md`](drive_autopush.md) for the weekday Drive companion naming details.

Parent folder id: `0AP1Zt35TN43AUk9PVA`  
Dated names: `opportunities_YYYY-MM-DD.csv`, `alerts_YYYY-MM-DD.json`, `heat_YYYY-MM-DD.csv`  
HTTPS ingest: **stubbed** (Drive auto-push interim).

## CSV headers

**Signals:** `id,ts,source,role,kind,url,product_key,tags,summary,quote,metrics_json,raw_ref`  
(`tags` pipe-separated; `metrics_json` stringified object or blank)

**Themes:** `digest_id,ts,window,sources_readable,sources_failed,nothing_new,label,tag,gist,url,relevance,signal_ids`  
(pipe-separated list fields; `nothing_new` TRUE|FALSE; empty themes still emit one blank theme row)

**Source Health:** `ts,run_id,alert_user,name,status,detail,last_ok,consecutive_failures,owner`  
(`status` ∈ OK|STALE|BLOCKED|AUTH|EMPTY_UNEXPECTED|SKIPPED; SLA columns additive — UI may ignore until ready; `owner` ∈ forecasting|ui|manual|context|blank)

**Opportunities:** `opportunity_id,ts,run_id,product_key,brand,pain,evidence_count,sources_json,confidence,suggested_next,alert_user,summary`  
Optional additive: `lane` (demand|competition|mixed|review), `url`  
`opportunity_id` stable across days = hash of `product_key|normalized_pain` (never daily-random).

**Heat (interim):** `product_key,heat,evidence_7d,source_diversity,recency_boost,competition_proxy,run_id,ts`  
Not a full ProductScore — see `heat_formula.md`.

**Products:** see `scored_product.columns.md` — config-only / unscored never emit.

## Required weekday source names

Always present in the latest **weekday** snapshot (never emit sparse follow-up `run_id`s that become "latest" with only one source):

`youtube`, `amazon_reviews_rad`, `amazon_reviews_aventon`, `google_reviews_rad`, `google_reviews_aventon`, `oem_help_rad`, `oem_help_aventon`  
(plus existing oem / etsy / makerworld / ebr / facebook_manual / etc.)

## Alerts

File: `data/alerts/YYYY-MM-DD.json` — envelope in `alert.schema.json`. Routing notes: `alert_routing.md`.

## UI badge map (`suggested_next` → Pulse badge)

| suggested_next | UI badge |
| --- | --- |
| WATCH | WATCH |
| `PRINT_SAMPLE` / `DESIGN` | PROTOTYPE |
| SHOPIFY | CLOSEST |
| KEEP_HUNTING | NEEDS DATA |

## Pulse handoffs

Forecasting accepts handoffs per `handoff.schema.json`:

- `KEEP_HUNTING` — Forecasting deepens listen
- `DESIGN_BRIEF` / `SHOPIFY_DRAFT` — Design/Shopify **draft only, never publish**
- `draft_only` must always be `true`; `requested_by` = `demand_monitor_ui`
