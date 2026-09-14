# Retail Data Model Roadmap — What to Build Next

## Context

Yesterday we published two data models to the Sigma playground (`playground-sean-miller`):

- **Retail Uploads** (`b765b086-4e7e-426b-ac82-7d6e0cf5a71c`) — raw layer, **all 23 CSVs** uploaded as elements.
- **Retail Sales Activity** (`8c548776-acb2-46ac-b60d-dd5a70781bd2`) — curated model with 6 conformed dims, `sales_activity` (4.9M order lines, sales + returns unioned), `sales_orders` (717,747), `budget`, `markdowns`, and 18 model-level metrics.

That model consumed **11 of the 23** uploaded tables. The other 12 — roughly **300 MB and 13 million rows** of labor, traffic, inventory, purchasing, review, web, and org data — are already sitting in Retail Uploads, unmodeled and unreferenced.

This plan ranks what to build next. Every claim below was verified by querying the live models, not inferred from headers.

---

## What the data actually supports (verified findings)

| Finding | Evidence |
|---|---|
| **Sales, labor, and traffic share an exact hourly grain.** | Retail sale timestamps span hours **9–20**; `F_LABOR` and `F_STORE_TRAFFIC` span hours **9–20**. Both facts are 3,332,953 rows, Store × Date × Hour, co-grained 1:1. A test join produced clean hourly conversion: **8.16% overall**, peaking **8.56% at noon** and 8.45% at 5pm, troughing 6.7% at 9am. |
| **All facts align on one window.** | Sales, labor, traffic all run **2021-08-19 → 2025-10-18/19**. Inventory runs 2021-08-15 → 2025-10-12. `D_DATE` is wider (2021-01-03 →) but that's just calendar padding. |
| **Omnichannel routing is fully encoded and completely unexploited.** | `Transaction Location Key` / `Fulfillment Location Key` are carried in `sales_orders` but never interpreted. Retail (536,065): store = txn = fulfillment. Web (122,713): txn always 9999 (warehouse); fulfillment = warehouse for 85,761 but **a store for 36,952 → ship-from-store**. BOPIS (38,148) and BOSS (20,821): txn 9999, fulfillment = a store. |
| **Inventory is a sparse change-log over a full assortment.** | 220,296 store-product pairs = exactly 201 × 1,096 (every store carries every SKU). 5.95M rows over 218 weekly dates ≈ **27 changes per pair**, so a dense weekly position requires last-value-carried-forward. ~~23.5% of rows sit at zero on hand; 25.4% at or below reorder point.~~ **Corrected during the Model 2 build: those row-weighted figures are artefacts. Time-weighted, stockout is 3.19% and below-reorder-point 6.57% — see the build log.** |
| **Purchasing is clean but store-blind.** | 53,137 received PO lines + 452 in transit, **$979.8M**, one line per PO number, avg **−0.02 days** vs expected (on time in aggregate; the distribution is where the vendor signal lives). No `Store Key` — vendor/product grain only. |
| **The org hierarchy is a tidy 3 levels.** | 200 Store Managers (one per store) → 18 AVPs → 5 RVPs. No store assignment above SM. 1,840 employees, **406 terminated (22% attrition)**. No recursion needed — a double self-join flattens it. |
| **Marketing is day × source, sales are not attributed.** | `F_WEB_TRAFFIC` and `F_MARKETING_SPEND` are co-grained (1,522 days × 6 sources): Organic Search, Social, Paid Search, Direct, Referral, Email. **4.83M web visits → 122,713 web orders ≈ 2.54%.** No traffic source on any order, so ROAS is blended at day level, never per-source. |
| **Two dead columns to drop.** | `F_PRODUCT_REVIEW.Verified Purchase` is `'Y'` for all 137,944 rows. `D_STORE`'s parking block and `Monthly Rent Cost` are UPPER_SNAKE-only and currently unused (rent is genuinely useful — see Model 1). |

Also relevant: the four planning docs already in this repo (`STORE_PERFORMANCE_COMMAND_CENTER_PLAN.md`, `Inventory_Risk_Reorder_Assistant_Build_Plan.md`, `Commission_Performance_Coach_Sigma_Scope.md`, `clienteling-app-plan.md`) are all **app/workbook** designs written against raw CSVs. Each one is blocked on a semantic layer that doesn't exist yet. Models 1, 2, 5, and 6 below are exactly those missing layers.

---

## Recommended portfolio — 6 models, ranked

### 1. Retail Store Operations — ✅ BUILT 2026-09-13

**Grain:** Store × Date × Hour (3,332,953 rows)
**Sources:** `F_LABOR`, `F_STORE_TRAFFIC`, `F_SALES` (pre-aggregated to store-date-hour), `D_TIME`, `D_STORE`, `D_STORE_LEADERSHIP`, `F_BUDGET`

This is the highest-value model in the mart and the only one that answers questions Sales Activity structurally cannot: *was the store staffed for the rush?* Sales Activity knows what sold; it has no idea how many people walked in or how many associates were on the floor.

**Elements**
- `store_hour` — the co-grained fact. Traffic ⨝ labor 1:1 on Store Key + Date Key + Hour, then LEFT JOIN pre-aggregated hourly orders. **Pre-aggregate sales to store-date-hour before joining or the fact fans out.**
- `store_day` — daily rollup for trend work, so dashboards don't scan 3.3M rows for a weekly chart.
- `dim_time` — `D_TIME` (Hour, Hour Label, Daypart, Is Typical Business Hour), the ready-made hour dimension.
- `dim_leadership` — flattened Store Manager / AVP / RVP per store.

**Metrics:** Conversion Rate (orders ÷ visits), Traffic, Sales per Visit, Sales per Labor Hour, Labor Cost %, Staffing Variance (actual − scheduled), Traffic per Staff, Sales vs Budget %, Four-Wall Contribution (net margin − labor − rent, using the unused `MONTHLY_RENT_COST`).

**Design notes**
- Warehouse 9999 has no labor or traffic — this model is **200 stores**, not 201.
- Store-hours per hour-of-day vary by design (150,075 at 9am vs 304,400 at 11am–5pm) because stores keep different weekday/Sunday hours. Use `D_STORE`'s `Weekday Open Hour / Close Hour / Sunday Open Hour / Close Hour` to distinguish **closed** from **open but zero traffic** — averaging without that split understates conversion at the shoulders.
- `F_LABOR` carries **staff counts**, not hours (the daily backup on disk had true hours; the hourly version replaced them). "Sales per Labor Hour" is really sales per staffed store-hour — name it honestly.
- Scheduled and actual staff net out almost exactly in aggregate (12,450,083 vs 12,451,983). The signal is entirely in per-store-hour variance, so surface variance, never the totals.

---

### 2. Retail Inventory & Replenishment — ✅ BUILT 2026-09-13

**Grain:** Store × Product × Week (5,954,664 change-log rows → ~48M dense weeks)
**Sources:** `F_INVENTORY_SNAPSHOT`, `F_INVENTORY_ADJUSTMENT`, `F_PURCHASE_ORDER`, `D_VENDOR`, `D_PRODUCT`, `D_STORE`

The second-largest untapped asset, and the one with the richest built-in signal: a quarter of all snapshot rows are stocked out or below reorder point.

**Elements**
- `inventory_position` — the weekly position. **The core modeling challenge is here:** the source is a sparse change-log (~27 rows per store-product over 218 weeks), so a naive join to a week spine leaves 96% nulls. Either carry last value forward against the 218 distinct effective dates, or model as-of and accept a point-in-time-only element. Decide this before building anything else.
- `inventory_adjustments` — 66,088 rows, Store × Product × Date, with reason codes → shrink and damage analysis.
- `purchase_orders` — **keep separate.** No `Store Key` means it cannot join to the store-product grain; forcing it will silently fan out.
- `dim_vendor` — 20 vendors with lead time, payment terms, rating.

