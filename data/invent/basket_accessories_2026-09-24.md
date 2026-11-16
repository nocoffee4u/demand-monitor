# Invent lane: non-load accessories for Rad front baskets (demand + competition check)

- **run_id:** invent-basket-acc-2026-09-24
- **ts:** 2026-09-24 ~22:15 PT (UTC-7)
- **Parent:** teardown opp-5a782a21 (`data/teardowns/opp-5a782a21_2026-09-24.md`). It found the basket and mount are structural (no-go) and only non-load accessories are safe.
- **Owner lead (not counted as demand):** the owner runs a Large FMB on a RadRunner Plus (Silver) and a Small FMB on a RadRunner 3 Plus. He wants a cup holder and better ways to secure and organize things. All scores below use **other buyers' evidence only**.
- **Printer:** Bambu Lab H2S (planned, not purchased). Build volume **340 x 320 x 340 mm** per https://bambulab.com/en-us/h2s.
- **Counting rule:** every count tagged "~" is an approximate regex keyword tally over review text. Named quotes were read by hand. Nothing here is invented. Reddit results showed up in WebSearch snippets and were **excluded** per policy.

## TL;DR

| Idea | product_key / opp id | Demand (other buyers) | Competitor price band | Rad-specific competitor? | H2S printability | Liability | suggested_next |
|---|---|---|---|---|---|---|---|
| 1. Cup / bottle holder in or on the basket | `rad_basket_cup_holder` / opp-c5313620 | **THIN–MODERATE.** 9 hand-read items: 2 explicit "wants" in ~2,285 Rad basket reviews, 4 workarounds, 1 bottle-fell-out, 1 EBR 2019 WTB-ish. Rad's own handlebar Water Bottle Holder has ~24 mount/location complaints (3.86★, 394 reviews) | Basket-specific $18.50–$41.98 (Etsy PLA $18.50, Amazon PETG clip $25.60, Etsy leather $41.98). Universal bar/stroller holders $4.99–$32.99. Free STLs on MakerWorld/Thingiverse | **No paid Rad-basket cup holder found.** Rad-frame (bottle-boss) holders exist: Etsy bracket $31.98, GZila $45, Ride And Carry Stanley $49.95. One free MakerWorld model adapts a clamp to "~12 mm … basket on a Rad Powered Bike" | Easy (≈Ø90–110 mm cup + rail clip, single part). PETG/ASA | LOW, if it stays inside the basket envelope, clears the headlight beam and the handlebar/brake-line sweep, and adds no load to the bike | **KEEP_HUNTING** |
| 2. Divider / organizer / small-item bin or tray | `rad_basket_divider_organizer` / opp-a9020bd9 | **MODERATE for "small items fall out or through"**: ~20 hand-read explicit asks + DIY fixes (6 on the FMBs, the rest on the rack-mounted Large/Small Basket). **THIN for "divider"** (~2 keyword hits, 0 explicit asks) | Soft liners/bags $6.99–$65.25 (Rad bag $47, Rad roll-top liners $51.75/$65.25, Line and Ride Rad-fit liners $34.99–$39.99, Topeak rigid-basket inner pad $24.27). **No rigid printed Rad insert found** | **Yes, but soft only:** Rad OEM bags/liners (in stock) and Line and Ride "Rad Power SMALL FRONT MOUNT Basket ONLY" liners. No rigid/printed Rad inserts found | Medium. Full-floor trays exceed the bed on the Large FMB (outer 346x536 mm) and Large Basket (12x19.5 in ≈ 305x495 mm), so it has to be modular bins ≤ ~320 mm. SFMB outer is 348 mm long, so the inner size must be measured | LOW. It sits inside the basket and carries only the items in it. Needs anti-rattle feet (hard plastic noise is a stated buyer concern) | **DESIGN (gated)**: modular drop-in small-item bin(s), after owner measurements |
| 3. Cargo securing: tie-down anchors / hooks / anti-bounce stops | `rad_basket_cargo_tiedown` / opp-6772fd7a | **MODERATE.** Rad Cargo Net reviews: ~18 of 177 about hooks breaking, falling off, being too big for the basket or not fitting the wood/rail. Straps: 2 fit complaints on the FMB bars. LFMB: "top rim … too bulky for the cargo net". Bounce-out even when bungeed: 1 | Nets with hooks $6.93–$25 (Amazon). Rad Cargo Net $15, Rad Cargo Straps $18.75 (3-pack). Free printable replacement hooks on MakerWorld | **Rad OEM net/straps are "sized for Rad racks"** but draw the fit complaints. No aftermarket Rad-basket anchor/hook found | Easy (small parts). PETG/ASA, maybe a stronger material after pull tests | **MEDIUM.** It's a cargo restraint under bungee tension. A failure can snap the hook back or drop cargo, and a front-basket item could fall toward the front wheel. Not bike-structural | **KEEP_HUNTING** (low ceiling ~$8–15, liability testing needed). Could bundle clips with idea 2 |

