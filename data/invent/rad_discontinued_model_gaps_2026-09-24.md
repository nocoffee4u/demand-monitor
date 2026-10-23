# Rad discontinued-model accessory gaps: SoMo Manufacturing (Bambu H2S, not purchased)
_Generated 2026-09-24 ~23:45 PT by Demand Forecasting Bot. Sources were pulled 2026-09-24 (PT). Companion CSV: `rad_discontinued_model_gaps_2026-09-24.csv`. It has three row types: 10 `gap` rows, 171 `accessory_fit` rows (US+CA catalog fit tags) and 18 `removed_or_unlisted` rows._

Rules applied: no invented numbers or quotes (unknowns say NEEDS DATA); no Reddit or Facebook; free stack only. Yotpo dates are as returned by the API. YouTube times were converted to PT (UTC-7).

---
## 1. Direct answer: has Rad de-prioritized accessories for discontinued models?

**Mixed. On paper, no. In practice, yes, for model-specific hardware. Since the 2026 asset sale, support for pre-Dec-15-2025 bikes has also been formally cut.**

Evidence it has NOT (catalog still serves old bikes):
- Rad's Shopify tags still put RR2, RadRunner Plus, RR3+, RadRover 6 Plus, RadCity 5 Plus, RadWagon 4, RadExpand 5 and RadTrike under **"Current Model Compatibility"**. Older bikes get **"Legacy Model Compatibility"** tags; they are not dropped.
- The US catalog lists many in-stock accessories for each discontinued model. From the US tags: RadWagon 4 43, RR2 41, RadMission 41, RR3+ 39, RadCity 4 39, RadExpand 5 38, RadRunner 1 38, RR Plus 37, RC5+ 37, RR6+ 36, RadRover 5 36, RadMini 4 35, RadTrike 32. In-stock totals: US 62/66 accessories and 64/65 spare parts. CA: 45/65 and 45/63.
- Legacy-specific items are still sold: RadMini Full Fenders ($62), RadMission Full Fenders ($29), RadRunner Full Fenders (RR1/RR2, $89), RR2 console/passenger package (RR1/RR2/RR Plus), RR3+ Center Kickstand ($75), RW4 running boards.
- Safe Shield batteries are "available in builds that match every Rad model, past or present". The 2025 charger fits every Rad except RadMini 1 and RadKick. These are battery items, out of scope for SoMo; cited only as evidence.

Evidence it HAS (the gaps):
- **Cockpit, trim and electronics spares are gone from both stores.** Rad UI Remote (Shopify 6570871160928), Rad UI Display (6570871521376), all controllers, LCD/LED displays, Cable Cover – RadCity 5 ST, Fender Hardware Kits (RadCity 5 front, RadRover 6 front, Rover front 2019, Mini rear), Kickstand – RadExpand 5, and Fender – RadTrike Front. All of these appear in Yotpo's product map but not in US/CA products.json.
- **Model-specific load and fender items removed or OOS:** RadRover Full Fenders (404; last Wayback 2023-01-29, tagged 2018/2019 RadRover only), RadRover Rear Rack (OOS US $99 and CA $129), RadMini Rear Rack, Medium Front-Mounted Basket, Hardshell Locking Box, LCD Display Upgrade (CA OOS), RadMission Kickstand (CA OOS). The 2024-12-26 accessories collection (Wayback) vs today: 6 items removed.
- **Official "not compatible" text leaves discontinued bikes with nothing:**
  - Rad Mirror: "Works on all models except the RadRover 6 Plus models due to limited handlebar space".
  - GUB PRO-3 phone mount: "Not compatible with the RadRover 6 Plus".
  - Water Bottle Holder: not compatible with RadRover Plus models.
  - Front Rack: "NOT compatible with the Premium Headlight".
  - RadRunner Full Fenders: "Not compatible with the RadRunner Plus – Please contact us if you need replacement fenders".
