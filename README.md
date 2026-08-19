# Demand Monitor

Scores candidate 3D-printed products by real demand signal before you spend
filament and time on them: Google Ads search volume (primary), community
engagement, marketplace competition, Google Trends, optional eBay sold
listings, YouTube coverage, X (Twitter) chatter, and optional Reddit.

`out/*.csv` currently contains sample/demo data from a test run so you can
see the report format — running the pipeline for real will overwrite them.

## Comparing niches, not just products

`config/products.yaml` currently tracks four candidate niches side by side —
e-bikes/MTB, FPV drones, automotive, and ATV/UTV — each product tagged with
a `category`. The ranked `demand_report.csv` output includes that category
column, so a single run tells you not just "which product" but "which
niche" has the strongest real signal, before you commit to one. Delete a
niche's product rows (and any subreddits that were only there for it) once
you've decided rather than guessing upfront.

## What's automated vs. not

| Signal | Automated? | Tool |
|---|---|---|
| **Google Ads monthly search volume / CPC / competition** | Yes | `search_volume_scan.py` (DataForSEO — **primary demand signal**) |
| Printables + Cults + MakerWorld + Thangs downloads / makes / likes | Yes | `printables_cults_scan.py` (community demand; soft-fail per platform) |
| Existing listing count on Printables / Cults / Thangs | Yes | `marketplace_scan.py` (competition count) |
| Google Trends relative search interest + momentum | Yes | `trends_scan.py` (pytrends) |
| YouTube matching videos + views/likes/comments | Yes (API key) | `youtube_scan.py` — needs `YOUTUBE_API_KEY`. Skip with `SKIP_YOUTUBE=1` |
| eBay sold / completed listings + sold prices | Yes (API key) | `ebay_sold_scan.py` — SoldComps `EBAY_SOLD_API_KEY`. Skip with `SKIP_EBAY=1` |
| Etsy active listings + favorites (sold proxy limited) | Yes (API key) | `etsy_scan.py` — Open API v3 `ETSY_API_KEY`. Skip with `SKIP_ETSY=1` |
| Amazon autocomplete + problem language (optional listings) | Yes (free AC; optional Rainforest key) | `amazon_scan.py` — soft-fail. Skip with `SKIP_AMAZON=1` |
| X / Twitter keyword + brand-account chatter | Yes (API) or manual | `x_scan.py` — needs `X_BEARER_TOKEN` or `x_manual_log.csv` |
| Reddit posts/upvotes/comments | **Optional / off by default** | `reddit_scan.py` (PullPush or PRAW). Weekly path skips unless `INCLUDE_REDDIT=1` |
| Facebook / Pinkbike / MTBR | **No — manual** | `facebook_manual_log.csv` |

**YouTube (optional, free quota):** MTB / e-bike / FPV niches are heavy on
review and repair video. The scanner is a *secondary* awareness signal
(small weight in `score_demand.py`), not a substitute for search volume.
Setup: enable YouTube Data API v3 → API key → `YOUTUBE_API_KEY` in `.env`.
Estimate: `python3 youtube_scan.py --estimate`. Weekly cache under
`cache/youtube_cache.json`. Without a key, zeros are written and weights
redistribute automatically.

**eBay sold (optional, SoldComps):** Real completed eBay sales + sold prices
for replacement/functional parts. Small transaction signal
(`ebay_sold_volume` 0.04 + light price-band boost). Setup: free key at
https://sold-comps.com (keys start with `sc_`) → `EBAY_SOLD_API_KEY` in `.env`.
Estimate: `python3 ebay_sold_scan.py --estimate`. Cache:
`cache/ebay_sold_cache.json`. Soft-fails without a key.

**Etsy (optional, Open API v3):** Active listing density + prices + favorites
for 3D-print marketplace interest. **No public sold totals** from Etsy’s API —
`etsy_sold_proxy` stays 0; demand uses favorites via `etsy_engagement_volume`
(0.02); listing density is **competition** (`etsy_listing_saturation` 0.05),
not a demand bonus. Setup: register app at etsy.com/developers →
`ETSY_API_KEY=keystring:shared_secret` in `.env`. Estimate:
`python3 etsy_scan.py --estimate`. Cache: `cache/etsy_cache.json` (28d TTL).