**Bottom line:** the strongest real buyer signal isn't the cup holder. It's **"small stuff slips out or falls through, and metal items rattle."** Soft liners already answer much of it, including Rad's own and a Rad-specific Amazon seller. A **rigid, Rad-exact, modular drop-in bin with TPU anti-rattle feet**, sized for both FMBs, is the one idea with evidence beyond the owner and room to differentiate. The cup holder is a cheap add-on SKU to that bin (a cup-holder module that locks into the bin or clips on the rail), not a stand-alone hero.

---

## 1. Demand

### 1a. Rad reviews (Yotpo public widget feed; all stars, not just 1–3★)
Feed: `https://api-cdn.yotpo.com/v1/widget/<store key from product page>/products/<shopify id>/reviews.json?per_page=150&page=N&star=S`. Product IDs come from https://www.radpowerbikes.com/products.json (read 2026-09-24 ~22:06 PT).

| Product (Rad page) | Shopify id | Price / stock (products.json) | Yotpo bottomline | Unique reviews read |
|---|---|---|---|---|
| Large Front-Mounted Basket https://www.radpowerbikes.com/products/large-front-mounted-basket | 6631201439840 | $119, **available=false** | 265, 4.28 | 270 |
| Small Front-Mounted Basket https://www.radpowerbikes.com/products/small-front-mounted-basket | 6656718372960 | $89, in stock | 223, 4.39 | 248 |
| Large Basket (Front Rack / rear rack) https://www.radpowerbikes.com/products/large-basket | 376110153759 | $119, in stock | 1006, 4.29 | 1057 |
| Small Basket (rack-mounted; context) https://www.radpowerbikes.com/products/small-basket | 6588872687712 | $89, in stock | 752, 4.59 | 710 |
| Cargo Net https://www.radpowerbikes.com/products/cargo-net | 6546367381600 | $15 (compare $20), in stock | 177, 4.06 | 177 |
| Cargo Straps https://www.radpowerbikes.com/products/cargo-straps | 6546362269792 | $18.75 (compare $25), in stock | 249, 4.57 | 256 |
| Water Bottle Holder https://www.radpowerbikes.com/products/water-bottle-cage | 4652398280800 | $20, in stock | 411, 3.86 | 394 |

*Why "read" differs from bottomline:* the plain paginated feed skipped reviews (it returned only 815 of 1006 for the Large Basket, with no 3★). Pulling each star level separately (`&star=1..5`) recovered more, sometimes a few more than the bottomline total. Treat all totals as approximate.

**Geometry note (the Large Basket differs):** Large FMB = 13.6 x 21.2 x 6.4 in, aluminum siding, **wood bottom**, head-tube 4-point mount, 22 lb. Small FMB = 10.6 x 13.7 x 5.5 in, aluminum siding, wood bottom, 22 lb, "Not compatible with the Pet Basket Liner". Large Basket = **12 x 19.5 x 5.5 in**, aluminum, **open-bar floor**, needs the Front Rack (or a rear rack), and Rad says mount it perpendicular only. Small Basket = 12 x 9 x 5.5 in, rack-mounted. So a Large-Basket insert is a **different SKU** from a Large-FMB insert. (All from the product pages above.)

**Approximate theme tallies (regex over title+body; ~ = approximate):**

| Theme | Large FMB (270) | Small FMB (248) | Large Basket (1057) | Small Basket (710) | Cargo Net (177) | Cargo Straps (256) | Water Bottle Holder (394) |
|---|---|---|---|---|---|---|---|
| Drink words (cup/coffee/drink/bottle/beverage…) | ~6 | ~6 | ~13 | ~12 | ~1 | ~1 | ~167 |
| Explicit cup-holder want or drink fell out | ~0 | ~2 | ~4 | ~0 | 0 | 0 | ~5 |
| Bounce / fly / pop / fall / slide out | ~9 | ~8 | ~14 | ~6 | ~4 | ~2 | ~16 |
| Small items fall through / need insert-liner-bottom (includes liner mentions, so inflated) | ~7 | ~9 | ~52 | ~30 | ~5 | ~1 | ~1 |
| Uses or needs bungee / net / straps | ~13 | ~10 | ~47 | ~26 | ~61 | ~112 | ~1 |
| Rattle / noise | ~7 | ~2 | ~21 (mostly weld defects) | ~2 | 0 | 0 | ~2 |
| Sides too low / shallow | ~3 | ~3 | ~5 | ~8 | 0 | 0 | 0 |
| Organize / divider / compartment | 0 | 0 | ~2 | 0 | 0 | 0 | 0 |
| Phone (excl. "phone support") | 0 | ~2 | ~3 | ~6 | ~1 | ~1 | ~3 |
| Net/strap/hook fit or breakage complaint | ~4 | ~2 | ~1 | 0 | ~18 | ~2 | 0 |