**Metrics:** Weeks of Supply, In-Stock %, Stockout Rate, Sell-Through %, Inventory Turns, GMROI, Shrink Rate, PO On-Time %, Vendor Fill Rate, Actual vs Quoted Lead Time (`D_VENDOR.Lead Time Days` vs the PO date spread).

**Design notes**
- Join sales velocity from `sales_activity` at store-product-week to compute supply days. This is the one model that must cross-reference the existing model's fact, not just its dims.
- `F_INVENTORY_ADJUSTED.csv` on disk (company-wide, no store, no date) is inconsistent with everything else and **was deliberately not uploaded**. Leave it out.
- Warehouse 9999 **is** in the snapshot (201 stores) — unlike Model 1. Filter it explicitly for store-level in-stock reporting.

---

### 3. Retail Omnichannel Fulfillment — ✅ BUILT 2026-09-13

**Grain:** Order (717,747)
**Sources:** `sales_orders` from the existing model + `D_STORE` (twice)

The data is already in the published model; nobody has given it meaning. This is a small model with a high insight-per-hour ratio.

**Elements**
- `fulfillment_orders` — `sales_orders` with a derived `Fulfillment Pattern` (In-Store / Ship-from-DC / Ship-from-Store / BOPIS / BOSS), plus `Store` joined **twice as a role-playing dimension**: selling store (`Store Key`) and fulfilling store (`Fulfillment Location Key`).

**Metrics:** Digital Mix %, Ship-from-Store Rate (**36,952 of 122,713 web orders = 30.1%** — the headline number), Cross-Store Fulfillment Rate, BOPIS Attach, Fulfillment Distance (`D_STORE` has real lat/long — haversine between selling and fulfilling store), Channel Return Rate.

**Design note:** the role-playing join is the whole point and also the only real complexity. Alias the two store references unmistakably (`Selling Store …` / `Fulfilling Store …`) or every downstream chart will be ambiguous.

---

### 4. Retail Customer 360 — ✅ BUILT 2026-09-13

**Grain:** Customer (4,971)
**Sources:** `dim_customer`, `sales_orders`, `sales_activity`, `F_RETURNS`, `F_PRODUCT_REVIEW`

**Elements:** `customer_profile` (RFM, lifetime spend, first/last purchase, tenure, order count, return rate, primary store, primary salesperson), `customer_reviews` (137,944 reviews, 4,442 of 4,971 customers, avg rating 4.014).

**Metrics:** Lifetime Value, Recency Days, Frequency, AOV, Return Rate, Repeat Rate, Avg Rating Given, Churn Risk.

**Design notes**
- `LOYALTY_TIER`, `DOWNLOADED_APP`, `BIRTHDAY_MONTH`, `BIRTHDAY_DAY` exist **only** in the UPPER_SNAKE block of `D_CUSTOMER`. `dim_customer` already surfaces loyalty tier and app download; birthday fields are still unexposed and are what the clienteling plan needs.
- **Drop `Verified Purchase`** — 100% `'Y'`, zero information.
- The static dataset ends 2025-10-19. Recency must be computed against an **As Of Date** control defaulting to `Max(Date)`, not `Today()`, or every customer reads as churned. All four repo planning docs converged on this same pattern; make it a model-level convention.

---

### 5. Retail Marketing & Digital Funnel — ✅ BUILT 2026-09-13

**Grain:** Date × Traffic Source (9,132)
**Sources:** `F_WEB_TRAFFIC`, `F_MARKETING_SPEND`, `dim_promotion`, `markdowns`, digital orders from `sales_orders`

Small, fast, and the only view of demand *before* it becomes a transaction.

**Metrics:** Web Visits, Spend, Cost per Visit, Web Conversion Rate (2.54% baseline), Revenue per Visit, Blended ROAS, Spend Mix, Promo Lift.

**Be explicit about the limitation:** orders carry no traffic source. Per-source ROAS is not derivable from this data. Model spend and visits per source, then join revenue **only at the day level as a blended metric**, and label it as such in the element description. Quietly implying per-source attribution is the one way this model can mislead.

---

### 6. Retail Workforce & Org — ✅ BUILT 2026-09-13

**Grain:** Employee (1,840)
**Sources:** `D_EMPLOYEE`, `D_STORE_LEADERSHIP`, `D_SALESPERSON`, `sales_activity`, `F_LABOR`

**Elements:** `dim_org` (flattened Employee → Store Manager → AVP → RVP), `employee_performance` (sales attributed via `Salesperson Key`, commission earned, tenure, status).

**Metrics:** Sales per Associate, Commission Earned, Attainment vs Tier Peers, Span of Control, Attrition Rate (22% baseline), Tenure-to-Productivity curve.

**Design notes**
- Only 3 levels — flatten with a double self-join, **not** recursion.
- `D_EMPLOYEE` (1,840) is the superset roster; `D_SALESPERSON` (1,617) is the commissioned subset. `D_EMPLOYEE` uniquely adds Store Area, Store Region, Reports To Key, Compensation Type, Annual Salary. Make `D_EMPLOYEE` the spine and treat `D_SALESPERSON` as a conformed subset, not a parallel truth.
- The commission-coach doc's key finding still holds: `Tier` is **seniority, not a volume threshold**, and `Commission Rate` varies *within* tier. Don't let the model imply tier determines rate.

---

## Architecture decision

All six models source from **Retail Uploads** and need the same six conformed dimensions that **Retail Sales Activity** already publishes as visible sources.

**Decided: reference `dim_date`, `dim_store`, `dim_product`, `dim_customer`, `dim_salesperson`, `dim_promotion` directly from Retail Sales Activity.** Zero refactor, guaranteed conformance, and it reuses the UPPER_SNAKE cleanup and the ragged product hierarchy already built there.

The accepted tradeoff is that Sales Activity becomes a dependency of every other model. If that becomes awkward later, extract a **Retail Conformed Dimensions** model between Uploads and the subject areas and repoint everything — a refactor to do once, deliberately, not a reason to delay Model 1.

```
Retail Uploads (23 raw CSVs)
  └── Retail Sales Activity ── dims ──┬── Store Operations        (1)
                                      ├── Inventory & Replen.     (2)
                                      ├── Omnichannel Fulfillment (3)
                                      ├── Customer 360            (4)
                                      ├── Marketing Funnel        (5)
                                      └── Workforce & Org         (6)
```

---

## Conventions to carry forward from Sales Activity

These were settled yesterday and should hold across every new model:

1. **Ratios are metrics, never row-level columns** — per-row ratios average wrong at every rollup.
2. **Pre-aggregate before joining** any fact whose grain is finer than the target.
3. **Column cleanup lives in the model layer**, not the CSVs.
4. **Document the traps in element descriptions**, as `sales_activity` does for the `Transaction Type = 'Return'` gotcha.
5. **Fiscal-first.** The 4-5-4 calendar is the reporting calendar; Sigma's built-in PoP and `DateLookback` are calendar-based and will not respect 4-5-4 boundaries. Use `Prior Year Date` for explicit fiscal-correct comps.
6. **As Of Date control** defaulting to `Max(Date)` wherever a rolling window is involved.
7. **Every published metric carries a description**, and a bare figure is not one. State what the metric measures, its unfiltered value as a benchmark, and the way it is most likely to be misread — the aggregation level it is valid at, what it excludes, what a null means. Inventory & Replenishment enforces this by making `desc` a required argument of its `met()` helper, so a metric without one fails at generation rather than shipping silently.

---

## Suggested sequence