**Amazon (optional):** Commercial intent + problem/replacement language, not
transaction proof. **Free path** uses Amazon public autocomplete
(`completion.amazon.com`) → `amazon_autocomplete_hits`, persisted
`amazon_suggestions` (unique strings joined by ` | `, max 11; restored from
cache on hit), and `amazon_problem_mention_score` (sample-size shrunk).
**Market Voice** uses those suggestion strings for problem/proof evidence when
complaint terms match. **Optional** `RAINFOREST_API_KEY` adds listing density
+ avg price. No PA-API / invented BSR / Playwright. Estimate:
`python3 amazon_scan.py --estimate`. Cache: `cache/amazon_cache.json` (28d).
Skip: `SKIP_AMAZON=1`. Weights: `amazon_problem_signal` 0.025 +
`amazon_listing_saturation` 0.01 (when listings present).

Facebook actively blocks automated scraping and its ToS prohibits it.
Pinkbike Forum and MTBR Forum were tested directly (July 2026) and both run
JS/session-gated search — neither has a plain keyword-in-URL results page an
unauthenticated script can fetch, the same practical blocker as Facebook.
Rather than build something fragile, do a **5-minute weekly manual check**
across all three: search each source for your keyword list, note roughly
how many threads mention it and how recent they are, in
`facebook_manual_log.csv` (template included, now covers all three sources —
kept the original filename so it stays a single log). Quick links for the
weekly check:

- Facebook: your target groups directly (e.g. Rad Power Bikes Owners)
- Pinkbike: https://www.pinkbike.com/forum/ (use the on-page "Search Forum" box)
- MTBR: https://www.mtbr.com/search/?type=post (Advanced Search page)

If this becomes worth automating later, both forums are Google-indexed, so
a paid SERP API doing a `site:pinkbike.com/forum <keyword>` /
`site:mtbr.com <keyword>` query could replace the manual check without
needing the forums' own (session-gated) search.

## One-time setup

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### Search volume (DataForSEO — recommended first)

1. Create an account at https://app.dataforseo.com/api-access
2. Copy login + password into `.env`:
   ```bash
   cp .env.example .env
   # DATAFORSEO_LOGIN=...
   # DATAFORSEO_PASSWORD=...
   ```
3. Estimate cost (no charge), then run:
   ```bash
   python3 search_volume_scan.py --estimate
   python3 search_volume_scan.py              # Standard queue (cheaper, may take minutes)
   # python3 search_volume_scan.py --live     # faster, higher cost
   ```

Keywords are cached under `cache/search_volume_cache.json` (default TTL **7 days**).
A full product list is typically **one task** (≤1000 keywords) ≈ **$0.05** on Standard
queue when the cache is cold; weekly re-runs cost $0 while the cache is fresh.

Outputs:
- `out/search_volume_signal.csv` — one row per product (`search_volume` = max monthly volume)
- `out/search_volume_keywords.csv` — one row per keyword (audit)

Optional per-product override in `config/products.yaml`:
`search_volume_keywords: [...]` (else uses `keywords`).

### Reddit data (optional — off in the weekly pipeline)

Reddit is **not** part of the default `./run_all.sh` path (PullPush waits
and flaky 429s used to stall the weekly job). Scoring already redistributes
tiny Reddit weights when the signal is empty; Dashboard chips show Reddit
inactive/skipped.

**Opt in for a full pipeline run:**

```bash
INCLUDE_REDDIT=1 ./run_all.sh
INCLUDE_REDDIT=1 WAIT_FOR_PULLPUSH=1 ./run_all.sh   # poll PullPush first
INCLUDE_REDDIT=1 REDDIT_BACKEND=praw ./run_all.sh   # needs approved creds
```

**Or run the scanner alone:**

```bash
python3 reddit_scan.py                  # PullPush backend
python3 reddit_scan.py --per-subreddit  # slower, more thorough
python3 reddit_scan.py --delay 5        # if you hit rate limits (HTTP 429)
python3 reddit_scan.py --write-empty    # zeros only (what weekly skip writes)

# If PullPush is down / rate-limiting:
python3 wait_for_pullpush.py            # polls, then reddit_scan.py --delay 5
python3 wait_for_pullpush.py --check-only
```

**Status in 2026 (often degraded):**
- **PullPush** — volunteer archive; frequently 429s / lags live Reddit by
  weeks–months. Fine as a manual research tool, not a reliable weekly carrier.