Water Bottle Holder only: mount-location complaints ("no room", "in the way", "catches my feet", "slides down the bar") ~24 (22 of them ≤3★). Bottle size fit (too small, Yeti, 40 oz) ~10. Broke / weld ~27.

**Best buyer quotes (hand-read; review id = Yotpo id on that product page):**
1. Small FMB, 4★, 2025-04-06: "it's roomy enough for a lot of essentials, BUT - it needs a cup holder." (id 696154503) https://www.radpowerbikes.com/products/small-front-mounted-basket
2. Large Basket, 4★, 2025-05-03: "Would like to see a place for water bottle perhaps adjustable clamp system to secure or a small inner basket for small items." (id 703971832) https://www.radpowerbikes.com/products/large-basket
3. Large FMB, 4★, 2024-05-23: "things slips out of the basket sides (bike lock and smaller things) and 2) anything that is metal like a bike lock or water bottle etc makes for a very loud ride! I wish there was an insert to alleviate these two things." (id 584160204) https://www.radpowerbikes.com/products/large-front-mounted-basket
4. Small FMB, 4★, 2025-09-23: "Due to the wide spacing of the bars you really need a bag or basket inside to keep small items from falling through the bars." (id 762822988) https://www.radpowerbikes.com/products/small-front-mounted-basket
5. Cargo Net, 1★, 2023-04-20: "hooks are too big to properly grab at the bottom of the basket and not interfere with wood insert." (id 462907417) https://www.radpowerbikes.com/products/cargo-net
6. Large FMB, 4★, 2023-09-08: "light stuff will literally fly out. I have a cargo net which really helps … BUT- the top rim of the basket is too bulky for the cargo net and I have to fasten it lower." (id 499060948) https://www.radpowerbikes.com/products/large-front-mounted-basket
7. Cargo Straps, 3★, 2022-03-13: "The hooks are also too thick to latch onto the front basket bars in places between the wood and basket frame." (id 346441374) https://www.radpowerbikes.com/products/cargo-straps
8. Large Basket, 5★, 2022-06-04: "Instead of getting an individual cup holder and cell phone holder, I ordered a stroller bag from amazon and attached it to the basket. It holds 2 cups, cellphone, keys" (id 374631404) https://www.radpowerbikes.com/products/large-basket
9. Water Bottle Holder, 2★, 2024-10-25: "I just put my water bottle in my front basket because it's so much easier to use when I'm riding." (id 642632379) https://www.radpowerbikes.com/products/water-bottle-cage

**Other hand-read evidence used in counts:**
- *Cup (idea 1):* Large Basket 5★ 2022-09-03, basket design lets you "attach multiple items to it including cupholders" (399383685). Large Basket 5★ 2025-04-21, "some water bottles have fallen out" (700880906). Water Bottle Holder 3★ 2022-12-25, "needs to be on front of bike / basket area" (427653128).
- *Small items (idea 2):* explicit asks: Large Basket 224309062 ("needs an insert"), 224325059 (neoprene mesh liner suggestion, "should NOT make the irritating vibrating sounds associated with hard plastics"), 512588733, 406548222, 391749354, 414978314. Small FMB 598060319 ("gaping holes … impossible for small items"), 591233618, 608502745. DIY workarounds: Large Basket 608686661 (plywood/plexiglass bottom), 407982179 (put a bottom in), 655124409 (plastic box), 390644323 (drill a plastic tub instead). Small Basket 325309325, 344501927 (screening + leather straps), 325309578 (made a platform), 325309610 (plastic crate).
- *Tie-down (idea 3):* Cargo Net 549760345 ("clips do not secure well to the basket … not designed for cargo to shift in the RAD basket"), 410658923, 387283815, 523553604, 525641776/473731583 (too big for the medium FMB), 395447366, 590410353. Cargo Straps 377459466 ("not sized with or specifically designed for the Front Mounted Basket"). Large FMB 714131011 ("Even after bungeeing things down, they pop out on the bumps"). Plus **positive** Rad-fit praise that the design has to match: Cargo Straps 342095408 ("The hooks fit the rack tubing perfectly and don't gouge the paint").