| Phase | Model | Why here |
|---|---|---|
| 1 | ~~**Store Operations**~~ ✅ | Built and verified 2026-09-13 — `07c9d946-3ccc-477d-8dd6-0ce4ebdf00bb` |
| 2 | ~~**Omnichannel Fulfillment**~~ ✅ | Built and verified 2026-09-13 — `0fae0207-760c-45ff-838c-f9beff22c894` |
| 3 | ~~**Inventory & Replenishment**~~ ✅ | Built and verified 2026-09-13 — `7a80315d-8faa-44cc-a5d0-18483bb3707e`. Built ahead of Omnichannel at request. |
| 4 | ~~**Customer 360**~~ ✅ | Built and verified 2026-09-13 — `14327edf-2fe7-4263-9444-8330a0668117` |
| 5 | ~~**Marketing Funnel**~~ ✅ | Built and verified 2026-09-13 — `ef97b1ac-88e6-471b-9aad-145b82b43a27` |
| 6 | ~~**Workforce & Org**~~ ✅ | Built and verified 2026-09-13 — `273cce13-d3be-489c-9adf-20d69ef975fe` |

---

## Build spec — Model 1: Retail Store Operations

Confirmed as the next build. New data model in `playground-sean-miller`, published via `POST /v2/workbooks/spec` using the `sigma-workbooks` skill (get a token via `sigma-api` first; the playground profile is the CLI default).

### Page 1 — Sources (`visibleAsSource: false`)

Cross-model references, prefixed `SRC` in formulas, mirroring the pattern in Retail Sales Activity:

| Ref | From | Element ID |
|---|---|---|
| `SRC F_LABOR` | Retail Uploads `b765b086-…` | `jU63b1LbRX` |
| `SRC F_STORE_TRAFFIC` | Retail Uploads | `qE363PAKVb` |
| `SRC F_SALES` | Retail Uploads | `TOhPY4-KGV` |
| `SRC D_TIME` | Retail Uploads | `6d0QSJNwQ2` |
| `SRC D_STORE_LEADERSHIP` | Retail Uploads | `O-JjreO6D0` |
| `SRC F_BUDGET` | Retail Uploads | `xQ5dfXHoWm` |
| `SRC Date` | Retail Sales Activity `8c548776-…` | `dim_date` |
| `SRC Store` | Retail Sales Activity | `dim_store` |

### Page 2 — Conformed Dimensions (`visibleAsSource: true`)

- `dim_time` — `D_TIME` passthrough (Hour, Hour Label, Daypart, Is Typical Business Hour).
- `dim_leadership` — `D_STORE_LEADERSHIP` flattened by a double self-join on `Reports To Key`: one row per store with Store Manager / AVP / RVP name, performance tier, bonus rate. Only 3 levels (200 → 18 → 5); RVPs have a null `Reports To Key` and terminate the chain.
- `Date` and `Store` re-exposed from the Sales Activity references so this model is self-sufficient as a source.

### Page 3 — Store Hour (the fact)

1. `hourly_orders` (hidden) — `SRC F_SALES` aggregated to Store Key × Date Key × `DATE_PART('hour', Date)`, producing order count and distinct customers. **This pre-aggregation is mandatory**; joining raw `F_SALES` fans the fact out. Keep `Channel Type` split so in-store conversion (Retail only) is separable from digital orders credited to the store.
2. `store_hour` (exposed, 3,332,953 rows) — `SRC F_STORE_TRAFFIC` ⨝ `SRC F_LABOR` 1:1 on Store Key + Date Key + Hour, LEFT JOIN `hourly_orders`, LEFT JOIN `Store` for attributes and open/close hours. Derived columns: `Is Open Hour` (from the weekday/Sunday open-close columns), `Staffing Variance` = Actual − Scheduled, `Daypart` via `D_TIME`.
3. `store_day` (exposed) — daily rollup so trend dashboards don't scan 3.3M rows.

### Page 4 — Supporting Facts

- `budget` — re-reference at Store × Fiscal Year × Fiscal Period. **Coarser grain than `store_day`**; join on Store Key + Fiscal Year + Fiscal Period, never on date.

### Model-level metrics on `store_hour`

All ratios as metrics, never row-level columns:

| Name | Formula sketch |
|---|---|
| Store Visits | `Sum([Store Visits])` |
| Orders | `Sum([Orders])` |
| Conversion Rate % | `[Metrics/Orders] / [Metrics/Store Visits]` |
| Labor Cost | `Sum([Labor Cost])` |
| Scheduled Staff | `Sum([Scheduled Staff Count])` |
| Actual Staff | `Sum([Actual Staff Count])` |
| Staffing Variance | `[Metrics/Actual Staff] - [Metrics/Scheduled Staff]` |
| Traffic per Staff | `[Metrics/Store Visits] / [Metrics/Actual Staff]` |
| Sales per Visit | `[Metrics/Net Sales] / [Metrics/Store Visits]` |
| Sales per Staffed Hour | `[Metrics/Net Sales] / [Metrics/Actual Staff]` |
| Labor Cost % | `[Metrics/Labor Cost] / [Metrics/Net Sales]` |

Net Sales here requires joining `sales_activity` amounts at store-date-hour, or deferring dollar metrics to `store_day` where the join is cheaper. Decide during build — **counts and labor work at hour grain regardless**, so ship those first if the dollar join proves expensive.

### Traps to encode in element descriptions

- 200 stores, not 201 — warehouse 9999 has no labor or traffic.
- `F_LABOR` carries **staff counts, not hours**. Name metrics accordingly ("per staffed hour", not "per labor hour").
- Scheduled and actual staff net out in aggregate (12,450,083 vs 12,451,983); only per-store-hour variance carries signal.
- Store-hours per hour-of-day legitimately differ (150,075 at 9am vs 304,400 midday) because of varying open hours. Use `Is Open Hour` to keep closed hours out of conversion denominators.
- `Transaction Type = 'Return'` in `F_SALES` is an order-level flag on positive-amount orders, unrelated to the returns ledger — the same gotcha documented on `sales_activity`.

---

## Verification

For whichever model we build:

1. **Row-count reconciliation** — the fact's row count must match the source element's, or the difference must be explained by a documented filter. Store Operations must land on **3,332,953**; a larger number means the sales join fanned out.
2. **Benchmark the headline metric** against the values verified here: hourly conversion ~8.16% overall / 8.56% at noon; ship-from-store 30.1% of web orders; 23.5% of inventory rows at zero on hand; PO on-time avg −0.02 days; 22% employee attrition.
3. **Query through the MCP** (`describe` → `query` against the new `dataModelId`) to confirm elements, columns, and metrics resolve as published.
4. **Cross-check against Sales Activity** where the models overlap — net sales by store and fiscal period must tie exactly between Store Operations' `store_day` rollup and `sales_activity`. All-time benchmarks: Gross Sales **$1,178,971,664**, Returns **$64,116,012**, Return Rate **5.44%**.
5. **Null audit on every join key** before publishing — especially the inventory carry-forward, where a silent gap looks identical to a genuine stockout.

---

## Build log — Model 1 shipped

**Retail Store Operations** — `07c9d946-3ccc-477d-8dd6-0ce4ebdf00bb`
<https://app.sigmacomputing.com/playground-sean-miller/data-model/Retail-Store-Operations-eHbRNEwqLeuogeqrbhzwD>

8 elements across 5 pages: `dim_time`, `dim_store`, `dim_date`, `dim_leadership`, `store_hour` (17 metrics), `store_day` (9 metrics), `budget` (2 metrics), plus two hidden pre-aggregation elements. Spec generator committed as `gen_store_ops.py`; regenerate and re-publish with `api data-models spec update`.

### Verified against every pre-build benchmark

