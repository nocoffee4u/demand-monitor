# Invent candidates (OEM cargo OOS + buyer talk)

Loud OEM **out-of-stock** cargo themes become invent candidates **only when buyer talk exists** (FB/EBR/rider hangouts WTB or DIY workaround — not YT install alone).

Path: `data/invent/invent_candidates_YYYY-MM-DD.csv`

Columns:

`candidate_id,product_key,brand,oem_handle,oem_title,oem_price,oem_status,pain,buyer_evidence_count,buyer_sources_json,howto_only_count,unmet_demand,competition_density,suggested_next,summary,url,run_id,ts`

`candidate_id` = `inv-` + sha256(product_key|oem_handle)[:8] (stable).

Honesty rule: if buyer evidence is thin (carry-forward weekly theme only, no fresh WTB quotes), keep `suggested_next=WATCH` / `KEEP_HUNTING` and say so in `summary` — do not invent demand.
