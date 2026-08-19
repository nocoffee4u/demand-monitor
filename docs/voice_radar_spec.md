# Market Voice + Opportunity Radar — Spec v1

Owner: Claude (architecture/data model/Dashboard design, per `PROJECT_BRIEF.md`).
Implementer: Grok.
Status: Market Voice **v1 + Amazon suggestions** implemented (Sheets tab +
`market_voice.py`; `amazon_suggestions` persisted). Prerequisites + History
coverage done. Opportunity Radar / design briefs / YouTube titles still open.

Grounded in the actual current data shape as of 2026-08-17 (`out/demand_report.csv`
= 177 columns, `HISTORY_COLS` in `export_to_sheets.py`, `amazon_scan.py`,
`ebay_sold_scan.py`, `etsy_scan.py`, `youtube_scan.py`,
`printables_cults_scan.py`, `out/search_volume_keywords.csv`,
`out/run_meta.json`) — not written from the proposal alone. Two things found
while grounding this change the plan and are called out explicitly below.

---

## 0. Two things found while grounding this, before any design starts

**Bug, fix first, independent of everything else below:** `score_demand.py`'s
merge chain collides three identically-named `fetched_at` columns from
`ebay_sold_signal.csv`, `etsy_signal.csv`, and `amazon_signal.csv`. Pandas
silently renames them to `fetched_at_x` / `fetched_at_y` / `fetched_at` on
merge — there is currently no reliable way to tell, from `demand_report.csv`,
whether a given product's eBay data is from today's run or a 28-day-old
cache hit. This matters a lot for Market Voice (§2) — a "proof snippet"
attributed to a stale cache read weeks ago, presented as current market
voice, is misleading. Fix: rename before merging (`ebay_fetched_at` /
`etsy_fetched_at` / `amazon_fetched_at`) in each scanner's output or at
merge time in `score_demand.py`. Small, mechanical, do this first — it's a
prerequisite for Market Voice's "data as of" column (§2.3).

**The richest candidate input for Market Voice doesn't reach the CSV
today.** `amazon_scan.py` builds `all_suggestions` (the full deduped list of
Amazon autocomplete phrases per product — real customer-typed search
language, e.g. `"iottie phone mount replacement parts"`,
`"phone mount replacement adhesive"`, confirmed via live testing during the
Amazon review) and uses it internally to compute `amazon_problem_mention_score`
and `amazon_top_title` — then discards the list. Only one derived score and
one derived title survive to `out/amazon_signal.csv`. "No new scanners" is
achievable, but "no new fields on existing scanners" would leave Market
Voice materially thinner than the proposal implies. §2 recommends one small
field addition as part of v1, not a future nice-to-have.

---

## 1. Answering "is this the right split?" — four surfaces, not five

Keep **A** (Action This Week) exactly as-is — it's validated, it's short,
it's the only weekly execution list, don't touch it.

Keep **B** (Market Voice) and **C** (Opportunity Radar) as proposed — they
answer genuinely different questions (*what should I say/design* vs. *is
this building or fading*) and neither belongs inside Action This Week
without breaking "stay primary and short."

**Merge D into C.** A standalone monthly narrative one-pager is a new
output format, a new generation cadence, and a new file/tab to remember to
check — for a solo operator whose own stated success criterion (per
`PROJECT_BRIEF.md`) is "every Monday I can open **one** Google Sheet." A
separate monthly artifact works against that. Instead: make the top of the
Opportunity Radar tab a short auto-generated narrative block (3-5
sentences, built the same deterministic-template way Action This Week's
bullets already are — string-formatted from real deltas, not a new
generation system) sitting above the Radar's trend chart and table. Same
information the standalone one-pager would have contained, zero new
surface area, and it naturally updates every run instead of needing its
own monthly trigger.

**Keep E (design/manufacture brief) but sequence it last and gate it hard.**
It's naturally scoped already (fires only for rows tagged `PROTOTYPE` in
Action This Week — 0-3 products on a normal week), and its best content
(design must-haves, competitive title language) depends on Market Voice
existing first. Don't build it in parallel with B; build it after.

Net: **A (done) → B → C (absorbs D) → E**, in that dependency order.

---

## 2. Minimum viable Market Voice using existing fields

Two different kinds of "voice" are folded together in the proposal, and
they should be visually separated in the output, not blended into one
column — they answer different questions and come from structurally
different sources:

- **Buyer intent language** — what people actually type when searching.
  Closest thing this pipeline has to true voice-of-customer.