| Check | Expected | Actual |
|---|---|---|
| `store_hour` rows | 3,332,953 (no fan-out) | **3,332,953** ✅ |
| Stores | 200 (warehouse absent) | **200** ✅ |
| Hours | 9–20 | **9–20** ✅ |
| Conversion, all hours | 8.16% | **8.16%** ✅ |
| Conversion at noon / 9am | 8.56% / 6.70% | **8.56% / 6.70%** ✅ |
| Labor cost | $215,386,540.31 | **$215,386,540.31** ✅ |
| Scheduled / actual staff | 12,450,083 / 12,451,983 | **exact** ✅ |
| Retail net sales vs Sales Activity | $844,609,615.53 | **$844,609,615.53** ✅ |
| `store_day` rollup | ties to `store_hour` | **ties exactly** ✅ |

### Two findings that changed the design mid-build

1. **All-channel dollars corrupt every traffic ratio.** Web/BOPIS/BOSS sales are credited to a store but never walked through its door, and digital orders placed outside trading hours have no store-hour to land on at all (~9% of company net sales). The fact now carries `Retail Net Sales` — in-store only, and complete — and **every traffic-based metric (Sales per Visit, ATV, Labor Cost %, Sales per Staffed Hour) divides by that**. The all-channel columns are retained but renamed `… (All Channels, In-Hours)` with descriptions stating they are partial by design and must never be used as a company total.
2. **`Is Open Hour` is true for every row.** Traffic and labor are only recorded for hours a store actually trades, so shoulder hours have *fewer store-hours* rather than closed rows (hour 9 has 150,075 store-hours vs 304,400 midday). The column is kept as a guard, with a description saying plainly that it currently filters nothing.

### First insight off the model

Staffing is inverted against demand. Hour 9 runs **+3,904 staff over schedule** at the worst conversion of the day (6.70%) and a 43.0% labor cost ratio, while the three peak hours are *under* schedule — noon −317, 5pm −475, 6pm −410 — at the best conversion (8.56% / 8.45% / 8.42%). Moving morning coverage into the midday and evening peaks is the obvious first test.

### API gotchas worth remembering

- `folderId` is **required** on `POST /v2/dataModels/spec` and is absent from the `get` round-trip, so a spec copied from an existing model fails with a misleading `"Unknown error in data model spec"`.
- The API returns only an error *count*, never the errors, and local OpenAPI validation passes specs the server rejects — bisect by submitting subsets.
- `And(...)` / `Or(...)` are not valid Sigma formula functions; use the infix `and` / `or` operators.


---

## Build log — Model 3 shipped

**Retail Omnichannel Fulfillment** — `0fae0207-760c-45ff-838c-f9beff22c894`
<https://app.sigmacomputing.com/playground-sean-miller/data-model/Retail-Omnichannel-Fulfillment-tApdxLNAKhFyH02QZUBVy>

11 elements across 5 pages. Exposed as sources: `Store`, `Date`, `Customer`, `fulfillment_orders` (31 metrics), `fulfillment_day` (11 metrics). Hidden: 5 `SRC` references, the `Fulfilling Location` role-playing alias, and the `order_amounts` pre-aggregation. Spec generator committed as `gen_omni_fulfillment.py`.

### Verified against every pre-build benchmark

| Check | Expected | Actual |
|---|---|---|
| `fulfillment_orders` rows / distinct orders | 717,747 (no fan-out) | **717,747 / 717,747** ✅ |
| Pattern split | 536,065 / 85,761 / 36,952 / 38,148 / 20,821 | **exact on all five** ✅ |
| Ship-from-Store Rate (of web orders) | 30.1% | **30.11%** ✅ |
| Gross Sales | $1,178,971,663.73 | **exact** ✅ |
| Returns / Return Rate | $64,116,011.81 / 5.44% | **exact / 5.438%** ✅ |
| In-Store net sales vs Store Operations | $844,609,615.53 | **exact cross-model tie** ✅ |
| Order lines collapsed by pre-agg | ~4.9M | **4,899,866 → 717,747** ✅ |
| Null audit on every join key | 0 | **0** ✅ |
| `fulfillment_day` rollup | ties to order grain | **ties exactly** ✅ |

### Three findings that changed the design mid-build

1. **Cross-store fulfilment does not exist — the metric had to be cut.** `Store Key` *equals* `Fulfillment Location Key` on all 631,986 store-fulfilled orders; the count of genuine cross-store fulfilments is **exactly 0**. The planned "Cross-Store Fulfillment Rate" would have been a permanent zero dressed up as a KPI. It ships instead as `Cross-Store Fulfillment Orders (Guard)`, documented as 0 by construction and retained only to detect that changing — the same treatment `Is Open Hour` got in Model 1.

2. **Fulfilment distance is not computable, so no distance metric shipped.** All three possible endpoints fail: the Central Warehouse (9999) has **null latitude and longitude** (its `D_STORE` row is almost entirely empty), `D_CUSTOMER` has **no coordinates at all** — only city/state/ZIP/county — and store-to-store distance would be zero everywhere per finding 1. The roadmap's haversine plan cannot be built on this data. Shipped instead: **In-Region / In-State Fulfillment %** (96.6% / 96.0%), defined **only over store-fulfilled orders** because the warehouse has no region and would otherwise read as a false out-of-region ship.

3. **`[Metrics/X]` references break inside a grouped element.** On `fulfillment_day` (which has a `groupings` block), metric-to-metric formulas failed with `Column "…--metric-["returns_amount"] does not exist` — the reference resolved to the like-named *column* instead of the metric. The ungrouped `fulfillment_orders` element has the same name collisions and resolves fine. Every ratio metric on the rollup now aggregates its columns directly (`Sum([Returns]) / Sum([Gross Sales])`).

Also documented: `Prior Year Date` is null for 62,463 orders — all of FY2021 (no prior year loaded) **plus the 3,399 orders in FY2023 week 53**, because FY2023 is a 53-week year and FY2022 had no week 53. Correct 4-5-4 behaviour, but year-over-year charts will silently drop week 53 unless handled.

### First insight off the model — the return rate is a mix illusion

Company return rate rose every year, 5.12% (FY2021) → 5.58% (FY2025). **Every individual fulfilment pattern improved or held flat over the same span:**

| Pattern | FY2021 | FY2025 | All-time |
|---|---|---|---|
| Ship-from-Store | 10.41% | **9.87%** | 10.09% |
| Ship-from-DC | 10.36% | **9.44%** | 9.86% |
| BOPIS | 6.81% | 6.98% | 7.12% |
| BOSS | 7.55% | **6.93%** | 7.07% |
| In-Store | 4.38% | **4.12%** | 4.23% |

The blended number worsened purely because digital mix **doubled**, 15.0% → 31.9% of orders, and digital returns at ~2.4× the in-store rate. Textbook Simpson's paradox: returns performance is improving everywhere and degrading in aggregate.

The second-order finding: **Ship-from-Store Rate has been dead flat at ~30.1% for all five years** (30.07 / 29.81 / 30.28 / 30.19 / 30.11) while digital volume more than quintupled. The routing policy has never changed. Since ship-from-store carries the *worst* return rate of any pattern (10.09%) and BOPIS the best of the digital routes (7.12%), shifting web demand toward BOPIS — currently only 21.0% of digital orders — is the obvious first test.

### All 42 published metrics carry descriptions

Every metric on both exposed elements (`fulfillment_orders` 31, `fulfillment_day` 11) has a description stating what it measures, the **denominator** where it is a ratio, its verified all-time value, and any trap. Metric `description` is undocumented — the cached OpenAPI defines no metric schema whatsoever — but it round-trips through `spec get` and renders in MCP `describe` beside the formula, which is the surface a consumer or agent actually reads when choosing a metric. Worth making a convention across the mart: a ratio's denominator is the one thing its name can never convey, and three of this model's ratios (Ship-from-Store Rate %, In-Region %, In-State %) have deliberately non-obvious denominators.

### API gotchas worth remembering

