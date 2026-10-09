# Competitive teardown (required above WATCH)

Any Pulse card with `suggested_next` **above** `WATCH` (i.e. `KEEP_HUNTING`, `PRINT_SAMPLE`, `DESIGN`, `SHOPIFY`) **must** have a competitive teardown. No teardown → cannot claim opportunity (treat as `NEEDS DATA` / stay `WATCH`).

## Fields (CSV companion or JSON)

Path options (UI may ingest either):

- `data/teardowns/YYYY-MM-DD.csv` (one row per `opportunity_id`)
- `data/teardowns/{opportunity_id}.json`
- Additive columns on opportunities (optional): `teardown_status`, `teardown_ref`

| Field | Required | Notes |
| --- | --- | --- |
| `opportunity_id` | yes | Stable id |
| `product_key` | yes | |
| `teardown_status` | yes | `COMPLETE` \| `PARTIAL` \| `NEEDS DATA` |
| `sellers_json` | yes | JSON array of `{name,channel,url,price}` — use `[]` + NEEDS DATA if unknown |
| `price_band` | yes | e.g. `$12–$28` or `NEEDS DATA` |
| `materials_fit_claims` | yes | Short text or `NEEDS DATA` |
| `review_complaints` | yes | Short text or `NEEDS DATA` |
| `somo_differentiator` | yes | Concrete SoMo angle or `NEEDS DATA` |
| `run_id` | yes | |
| `ts` | yes | |

**Gate:** `suggested_next` ∈ {KEEP_HUNTING, PRINT_SAMPLE, DESIGN, SHOPIFY} requires `teardown_status` ≠ empty. If `teardown_status=NEEDS DATA` for all differentiator fields, UI must not badge as opportunity — show NEEDS DATA.

See also `competitive_teardown.schema.json`.
