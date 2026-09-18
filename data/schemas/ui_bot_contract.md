# Demand Monitor UI Bot ingest contract (locked 2026-09-17)

Emit under `bot/signal-hunt` with `data/` prefix:

| Artifact | Path |
| --- | --- |
| Signals | `data/signals/YYYY-MM-DD.jsonl` |
| Themes | `data/themes/YYYY-Www.json` + `.csv` |
| Source Health | `data/source_health/YYYY-MM-DD.json` + `.csv` |
| Scored products | `data/scored/dashboard_run_YYYY-MM-DD.csv` (optional mirror `out/dashboard_run.csv`) |

Column names match UI Bot sheet tabs exactly (see Signals / Themes / Products / Source Health specs).
Config-only WATCH never goes to Products until scored.