### 1b. YouTube (Data API: search + videos + commentThreads)
32 Rad basket / Rad accessory / cup-holder / basket-net videos queried; **444 comments** scanned from the 30 with readable comments (comments disabled on 8j_JpAJOpxs and lHHgorMleAk). Approximate keyword hits: straps ~9, ties ~7 (mostly zip-tying baskets to racks, which is structural and ignored), holder ~4, secure ~3, bottle ~3, phone ~3, cup ~2, drink ~2, bungee ~2, coffee ~1, rattle ~1. **No explicit ask for a Rad basket cup holder, divider or tie-down.**
- "If you're delivering food, how do you put the drink so it won't spill??" (2022-10-03) on *Unbelievable! RadRunner Accessories* https://www.youtube.com/watch?v=cxDsOaeL-vU (4,759 views)
- DIY: *Rad Rover Cup Holder (Home made for any size cup)*, 801 views, 2021-05-09. The description says average cupholders don't hold "a coffee cup of any size". https://www.youtube.com/watch?v=8vzCKWxYZn4
- How-to only (0 comments): *Radrunner ebike cupholder install* 1,269 views https://www.youtube.com/watch?v=uKWWtAl29wg ; *Installation – Stanley Cup Holder* (Ride And Carry; RadRunner 2.5" bolt spacing) 870 views https://www.youtube.com/watch?v=hk9vWytfK_A ; *GZila Water Bottle Holder RAD Power Bike* 5,626 views https://www.youtube.com/watch?v=yadWGiZnr_0
- Generic: "what's that neat strap holding the U-lock to the basket at 05:22 ? Need one of those!" (2024-11-02) on garys.projects basket comparison, 92,544 views https://www.youtube.com/watch?v=1wXdtYtl1IU

### 1c. EBR forum (public pages, XenForo `/search/search?keywords=`)
Thin. Hits:
- 2019-09-26: "I've been trying to get one of those cup holder thingies" from mri-denver.com's Rad add-ons (WTB-ish; the shop no longer resolves) https://forums.electricbikereview.com/threads/accessories-for-rad-powerbikes-on-mri-denver-com.30003/
- 2019-08-07: RadWagon owner with the front rack + "large front basket" (X-side design, i.e. the rack-mounted Large Basket): top-bar weld gap "rattles and vibrates" (structural, not an accessory fix) https://forums.electricbikereview.com/threads/new-radwagon-owner-sharing-the-good-and-the-bad.29132/
- 2023-05-14: Rad Trike owner: "wire baskets rattle" https://forums.electricbikereview.com/threads/modifying-my-rad-trike-for-my-particular-physical-limitations.52937/
- Searches for "rad basket liner" and "basket organizer" returned 0 results.

### 1d. Generic e-bike / bike basket demand (Amazon; this is competition context, not Rad demand)
Amazon SERPs and /dp pages were readable via curl (no captcha). Review bodies rendered on only 2 of 10 /dp pages, so these are the decoded "Customers say" AI summaries. **Amazon Q&A: NEEDS DATA** (not loaded in static HTML; not attempted).
- Kroozie 2.0 cup holder B06XGZ522H ($26.99, 4.4★, 1,991): "customers report containers popping out during rides … too small for larger bottles" https://www.amazon.com/dp/B06XGZ522H
- Accmor stroller/bike cup holder B086TZXKMJ ($9.98, 4.3★, 28,472, "10K+ bought in past month"): durability "breaking quickly and not staying in place" https://www.amazon.com/dp/B086TZXKMJ
- Topeak Cargo Net for Baskets B0038F1EJK ($11.05, 4.6★, 872): "rubber protective tips fall off … others say it's too big" https://www.amazon.com/dp/B0038F1EJK
- PowerTye cargo net B0022ZXO40 ($9.95, 4.5★, 7,047): "plastic clips breaking easily" https://www.amazon.com/dp/B0022ZXO40
- **Read:** the generic cup-holder category is huge and cheap (mostly handlebar/stroller). Its universal pains, pop-out and wrong size, match the Rad bottle-holder complaints.

## 2. Competition