- `sigma api data-models spec create --params @file` puts the whole spec in the **query string** and fails with `414 Request-URI Too Large`. The spec must go in `--body`; `--params` is only for path/query parameters. (Model 1 hit this too and is why `spec update` takes both flags.)


---

## Build log — Model 6 shipped

**Retail Workforce & Org** — `273cce13-d3be-489c-9adf-20d69ef975fe`
<https://app.sigmacomputing.com/playground-sean-miller/data-model/Retail-Workforce-and-Org-1c2uiBpVJNsVw3Uzbw9hM2>

13 elements across 6 pages. Five exposed as sources: `Org`, `Employee Performance` (24 metrics), `Employee Period` (9 metrics), plus conformed `Store` and `Date`. Spec generator committed as `gen_workforce_org.py`; regenerate and re-publish with `api data-models spec update`.

### Verified against every pre-build benchmark

| Check | Expected | Actual |
|---|---|---|
| `employee_performance` rows | 1,840 (no fan-out) | **1,840** ✅ |
| Hierarchy | 200 SM → 18 AVP → 5 RVP | **exact, all levels resolve** ✅ |
| Net sales attributed | ties Sales Activity | **$1,114,855,651.92** ✅ |
| Gross sales | $1,178,971,664 | **$1,178,971,663.73** ✅ |
| Returns / return rate | $64,116,012 / 5.44% | **$64,116,011.81 / 5.4383%** ✅ |
| Orders | 717,747 | **717,747** ✅ |
| Attrition | 22% | **22.07%** ✅ |
| Commissioned / selling | 1,617 / 1,522 | **1,617 / 1,522** ✅ |
| Span of control | SM 8.09, AVP 11.11, RVP 3.60 | **exact** ✅ |
| `employee_period` net sales | ties `employee_performance` | **ties exactly** ✅ |

**100% of company net sales attribute to a named associate** — every order line carries a Salesperson Key, and the associate's home store always equals the order's store. There is no unattributed residual to reconcile.

### Four findings that changed the design mid-build

1. **`Tenure Years` is hire-to-today for everyone, including the 406 who have left.** It keeps accruing after termination, overstating leaver tenure by a mean of **2.53 years** (5.18 reported vs 2.64 actual). Any attrition-by-tenure or tenure-band analysis built on the raw column is wrong. The model now publishes a corrected `Tenure Years` (hire-to-termination for leavers, as-reported for actives) plus `Tenure Years at Exit`, and retains the original as `Tenure Years (As Reported)`.

2. **The tenure-to-productivity curve the roadmap asked for does not exist.** Raw all-time sales suggest an 8.2× ramp (\$122,527 at <1yr → \$1,004,253 at 5-8yr) — but average active days rise 8.7× over the same bands (170 → 1,444). It is pure exposure. Normalised to **Net Sales per Active Day** the curve is flat and slightly *declining*: 721 → 668 → 733 → 714 → 696 → **648** at 8yr+. Attainment Index tells the same story: the newest cohort runs **1.056**, the longest-tenured **0.945**. The model therefore carries `Active Days` as a first-class exposure denominator and makes the per-day rate the headline productivity metric. Shipping the roadmap's metric on raw sales would have manufactured a finding the data does not support.

3. **Blended attrition hides two completely different populations.** The 22% headline is really **25.11% for commissioned associates and exactly 0% for all 223 leaders** — not one Store Manager, AVP or RVP has ever left. Quoting 22% understates the frontline problem and invents a retention problem in leadership that does not exist. Encoded in the metric description.

4. **Orders are not additive across fiscal periods.** An order returned in a later period appears in both, giving 867,401 order-period pairs against only 717,747 real orders. `Employee Period` now publishes `Orders Sold` (additive, ties to 717,747) alongside `Orders Touched` (period-local only), with the trap in the element description.

### First insight off the model

**Commission rate is decoupled from productivity.** Pooled net sales per active day is nearly flat across tiers — Cashier 703.5, Ambassador 697.4, Lead 686.1, Senior Ambassador 634.7 — while the commission rate paid runs **1.47% → 3.01% → 4.12% → 5.75%**, a 3.9× spread. Senior Ambassadors are the *least* productive per day and earn the second-highest rate. This confirms and sharpens the commission-coach doc's finding that `Tier` is seniority, not a volume threshold: the company pays a 3.9× rate premium for seniority that buys no measurable daily productivity. Blended commission cost is **2.77%** of net sales (\$30,839,726).

### Design decisions worth recording

- **`D_SALESPERSON` is deliberately not sourced.** Its 1,617 rows are provably identical to the `Compensation Type = 'Commission'` subset of `D_EMPLOYEE` on key, name, store, tier and rate (verified 100% on every column). Sourcing both would create two truths for one fact; the roadmap's "conformed subset, not parallel truth" is implemented by deriving the subset.
- **`F_LABOR` is deliberately not sourced.** It is Store × Date × Hour with no employee key and cannot reach employee grain — the same reason `purchase_orders` stays separate in Model 2. Staffing lives in Store Operations.
- **`D_STORE_LEADERSHIP` uses a separate keyspace.** `Leadership Key` runs 1-223 while the same 223 people are `Employee Key` 1618-1840 — a clean +1617 offset, verified on name, role, store, salary and hire date. The model joins on `Employee Name` (unique in both) rather than the arithmetic offset, which is coincidental to load order.
- **Three fixed self-joins, not recursion**, as the roadmap directed. Role-playing copies of `D_EMPLOYEE` are named `Manager` / `Manager L2` / `Manager L3` by *level*, because the chain is level-relative: an IC's `Manager` is a Store Manager, but a Store Manager's `Manager` is an AVP. Role-absolute `Store Manager` / `AVP` / `RVP` columns are then derived from the level plus the employee's own type, so every person — including leaders — resolves their own chain.
- **Recency and exposure are measured against a `Sales Window` element** holding `Max(Sale Date)` from the fact, not `Today()`, per convention 6. It is data-driven rather than hardcoded, so it follows the data if the window ever moves.

### API gotchas worth remembering

- **`folderId` goes in the request BODY, not the query string.** The OpenAPI schema lists it as required alongside `name` in `CreateDataModelSpec`. Passing it via `--params` puts it in the URL and returns the same misleading `"Unknown error in data model spec"` as omitting it entirely.
- The Sigma CLI splits `--params` (path/query) from `--body` (request body). Passing a whole create payload to `--params` URL-encodes the entire spec into the query string and fails with a `builder error for url`.

---

## Build log — Model 5 shipped

**Retail Marketing & Digital Funnel** — `ef97b1ac-88e6-471b-9aad-145b82b43a27`
<https://app.sigmacomputing.com/playground-sean-miller/data-model/Retail-Marketing-and-Digital-Funnel-7i6upyuRpmhUANApeRwjt5>

15 elements across 4 pages. Exposed as sources: `Date`, `Traffic Source`, `Promotion`, `funnel_source` (7 metrics), `funnel_day` (22 metrics). Hidden: 6 `SRC` references and 4 pre-aggregations (`web_daily`, `digital_daily`, `promo_day`, `markdown_day`). Spec generator committed as `gen_marketing_funnel.py`, rendered spec as `marketing_funnel_spec.json`.

All **29 published metrics carry descriptions** (`MET_DESC` in the generator), each stating what the metric measures, its verified all-time value, and the trap that applies to it — which ratios are blended across sources, which denominators include free traffic, and which figures (ROAS above all) must not be planned against.

### Verified against every pre-build benchmark

