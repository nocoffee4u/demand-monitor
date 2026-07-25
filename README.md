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
| Reddit posts/comments/upvotes mentioning a keyword | Yes | `reddit_scan.py` (PRAW) |
| Google Trends relative search interest + momentum | Yes | `trends_scan.py` (pytrends) |
| Existing listing count on Printables / MakerWorld | Yes (generic HTML scan) | `marketplace_scan.py` |
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

Reddit API credentials (free, ~5 min):
1. https://www.reddit.com/prefs/apps → "create another app..." → type "script"
2. Redirect URI: `http://localhost:8080` (required field, unused)
3. Copy `.env.example` to `.env` and fill in the three values:
   ```bash
   cp .env.example .env
   # then edit .env with your client ID, secret, and user agent
   ```
   `.env` is gitignored, so credentials never get committed. `reddit_scan.py`
   loads it automatically via `python-dotenv`. If you'd rather not use a
   file, exporting the same three variables as environment variables works
   too:
   ```bash
   export REDDIT_CLIENT_ID=xxxx
   export REDDIT_CLIENT_SECRET=xxxx
   export REDDIT_USER_AGENT="yourshopname-demand-scan/0.1 by u/yourusername"
   ```

## Running it

```bash
./run_all.sh
```

Or run stages individually — useful while you're tuning `config/products.yaml`:

```bash
python3 reddit_scan.py
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

## Tuning the scoring

Open `score_demand.py` and adjust the `WEIGHTS` dict at the top — e.g. if
you want to chase pure whitespace opportunities over proven high-volume
items, raise `marketplace_gap` and lower `reddit_engagement`.

## Extending it later

- Add more subreddits or marketplaces in `config/products.yaml` — no code
  changes needed for new subreddits; new marketplaces just need a
  `search_url_template` and a CSS `result_selector`.
- If Reddit's free tier ever becomes limiting (unlikely at weekly-scan
  volume), Reddit's paid tier is $0.24/1,000 calls.
- If pytrends breaks (it's an unmaintained wrapper around a private Google
  endpoint), swap in Google's official Trends API (alpha, limited quota) or
  a paid provider like SerpApi's Trends endpoint — same output shape, just
  replace the internals of `trends_scan.py`.
