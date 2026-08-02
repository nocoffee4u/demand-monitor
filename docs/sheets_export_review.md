# Review — Google Sheets export v1 (`export_to_sheets.py`)

Reviewer: Claude, per `PROJECT_BRIEF.md` ("Claude owns: ... final review").
Reviewed against: `docs/sheets_dashboard_spec.md` (v1).
Method: read `export_to_sheets.py` in full, ran `python3 export_to_sheets.py
--dry-run` output already present in `out/sheets_dry_run/`, traced
`run_meta.json` production in `score_demand.py` through to Dashboard build.

Overall: the tab structure, column sets, Action This Week rules, and setup
docs (`docs/sheets_setup.md`) match the spec closely and are genuinely
good — `score_explanation` and `fit_flags` carrying through, the
blank-vs-zero handling, the phantom-product blocking added in `c170066`,
and the Action This Week bullets in the dry-run output
(`"Prototype this week: MTB chain guide / bash guard (priority 87, fit 89,
comp 15)"`) are exactly the kind of scannable, decision-ready output the
brief asked for. The issues below are specific gaps, not a rejection of
the approach.

---

## P0 — fix before calling this phase done

### 1. Three of the five spec'd charts don't exist
`add_dashboard_charts()` (`export_to_sheets.py:1016-1181`) creates exactly
two charts: "Top Priority Scores" (bar) and "Demand vs Fit" (scatter).
Missing:
- **Category/niche comparison bar chart** — the data is computed and
  written to the Dashboard as a plain text table (`CHART DATA — Category
  avg priority`, lines 780-802, confirmed present in
  `out/sheets_dry_run/dashboard.txt`), but no chart object is bound to it.
- **Priority score trend line** — no data block and no chart at all. This
  is the one both `sheets_dashboard_spec.md` §2/§3 and
  `PROJECT_BRIEF.md` itself call out explicitly ("Key charts (bar,
  **trend**, ranking)"). Right now there is no way to see whether a
  product's momentum is real or a one-week blip from the Dashboard —
  which is the exact question that chart exists to answer, and it's the
  one piece of "Demand vs Fit *and* trend" that the brief names twice.
- **Search volume vs. competition scatter** — not implemented at all
  (spec placed this on Search Volume/Marketplace, not Dashboard, so it's
  lower priority than the trend chart, but still missing).

This is the single biggest gap versus both documents. Recommend
prioritizing the trend chart first (bind to `History`, filtered to
current top 5-8 products) since it's the one explicitly named in the
brief; category-avg chart second (data's already computed, just needs an
`addChart` request); search-volume-vs-competition third.

### 2. Dashboard "top-10 churn" KPI will silently produce wrong results starting the 3rd weekly run
In `build_dashboard()` (`export_to_sheets.py:685-713`), churn is computed
via `history[...].nsmallest(10, "rank")` / `.nlargest(10, "priority_score")`
against `history_existing` — which, once a real prior History exists, is
built by `pd.DataFrame(prev_vals[1:], columns=header)` from a raw
`values().get()` Sheets API read (`export_to_sheets.py:1286-1289`). Every
cell from that read is a **string**. `nsmallest`/`nlargest` on a string
column don't error — they silently sort lexicographically ("10" sorts
before "2"), so the churn set is quietly wrong, not obviously broken.

Compare: `compute_actions()` (used for the Watch-rising/Reconsider-drop
rules) correctly does `hist["priority_score"] = pd.to_numeric(...)`
before comparing. The separate churn block in `build_dashboard()` has no
equivalent coercion for `rank` or `priority_score`. This passes every
test available right now — dry-run has no history, and the first live run
has nothing to compare against — and will only start producing visibly
wrong "N new in top 10" numbers once there are ≥2 real runs in the sheet.
Worth fixing now specifically because it's the kind of bug that looks
done today and quietly misleads three weeks from now. Fix: coerce `rank`
and `priority_score` to numeric on `history_existing` right after the
Sheets read, once, rather than per-block.

---

## P1 — should fix before relying on multi-week data

