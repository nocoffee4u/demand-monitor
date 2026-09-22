# Pipeline flow

```
Context.dev monitors (daily)
  → list-monitor-changes / get-change
  → append data/signals/YYYY-MM-DD.jsonl (role=demand|competition)
  → Context webhooks attach when UI HTTPS URL exists (stubbed for now)

Weekday Rad hunt
  → OEM / EBR RSS / Report / Amazon / X / Etsy+MW competition
  → YouTube via youtube_scan.py when YOUTUBE_API_KEY set; else youtube SKIPPED/AUTH
  → review/help lanes + OEM live
  → append signals + write data/source_health/YYYY-MM-DD_weekday.json
  → alert user if important source BLOCKED/AUTH (→ data/alerts/YYYY-MM-DD.json)
  → Opportunity emit after hunts → data/opportunities/YYYY-MM-DD.csv (+ jsonl)
  → optional interim heat → data/scored/heat_YYYY-MM-DD.csv

Weekly EBR browser + Weekly FB listen
  → data/themes/YYYY-MM-DD_{ebr|fb}.json
  → linked signal rows

Pulse
  → feeds from opportunities (+ alerts / heat companions)
  → handoffs (KEEP_HUNTING / DESIGN_BRIEF / SHOPIFY_DRAFT) draft_only

Drive auto-push (interim until HTTPS webhook)
  → parent 0AP1Zt35TN43AUk9PVA
  → opportunities_YYYY-MM-DD.csv, alerts_YYYY-MM-DD.json, heat_YYYY-MM-DD.csv

Scorer (on demand / hero decision)
  → data/scored/YYYY-MM-DD_run.csv
  → brief Demand Monitor UI Bot → Google Sheet "Demand Monitor – 3D Printing"
```

Notes:

- Launch extract monitors deleted (cap); review/help + OEM live.
- Do not invent sales/engagement; heat is not full ProductScore.

Sheet tabs (proposed; UI Bot owns final columns):

1. **Products** — scored CSV ingest (existing)
2. **Signals** — recent signal rows (append)
3. **Themes** — weekly digests
4. **Source Health** — last N hunt health snapshots
5. **Opportunities** — Pulse pain stitch rows
6. **Alerts** — routing envelope (optional companion)
