# Pipeline flow

```
Context.dev monitors (daily)
  → list-monitor-changes / get-change
  → append data/signals/YYYY-MM-DD.jsonl (role=demand|competition)

Weekday Rad hunt
  → OEM / EBR RSS / Report / Amazon / X / Etsy+MW competition
  → YouTube via youtube_scan.py when YOUTUBE_API_KEY set; else youtube SKIPPED/AUTH
  → append signals + write data/source_health/YYYY-MM-DD_weekday.json
  → alert user if important source BLOCKED/AUTH

Weekly EBR browser + Weekly FB listen
  → data/themes/YYYY-MM-DD_{ebr|fb}.json
  → linked signal rows

Scorer (on demand / hero decision)
  → data/scored/YYYY-MM-DD_run.csv
  → brief Demand Monitor UI Bot → Google Sheet "Demand Monitor – 3D Printing"
```

Sheet tabs (proposed; UI Bot owns final columns):

1. **Products** — scored CSV ingest (existing)
2. **Signals** — recent signal rows (append)
3. **Themes** — weekly digests
4. **Source Health** — last N hunt health snapshots