| Check | Expected | Actual |
|---|---|---|
| `funnel_source` rows | 9,132 = 1,522 days × 6 sources | **9,132 / 1,522 / 6** ✅ |
| `funnel_day` rows | 1,522 (no fan-out) | **1,522** ✅ |
| Web visits | 4,834,940 | **exact** ✅ |
| Marketing spend | $1,564,043.87 | **exact** ✅ |
| Web orders / conversion | 122,713 / 2.54% | **122,713 / 2.5380%** ✅ |
| Digital orders / conversion | 181,682 / 3.76% | **181,682 / 3.7577%** ✅ |
| Digital gross / returns / net | $297,012,840.24 / $26,766,803.85 / $270,246,036.39 | **exact on all three** ✅ |
| Total gross sales (all channels) | $1,178,971,663.73 | **exact** ✅ |
| Digital return rate | 9.01% vs 5.44% company | **9.012%** ✅ |
| Revenue per visit / Blended ROAS | $61.43 / 189.90 | **exact** ✅ |
| Markdowns vs price resets | 1,118 / 4,933 | **exact** ✅ |
| Promotional days | 288 of 1,522 | **288** ✅ |
| Cross-model tie to `sales_activity` | all five digital aggregates | **exact** ✅ |
| Null audit on every join key | 0 | **0** ✅ |

### Three findings that changed the design mid-build

1. **Two of the six sources are free, and blending them destroys every efficiency metric.** Direct and Organic Search record **$0 spend on all 1,522 days** — not missing data, genuinely unpaid — yet they supply 2,148,437 visits, **44.4% of all sessions**. A blended cost per visit ($0.3235) is therefore ~1.8× understated against paid media. `Is Paid Source` and `Source Group` ship on the Traffic Source dimension so every efficiency figure can be restricted to traffic that actually cost something.

2. **The roadmap's 2.54% baseline understates conversion, because BOPIS and BOSS are also web sessions.** All three digital channels transact at location 9999 — they are placed online and are outcomes of the same traffic. Web-only conversion is 2.5380%; **Web + BOPIS + BOSS is 3.7577%**, half again as high. Both ship (`Web Conversion Rate %` and `Digital Conversion Rate %`) rather than picking one, since 2.54% is the published baseline and 3.76% is the honest funnel number.

3. **Returns are dated by the SALE date, not the refund date — a deliberate break from Sales Activity.** A ROAS denominator has to face the revenue that the spend actually bought. `digital_daily` groups on `Sale Date`, so a refund lands on the day of the order that produced it and each day is one cohort. All-time totals are unaffected and tie exactly to `sales_activity` ($26,766,803.85); only the day-by-day distribution differs, and the element description says so.

Also encoded: **4,933 of the 6,051 `F_MARKDOWN` rows carry `Discount Percent = 0`** — they are price *resets* back to full price, not markdowns. Counting the ledger raw overstates promotional pressure five-fold, so `Markdowns` and `Price Resets` ship as separate columns.

### First insight off the model — the promotion calendar does nothing

288 promotional days against 1,234 clean ones, and the promotions are invisible in the demand data:

| | Promo days | Non-promo days | Δ |
|---|---|---|---|
| Days | 288 | 1,234 | |
| Visits / day | 3,102 | 3,194 | **−2.9%** |
| Digital orders / day | 117.5 | 119.8 | **−1.9%** |
| Digital revenue / day | $192,434 | $195,779 | **−1.7%** |
| Conversion | 3.7868% | 3.7511% | +1.0% rel. |
| Revenue per visit | $62.03 | $61.29 | +1.2% |

Promotions run 10–34% off, yet promotional days draw *fewer* visits and book *less* revenue than ordinary days. The conversion and revenue-per-visit edges are under 1.2% relative — noise at this sample. Whatever the promotion calendar is doing, it is not moving digital demand, and any "Promo Lift" metric built on this data would report roughly zero.

The paid-media picture is the actionable one: **Paid Search costs $1.0041 per visit and Social $0.3976 — 2.5× cheaper — yet Paid Search absorbs $1,061,418 of the $1,564,044 total spend (67.9%) to deliver *fewer* visits than Social** (1,057,068 vs 1,105,799). Email is cheapest of all at $0.0301. Shifting budget from Paid Search toward Social and Email is the obvious first test, with the caveat below.

**Do not plan against ROAS from this model.** Blended ROAS reads 189.90× because total recorded spend ($1.56M) is 0.53% of digital revenue ($297M). That is a property of the synthetic dataset, not a business result. Cost per visit, spend mix and conversion are sound; ROAS is retained only for completeness.

### API gotchas worth remembering

- **`in (...)` is not a valid Sigma formula operator.** `[Col] in ("A", "B")` is rejected as a *schema* error, with no hint that a formula is at fault — the same trap as `And()` / `Or()`. Use an infix `or` chain: `[Col] = "A" or [Col] = "B"`. This alone produced all 33 errors on the first submission, cascading from 5 source columns into every element that referenced them, which badly overstates how localised the fault is. Bisect by page, then by element, then by formula.
- **`spec update` needs `schemaVersion: 1` in the body but NOT `folderId`** (the reverse of create, which needs both). Omitting `schemaVersion` returns `Syntax error in data model spec`; omitting `folderId` on create returns `Unknown error in data model spec`. The two messages are the fastest way to tell which one you dropped. The `dataModelId` goes in `--params`, the spec in `--body`.
- **`visibleAsSource` does not survive the `spec get` round-trip** — every element reads back with the flag absent, so a spec copied from `get` republishes with nothing exposed. Verify exposure with the MCP `describe` (type `datamodel`), which lists only the visible elements, not with the spec JSON.
- **Non-equi joins DO work** and are undocumented in the obvious places: `columns: [{left, right, op: ">="}]` accepts `<`, `<=`, `=`, `!=`, `>=`, `>`. That is what explodes the 52 promotions onto the calendar (`Date Key >= Start Date and Date Key <= End Date`) without a cross join, which the spec has no way to express. Verified in the generated SQL.

---

## Build log — Model 4 shipped

**Retail Customer 360** — `14327edf-2fe7-4263-9444-8330a0668117`
<https://app.sigmacomputing.com/playground-sean-miller/data-model/Retail-Customer-360-C6VemfRKjSrdXE0y9n4Ld>

27 elements across 4 pages. Visible: `Customer` (dim, extended with the birthday block), `Date`, `Product`, `Store`, `Salesperson`, plus `customer_profile` (71 columns, 27 metrics), `customer_reviews` (26 columns, 8 metrics) and `customer_category_mix` (9 columns, 8 metrics). 19 hidden source and build elements. Spec generator committed as `gen_customer_360.py`; regenerate and re-publish with `api data-models spec update`.

### Verified against every pre-build benchmark

| Check | Expected | Actual |
|---|---|---|
| `customer_profile` rows | 4,972 (one per customer, no fan-out) | **4,972** ✅ |
| Purchasing customers | 4,867 | **4,867** ✅ |
| Never-transacted customers retained | 105 | **105** ✅ |
| Orders | 717,747 | **717,747** ✅ |
| Gross Sales | $1,178,971,663.73 | **exact** ✅ |
| Returns / Return Rate % | $64,116,011.81 / 5.44% | **exact / 5.438%** ✅ |
| Net Sales | $1,114,855,651.92 | **exact** ✅ |
| `customer_reviews` rows / reviewers / avg rating | 137,944 / 4,442 / 4.014 | **exact** ✅ |
| `customer_category_mix` net sales | ties to company net sales | **ties exactly** ✅ |
| Digital order mix | 25.31% | **25.31%** ✅ |
| Null audit on every join key | 0 | **0** ✅ |

### Four decisions that departed from the plan

1. **The grain is the customer dimension, not the fact.** 4,972 customers exist; only 4,867 have ever transacted. Building off `sales_activity` would have silently dropped 105 people and understated the base. Everything LEFT JOINs onto the dimension, `Has Purchased` marks the difference, and the metric layer carries **both** `Customers` (4,972) and `Purchasing Customers` (4,867) so a rate can never quietly pick the wrong denominator.