- **Corporate:**
  - RLM warranty page (updated 2026-05-14): RLM "has no obligation to provide warranty or other service for Products purchased prior to December 15, 2025" (claims go to Chapter 11 case 25-02183).
  - CPSC 2025-11-24 warning on batteries RP-1304 / RAD-S1304Y / HL-RP-S1304 (RW4, RC4, RR5, RC ST3, RR ST1, RR2, RR1, RadRunner Plus, RE5). Rad said it could not offer replacements or refunds.
- **Owner quotes** (Yotpo):
  - 424998044 (2022-12-13, RadMission): LCD display "will not be available based on discontinuing bike".
  - 397704686 (2022-08-26, RadMini ST2): "I wish that RAD would HAVE IN STOCK the accessories to outfit the bikes".
  - 528039815 (2023-12-05, RadWagon Caboose): "They don't sell a caboose that fits an older wagon."
  - 574247812 (2024-04-19, RR2): "since you no longer offer the post for the seat".
  - 498880109 (2023-09-07, RadRover Full Fenders): "Told my part was not available and was not going to become available."
  - 774444052 (2025-10-28): "disappointed you discontinued the medium size."
- **YouTube:**
  - UgxUVhMECnqZWCRamIZ4AaABAg (video 85zBWnWdr0A, 2026-02-04 PT): "During the bankruptcy, all Rad spare parts hard to find."
  - Ugz-zHjRdR2iCYTCqNx4AaABAg.AGgCNc6xYgaAaaXxbW-MPP (Kn-Uf0DA85k, 2026-09-10 PT), RR6 controller: "it's 165 It is in back order though".
- **EBR forum:**
  - Post 701345 (2025-12-18): "They aren't offering support or parts for existing customers."
  - Counterpoint, post 714895 (2026-06-10): Rad "appears to be operating; bikes and parts are still available."

**Where SoMo fits:** Rad cut the small plastic cockpit and trim parts first, and it never made mounts for the "not compatible" combinations. Those are both low-liability, printable niches.

---
## 2. Corporate and ownership timeline (as publicly reported only)
| Date | Event | Source |
|---|---|---|
| 2025-04-30 | New RadRunner ($1,499), RadRunner Plus ($1,799) and RadRunner Max ($2,299, the reimagined RR3+) announced | PR Newswire / Electrek 2025-04-30 |
| 2025-11 | Rad warned staff it could shut down in January without funding | TechCrunch Nov 2025; EBR forum post 698782 (2025-11-10) |
| 2025-11-24 | CPSC warns consumers to stop using Rad batteries RP-1304, RAD-S1304Y, HL-RP-S1304; Rad declined an acceptable recall | cpsc.gov warning; Bicycle Retailer (BRAIN) 2025-11-24 |
| 2025-12 | Chapter 11 filed (case 25-02183); asset auction Jan 22 | BRAIN / TechCrunch / GeekWire |
| 2026-01-13 | "New RadWagon" ($1,799) launched; frame appears derived from RadWagon 4 | Electrek 2026-01-13 |
| 2026-03-05 | Life EV (OTC: LFEV) completed asset purchase: $13,276,102 cash ($14,926,706 incl. assumed liabilities). Brand now run by Rad Life Mobility (RLM) | GeekWire; TechCrunch 2026-03-06; BRAIN 2026-03-06; Electrek 2026-03-06; Rad blog |
| 2026-05-14 | Warranty page: RLM has no warranty or service obligation for bikes purchased before 2025-12-15; new warranty for purchases from 2026-05-15 | radpowerbikes.com/pages/warranty (fetched 2026-09-24) |
| 2026-06-15 | Radster Trail product created in US store ($1,999.99) | US products.json |