### 3. Dead "CHART DATA — Demand vs Fit" block on the Dashboard
`build_dashboard()` writes a full per-product `product / fit_score /
demand_score / search_volume / category` table to the Dashboard tab
(`export_to_sheets.py:765-778`), but neither chart references it — both
`addChart` requests in `add_dashboard_charts()` bind to the **Product
Rankings** sheet directly (`rank_id`), not Dashboard. That's actually the
more robust choice (doesn't break if Dashboard's row layout shifts), but
it means the block on Dashboard is now dead weight: raw per-product data
sitting on the one tab the spec explicitly says should hold none
("§1.1: No raw data lives here — every element either reads from another
tab's range..."). Either wire a chart to consume it, or delete it — right
now it's duplicate data that contradicts the tab's own design intent.

### 4. Blank-vs-stale handling doesn't reach every regenerated tab
`blank_unused_sources()` (`export_to_sheets.py:188-216`) — the mechanism
that turns a skipped source's cells blank instead of a misleading `0` —
is only applied in `build_rankings()` and `build_scoring_detail()`.
`build_search_volume_tab()` and `build_marketplace_tab()` read their
source CSVs directly off disk with no reference to `meta["sources"]` at
all. Concretely: if `SKIP_COMMUNITY=1` is set for a run, the cached
`printables_cults_signal.csv` from a prior run is still sitting in `out/`,
and `build_marketplace_tab()` will happily display it with nothing
indicating it's not from this run — while Product Rankings, drawing off
the same underlying `community_downloads` column, correctly blanks it.
Same gap for Search Volume under `SKIP_SEARCH_VOLUME=1`. Two tabs
disagreeing about whether a number is current undermines the "one
canonical freshness source" rule in spec §5.

### 5. History append has no header-shape check before appending
`append_history()` (`export_to_sheets.py:962-992`) treats
`existing[0]` as the header and appends new rows positionally, assuming
they line up with `HISTORY_COLS`. There's no check that the tab's actual
header row still matches `HISTORY_COLS` before appending. History is the
one tab explicitly designed to be append-only and to feed everything
else (churn, rising/drop rules, and — once built — the trend chart); if a
solo operator ever manually touches a cell in that tab (reasonable to
expect over time), a silent column-shift would corrupt the log with no
warning. Cheap to add: compare `existing[0] == HISTORY_COLS` and abort
loudly if it doesn't match, rather than trusting positional alignment.

---

## P2 — polish, lower priority

### 6. Local Service mini-panel's `rank` column is confusing
`export_to_sheets.py:804-823` sorts local-service keywords by
`search_volume` for the Dashboard's top-5 mini-panel, but displays each
row's **original full-list rank** (`r.get("rank", i)`) rather than its
position in this resorted subset. Confirmed in the actual dry-run output
— the panel reads `rank 1, 3, 2, 4, 5` top to bottom, which looks like a
data error at a glance even though the underlying numbers are correct.
Trivial fix: use the loop's own counter (`i`) instead of the source
file's `rank` column, or drop the rank column from this panel entirely.

### 7. Uncaught exception path for a malformed service-account JSON
`get_sheets_service()` (`export_to_sheets.py:840-855`) pre-checks that
the JSON path exists (giving the clean "File not found" message in the
troubleshooting table), but a JSON file that exists yet is corrupt or the
wrong credential type will raise inside
`service_account.Credentials.from_service_account_file` uncaught — a raw
traceback instead of the same friendly style used elsewhere. Minor, but
worth a one-line `try/except` to match the rest of the error handling's
tone, since this is exactly the kind of mistake a solo operator copying a
path by hand will make once.

### 8. Redundant source-active logic
`build_dashboard()`'s per-chip active/inactive derivation
(`export_to_sheets.py:646-676`) re-checks `demand_unused` membership even
though `meta["sources"]` (written once, authoritatively, by
`score_demand.py`) already has the true/false answer for every source.
The two agree today, but it's two places encoding the same fact — exactly
the drift risk spec §5's "one canonical source" rule exists to prevent.
Simplify to just reading `meta["sources"]` directly.

---

## Setup / first-run notes (minor, not blocking)

- `ensure_tabs()` doesn't address the default "Sheet1" tab Google creates
  automatically in any brand-new spreadsheet — it'll sit alongside the 8
  spec'd tabs at some index after the first run. Not a functional issue,
  just cosmetic clutter worth a line in `docs/sheets_setup.md` ("delete
  the default Sheet1 after the first run") or an auto-delete-if-empty
  check in the script.
- Everything else in `docs/sheets_setup.md` (service account creation,
  least-privilege sharing, `.env` keys, troubleshooting table) is clear
  and matches what the code actually needs — no gaps found there.

---

## Answering the five review questions directly

1. **Matches the spec?** Tab structure, columns, and Action This Week
   rules: yes, closely. Charts: partially — 2 of 5, with the specifically
   brief-mandated trend chart missing (P0 #1).
2. **Clear and actionable for a solo operator?** Yes for the parts that
   exist — Action This Week reads well, `score_explanation`/`fit_flags`
   give "why" without extra clicks. The missing trend chart is the one
   real gap in "actionable" — momentum is computed internally
   (`compute_actions`) but never shown visually.
3. **Missing error handling / edge cases?** P0 #2 (churn type bug), P1 #5
   (History header drift), P2 #7 (malformed credentials) are the concrete
   ones; general Sheets API call failures mid-export aren't individually
   caught (only chart creation is), so a transient API error partway
   through could leave some tabs updated and others stale with no summary
   of which — worth a wrapping try/except per tab with a final "N/8 tabs
   written" log line.
4. **Dashboard/Action This Week clarity improvements?** Build the trend
   chart (P0 #1) and category chart; consider real conditional formatting
   on the Freshness cell (currently a plain "GREEN — ..." string, not an
   actual visual color signal) — this was implicit in the spec's
   green/yellow/red language but text alone doesn't fully deliver the
   at-a-glance value.
5. **What to simplify/fix before calling this phase done?** P0 #1 and #2
   are the bar for "done" — the missing trend chart directly undercuts
   the brief's own stated requirement, and the churn bug is a
   silent-wrong-answer risk that will surface on its own timeline (week
   3) if left in. P1 items are worth doing in the same pass since they're
   small and touch the same code paths.