- **Competitive listing language** — what sellers/makers *title* their
  existing products. Useful for positioning ("everyone calls theirs
  'universal'") and design cues, but it's marketing copy, not customer pain.

### 2.1 Inputs, tiered by what's actually available right now

| Tier | Source | What it gives | Change needed |
|---|---|---|---|
| 1 | `out/search_volume_keywords.csv` | Real per-product keyword phrases **with actual Google Ads search volume** — the only source that lets you rank phrases by real demand, not just presence. Confirmed live: ~4 keyword rows/product today (thin but real, volume-attested, zero-cost). | None — already exists, currently only mined for a single max-volume phrase (`search_volume_best_keyword`); the rest are discarded after aggregation. |
| 2 | Amazon autocomplete suggestions | Genuine customer-typed search language (verified live: e.g. `"phone mount replacement adhesive"`). Richest *intent* source by far. | One field: persist top 5-8 unique `all_suggestions` to a new `amazon_suggestions_sample` column in `amazon_scan.py`'s output. This is a field addition to an existing scanner, not a new scanner — stays inside "no new scanners." |
| 3 | `ebay_top_title`, `etsy_top_listing_title`, `printables_top_name` / `cults_top_name` / `makerworld_top_name` / `thangs_top_name` | Competitive listing language (best-selling/highest-favorited/highest-download title per source). | None — already exists. Label clearly as "how sellers title this," not customer voice. |
| — | YouTube | Nothing today. `youtube_signal.csv` has no title field at all — only counts and links. | Out of scope for v1; note as an honest gap, not silently implied as covered. Fast-follow: add `youtube_top_title` to `youtube_scan.py` using the same one-field pattern as Tier 2. |

**v1 + Tier 2 fast-follow shipped** (`market_voice.py` → Sheets **Market Voice**).
`amazon_scan.py` persists `amazon_suggestions` (unique AC strings, separator
`" | "`, max 11). Voice prefers complaint-filtered suggestions for
`top_problem_phrases` / `proof_snippets`; if suggestions exist but none match
narrow complaint language, problem phrases stay empty (honest). Tier-1
search-phrase filter is fallback only when no Amazon suggestion text.
Extra columns beyond §2.3: `rank`, `proof_snippets`, `channel_bias`, `voice_notes`.

### 2.2 "Clustering" — rule-based tagging, not NLP

Do **not** introduce embeddings/clustering/a new ML dependency for this.
It contradicts the project's own stated philosophy
(`score_demand.py`'s docstring: *"rule-based, explainable"*) and the
pattern already proven out in `PROBLEM_TERMS`/`_H2S_*` regex tagging
elsewhere in this codebase. Reuse the same approach: a small, fixed tag
vocabulary matched via keyword regex against the Tier 1/2 phrase pool —
e.g. `replace|broken|loose|missing` → **durability/fit**,
`adapter|mount|bracket` → **compatibility**, `cover|cap|guard` →
**protection**, `universal|generic` (appearing in Tier 3 competitive
titles but *absent* from Tier 1/2 buyer phrases) → **differentiation
opportunity**. This is a ~30-line function, not a subsystem.

### 2.3 Sheet shape

New tab: **Market Voice**. One row per product (all products, sorted by
`priority_score` — don't pre-truncate to top-N; let the operator scroll/filter
in Sheets, consistent with how Product Rankings already works):

| Column | Source | Notes |
|---|---|---|
| `product`, `category`, `priority_score` | existing | sort/context |
| `top_intent_phrases` | Tier 1, top 3-5 by `search_volume` | real buyer language, volume-ranked |
| `top_problem_phrases` | Tier 2 (once landed), filtered through `PROBLEM_TERMS` | blank/fallback until the field exists |
| `competitive_titles` | Tier 3, concatenated | explicitly labeled "how sellers title this" |
| `design_must_haves` | rule-based tags (§2.2) from Tier 1/2 | e.g. `durability/fit; compatibility` |
| `social_hook` | one templated sentence | e.g. `"'{top phrase}' — real search phrase, {volume}/mo"` |
| `confidence` | sample size (§4, gotcha 3) | e.g. `n=1 phrase — low confidence` |
| `data_as_of` | the fixed `fetched_at` fields (§0) | per-source freshness, not implied-live |

---

## 3. Sheets vs. `out/*.md`

Look at what this project already does, not a fresh rule: the only
existing `out/*.md` (`local_service_market_phoenix_az.md`) is explicitly an
occasional, separately-triggered deep-dive artifact for Phase 2 research —
never part of the weekly loop. Everything in the *weekly* loop
(`PROJECT_BRIEF.md`'s own success criterion: "one Google Sheet") lives in
Sheets, full stop, including narrative text — Action This Week already
proves narrative-in-Sheets works fine, it's just rows of text in a cell.

- **Market Voice → Sheets tab.** Weekly-refreshed, tabular, meant to be
  scanned/filtered.
- **Opportunity Radar (+ folded-in monthly narrative) → Sheets tab.** Same
  reasoning; the narrative block is just the first few rows of the tab, not
  a separate artifact.
- **Design/manufacture brief (E) → `out/briefs/{product-slug}.md`.** This
  one's genuinely different in character, not just smaller: it's a working
  document for an active task (open it next to CAD software while
  designing), triggered per-product only when that product enters
  `PROTOTYPE` status (0-3 files most weeks, not a weekly summary), and its
  natural habitat is a file you open once for a specific job, not a
  dashboard you scan every Monday. This matches the existing
  `local_service_market_*.md` precedent exactly — that's what `.md` is
  *for* in this project already.

---

## 4. Scoring/History gotchas that would mislead a Voice/Radar view

Drawn from concrete bugs and behaviors found across the eBay/Etsy/YouTube/
community/Amazon reviews — not hypothetical:

1. **Weight redistribution makes `priority_score` deltas ambiguous.** When a
   source is empty, its weight redistributes to the others (`_redistribute`
   in `score_demand.py`) — so a week-over-week jump in `priority_score`
   could be real demand movement, or just a different set of sources being
   active that week. `HISTORY_COLS` (`export_to_sheets.py:241-255`)
   currently has no coverage field at all, so Radar's trend chart can't
   currently distinguish these. **Fix (prerequisite for Radar):** add a
   compact `sources_active_count` (or similar) column to `HISTORY_COLS`,
   sourced from `run_meta.json`'s existing `sources` dict — the data's
   already computed every run, it's just never written to History.
2. **Partial community coverage pollutes both Radar and Voice.** Confirmed
   in the MakerWorld/Thangs review: Printables and Thangs are both
   Cloudflare-challenge-prone; `community_downloads` is a straight sum
   across whichever platforms succeeded that specific week. A
   week-over-week swing can be almost entirely "did Printables get through
   this week" rather than real download growth — and if Printables was
   blocked, `printables_top_name` is blank that week. Voice must render
   that as "Printables data unavailable this week," never silently as "no
   community interest." `run_meta.json`'s existing `community_platforms`
   block already has this — thread it through rather than re-deriving it.
3. **Amazon problem score is unreliable at low sample size.** Confirmed
   live during the Amazon review: a single autocomplete hit can produce a
   `100/100` problem score, since the scoring formula saturates trivially
   at `n=1`. Any Voice/Radar view citing a problem-score number must show
   the sample size alongside it (the `confidence` column in §2.3 exists
   specifically for this) and should treat scores below some minimum `n`
   (e.g. 3) as low-confidence, not hide the number but don't headline it either.
4. **Cache TTLs vary 7-28 days across sources.** A cited "top title" could
   be reflecting a search from up to 28 days ago even in a run marked
   "active" (Etsy/eBay/Amazon/community all cache at 28d). This is what
   §2.3's `data_as_of` column is for — once §0's merge-collision fix lands,
   it's a real per-source date, not a guess.
5. **Competition-side listing counts have the same coverage-churn problem
   as demand-side**, for the same curl_cffi-related reasons — a
   `total_listings` swing can reflect which platforms got scraped that
   week, not a real competitive shift. Same mitigation as gotcha 2: surface
   coverage next to the number, don't present it bare.

---

## 5. Implementation order

Small, independently reviewable steps, in dependency order — matches how
every other signal in this project has shipped (one vertical slice at a
time, each with its own Claude review pass):

1. **Fix the `fetched_at` merge collision** (§0). **Done** —
   scanners emit `ebay_fetched_at` / `etsy_fetched_at` / `amazon_fetched_at`;
   `score_demand._disambiguate_fetched_at` renames legacy CSVs on merge.
2. **Add `amazon_suggestions` to `amazon_scan.py`** (§2.1, Tier 2). **Done** —
   persisted AC strings (` | ` sep, max 11); Voice consumes them. Optional
   follow-up: `youtube_top_title` still open.
3. **Add coverage snapshot to `HISTORY_COLS`** (§4, gotcha 1–2). **Done** —
   `sources_active_count`, `sources_active`, `community_platforms_ok`,
   `community_platforms_total`. `append_history` upgrades old headers.
4. **Ship Market Voice tab** (§2.3). **Done (v1)** — `market_voice.py` +
   Sheets tab; Tier 1+3 only; Tier 2 amazon suggestions still fast-follow.
5. **Ship Opportunity Radar tab** (§1, absorbing D). Depends on step 3 to
   be meaningful. Should be a smaller PR than Voice — the trend-chart and
   category-average machinery (`build_trend_pivot`, `build_category_avg`,
   `_ChartData`) already exists and can be reused directly; this is mostly
   a new table layout plus the narrative-header template.
6. **Ship the design/manufacture brief generator** (E). Smallest PR,
   depends on step 4 for its richest content (must-haves, competitive
   titles) — templating already-computed fields into a per-product
   markdown file, gated on `PROTOTYPE` status.
