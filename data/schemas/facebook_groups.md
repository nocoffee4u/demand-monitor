# Facebook group listen registry (updated 2026-10-05)

Read-only weekly listen on Grant's **personal** Meta session on the box (never SoMo / @somomfg brand accounts).
Coverage is **5 weekly groups + 1 monthly group** (no longer 3 groups).
The `facebook_manual` row in the weekday Source Health file rolls up this listen.

## Source keys

From 2026-10-05, per-group rows in `data/source_health/YYYY-MM-DD_fb_weekly.*` and `source` on `sig-fb-*` signals use
**`fb_<numeric group id>`**. The three original groups were keyed `facebook_rpboc` / `facebook_upgrades` / `facebook_aventon`
through 2026-09-28. Those are **legacy aliases** (`legacy_key`) for history and UI mapping. Do not reuse them for new rows.

| source key | legacy_key | Group | URL | cadence | pass |
| --- | --- | --- | --- | --- | --- |
| `fb_1654952334789041` | `facebook_rpboc` | Rad Power Bikes Owners Community | https://www.facebook.com/groups/rpboc | weekly | full scroll |
| `fb_629167654165317` | `facebook_upgrades` | Rad Power Bike Upgrades | https://www.facebook.com/groups/629167654165317 | weekly | full scroll |
| `fb_860508022428626` | `facebook_aventon` | Aventon Bikes | https://www.facebook.com/groups/860508022428626 | weekly | full scroll. First-party (Aventure 2) + competitive/generic |
| `fb_333458264803610` | — | Aventon Aventure Owners (`aventureowners`) | https://www.facebook.com/groups/aventureowners | weekly (added 2026-09-30) | longer scroll budget: chronological, ~60 top-level posts or ~7 days back, plus group search (basket, visor/glare, mount, rack, fender, cup holder, clip/clamp). A tiny loaded sample is `PARTIAL`, never NOTHING_NEW |
| `fb_2677348212546303` | — | Rad Power Bike Troubleshooters | https://www.facebook.com/groups/2677348212546303 | weekly (moved 2026-09-30) | **keyword pass only**: clamp, clip, mount, cover, broken plastic, cracked, snapped, replacement part (~last 7 days). Electrical/battery/brake repair is log-only |
| `fb_746195242754268` | — | eBikes All Brands Group (`ebikesallbrandsgroup`) | https://www.facebook.com/groups/ebikesallbrandsgroup | **monthly** (first Monday, day 1–7) | WATCH pass. Hits tagged `monthly_watch` + `transferable-generic`. Status `NOT_DUE` on other Mondays |

The rpboc numeric id `1654952334789041` comes from the Boss/UI registry (`fb_sources.json`, 2026-09-30).

**Skipped by Boss (do not scan):** Aventon Aventure 3, Aventon Ebike Owners - East Coast, EMTB mid-drive builders.

## Artifacts (branch `bot/signal-hunt` only)

| Artifact | Path | Notes |
| --- | --- | --- |
| Themes | `data/themes/YYYY-MM-DD_fb.csv` + `.json` | `theme.schema.json`. Max ~3 themes total across groups (monthly hits don't count unless clear) |
| Per-group health | `data/source_health/YYYY-MM-DD_fb_weekly.csv` + `.json` | One row per group (6 rows, monthly `NOT_DUE` when not due) + `facebook_groups` roll-up row |
| Signals | `sig-fb-*` rows appended to `data/signals/YYYY-MM-DD.jsonl` + `.csv` | `source` = `fb_<id>` |
| Weekday roll-up | `facebook_manual` row patched in `data/source_health/YYYY-MM-DD_weekday.csv` + `.json` | Detail should say 5 weekly + 1 monthly |

`_fb_weekly.csv` keeps the original leading columns `date,source,status,detail`. Optional columns may be added after them:
`group_name,group_id,cadence,legacy_key,url,posts_loaded,search_hits`.

FB-weekly statuses: the standard set (`OK|STALE|BLOCKED|AUTH|EMPTY_UNEXPECTED|SKIPPED`) plus `PARTIAL` (readable but too few posts
loaded) and `NOT_DUE` (monthly group on a non-first Monday). A group showing Pending / not Joined is `SKIPPED` with a reason.
None of these counts as NOTHING_NEW.