- **Official Reddit API (PRAW)** — **approval-gated** under the Responsible
  Builder Policy (manual review). Not a quick self-serve signup; do not plan
  on “register in five minutes.” Unauthenticated `reddit.com/.../.json`
  bulk access is effectively dead.
- After approval: create a “script” app at https://www.reddit.com/prefs/apps,
  set `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` / `REDDIT_USER_AGENT` in
  `.env`, then `python3 reddit_scan.py --backend praw`.

## Running it

```bash
./run_all.sh
```

Or run stages individually — useful while you're tuning `config/products.yaml`:

```bash
python3 search_volume_scan.py --estimate
python3 search_volume_scan.py           # DataForSEO (needs credentials)
python3 trends_scan.py
python3 marketplace_scan.py             # listing counts (competition)
python3 printables_cults_scan.py        # downloads / makes / likes (demand)
python3 x_scan.py                       # API if X_BEARER_TOKEN set, else manual log
# python3 reddit_scan.py                # optional
python3 score_demand.py
```

Pipeline env knobs: `SKIP_SEARCH_VOLUME=1`, `SKIP_COMMUNITY=1`, `SKIP_X=1`,
`SKIP_AMAZON=1`, `INCLUDE_REDDIT=1` (Reddit is **off** unless set).

## Local 3D printing *service* keywords (city-level)

Separate from product demand: discovers how people search for a **local 3D
printing / prototype / small-batch service** in a metro area (default
**Phoenix, AZ**).

```bash
python3 local_service_keywords_scan.py --estimate
python3 local_service_keywords_scan.py                    # Phoenix default
python3 local_service_keywords_scan.py --city "Austin, TX"
python3 local_service_keywords_scan.py --force            # ignore 14-day cache
python3 local_service_keywords_scan.py --top 15
```

Uses DataForSEO Google Ads **Keywords For Keywords** (Standard queue, ~one
task) plus a seed **Search Volume** task so exact service phrases are covered.
Same `DATAFORSEO_LOGIN` / `DATAFORSEO_PASSWORD` as the product volume scan.

| Config | File |
|---|---|
| City, seeds, TTL, top_n | `config/local_service.yaml` |
| Cache | `cache/local_service_keywords/{city}.json` (default 14 days) |
| Output | `out/local_service_keywords_{city}.json` + `.csv` |

Output columns: `keyword`, `search_volume`, `competition`, `cpc`, location,
timestamp — easy to open in a spreadsheet or load in future reports. Does
**not** feed `score_demand.py` (product ranking stays separate).

### Full local market pack (keywords + questions + competitors)

```bash
python3 local_service_market_scan.py --estimate
python3 local_service_market_scan.py                 # Phoenix default
python3 local_service_market_scan.py --city "Austin, TX"
python3 local_service_market_scan.py --paa-limit 3
python3 local_service_market_scan.py --skip-maps     # keywords + PAA only
```

Adds on top of the keyword scan:

1. **Intent-tagged related keywords** (near_me, online, process, prototype, …)
2. **People Also Ask** via DataForSEO Google Organic SERP (live)
3. **Local competitors** via DataForSEO Google Maps SERP (name, rating, reviews)

| Output | Contents |
|---|---|
| `out/local_service_market_{city}.json` | Full structured market report |
| `out/local_service_market_{city}.md` | Human-readable summary |

Same DataForSEO credentials. Keyword data is reused from cache when fresh;
PAA/Maps are cached under `cache/local_service_market/` (TTL from config).

### Community engagement (Printables + Cults + MakerWorld + Thangs)

```bash
python3 printables_cults_scan.py --estimate
python3 printables_cults_scan.py           # all products / all platforms
python3 printables_cults_scan.py --smoke   # first product only
python3 printables_cults_scan.py --top 5 --delay 2
python3 printables_cults_scan.py --skip-thangs   # if Cloudflare blocks Thangs
# → out/printables_cults_signal.csv
```

For each product, searches by `marketplace_keywords` (else broader keywords;
optional `makerworld_keywords` / `thangs_keywords`), samples the top N models
per site, and sums **downloads / makes / likes**. Soft-fails **per platform**
so one site down does not kill the community row. MakerWorld/Thangs results
are cached under `cache/community_platforms_cache.json` (28d TTL). Per-run
platform coverage (ok/skipped/error per site) is written to
`out/community_platforms_meta.json` for the Dashboard coverage chip.

