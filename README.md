# Demand Monitor

Scores candidate 3D-printed products by real demand signal before you spend
filament and time on them: Reddit conversation volume/engagement, Google
Trends search interest, marketplace competition/saturation, and optional
X (Twitter) chatter.

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
| Printables + Cults downloads / makes / likes | Yes | `printables_cults_scan.py` (community demand) |
| Existing listing count on Printables / Cults / Thangs | Yes | `marketplace_scan.py` (competition count) |
| Google Trends relative search interest + momentum | Yes | `trends_scan.py` (pytrends) |
| X / Twitter keyword + brand-account chatter | Yes (API) or manual | `x_scan.py` — needs `X_BEARER_TOKEN` or `x_manual_log.csv` |
| Reddit posts/upvotes/comments | Optional / unreliable | `reddit_scan.py` (PullPush default; PRAW optional). Skip with `SKIP_REDDIT=1` |
| Facebook / Pinkbike / MTBR | **No — manual** | `facebook_manual_log.csv` |

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

### Reddit data (two backends, optional)

**Default: PullPush** — no Reddit API credentials. Uses the public
[PullPush](https://pullpush.io/) archive to keyword-search submissions in your
configured subreddits. Good enough for weekly demand ranking while Reddit's
API approval is pending.

```bash
python3 reddit_scan.py                  # same as --backend pullpush
python3 reddit_scan.py --per-subreddit  # slower, more thorough for generic keywords
python3 reddit_scan.py --delay 5        # if you hit rate limits (HTTP 429)

# If PullPush is down / rate-limiting, wait until healthy then scan:
python3 wait_for_pullpush.py            # polls, then reddit_scan.py --delay 5
python3 wait_for_pullpush.py --full-pipeline   # then ./run_all.sh
python3 wait_for_pullpush.py --check-only      # one-shot health check
python3 wait_for_pullpush.py --timeout 7200 --interval 60
python3 wait_for_pullpush.py -- --per-subreddit   # extra args to reddit_scan.py
```

Caveats: PullPush is a volunteer archive. Index freshness can lag live Reddit
(sometimes by weeks/months). The scanner probes the archive tip and, if the
tip is older than `reddit_lookback_days`, scores the most recent lookback
window of *indexed* data so relative product rankings still work. Prefer the
official API once approved.

PullPush also rate-limits shared traffic. The scanner backs off and retries on
HTTP 429; if a run still comes back all zeros, wait a few minutes and re-run
with `--delay 5` (or higher), or use `wait_for_pullpush.py` so it polls for
you. Weekly cadence is the intended use.

**Optional: official Reddit API (PRAW)** — requires approval under Reddit's
Responsible Builder Policy (manual review; no longer self-serve):

1. Get approved API access, then create a "script" app at
   https://www.reddit.com/prefs/apps
2. Redirect URI: `http://localhost:8080` (required field, unused)
3. Copy `.env.example` to `.env` and fill in the three values:
   ```bash
   cp .env.example .env
   # then edit .env with your client ID, secret, and user agent
   ```
   `.env` is gitignored, so credentials never get committed. `reddit_scan.py`
   loads it automatically via `python-dotenv`.
4. Run with the praw backend:
   ```bash
   python3 reddit_scan.py --backend praw
   ```

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

Pipeline env knobs: `SKIP_SEARCH_VOLUME=1`, `SKIP_COMMUNITY=1`, `SKIP_REDDIT=1`, `SKIP_X=1`.

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

### Printables + Cults engagement (community demand)

```bash
python3 printables_cults_scan.py           # all products
python3 printables_cults_scan.py --smoke   # first product only
python3 printables_cults_scan.py --top 5 --delay 2
# → out/printables_cults_signal.csv
```

For each product, searches by `marketplace_keywords` (else broader keywords),
samples the top N models on each site, and sums **downloads / makes / likes**.

| Site | How stats are collected |
|---|---|
| **Printables** | Search HTML → model ids → public GraphQL (`downloadCount`, `makesCount`, `likesCount`) |
| **Cults3D** | Search HTML → model pages → parse download/like/make text |

`community_downloads` / `community_makes` / `community_likes` feed scoring as
demand-side engagement (separate from listing *counts* in `marketplace_scan.py`).

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

## Scoring: Demand vs Competition vs Opportunity

`score_demand.py` produces three scores per product (all 0–100):

| Score | Meaning | Built from |
|---|---|---|
| **demand_score** | How strong is the pull? | Search volume, Printables/Cults downloads·makes·likes, Trends, X; Reddit only if present (tiny weight, dropped when empty) |
| **competition_score** | How crowded is supply? | Marketplace listing counts, Google Ads competition index, incumbent download strength |
| **opportunity_score** | **Primary rank** — demand relative to competition | Blend of `demand/(competition+floor)` and `demand × whitespace` |

```bash
python3 score_demand.py
# → out/demand_report.csv  (sorted by opportunity_score)
```

Each row includes transparent contribution columns (`contrib_demand_*`,
`contrib_competition_*`) and a short `score_explanation` string.

Tune weights in `score_demand.py`:

- `DEMAND_WEIGHTS` / `COMPETITION_WEIGHTS`
- `OPPORTUNITY_COMPETITION_FLOOR` (default 12)
- `OPPORTUNITY_RATIO_BLEND` (default 0.65 toward pure ratio)

**Reading results:** high opportunity = real demand with relatively thin
competition. High demand + high competition = validated market but harder
to win (e.g. generic car phone mounts). Low demand + low competition =
quiet niche — only interesting if you already know the pain point.

## Extending it later

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
