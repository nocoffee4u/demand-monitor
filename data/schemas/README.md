# SoMo demand data pipeline (canonical store)

Rider-first demand infrastructure. This folder is the **system of record for raw and intermediate demand data** on `bot/signal-hunt`. The Google Sheet / Demand Monitor UI remains the **human dashboard** for *scored products* only.

## Layers

| Layer | Path | Who writes | Who reads |
| --- | --- | --- | --- |
| Raw signals | `data/signals/*.jsonl` | Demand hunts, Context.dev change pulls | Scorer, UI ingest |
| Themes | `data/themes/*.json` | Weekly FB / EBR digests | Scorer, UI Themes tab |
| Source health | `data/source_health/*.json` | Every hunt | User alerts, UI Health tab |
| Scored products | `data/scored/*.csv` | `score_dashboard` / live runs | Demand Monitor UI Bot → Sheet |

## Rules

1. Append-only for signals (never rewrite history; correct with a new event).
2. Never invent sales, likes, downloads, or engagement.
3. Etsy / MakerWorld events are `role=competition` only; rider hangouts are `role=demand`.
4. Config-only WATCH SKUs stay out of the Sheet until a scored CSV exists.
5. Alert the user if an important source is BLOCKED/AUTH — do not log NOTHING_NEW for unread sources.

## Schemas

See `signal.schema.json`, `theme.schema.json`, `source_health.schema.json`, and `scored_product.columns.md`.