| Site | How stats are collected |
|---|---|
| **Printables** | Search HTML → model ids → public GraphQL for stats. HTML search is often Cloudflare-fingerprinted for plain `requests`; optional **`curl_cffi`** (Chrome impersonation) can recover it when the block is TLS/JA3-only. GraphQL stats at `api.printables.com` are **not** challenged. |
| **Cults3D** | Search HTML → model pages → parse metrics |
| **MakerWorld** | Public JSON `search/design` API (`downloadCount`, `printCount`, `likeCount`) |
| **Thangs** | Best-effort HTML; same optional `curl_cffi` path as Printables. Still soft-fails (zeros + note) if CF returns a managed challenge/Turnstile. |

`community_downloads` / `community_makes` / `community_likes` = sum across
platforms and feed existing community weights in scoring (no new big weights).

**Optional `curl_cffi`:** `pip install curl_cffi` (also in `requirements.txt`).
Improves Printables/Thangs HTML search against Cloudflare *fingerprint*
blocking. Without it, those platforms soft-fail as before. This is **not** a
guaranteed bypass — escalated challenges can still block.

**Operating policy:** MakerWorld + Cults remain the most reliable carriers when
Printables/Thangs are blocked. Soft-fail keeps the community row scoring on
remaining platforms. Durable long-term for Printables is GraphQL-based search
(if/when exposed), not HTML.

Output: `out/demand_report.csv`, ranked highest-demand-score first, plus a
printed table in the terminal.

## X (Twitter) signal

