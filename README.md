# Demand Monitor

Scores candidate 3D-printed products by real demand signal before you spend
filament and time on them: Reddit conversation volume/engagement, Google
Trends search interest, and existing marketplace competition/saturation.

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
| Reddit posts/upvotes/comments mentioning a keyword | Yes | `reddit_scan.py` (PullPush by default; PRAW optional) |
| Google Trends relative search interest + momentum | Yes | `trends_scan.py` (pytrends) |
| Existing listing count on Printables / Cults / Thangs (+ MakerWorld best-effort) | Yes | `marketplace_scan.py` |
| Facebook Group discussion volume | **No — manual** | see below |
| Pinkbike Forum discussion volume | **No — manual** | see below |
| MTBR Forum discussion volume | **No — manual** | see below |

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

### Reddit data (two backends)

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
python3 reddit_scan.py                  # PullPush default, no credentials
# python3 reddit_scan.py --backend praw # after Reddit API approval
python3 trends_scan.py
python3 marketplace_scan.py
python3 score_demand.py
```

Output: `out/demand_report.csv`, ranked highest-demand-score first, plus a
printed table in the terminal.

## Recommended cadence (keeps you inside free API limits)

- **Weekly**: run the full pipeline (`./run_all.sh`), 5 minutes, scheduled
  via cron or your OS task scheduler.
- **Adding products**: edit `config/products.yaml` — add a product block
  with its own keyword list and it's automatically included in the next run.
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

## Tuning the scoring

Open `score_demand.py` and adjust the `WEIGHTS` dict at the top — e.g. if
you want to chase pure whitespace opportunities over proven high-volume
items, raise `marketplace_gap` and lower `reddit_engagement`.

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