---
## 3. Model inventory (US + CA products.json, fetched 2026-09-24)
| Model | Status | Evidence | UI | Battery style | Yotpo reviews pulled (installed-base proxy) |
|---|---|---|---|---|---|
| RadRunner (MY25) | CURRENT (US $1,499; CA unavailable) | products.json 7353309462624 | NEEDS DATA | external | n/a |
| RadRunner Plus (MY25, matte black) | CURRENT (US $1,799; CA unavailable) | 7353310117984 | larger control/display unit (review 784435007) | external | n/a |
| RadRunner Max | CURRENT (US $2,299; CA $2,999) | 7353310314592 | NEEDS DATA | semi-integrated (NEEDS DATA) | n/a |
| RadWagon 5 | CURRENT (US $2,399; CA available) | 6854275924064 | NEEDS DATA | NEEDS DATA | n/a |
| New RadWagon (MY25) | CURRENT (US $1,799, published 2026-01-12) | 7541654782048 | NEEDS DATA | NEEDS DATA | n/a |
| Radster Road | CURRENT (US $1,999; CA available) | 6854277496928 | buttons-only (per brief) | semi-integrated | n/a |
| Radster Trail | CURRENT (US $1,999.99; CA available) | 7733444968544 | buttons-only (per brief) | semi-integrated | n/a |
| RadExpand 5 Plus | CURRENT (US $1,899; CA unavailable) | 6854276743264 | NEEDS DATA | NEEDS DATA | n/a |
| RadKick (7-speed) | CURRENT CA only ($1,899) | CA products.json | NEEDS DATA | NEEDS DATA | n/a |
| RadRunner 3 Plus | DISCONTINUED (absent both stores; Max is the successor per Electrek 2025-04-30) | absent | **Rad UI Remote** | semi-integrated | 253 |
| RadRunner Plus (original, owner's silver) | DISCONTINUED (absent; replaced by MY25 RR Plus) | absent; CPSC battery warning | LCD (Yotpo spare "LCD Display - RadMini/Runner Plus") | external (CPSC-listed) | 1,463 |
| RadRunner 2 | DISCONTINUED | absent; CPSC-listed | LED (Yotpo spare "LED Display - RadRunner 2 / RadExpand") | external | 1,150 |
| RadRunner 1 | DISCONTINUED | absent; CPSC-listed | NEEDS DATA | external | 2,620 |
| RadRover 6 Plus (HS/ST) | DISCONTINUED | absent | **Rad UI Remote + UI Display** | semi-integrated | 3,090 |
| RadRover 5 / RadRover ST 1 | DISCONTINUED (Legacy tag) | absent; CPSC-listed | LCD (Yotpo spare "LCD Display - Rover"); ST1 NEEDS DATA | external | 2,361 / 1,505 |
| RadCity 5 Plus (HS/ST) | DISCONTINUED | absent | **Rad UI Remote + UI Display** | semi-integrated | 1,029 |
| RadCity 4 / RadCity ST 3 | DISCONTINUED (Legacy tag) | absent; CPSC-listed | LCD (Yotpo spare "LCD Display - City"); ST3 NEEDS DATA | external | 870 / 2,103 |
| RadWagon 4 | DISCONTINUED (Current-compat tag) | absent; CPSC-listed | LCD (Yotpo spare "LCD Display - Wagon") | external | 1,058 |
| RadMini 4 / RadMini ST 2 | DISCONTINUED (EBR thread 2022-04-01) | absent | LCD (Yotpo spare "LCD Display - RadMini/Runner Plus") | external | 876 / 1,258 |
| RadExpand 5 | DISCONTINUED | absent; CPSC-listed | LED (Yotpo spare "LED Display - RadRunner 2 / RadExpand") | external | 1,122 |
| RadMission 1 | DISCONTINUED (review 424998044, 2022-12-13) | absent | LCD display was an accessory (424998044) | external | 1,329 |
| RadTrike | NOT LISTED in either store (official discontinuation notice NEEDS DATA) | absent | NEEDS DATA | NEEDS DATA | 236 |
| Other 2025-26 models | none found beyond those above (RadKick, Radster Trail, New RadWagon, RR Max) | – | – | – | – |

Store counts: US 148 products, CA 139 products (single products.json page each).

---
## 4. Accessory compatibility matrix (summary; full per-SKU matrix in the CSV)
Fit data comes from Shopify tags (`Current Model Compatibility_*` / `Legacy Model Compatibility_*`) plus the fit text on the US product pages. The US store does **not** tag MY25 RadRunner, RR Plus MY25 or RR Max. The CA store does.

| Focus area | Current Rad item (US price, stock) | Discontinued models in fit list | Gap / flag |
|---|---|---|---|
| Front baskets/racks | Front Rack $59 ✔; Small FMB ✔; Large FMB (OOS US) | "all 2018 and after" | Front Rack **not compatible with Premium Headlight**; Medium FMB **removed** |
| Rear racks | RadRover Rear Rack **OOS US+CA**; RadMini Rear Rack **removed** | RR5/RR6+ | RadRover rack effectively unavailable |
| Fenders | RadRunner Full Fenders $89 (RR1/RR2/MY25); RadMini $62; RadMission $29 | RR Plus **excluded** ("contact us") | RadRover Full Fenders **removed**; fender hardware kits **removed** |
| Display / remote | none | – | Rad UI Remote, UI Display, LCD/LED displays **removed**; LCD Display Upgrade CA OOS / US 404 |
| Mirrors | Rad Mirror $34 (21–26 mm bar OD) | all except RR6+; RR3+ "requires repositioning of the UI remote and bell"; RC5+ conflicts with GUB | **RR6+ never offered** |
| Phone mount | GUB PRO-3 $25 | all except RR6+ | **RR6+ never offered** |
| Bottle | Water Bottle Holder $20 | not RadRover Plus models; conflicts RC5+; RadTrike no bosses | **RR6+/RC5+ never offered** |
| Lights | Premium Headlight $49 (all except RE5+, RadKick, Radster, RW5, RR Max); Standard $44; Taillight – RadRunner | broad | No bracket for Premium light + Front Rack/basket |
| Kickstands | RR3+ Center Kickstand $75 (RR3+/Max); RadRunner kickstand (RR1/RR2 only) | family-specific | Kickstand – RR3+ (side) & RE5 **removed** |
| Chain guard | none | – | never offered |
| Passenger/cargo | RR2 console & passenger pkg (RR1/2/Plus/MY25); RR3 console/pkg (RR3+/Max); RW4 running boards (RW4/MY25 Wagon) | yes | RR passenger package OOS US; RW deckpad OOS; Caboose doesn't fit older wagon (528039815) |
| Port/terminal covers | External Battery Charge Port Cover $5; Battery Terminal Cover $20 | limited | Terminal cover doesn't fit RadMini (344020396) |
| Plastic trim (cable covers, controller covers, light housings, reflector brackets, fender stays, bottle bosses) | **none in catalog** | – | Cable Cover – RC5 ST **removed**; no trim SKUs at all |

Wayback comparisons that worked:
- Premium Headlight 2023-02-07: same fit tags as now; RR3+ added since.
- RadRover Rear Rack 2024-02-21: same tags; now OOS.
- Accessories collection 2024-12-26 vs now: removed hardshell-locking-box, lcd-display-upgrade, radmission-kickstand, sr-suntour seatpost, tannus-armour-bundle, thule-yepp-maxi.
- Replacement-parts page 2023-05-28 vs now: removed radrover-full-fenders, legacy battery packs, chargers.

**Bottom line:** fit lists were **not pruned**. Rad removed SKUs outright instead.

---
## 5. Geometry commonality
| Interface | Old ↔ new sharing | Status |
|---|---|---|
| Front Rack / front-mounted basket mount | Same rack/baskets for "all 2018 and after" models | CONFIRMED (fit text) |
| Rear-rack baskets & bags | 2018+ | CONFIRMED (fit text) |
| Premium headlight mount | Fork-arch bolt shared with front fender on RR6+ (5 mm hex, 6 Nm, 2021 RR6+ manual); conflicts with Front Rack | CONFIRMED (manual + fit text); RR Plus bolt size NEEDS DATA |
| Rad UI Remote / UI Display | RR6+, RC5+, RR3+ share the remote; clamps 3 mm hex @ 3 Nm (RR6+ manual) | CONFIRMED for the list. Radster buttons-only (per brief). MY25 RR Plus uses a larger control unit (784435007). RR Max UI NEEDS DATA |
| Handlebar width | RR Plus orig 680 mm; RR/RR Plus MY25 27 in (686 mm); RR Max 28 in; Radster Road 710 mm; RW5 680 mm; New RadWagon 700 mm; RE5+ 680 mm; RR6+ 700 mm (secondary source) | CONFIRMED (spec pages / EBR); RR6+ secondary |
| Handlebar OD at grip | Rad Mirror fits 21–26 mm OD | CONFIRMED range; exact OD at remote location NEEDS DATA (caliper owner's RR3+) |
| Stem | RR Plus orig 50 mm / 30° / 15 mm rise; RR MY25 50 mm + 30°; Radster Road 70 mm; RW5 35 mm; New RadWagon tool-free adjustable | CONFIRMED lengths; clamp diameters NEEDS DATA |
| Head tube / steerer | – | NEEDS DATA |
| Rear rack bolt pattern | family-specific rear racks | NEEDS DATA |
| Fender mounts | RR6+ front fender uses P-clamps on fork + fork-arch bolt | CONFIRMED RR6+; others NEEDS DATA |
| Passenger/console | RR1/2/Plus/MY25 share; RR3+/Max share | CONFIRMED (fit text) |
| Running boards | RW4 ↔ New RadWagon share; RW5 differs | CONFIRMED (fit text) |
| Battery | external vs semi-integrated (RC5+, RR6+, RR3+, Radster) | CONFIRMED; out of scope |
| Bottle bosses | absent on RR6+/RC5+ (fit text + reviews); RadTrike none | CONFIRMED by fit text; manual confirmation NEEDS DATA |
| Kickstand | family-specific | CONFIRMED (fit text) |

---
## 6. Ranked gap list
Classes: (a) product / (b) load mount / (c) non-load accessory. H2S build volume is 340×320×340 mm. The printer is not purchased.

| # | Model(s) | Part | Evidence (count) | OEM status | Competitor price band | Class & liability | H2S | suggested_next |
|---|---|---|---|---|---|---|---|---|
| 1 | RR6+ (HS/ST), RC5+ (HS/ST), RR3+ | Rad UI Remote/Display clamp (replacement) + drain-friendly protective cover | Yotpo 11 (8 clamp/mount broken, 3 cover wishes); DIY 1 (wire tie, 425697954) | **Removed** (UI Remote/Display spares delisted; standalone clamp never listed) | Covers $7.95–$23.99 (Etsy/Amazon); free Printables UI bracket; full remote $99 at Bikeshop West | (c); low. Not throttle; keep clear of brake clamp; don't seal electronics | Yes, tiny | **DESIGN** (measure owner's RR3+) |
| 2 | RadRunner Plus orig (owner's) + other Premium-Headlight bikes w/ Front Rack or FMB | Premium Headlight relocation bracket + wire strain relief | Yotpo 45, **17 WTB/DIY** | **Never offered** (Rad: buy $44 Standard light) | Free Printables STL (657351, 32 dl); paid NEEDS DATA | (c); medium (lamp-into-spokes risk, 224327340). Metal fasteners, tether, vibration test | Yes | **DESIGN** |
| 3 | RR6+ (partly RR3+) | Cockpit accessory mount / short extender for mirror & phone | Yotpo 19 wish, **6 WTB**; ≥4 GUB no-fit | **Never offered**; Rad Mirror & GUB exclude RR6+ | Mirrors $22.99–$26.87 (Amazon, bought in); free MakerWorld extender | (c); low-medium | Yes | **DESIGN (gated)**: RR6+ fit data NEEDS DATA |
| 4 | RR6+, RC5+ | Bottle-cage adapter | Yotpo 43, 8 WTB/DIY | Never offered for these (Rad holder excludes them) | Etsy $31.98 (547 favs); GZilla price NEEDS DATA | (c); low-medium; keep off battery | Yes | WATCH (strong incumbent) |
| 5 | RR6+ / RR5 with Rad rear rack | Rack-to-fender anti-rattle bumper + taillight-wire clip (no stays) | Yotpo 52, 7 WTB/DIY | Fenders removed; rack OOS; hardware kits removed | Fenders $39 (Bikeshop West); bumper NEEDS DATA | (c); low (stays excluded) | Yes | WATCH |
| 6 | RC5+, RR6+, RR2, RC4 | Chainring / pant guard | Yotpo 14, 2 WTB | Never offered | Free MakerWorld RE5 guard; Amazon generic $34.02 | (c); medium (drivetrain jam) | Likely | KEEP_HUNTING |
| 7 | RW4, New RadWagon | Center-stand retention clip/stabilizer | Yotpo 47, 3 DIY/WTB (+ Etsy reviews, not counted) | Kickstand spare $40 in stock; spring $10 at Bikeshop West | Crowded: $14.99–$19.99 (Etsy/Amazon, ≥8 listings) | (c); medium (stand drop if clip fails) | Yes | WATCH |
| 8 | RadRunner Plus orig | Full fenders | Yotpo 6, 0 WTB | Never sold separately ("contact us") | Amazon $39.99–$75.99 | (c) with structural stays; med-high | No (segmented) | DROP |
| 9 | Legacy external-battery bikes | Charge-port / terminal caps | Yotpo 91, 3 WTB | In stock ($5 / $20) | Etsy $4.00–$20.00; Amazon $19.90–$30.00 | battery-adjacent; not launch | Yes | DROP |
| 10 | Legacy 2018+ | Medium FMB / Hardshell box / RadMini rack | discontinuation complaints | Removed | n/a | (b) load path; never launch | – | DROP |

Owner note: the owner's silver RadRunner Plus is directly served by **#2**. His RR3+ is the fit mule for **#1** and partly **#3**. His Aventon Aventure 2 is out of Rad scope.

---
## 7. Top quotes (verbatim; Yotpo id, date, product)
1. **425697954**, 2022-12-16, RadRover Rear Rack page: "The clamp holding the smaller digital power screen to the handle bar was cracked. I have been using a wire tie to hold it on." *(DIY, #1)*
2. **475594244**, 2023-06-11, RadRover 6 Plus: "The PAS control screen handlebar mount ring broke at the screw mount after normal use." *(#1)*
3. **717913183**, 2025-06-13, RadRover 6 Plus: "love bike, but have broken part ( that connects screen to handle bars) ,sent email to Rad Bikes and called but no response." *(#1)*
4. **387319502**, 2022-07-22, Rad UI Remote: "I wish it had protection cover and was waterproof." *(#1)*
5. **424013553**, 2022-12-09, RadRunner Plus: "I do wish I could run the front rack with the deluxe headlight. I do think a simple bracket could be designed to allow headlight to mount under the front rack and still be attached to the front fork/fender support bolt." *(#2)*
6. **239788662**, 2021-03-19, Front Rack: "I had a local auto body shop fabricate a bracket for me which works much better than the one supplied" *(DIY, #2)*
7. **271745759**, 2021-06-30, Medium Front-Mounted Basket: "I plan to fabricate my own bracket." *(DIY, #2)*
8. **281785675**, 2021-08-10, Premium Headlight: "Rad does say they have no bracket for the light if you get any front accessories, basket/rack" *(#2)*
9. **534053385**, 2023-12-31, RadRover 6 Plus: "Love the bike only wish they made a mirror to fit the bike" *(#3)*
10. **658272467**, 2024-12-11, RadRover 6 Plus: "just wish they offered more accessories like a phone holder and a rear view mirror." *(#3)*
11. **496264681**, 2023-08-25, GUB PRO-3: "There is no room to mount the phone mount on the flat parts of the handle bars. The display takes center stage" *(#3)*
12. **494638730**, 2023-08-18, RadRover 6 Plus: "the rear fender rattles against the rear rack when going over bumps. Fixed it with some sticky back foam gasket." *(DIY, #5)*
13. **482588759**, 2023-07-11, RadCity 5 Plus: "Wish you guys had a Rad designed bottle holder for the RadCity 5. Bought an after market holder by GZilla" *(#4)*
14. **541040570**, 2024-01-31, RadRover 6 Plus: "Wish there was a chain guard and a better horn." *(#6)*
15. YouTube **UgxUVhMECnqZWCRamIZ4AaABAg** (85zBWnWdr0A, 2026-02-04 PT): "During the bankruptcy, all Rad spare parts hard to find." *(de-prioritization)*
16. YouTube **UgzfoVVK6yNRE3ZiNzB4AaABAg** (Kn-Uf0DA85k, 2025-09-04 PT): "Do you know what size the screws are for the internal cable cover? One of mine was stripped out from the start." *(RR6 trim; KEEP_HUNTING)*

---
## 8. Demand-evidence method and counts
- **Yotpo** store-wide feed (Rad app key, public `filter.json`): 67,899 reviews store-wide. Pulled **56,236 unique (82.8%)** via star slices × asc/desc sort plus keyword queries, merged by review id. The feed's newest review is 2026-04-15; only 1 review is from 2026 (the feed is effectively frozen after the bankruptcy).
  - Keyword scan: discontinued / can't find / no longer available / out of stock / replacement / part / broken / cracked / plastic / cover / bracket / clip / mount / won't fit / older model / support / parts. WTB/DIY phrases weighted higher.
- **YouTube Data API:** 120 videos, 7,491 comments (4 videos had comments disabled). Recent parts wishes are mostly **electrical** (controllers, batteries, fuses, printed thumb throttles). Those are liability items and excluded.
- **EBR forums:** 9 searches, thin on parts. Posts 698782, 701345 and 714895 used for corporate context.
- **Etsy listing reviews** (18 listings) corroborate RW4 kickstand demand (StandKeeper 1034753207, 20 reviews). These count as competition, not SoMo demand.

---
## 9. Competition (real prices only, fetched 2026-09-24)
- **Etsy API v3** (107 listings):
  - Bottle Holder Mounting Bracket $31.98 (811472398, 547 favs); Rad battery cap $10.99 (768189023, 396 favs); Screen Cover $24.99 (846589238).
  - RR6+/RC5 display covers $7.95 (1386731282) and $19.99 (1163000482); Remote UI Cover $14.99 (1327914181); KT display cover $6.95; RR6+ head/tail light covers $8.95.
  - Charge-port plug 2-pack $20.00; fuse covers $9.99 / $4.00; RR6+ KT controller mounting hardware $6.95.
  - RW4 Fender Upgrade Kit $14.99; RW4 StandKeeper $15.00 (1034753207, 221 favs); RW4 Kickstand Stabilizer $19.99; kickstand booties $16.00.
  - GoPro mounts $9.99; RW4 stand holder STL $2.90; deck pad fasteners $10.95; pannier adapter $22.00 (858026406).
- **Amazon search results** (not blocked; many new zero-review listings):
  - RR Plus fender sets $39.99–$75.99; RadCity fender sets $36.99–$59.99.
  - RR6+/RC5+ dashboard rain covers $21.99–$23.99.
  - RW4 kickstand holders $14.99–$19.99 (incl. "3D-Printed" at $15.99); RW4 kickstands $23.99–$42.99.
  - Charge-port covers $19.90–$30.00; mirror for RadRover 5 $26.87 (2,696 ratings); Rad LCD display $85.
  - Amazon product (/dp) pages: NOT ATTEMPTED.
- **Bikeshop West** (third-party Rad parts, 267 products):
  - Rad UI Remote $99 and Rad UI Display $129 (in stock).
  - Fenders: RR6 front/rear $39 each; RW4 $39; RC5 $39/$29.
  - RR Plus kickstand $35; RW4 kickstand $69; RW4 kickstand spring $10; accessory port cover $10; LED display cover $7.
- **St George Ebikes** "UI Remote for Rad Power Plus Bikes": BLOCKED, price NEEDS DATA.
- **eBay:** BLOCKED, NEEDS DATA.
- **Free files:**
  - Printables: Radrover 6+ Display Covers and UI Bracket (995999); Rad Runner Premium Headlight bracket (657351); RadRunner charge-port cover; 35A controller mount; Radrunner Front Rack; thumb throttles.
  - MakerWorld: RadExpand 5 Chain Ring Guard; Rad Runner handlebar extender; Rad battery/throttle/cap set.

---
## 10. Source health
| Source | Status | Notes |
|---|---|---|
| Rad products.json US | OK | 148 products |
| Rad products.json CA | OK | 139 products |
| Rad product pages (US) | OK | fit text scraped |
| Rad warranty page | OK | updated 2026-05-14 |
| Rad help center | PARTIAL | JS-rendered; RR6+ 2021 manual via rideemtb PDF OK |
| Yotpo filter.json store-wide | OK (capped) | 10k results/query cap; sliced; 82.8% coverage; newest 2026-04-15 |
| Wayback availability API | OK | |
| Wayback CDX | DOWN | timeouts |
| web.archive.org snapshots | PARTIAL | TLS errors; ~5/15 fetches succeeded (`--http1.1` retries) |
| YouTube Data API v3 | OK | 120 videos / 7,491 comments |
| EBR forums `/search/search?keywords=` | OK | thin |
| Electric Bike Report | PARTIAL | web-search only; nothing parts-specific |
| Etsy API v3 | OK | 107 listings, reviews for 18 |
| MakerWorld | OK | HTML search |
| Printables | BLOCKED (403) | fallback: web-search snippets + one GraphQL probe |
| Amazon search results | OK | 10 queries |
| Amazon product pages | NOT ATTEMPTED | would be BLOCKED |
| eBay | BLOCKED (403) | NEEDS DATA |
| Bikeshop West products.json | OK | 267 products |
| St George Ebikes | BLOCKED (Cloudflare) | |
| 99spokes | BLOCKED (Cloudflare) | |
| Context.dev | DOWN (401 USAGE_EXCEEDED) | tried once |
| News (TechCrunch, GeekWire, BRAIN, Electrek, CPSC) | OK | via web search |
| Reddit / Facebook | SKIPPED (policy) | Reddit snippets excluded |

A BLOCKED source is not treated as "nothing found".

---
## 11. Method lessons
1. Rad's Shopify tags (`Current Model Compatibility_*` vs `Legacy Model Compatibility_*`) are a ready-made fit matrix. Use **both** US and CA: the US store doesn't tag MY25 RadRunner models or the Max.
2. Yotpo's store-wide feed caps each query at 10k results. Slice by star, sort both ways, add keyword queries, then merge by id. Its product map exposes **delisted spare-part SKUs** (UI Remote, controllers, cable covers), which proves removals better than the flaky Wayback.
3. Yotpo free-text search is fuzzy/OR, so always regex-filter locally.
4. Official "not compatible" fit text is the fastest gap finder (mirror, phone mount, bottle, headlight vs rack, RR Plus fenders).
5. Wayback: the availability API works; CDX times out; snapshots need `--http1.1` plus retries; products.json is not archived.
6. The Yotpo feed stopped after 2026-04, so post-acquisition demand must come from YouTube, forums and Etsy reviews.
7. Amazon is filling with new zero-review Rad-fit listings. Treat that as a competition signal, not demand.
8. YouTube parts demand skews electrical (controllers, batteries, throttles). Filter those out as liability before ranking.