2. **RFM ships as three continuous columns, not as 1–5 scores.** This base is extraordinarily dense — median **140 orders** per customer, and 80% of customers bought within **38 days** of the As Of Date. Quintile cut points computed on it (recency 2/4/7/38 days) are meaningless and would rot the moment the data moved. Recency Days, Orders and Lifetime Net Sales ship raw; workbooks cut their own quintiles.

3. **Churn is cadence-relative, not calendar-relative.** A fixed 90-day-inactive rule flags almost nobody here. `Cadence Ratio` divides each customer's recency by *their own* average gap between orders, and `Churn Risk` bands it: **Lapsed 657, Stretching 306, On Cadence 3,903, Unknown 106**. This is the design decision the model turns on — see the insight below for why absolute recency gets the answer backwards.

4. **No "favourite category" column.** A single winner hides the mix, so category affinity ships as its own `customer_category_mix` element at Customer × Type × Family; sorting it by Net Sales recovers the favourite when that is genuinely what is wanted.

### Two traps found and encoded in element descriptions

- **`customer_category_mix` adds up in dollars but not in orders.** Net Sales over the whole element reconciles exactly to company net sales, because every order line belongs to one family. Orders does not: a basket spanning three families is counted in each, so summing gives **3,270,599 against a true 717,747 — 4.6× high**. Use Orders only within a family.
- **Birthday is null for 2,559 of 4,972 customers (51%).** The clienteling plan is written against birthday campaigns; at best they reach half the base. `Has Birthday` ships as the denominator guard.

Also confirmed: `Verified Purchase` is not merely constant `'Y'` but *redundant* — all 137,944 reviews were independently matched to a real purchase of that product by that customer. It is dropped, and the description now records that a review here genuinely does imply a purchase.

### First insight off the model — losing the associate loses the customer

Customers whose primary salesperson has been **terminated lapse at 29.4%, against 12.5% for those whose associate is still active — 2.4× the rate**, with average recency of 131 days against 52.

| Primary associate | Customers | Lapsed | Lapsed % | Avg recency | Lifetime value |
|---|---|---|---|---|---|
| Active | 4,571 | 570 | 12.5% | 52 days | $1,054.3M |
| **Terminated** | **296** | **87** | **29.4%** | **131 days** | **$60.6M** |

That is a named, finite reassignment queue — 296 customers worth $60.6M, of whom 209 have not lapsed yet — and it is exactly what `clienteling-app-plan.md` needs. `Primary Salesperson Status` ships on the profile for this reason.

The loyalty data makes the case for cadence-relative churn better than any argument could. The vendor-supplied `at_risk` tier carries by far the **worst absolute recency (118–125 days versus 5–6 for platinum)** — yet those customers lapse *less* than untiered ones (12.0–13.6% vs 14.6–17.7%). They are not at risk; they are slow-and-steady buyers with long natural cadences, and a recency-threshold churn model would have chased all 750 of them while missing the untiered group that is actually leaving.

### API gotchas worth remembering

- **Sigma has no arg-max aggregate**, so "the store/associate this customer uses most" takes the explicit three-element shape: count per customer-per-key, take the per-customer max, rejoin and keep the key sitting at that max with `Min(If(count = max, key, Null))`. `Min` breaks ties deterministically on the lowest key. Resolved cleanly for all 4,867 purchasers, and never exceeded each customer's total orders.
- **Column formulas resolve against source elements, not sibling columns of the same element.** `Churn Risk` could not reference `[Cadence Ratio]` next to it; the cadence arithmetic has to be composed in the generator and inlined at every use. Build long formulas from shared Python fragments so the definition still lives in one place.
- **A model-wide scalar reaches every row via a constant join key.** The single-row `As Of` element (`Max(Sale Date)` grouped by a literal `1`) joins to a matching constant on the spine. That constant lives on a hidden `Customer Spine` element rather than on the conformed `Customer` dimension, so the dimension stays clean for downstream models.
- **The grouped-element `[Metrics/…]` trap bit here too, and only showed up on query.** `customer_category_mix` carries a `groupings` block, so its `Return Rate %` and `Spend per Customer` metrics — written as `[Metrics/Returns] / [Metrics/Gross Sales]` — bound to the like-named *columns* and failed with `Column "…--metric-["activity_type"]" does not exist`. The spec published clean and the sum metrics all worked; only the ratios broke. On grouped elements aggregate columns directly (`Sum([Returns]) / Sum([Gross Sales])`), and **query every ratio metric after publishing** — a successful write proves nothing about them.

---

## Build log — Model 2 shipped

**Retail Inventory & Replenishment** — `7a80315d-8faa-44cc-a5d0-18483bb3707e`
<https://app.sigmacomputing.com/playground-sean-miller/data-model/Retail-Inventory-and-Replenishment-3J9EbBJ9tkvi6KYgk3iHvM>

9 exposed elements across 5 pages: `Product`, `Store`, `Date`, `Vendor`, `Inventory Weekly` (21 metrics), `Inventory Current` (15 metrics), `Inventory Changes` (8 metrics), `Inventory Adjustments` (8 metrics), `Purchase Orders` (10 metrics), plus 6 hidden build elements. Spec generator committed as `gen_inventory.py`; regenerate and re-publish with `api data-models spec update`.

### The carry-forward problem, solved

The plan above left the central decision open — carry last value forward, or accept a point-in-time-only element. **We built the dense position**, and it cost less than expected: a full aggregate over all 48M rows returns in ~21 seconds.

The mechanism, in two hidden elements:

1. `inv_changes_base` sorts by Store Key, Product Key, Effective Start Date and calls `Lead()` to find each row's successor. **Sigma's `Lead()` takes no partition argument** — it orders by the element's `sort` and nothing else, and passing group-by arguments fails with `Argument 3 invalid for function 'Lead'`. The partition is therefore enforced in the formula, by guarding that the next row belongs to the same pair: `If(Lead([Store Key]) = [Store Key] and Lead([Product Key]) = [Product Key], Lead([Effective Start Date]), Null)`. That yields `Weeks In Force` per change.
2. `inv_weekly_base` cross-joins those changes to a 218-row week spine on a constant key, then an element-level `filters` entry keeps only the weeks each change was actually in force. That filter is not cosmetic — it is what compiles the cross join into a range join. Without it the element is 1.3 billion rows.

Two facts made this tractable, both verified before any spec was written: the week spine is perfectly regular (218 Sundays, every gap exactly 7 days), so `Week Index` is pure arithmetic rather than a `RowNumber()`; and **every one of the 220,296 pairs has a row on the first date**, so the carry-forward has no leading nulls to handle.

The windowed computation lands in an inner subquery, so downstream filters cannot silently recompute it over a filtered row set — which would have made any date-filtered query quietly wrong.

### The finding that changes the headline number

**Row-weighted stockout is 23.46%. Time-weighted stockout is 3.19%.** A factor of 7.4.

The change log over-represents stockouts massively, because a stockout is resolved quickly — average duration **1.10 weeks** — and therefore generates a change row almost immediately, while a healthy position can sit unchanged for months and generate none. Counting rows counts *events*; counting weeks counts *time*. Only the second is a stockout rate.

The plan's pre-build figure of "23.5% of rows at zero on hand" was this artefact. Both weightings are now published side by side as metrics on `Inventory Changes`, the misleading one named `Stockout % (Row-Weighted - MISLEADING)`, so the trap is visible rather than merely avoided.

### Verified against every benchmark