X no longer has a practical free search tier for new developers (pay-per-use
as of 2026 — check [developer.x.com](https://developer.x.com) for current
Post-read rates). This tool supports two paths:

```bash
# Cost ceiling for the current product list (no API calls):
python3 x_scan.py --estimate

# API path — set X_BEARER_TOKEN in .env first
python3 x_scan.py --backend api

# Manual path — fill x_manual_log.csv weekly (no spend)
python3 x_scan.py --backend manual

# Skip X in the full pipeline
SKIP_X=1 ./run_all.sh
```

Config (`config/products.yaml` → `x:`):

- `brand_accounts` — e.g. `RadPowerBikes` (queries `from:` / `@` for matching categories)
- `brand_categories` — only those product categories get brand-scoped queries
- `max_results` — keep at 10 to bound weekly cost
- Per-product `x_keywords` — tighter phrases than Reddit discovery keywords

When X is all zeros, `score_demand.py` redistributes X's weight to the other
signals so empty X data does not flatten the ranking.

## Recommended cadence

- **Weekly**: run the full pipeline (`./run_all.sh`).
- **macOS schedule** (launchd, Sundays 09:15 by default):

  ```bash
  ./scripts/install_weekly_schedule.sh
  # WEEKDAY=1 HOUR=8 MINUTE=0 ./scripts/install_weekly_schedule.sh  # Monday 08:00
  ./scripts/install_weekly_schedule.sh --uninstall
  ```

  Logs land in `out/logs/weekly.stdout.log` and `weekly.stderr.log`.

- **Adding products**: edit `config/products.yaml` — add a product block
  with `keywords` (discovery) and preferably `marketplace_keywords`
  (tighter competition queries). Optional `x_keywords` for X.
- **When the demand_score for something new crosses ~70+** with rising
  Trends momentum and low marketplace saturation: that's your signal to
  prototype it.

## Marketplace competition scan

```bash
python3 marketplace_scan.py           # all products
python3 marketplace_scan.py --smoke   # first product only (debug adapters)
python3 marketplace_scan.py --delay 3
# → out/marketplace_signal.csv
```

| Marketplace | How counted | Notes |
|---|---|---|
| **Printables** | Page total ("N models"), else unique `/model/` ids | Most reliable |
| **Cults3D** | Title total ("N search results") | Good second signal |
| **Thangs** | Page total ("N Model(s)") | Occasional 403/CF |
| **MakerWorld** | Best-effort JSON API | Disabled by default — unauth API ignores keywords (would fake 0 or 10k) |

`ERR` means "couldn't measure", **not** zero competition. `score_demand.py`
coerces `ERR` to 0 for math — if a whole column is ERR, marketplace gap
won't differentiate products. Re-run or disable that marketplace in config.

Add/disable sources in `config/products.yaml` under `marketplaces`. Built-in
adapters: `printables`, `cults`, `thangs`, `makerworld`. Generic sites can use
`adapter: html` plus `search_url_template`, `result_selector`, and optional
`total_regex` / `id_regex`.

### Keeping competition queries tight

Discovery keywords (good for Reddit) are often too loose for marketplaces
(`"gopro mount"` returns thousands of unrelated listings). Two controls:

1. **`marketplace_keywords` per product** — preferred by `marketplace_scan.py`.
   Keep brand + part-specific tokens (e.g. `rad power phone mount`, not
   `phone mount`).
2. **Specificity filter** — the scanner ignores ultra-generic 1–2 token
   queries when tighter variants exist, and scores competition from the
   best *specific* hit rather than the global max of every shortened form.

## Google Sheets dashboard (weekly Monday view)

After scoring, push rankings into one master spreadsheet:

```bash
# One-time: docs/sheets_setup.md (service account + share sheet)
python3 export_to_sheets.py --dry-run   # preview without Google API
python3 export_to_sheets.py             # live export
```

Wired as the **last step** of `./run_all.sh` when:

```bash
GOOGLE_SERVICE_ACCOUNT_JSON=/path/to/sa.json
GOOGLE_SHEETS_SPREADSHEET_ID=your_spreadsheet_id
```

Skip: `SKIP_SHEETS=1 ./run_all.sh`.  
Tabs: Dashboard, Product Rankings, Scoring Detail, Market Voice, Search Volume, Marketplace,
Local Service (Phoenix), History (append-only), Config.  
Spec: `docs/sheets_dashboard_spec.md`. Setup: `docs/sheets_setup.md`.

## Scoring: Demand quality × Fit × Opportunity

`score_demand.py` ranks products for *this stage of the business* (own
products, Bambu FDM, low support), not raw Google volume alone.

| Score | Meaning |
|---|---|
| **demand_score** | Quality-weighted pull: intent, specificity, problem intensity, log-volume×specificity, community, trends, optional Etsy / eBay / Amazon / YouTube / X / Reddit |
| **fit_score** | Manufacturing + customer clarity: FDM-friendly, materials, clear buyer, low support burden |
| **competition_score** | Listing counts + ads competition + incumbent downloads |
| **opportunity_score** | Demand vs competition (market whitespace) |
| **priority_score** | **Primary rank** = opportunity × fit |

```bash
python3 score_demand.py
# → out/demand_report.csv  (sorted by priority_score)
```

Demand quality factors are **rule-based and visible**:
`contrib_demand_intent`, `contrib_demand_specificity`,
`contrib_demand_volume_quality`, etc., plus `intent_notes` /
`specificity_notes` / `fit_flags`.

Broad high-volume terms (e.g. “car phone holder”) are **penalized** on
specificity/intent so they don’t dominate. Etsy / eBay / YouTube / X / Reddit
are optional and dropped when empty (weights redistribute). Marketplace and
social optional signals are dampened by specificity so generic hits don’t
dominate ranking.

Optional per-product fit overrides in `config/products.yaml`:

```yaml
fit:
  fdm_fit: 90
  material_fit: 85
  customer_clarity: 95
  support_burden: 90   # high = low support burden
```

Tune constants at the top of `score_demand.py`: `DEMAND_WEIGHTS`,
`FIT_WEIGHTS`, `PRIORITY_FIT_FLOOR`, etc.

**Reading results:** high **priority** = quality demand + thin competition +
good FDM/customer fit. High volume alone is not enough.

## Extending it later

- **Planned next signals** (eBay sold listings, Etsy, expanded maker platforms, etc.): see [`docs/future_signals.md`](docs/future_signals.md).
- Add more subreddits in `config/products.yaml` — no code changes needed.
- New marketplaces: prefer a built-in adapter, or use `adapter: html` with a
  `search_url_template` + `result_selector` (and `total_regex` when possible).
- If Reddit's free tier ever becomes limiting (unlikely at weekly-scan
  volume), Reddit's paid tier is $0.24/1,000 calls.
- If pytrends breaks (it's an unmaintained wrapper around a private Google
  endpoint), swap in Google's official Trends API (alpha, limited quota) or
  a paid provider like SerpApi's Trends endpoint — same output shape, just
  replace the internals of `trends_scan.py`.
- X brand accounts: add handles under `x.brand_accounts` and map which
  `category` values should receive brand-scoped queries.