### Idea 1: Cup / bottle holder
| Seller / product | Price | Fit | Notes / fit complaints | URL |
|---|---|---|---|---|
| Amazon "Bike Basket Cup Holder, 77mm C-Shaped" (mfr lmrwTO), B0GXK8M8JR | $25.60 | Universal basket rim. "Serrated U-hooks – Clip onto basket rims", "Tool-free", "Durable PETG" (likely printed) | BSR #1,180,253 Sports & Outdoors. Rating count not shown (NEEDS DATA) | https://www.amazon.com/dp/B0GXK8M8JR |
| Etsy "Vintage Bicycle Basket Cup Holder" 1117134055 | $18.50 | Universal wire basket; PLA, ~14 h print | 542 favorites, 14,255 views, 4 reviews (all 5★, service-focused) | https://www.etsy.com/listing/1117134055 |
| Etsy leather basket/handlebar cup holder 179079811 | $41.98 | Universal | 242 favs, 0 reviews | https://www.etsy.com/listing/179079811 |
| Etsy German cargo-bike organizer with drink holder 4569952534 | $13.99 | Hangs on wood/plastic box wall, no drilling | Close analog to a drop-in basket organizer + cup. 67 views | https://www.etsy.com/listing/4569952534 |
| Rad Water Bottle Holder (OEM, handlebar clamp) | $20 | Rad OEM; not for RadRover Plus (per page) | 3.86★ (411). ~24 mount-location + ~27 broke/weld complaints (approx) | https://www.radpowerbikes.com/products/water-bottle-cage |
| Etsy "RAD POWER BIKE Bottle Holder Mounting Bracket" 811472398 (Cascade Manufacturing) | $31.98 | **Rad-specific (frame)**, aluminum, holds 2 cages | 547 favs, 48,901 views, 4 reviews 5★ | https://www.etsy.com/listing/811472398 |
| GZila Designs "Water Bottle Holder… Built for Rad Power Bikes" | $45.00 | **Rad-specific (frame)** mount | products.json | https://www.gziladesigns.com/products/rad-power-bike-water-bottle-holder |
| Ride And Carry "STANLEY Cup Holder for Most Bikes" | $49.95 (products.json; currency not labeled; store says Made in San Diego) | 2.5" bottle-boss spacing "such as … the Rad Runner" | | https://rideandcarry.com/products/stanley-cup-holder-for-most-bikes-copy |
| Universal Amazon bar / stroller holders (Accmor, WUVOP, Kemimoto, GEARV, Kroozie…) | $4.99–$32.99 | Universal | Pop-out, size fit, "flops around" (AI summaries) | e.g. https://www.amazon.com/dp/B0BG75WTV2 |
| Free: MakerWorld "Bike Basket Cup / Bottle Holder" 2759885 (72 dl); "Travel Mug Holder with Tube Clamp and Adapters" 662084 ("adapt down to a 12mm tube (which was the approximate diameter of the basket on a Rad Powered Bike)"); "Universal Bicycle Cup / Bottle Holder System" 2804440; Thingiverse "Coffee Cup Holder Bike Basket Attachment" (2014); Printables "Cupholder for Electric Bike Company Front Basket" | Free | Universal; 662084 is Rad-basket-adjacent (unverified tube size) | | https://makerworld.com/en/models/2759885 ; https://makerworld.com/en/models/662084 ; https://makerworld.com/en/models/2804440 ; https://3dsearch.net/model/coffee-cup-holder-bike-basket-attachment-tv392955 ; https://3dsearch.net/model/cupholder-for-electric-bike-company-front-basket-n-1787672 |

**Price band:** basket-specific $18.50–$41.98 (sweet spot ~$18–26). Universal $5–33. Rad-frame cup/bottle mounts $31.98–$49.95. **Rad-basket-specific paid competitor: none found.**

### Idea 2: Divider / organizer / small-item insert
| Seller / product | Price | Fit | URL |
|---|---|---|---|
| Rad Large Basket Bag (OEM) | $47 (compare $59) | Rad large baskets | https://www.radpowerbikes.com/products/basket-bag-large |
| Rad Large / Small Basket Roll Top Liner (OEM) | $65.25 / $51.75 | Rad large / small baskets | https://www.radpowerbikes.com/products/large-basket-roll-top-liner ; https://www.radpowerbikes.com/products/small-basket-roll-top-liner |
| Line and Ride "Custom-Fit E-Bike Basket Liner – Fits Rad Power Small Front Basket" B0FNL2Q87Q, plus "Basket Liner, Compatible with Rad Power" B0H4DH9ZBQ / B0H4DHLNZQ / B0H4DSNWCL / B0H8XJ8GPW | $34.99–$39.99 | **Rad-specific** ("For the Rad Power SMALL FRONT MOUNT Basket ONLY … measure your basket before ordering"). B0H4DH9ZBQ BSR #208,196 | https://www.amazon.com/dp/B0FNL2Q87Q ; https://www.amazon.com/dp/B0H4DH9ZBQ |
| Topeak Urban Basket DX 22L Inner Pad | $24.27 | Brand-specific rigid-basket pad: "Noise & Shock Dampening … Prevents Item Slippage" (same pitch as ours, different brand) | https://www.amazon.com/dp/B0F9B98K9V |
| Universal liners (Cruiser Candy, RAYMACE, ANZOME…) | $6.99–$45.81 | Universal | e.g. https://www.amazon.com/dp/B00KBDY192 |
| Rigid "bike basket divider" | — | **Amazon SERP had none** (results were baskets/liners). Etsy "bike basket divider" = 1 irrelevant listing | Amazon SERP `bike basket divider`; Etsy API |
| Free printable basket inserts (generic, non-bike): MakerWorld "Basket with Custom Divider INSERTS" 538045, "Shopping basket organizer" 912743 | Free | Not bike | https://makerworld.com/en/models/538045 |

**Price band:** soft liners $7–65 (Rad-fit $34.99–65.25). **Rigid Rad insert: no competitor found**, so the ceiling is set by liners: roughly **$20–35** for a rigid bin set.