| Check | Expected | Actual |
|---|---|---|
| `Inventory Weekly` rows | 220,296 × 218 = 48,024,528 | **48,024,528** ✅ |
| Stores / products / weeks | 201 / 1,096 / 218 | **201 / 1,096 / 218** ✅ |
| On-hand unit-weeks | 262,103,096 | **262,103,096** ✅ |
| Time-weighted stockout | 3.19% | **3.1861%** ✅ |
| Time-weighted below reorder point | 6.57% | **6.5709%** ✅ |
| Avg on hand per store-SKU | 5.458 | **5.4577** ✅ |
| Net units vs Sales Activity | 8,584,150 | **8,584,150** ✅ |
| Net sales vs Sales Activity | $1,114,855,651.92 | **$1,114,855,651.92** ✅ |
| Net COGS vs Sales Activity | $895,884,767.32 | **$895,884,767.32** ✅ |
| `Inventory Current` rows | 220,296 (one per pair) | **220,296** ✅ |
| Current on hand / at cost | 1,194,313 u / $260,485,156.88 | **exact** ✅ |
| Current stocked out / below ROP | 7,239 / 14,178 | **7,239 / 14,178** ✅ |
| `Inventory Changes` weeks covered | 48,024,528 | **48,024,528** ✅ |
| Stockout events / weeks | 1,396,947 / 1,530,108 | **exact** ✅ |
| PO lines / value / on-time | 53,589 / $987,898,638.38 / 65.84% | **exact** ✅ |
| PO avg days vs expected | −0.018 | **−0.01754** ✅ |
| Adjustments / net units | 66,088 / −416,623 | **exact** ✅ |
| Null audit on join keys | 0 | **0 on product, store, date, cost, vendor** ✅ |

`Weeks Covered` on the change log equalling the dense row count exactly is the strongest single check: it proves the carry-forward accounts for every store-product-week once and only once, with no gap and no double count.

### A bug caught in verification, worth generalising

The first publish had `Inventory Turns`, `GMROI` and `Sell-Through %` dividing a **total** (Net COGS, Net Units Sold) by a **per-pair average** (Avg Inventory at Cost per store-SKU). The metrics resolved, returned numbers, and were nonsense — turns of 179,807 and sell-through of 99.99993%.

Nothing about that fails validation. It only surfaced because the values were checked against what they ought to mean. **Ratio metrics must have numerator and denominator at the same aggregation level**, and on a fact whose grain is finer than the business entity, "average" is ambiguous until you say average *over what*. The model now publishes both explicitly: `Avg Inventory at Cost` (total position, the denominator for turns and GMROI) and `Avg Inventory at Cost per Store-SKU` (unit economics), each with a description saying which is which. Corrected: **0.82 turns a year, GMROI 0.84**.

### First insight off the model

Inventory capital and replenishment attention are pointed in opposite directions. Across the 200 selling stores:

| Segment | Pairs | Units | At cost | Below reorder point |
|---|---|---|---|---|
| Never sold a unit on net, 4 years | 77,103 | 769,381 | **$184.8M** | **1** |
| Sold historically, nothing in 13 weeks | 49,303 | 103,002 | $34.8M | 66 |
| Currently selling | 92,794 | 203,017 | **$28.8M** | **13,546** |

**71% of store inventory value sits in store-SKU combinations that have never sold a single unit**, and the reorder-point logic has essentially nothing to say about it — one flagged pair out of 77,103. Meanwhile all the replenishment pressure, 13,546 of 13,613 flagged pairs, lands on the 11% of capital that is actually moving.

Reorder points are calibrated to velocity, so dead stock never trips them; it simply sits. The obvious first test is a carrying-cost review of the never-sold tail, which is a far larger sum than anything the replenishment queue is currently arguing about.

### Metric documentation

All 64 published metrics carry descriptions, verified by reading the spec back from the server rather than trusting the write. Each one states what it measures, its unfiltered value as a benchmark, and its most likely misreading — which aggregation level it is valid at (`Avg Inventory at Cost` vs `Avg Inventory at Cost per Store-SKU`), what it silently excludes (in-transit lines from on-time %), what a null means (`Weeks of Supply` is undefined for no velocity, not for no stock), and where an average hides its distribution (`Avg Lead Time Variance Days` is −0.018 over an 18,536/16,450/18,151 early-exact-late split). The generator's `met()` helper takes `desc` as a required positional argument, so an undocumented metric cannot be added without the build failing.

### API notes to carry forward

- `schemaVersion: 1` is required on **update** as well as create. Omitting it returns `"Syntax error in data model spec"` — the same message as a malformed body, which sends you looking in the wrong place.
- Element-level `filters` use `{kind, mode: "include"|"exclude", values: [...]}`. An `include:` key is silently accepted and **does nothing** — the predicate renders as a projected column instead of a `WHERE`, and the element quietly returns every row. Always confirm the filter compiled by grepping the generated SQL for `where`.
- `RunningSum` is not a Sigma function (`Unknown function RunningSum`), and there is no cumulative max. `Lead`, `Lag`, `RowNumber` and `Rank` all work but order by the element's `sort` only.
- `api data-models elements query get` returning the generated SQL remains the fastest correctness check — unresolved references appear as string literals in the SELECT rather than as errors.

### Metric descriptions added (2026-09-13)

All **43** metrics the model defines now carry descriptions — 27 on `customer_profile`, 8 on `customer_reviews`, 8 on `customer_category_mix`. Each says what the metric means and where it misleads, not what the formula already shows: which denominator it uses, whether it survives a rollup, and the verified all-time value to check against. They round-trip through `spec get` and surface in the `AVAILABLE METRICS` catalog that `describe` returns, so they reach MCP and agent consumers, not just the Sigma UI.

Two things surfaced while doing it:

- **`description` is not in the cached OpenAPI's metric schema** (which declares only `formula` and `id`) yet is accepted, persisted and returned. The schema's metric property list is incomplete — it omits `name` and `format` too, both of which every real spec uses. Probe the server rather than trusting it.
- **Elements inherit their primary source's metrics, and colliding names get silently suffixed.** `customer_category_mix` sources `SRC Sales Activity` directly, so it publishes **18 inherited metrics from Retail Sales Activity on top of its own 8** — and because six of my names collided, Sigma renamed mine to `Net Sales (1)`, `Returns (1)`, `Spend per Customer (1)` and so on. All eight are now prefixed `Category …`, which ends the collision. Inheritance flows from the **primary source only**, not from joined elements — which is why `customer_profile` (anchored on the metric-free `Customer Spine`) and `customer_reviews` (anchored on the raw review upload) are clean.

**Fixed: the 18 inherited metrics are gone.** They referenced columns the grouping collapsed away — `metric('m_net_sales')` on `customer_category_mix` failed with `Could not resolve metric column t.amount` — so the element has been re-anchored. The aggregation moved to a hidden `cat_mix_agg`, and the visible element is now `Customer` **INNER JOIN** that aggregate. Because inheritance follows the primary source only, anchoring on the metric-free `Customer` dimension sheds all 18; `metric('m_net_sales')` there now returns `not found in catalog`, and the element publishes exactly its own 8.

Re-verified after the restructure — every figure identical to before:

| Check | Before | After |
|---|---|---|
| Rows / customers / families / types | 55,588 / 4,867 / 13 / 6 | **identical** ✅ |
| Category Net Sales | $1,114,855,651.92 | **identical** ✅ |
| Category Gross Sales / Returns | $1,178,971,663.73 / $64,116,011.81 | **identical** ✅ |
| Category Net Units / Orders | 8,584,150 / 3,270,599 | **identical** ✅ |
| Inherited `m_net_sales` | broken, published | **not in catalog** ✅ |
| `customer_profile` rows / orders / lapsed | 4,972 / 717,747 / 657 | **identical** ✅ |

The INNER join also drops the 105 never-transacted customers from this element, which is correct — they have no category rows to carry — and the element description now says so.

**Deliberately not done:** the other five models still have no metric descriptions, Retail Sales Activity's 22 included. Scoped out on 2026-09-13; the pattern to copy is in `gen_customer_360.py`'s `met()` helper, which makes a description mandatory rather than optional.