### Idea 3: Cargo securing
| Seller / product | Price | Fit | URL |
|---|---|---|---|
| Rad Cargo Net (OEM), 15x21 in unstretched, 3x3 in holes, plastic hooks | $15 (compare $20) | Rad baskets/racks; ~18 hook/fit complaints (approx) | https://www.radpowerbikes.com/products/cargo-net |
| Rad Cargo Straps (OEM), 12 in, set of 3, metal-reinforced plastic clips | $18.75 (compare $25) | Rad; mostly praised; 2 FMB-bar fit complaints | https://www.radpowerbikes.com/products/cargo-straps |
| Amazon basket/moto nets (Topeak $11.05, PowerTye $9.95, PDW Cargo Web $22–25, generic $6.93–14.49) | $6.93–$25 | Universal | https://www.amazon.com/dp/B0038F1EJK ; https://www.amazon.com/dp/B09WRVTGZD |
| Bungee cords / carabiner bungees | $4.68–$34.99 | Universal | Amazon SERP `bike basket bungee cord` |
| Free: MakerWorld "Bike Cargo Net Hook" 1498943 ("original hooks … keep breaking"), "Hook for Cargo Basket Net" 2393370, "Bungee Cord Hook (removable)" 2013650 | Free | Universal | https://makerworld.com/en/models/1498943 ; https://makerworld.com/en/models/2393370 |
| Etsy "bike cargo net hook" / "bungee hook clip bike" | — | 0 results each (Etsy API) | |

**Price band:** $7–25 for a complete net. Spare-hook / anchor sets would have to sit around **$8–15**. **Rad-basket anchor/hook: none found** (Rad's own net/straps are the incumbents).

## 3. Per-idea scoring

### Idea 1: `rad_basket_cup_holder` (opp-c5313620)
- **unmet_demand: THIN–MODERATE (35/100, analyst-calibrated).** Evidence: 2 explicit asks (696154503, 703971832) in ~2,285 Rad basket reviews (about 0.1%). 4 workarounds (stroller bag 374631404, attached cupholders 399383685, bottle kept in basket 642632379, DIY YouTube 8vzCKWxYZn4). 1 bottles-fell-out (700880906). 1 "needs to be on front / basket area" (427653128). 1 EBR 2019 WTB-ish. Indirect signal: ~24 mount-location complaints on Rad's handlebar bottle holder. Hardly any recent evidence (latest explicit ask 2025-05).
- **competition_density: 1.0 (formula v2, clamped).** Etsy basket-cup query count 9, MakerWorld ≥10 relevant cup/bottle models, and an OEM in-stock substitute (Rad Water Bottle Holder).
- **SoMo differentiator:** fits the actual Rad FMB rail/slat profile (both sizes). Placed where it clears the headlight (which moves to the basket front) and the handlebar/brake-line sweep. Tool-free clip. ASA/PETG UV. Sized for 20–40 oz tumblers and to-go cups (the common pain is "too small / pops out"). Made in USA.
- **Printability (H2S):** trivial single part. Print a cradle plus rail clip. No bed constraint.
- **Liability:** LOW if non-load. It must stay inside the basket envelope (the basket is frame-mounted and doesn't steer), not block the headlight beam, and not rise into the handlebar/brake-lever/cable sweep at full lock. Hot drinks: add a "don't carry lidless hot drinks" note.
- **Price ceiling:** ~$20–26 (Etsy $18.50, Amazon $25.60). Hard ceiling from universal bar holders ~$10–20.
- **suggested_next: KEEP_HUNTING.** It's real but thin. Best shipped as a **module/add-on to idea 2's bin** rather than a stand-alone hero. Re-check once the owner's measurements confirm a good corner position.

### Idea 2: `rad_basket_divider_organizer` (opp-a9020bd9)
- **unmet_demand: MODERATE (60/100, analyst-calibrated) for "small items slip out or through + rattle".** About 20 hand-read explicit asks + DIY fixes. Keyword tallies (approx): small-items/insert ~7 LFMB, ~9 SFMB, ~52 Large Basket, ~30 Small Basket (inflated by liner mentions); rattle/noise ~7 on the LFMB. **"Divider" per se is THIN** (~2 keyword hits, 0 explicit asks), so pitch it as a **small-item bin / tray**, not a divider. Caveat: most evidence is on the **open-bar rack baskets**. The FMBs have wood floors, so their complaint is *side* gaps + noise (6 FMB items).
- **competition_density: ~0.51 (formula v2).** Etsy rigid-insert ≈ 0–1 relevant, MakerWorld ≈ 2 generic, and OEM in-stock substitutes (Rad bag/liners).
- **SoMo differentiator:** **rigid, Rad-exact modular bins** (drop-in, no tools) for the Large FMB and Small FMB (and optionally the rack Large Basket as a separate SKU). Solid walls stop small items. TPU/soft feet and edge bumpers kill the "drum" rattle (a buyer explicitly asked that inserts NOT make hard-plastic vibration noise). Optional cup-holder module + clip-on anchor points (idea 3). Lighter and cheaper than a $65 liner. ASA/PETG UV. USA.
- **Printability (H2S):** full-floor trays don't fit (Large FMB outer 346x536 mm; Large Basket ≈305x495 mm; SFMB outer 348 mm long, inner TBD). Use **2–3 modular bins per basket, each ≤ ~320 mm**, interlocking. Print time and material are the main cost drivers. TPU pads: printability on the H2S still to be verified.
- **Liability:** LOW. It sits inside the basket, carries only its contents, and has no bike attachment. It must not raise cargo above the rail height enough to hit the handlebar sweep, and must not change the basket's 22 lb rating (put that on the label).
- **Price ceiling:** ~$20–35 (below the Line and Ride $34.99–39.99 and Rad $47–65.25 soft options).
- **suggested_next: DESIGN (gated).** There's buyer evidence beyond the owner (~20 explicit asks + DIY). Gate: owner caliper measurements (section 4) → one-bin prototype for the Small FMB → rattle/bounce ride test → then the Large FMB set.

### Idea 3: `rad_basket_cargo_tiedown` (opp-6772fd7a)
- **unmet_demand: MODERATE (50/100, analyst-calibrated).** About 22 hand-read items. Cargo Net hook/fit complaints ~18 (approx) out of 177 reviews. Strap bar-fit complaints 2. LFMB net-rim complaint 1. Bounce-out-while-bungeed 1. This is a *fix-the-OEM-accessory* pain, not a new need.
- **competition_density: ~0.55 (formula v2).** Etsy 0, MakerWorld ≈5 hook models, and OEM in-stock substitutes (Rad net/straps).
- **SoMo differentiator:** clip-on anchor points that snap onto the Rad FMB rail/slat and give nets/straps a hook point below the rim, clear of the wood panel. Plus captive replacement hooks that can't fall off the net. Anti-bounce corner stops. Sized for both FMBs.
- **Printability (H2S):** easy, small parts. The material needs pull and UV testing.
- **Liability: MEDIUM.** It restrains cargo under bungee tension, so a failure means hook snap-back (eye/face) or cargo ejected from a *front* basket, possibly toward the front wheel. Not bike-structural, and it doesn't touch steering, brakes or lights. It still needs a documented pull test and "secondary restraint only" wording.
- **Price ceiling:** ~$8–15 (a whole net with hooks is $7–15).
- **suggested_next: KEEP_HUNTING.** Evidence is real, but the price ceiling is low and it carries restraint liability. Keep it as a free add-on / bundle item with idea 2 until pull-tested.

## 4. Owner measuring list (calipers; Large FMB on RadRunner Plus, Small FMB on RadRunner 3 Plus)

**Protocol:** take every dimension **3 times**, record all three, and use the **middle (median)** value. Measure in mm to 0.1 where the calipers allow. The **caliper must be visible in the photo** for each measurement. Do both baskets unless noted. Tag each row with basket (L/S), bike (RR+ / RR3+), and location (front / rear / left / right / corner #).

**A. Basket interior envelope**
1. Inner width (left to right) at the floor, and again at the top rim.
2. Inner depth (front to rear) at the floor, and again at the top rim.
3. Inner height: floor (top of the wood) to the top of the rim, at all 4 corners + mid-front + mid-rear.
4. Any interior obstruction: the center bar running lengthwise (reported on the Large FMB), cross bars, bolt heads or nuts proud of the floor. Record position from the left/front inner wall, height above the floor, and size.

**B. Side rails / slats / bars**
5. Profile of each side member: round tube vs flat bar vs sheet. For round tubes: outer diameter. For flat bars: width x thickness.
6. Top-rim member profile and size (buyers say the rim is "too bulky" for net hooks).
7. Center-to-center spacing of side bars/slats, and the clear gap between them (vertical and horizontal), on each of the 4 sides.
8. Distance from the floor (wood top) to the lowest side bar, and the gap between the wood edge and the side frame (where buyers say hooks don't fit).
9. Wall thickness of tubes, if an open end is visible (else note "not measurable").

**C. Corners**
10. Corner type: welded square, bent radius, or a separate corner piece. If radiused: inside radius (use a radius gauge or fit a coin/cylinder of known diameter).
11. Corner post profile/diameter, and the distance from the corner to the first side bar on each side.

**D. Floor**
12. Floor material (wood/bamboo), thickness at an exposed edge, and whether it's flat or has a lip.
13. Floor fastener pattern: bolt-head diameter, height proud of the floor, and positions.
14. Any warp/delamination (photo) and its depth.

**E. Clearances (bike on stand, wheel straight, then full lock left and right)**
15. Vertical gap: top of the rear rim of the basket → underside of the handlebar/stem, straight and at full lock both ways.
16. Gap: rear rim → brake levers, display, and the nearest brake/shift/throttle cable or housing, straight and at full lock both ways. Note where cables drape into or over the basket.
17. Headlight: mount location on the basket (front face? which bar?), its height and lateral offset, and the **beam path**. Mark the zone in front of and above the light that must stay clear.
18. Gap from the basket bottom to the fork crown/fender/tire at full suspension compression (RR3+ has front suspension if equipped; if rigid, note rigid). Just record it; the accessories must not go below the floor.
19. Knee/leg clearance: distance from the rear rim to the rider's knees at the top of the pedal stroke, seated (to rule out rim-mounted clips at the rear corners).

**F. Cup-holder placement candidates**
20. For each inner corner (FL, FR, RL, RR): free interior footprint (W x D) and height to the rim, plus any headlight/cable/handlebar conflict from E. Mark the best 1–2 corners.
21. For the rim-clip option: the length of straight rim available on each side without hitting a weld, bracket, or the headlight mount.
22. Your usual drinks: outer diameter at the top and bottom, and height, of each cup/bottle you'd carry (e.g., tumbler, to-go coffee cup, 40 oz bottle).

**G. Photo list (caliper visible in every measurement photo)**
- P1–P2: each basket top-down, full frame, bike straight (ruler or tape laid across).
- P3–P6: each basket, the four sides straight on.
- P7–P10: each basket, all four inner corners close up, calipers on the corner post.
- P11: side bar/slat profile close-up with calipers (round OD or flat W x T).
- P12: top rim profile close-up with calipers.
- P13: bar spacing with calipers spanning the gap.
- P14: floor edge thickness + a floor bolt head with calipers.
- P15: the wood-to-frame gap where hooks would go.
- P16–P18: full-lock left / straight / full-lock right, from the rider's seat, showing the handlebar, levers and cables over the basket.
- P19: headlight mount close-up + a side view of the beam direction.
- P20: cable routing where it passes near or into the basket.
- P21: your drink(s) standing in the chosen corner, with calipers across the cup top.
- P22: bike/basket label or serial area, if any, to confirm the basket version (the small FMB has had 2 designs per a 2024-11-25 review).

## 5. Source health (this run)
| Source | Status | Notes |
|---|---|---|
| Rad products.json | OK | 148 products, 1 page; prices, availability, ids |
| Rad product pages (curl) | OK | Specs/geometry. The "You may also like" widget shows static "Out of Stock" text; use products.json for stock |
| Rad Yotpo public widget feed | OK | 11 products, all stars. `&star=N` needed for completeness |
| YouTube Data API (search, videos, commentThreads) | OK | 444 comments; 2 videos had comments disabled |
| EBR forum (XenForo `/search/search?keywords=`) | OK | The old `/search/1/?q=` URL form returns "Oops… page could not be found" |
| Amazon SERP (curl, desktop UA) | OK | 8 queries, no captcha |
| Amazon /dp pages (curl) | PARTIAL | 10 fetched OK; review bodies on 2 of 10; AI summaries decoded from `k+b64` blobs; Q&A NEEDS DATA |
| Etsy API v3 | OK | `x-api-key: KEYSTRING:SHARED_SECRET`; listing + reviews endpoints OK |
| MakerWorld HTTP (`__NEXT_DATA__`) | OK | Search + model pages |
| Printables direct | BLOCKED (403) | Used WebSearch/3dsearch snippets instead |
| Ride And Carry / GZila products.json | OK | Rad-frame cup/bottle mounts |
| mri-denver.com | BLOCKED/DOWN | curl connect failed (000) |
| Bambu H2S page | OK (cited from the parent teardown) | 340x320x340 mm |
| Reddit / Facebook | SKIPPED (policy) | Reddit threads surfaced in WebSearch results but weren't used |

## 6. Method lessons
1. **Yotpo feed pagination under-returns.** Page through `&star=1..5` separately and dedupe by review id. The plain pagination missed ~20% of Large Basket reviews and all of its 3★.
2. **Check the OEM's own accessory reviews, not just the host product.** The strongest tie-down and cup evidence came from Rad Cargo Net / Straps / Water Bottle Holder reviews, not basket reviews.
3. **Separate FMB (wood floor) from rack baskets (open bars).** "Things fall through" is mostly a rack-basket pain. On the FMBs it's side gaps + noise. This changes the SKU and the bed-size math.
4. **The v2 `unmet_demand` formula saturates on all-time review evidence** (a few explicit asks push it to 100). For review-mined invent cards, unmet_demand here is analyst-calibrated (thin ≈ 25–40, moderate ≈ 45–65, strong ≥ 70). Suggest a v3 that scales by evidence *rate* (asks per 1,000 reviews) and recency.
5. **Amazon AI "Customers say" text is base64 in `k+b64` blobs.** Decode those instead of scraping review lists; they give fit and durability complaints cheaply.
6. Keep the rule that **Etsy/MW/Amazon counts are competition only**. Etsy favorites/views (e.g., 542 favs on a $18.50 basket cup holder) are useful as a *competition-strength* proxy, not demand.
