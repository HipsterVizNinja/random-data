# Store Performance Command Center — Build Record

What was actually built in Sigma from `STORE_PERFORMANCE_COMMAND_CENTER_PLAN.md` and
`store_performance_command_center_wireframe.html`, where the build departs from the plan, and why.

Built 2026-09-14 in the **playground** org (`playground-sean-miller`).

| Artifact | Link / ID |
|---|---|
| Workbook | [Store Performance Command Center](https://app.sigmacomputing.com/playground-sean-miller/workbook/Store-Performance-Command-Center-3cEhnjB7odldbfo8jyT1qm) · `694635af-52a9-4d08-a9f2-b3325c9acf6e` |
| Data model extended | [Retail Store Operations](https://app.sigmacomputing.com/playground-sean-miller/data-model/Retail-Store-Operations-eHbRNEwqLeuogeqrbhzwD) · `07c9d946-3ccc-477d-8dd6-0ce4ebdf00bb` |

---

## The one decision that reshaped the plan

The plan was written on 2026-09-01, before the seven Retail data models existed. It specified the
workbook joining raw CSVs directly (`F_SALES` → `F_POINT_OF_SALE_master` → `D_STORE` → …) and
carrying ~24 calculated fields in the workbook itself.

**By the time of the build, the Retail Store Operations model already did most of that** — hourly
traffic and labour conformed and rolled up, orders and dollars pre-aggregated to avoid line-item
fan-out, and ratios published as metrics so they recompute at every rollup. Rebuilding that in the
workbook would have duplicated it and put the grain warnings the wireframe cares about in the wrong
layer.

So the joins and calculations went **into the data model**, and the workbook is presentation only.
The workbook holds no business logic beyond chart-level aggregation. That also makes every figure
reachable by Ask a Question and by any future workbook, not just this one.

---

## Data model additions (Retail Store Operations)

Nine new elements — seven hidden build steps and two published — plus two existing elements widened.

### Published

**`Manager Chain`** (`mgr_chain`) — the flattened helper the plan asked for, rather than a live
recursive walk. `D_STORE_LEADERSHIP` self-joined twice on `Reports To Key`: Store Manager → AVP →
RVP. The hierarchy is a fixed three levels (200 / 18 / 5), so two joins resolve it exactly.

Verified: 200 Store Manager rows, every one with a Store Key, an AVP and an RVP resolved; 18 AVP and
5 RVP rows with no Store Key. Because only Store Managers carry a Store Key, joining this on Store
Key yields exactly one row per store and the AVP/RVP rows drop out on their own — no filter needed.

**`Store Performance Daily`** (`store_day_perf`) — the command centre spine. One row per Store × Date
carrying actuals, the sales plan, the fiscally-aligned prior year, and the leadership chain. 22
metrics, each with a description naming its denominator.

### Hidden build steps

| Element | What it does |
|---|---|
| `src_leader_avp`, `src_leader_rvp` | Two aliases of `D_STORE_LEADERSHIP` for the chain walk |
| `daily_sales_all` | Complete all-channel net sales per Store × Date, **across all hours**. Materialized. |
| `period_days` | Date count per fiscal year + period — the budget-allocation denominator |
| `budget_day` | `F_BUDGET` exploded from Store × Fiscal Period onto each date in the period |
| `src_py_store_day` | Alias of the materialized `Store Day`, joined on `Prior Year Date` |
| `src_py_daily` | Alias of the materialized `daily_sales_all`, joined on `Prior Year Date` |

Two existing elements were also widened: `Store Hour` and `Store Day` now carry `Prior Year Date`
and `Fiscal Period Name`, which is what lets the spine be a flat join (see **Performance** below).

Every join is 1:1 on Store × Date, so nothing fans out.

---

## Four things the plan got materially wrong, corrected here

### 1. `F_BUDGET` is an all-channel plan, not an in-store one

The plan's `Sales vs Budget %` compares budget against `Total Sales`, and separately scopes
conversion to the Retail channel. But it never says which sales figure the budget is measured
against — and the answer moves the headline by 35 points.

| FY2025 P08 | Figure | vs plan $30.3M |
|---|---|---|
| All-channel net sales | $34.7M | **+14.5%** |
| Retail-channel only | $24.0M | −20.9% |

Retail-only would put the company at 79% of plan in P08 and 68% in P09, and read as a crisis that is
not in the data. So the spine carries **two sales bases** and the model description spells out which
is which:

- **Net Sales (all channels)** — the only figure comparable to Budget Sales.
- **Retail Net Sales** — the correct numerator for anything measured against door traffic
  (Conversion Rate, Sales per Visit, ATV). A web order never walked through the door.

**Labor Cost % uses the all-channel denominator**, which is what the plan specified and is the
defensible reading: store labour also picks BOPIS orders and ships store-fulfilled web orders (the
Omnichannel model puts 30.1% of web orders shipping from a store). An earlier pass had it on
retail-only sales, which read **24.4%** for FY2025 P09 against **16.8%** all-channel — high enough to
look like a crisis that is not there.

### 2. `Store Day` cannot see out-of-hours sales

The existing `Store Hour` element joins outward from `F_STORE_TRAFFIC`, which only has hours 9–20.
Any sale landing outside that window is invisible to it — which is why its all-channel column is
named "In-Hours" and is partial by design (P08: $30.6M in-hours vs $34.7M complete).

That partial figure is unusable against budget, so `daily_sales_all` aggregates the activity base at
day grain across all hours. It is derived from the existing `Hourly Sales` element rather than
re-scanning the 16.9M-row activity fact.

### 3. Conversion Rate has BOPIS pickups in its denominator but not its numerator

The plan's open item asked to confirm the `Channel Type` values. Confirmed exactly as hypothesised —
**Retail, Web, BOPIS, BOSS** — and the plan's instinct to scope conversion to Retail only is right.
But the four channels are not cleanly "in store" vs "not":

| Channel | Orders | Walks through the door? |
|---|---|---|
| Retail | 536,065 | Yes — counted in numerator and denominator |
| Web | 122,713 | No |
| BOPIS (buy online, pick up in store) | 38,148 | **Yes — counted in the denominator only** |
| BOSS | 20,821 | Depends on whether this is ship-*to*-store or ship-*from*-store |

A BOPIS customer is in `F_STORE_TRAFFIC` visits but their order is not a Retail-channel order, so
Conversion Rate understates by roughly **7% relative** (38,148 / 536,065). Left as the plan specified,
because the alternative — counting BOPIS in the numerator — mixes an order placed online into a
measure of in-store selling. It is flagged on the workbook's notes page so nobody reads conversion as
exact. Resolving `BOSS` against the Retail Omnichannel Fulfillment model would let this be made
precise.

### 4. `Sales per Labor Hour` is not per hour

`F_LABOR` records **staff counts** per store-hour, not hours worked. The plan's
`Total Sales / Sum(Actual Staff Count)` is therefore sales per *staffed store-hour*. Kept, with the
denominator named honestly in the metric description. Its numerator stays Retail Net Sales, because
unlike Labor Cost % this metric is about selling-floor productivity rather than cost efficiency.

---

## Workbook structure

Six pages. Four from the wireframe, plus a hidden data page and a closing notes page.

| Page | Contents |
|---|---|
| *Data* (hidden) | `Perf Base` (spine, filtered by fiscal year + period), `Perf Scoped` (also by region/area/store), `Hour Base` (native hourly grain) |
| **Executive Overview** | 6 KPI tiles; sales vs plan by fiscal week (combo, one dollar scale); region table with drill |
| **Region / AVP** | 6 KPI tiles; sales vs plan by store (diverging bars); labour efficiency; traffic-to-conversion with drill; escalated open items |
| **Store Detail** | 6 KPI tiles; store profile strip (state, type, manager, tier, AVP, RVP); traffic by hour and staffing by hour as two panels on one hour axis; daily sales vs prior year; this store's action log; Log action item button |
| **Action Log** | Open / In Progress / Escalated / Total counts, then the `INPUT_STORE_ACTION_LOG` input table with row actions |
| **Assistant & Notes** | AI readiness, the two sales bases, and the known simplifications |

A **sticky header panel** carries the control strip — Fiscal Year, Fiscal Period, Region, Area,
Store, Reset — across pages 1–3, so filters are one shared set rather than duplicated per page.
Pages are assigned to the panel in `document.panels`; the panel's elements are positioned with a
`<Panel id="…">` block in the layout XML.

**Two-tier filtering.** Fiscal Year and Period filter `Perf Base`, so they reach everything.
Region / Area / Store filter `Perf Scoped`, which reads `Perf Base`. The Executive Overview reads
`Perf Base` and so always shows the whole company for the chosen period; pages 2 and 3 read
`Perf Scoped` and follow the hierarchy selection. That is what the wireframe implies when page 1 is
labelled "all regions" while the strip has a region selected.

### KPI tiles

Sigma's `kpi-chart` does the wireframe's tile natively: `value` for the number, `comparisonColumn`
for the delta, and `timeline` + `trend` for the sparkline. Prior-year comparisons point at the
spine's own PY columns rather than `periodComparison`, which is calendar-based and would not line up
with a 4-5-4 fiscal calendar.

### Actions — all five from the plan

| Plan action | How it is built |
|---|---|
| 1. Drill to Store Detail | `on-select` on the region table sets the Region control and navigates; on the traffic-to-conversion table it sets Store and navigates to Store Detail |
| 2. Log Action Item | Button on Store Detail → `insert-rows` into the input table, pre-filling Store, Fiscal Year and Fiscal Period from the live controls, Status `Open`, Date Logged `Today()` |
| 3. Mark Resolved | Row action (right-click) → `update-rows` on the current row, sets Status `Resolved` and stamps the target date |
| 4. Escalate to AVP/RVP | Row action → sets the Escalated flag, which is what surfaces the row on page 2 |
| 5. Reset Filters | Button → `clear-control` on Region, Area and Store |

A **Reopen** row action was added beyond the plan, because Mark Resolved was otherwise one-way.

---

## Performance: the spine is a flat join over materialized leaves

This was the hardest part of the build and it reshaped the model, so it is worth explaining rather
than just recording.

The chain is deep: 16.9M POS lines → order/product aggregation → activity base with a sales/returns
union and six dimension joins → hourly regroup → 3.3M store-hours → store-days → the all-channel
daily regroup → the prior-year self-join. On the shared sample Snowflake warehouse, a single-period
query against the first version of the spine **timed out**, and so did the attempt to materialize it.

**The governing fact, learned the hard way:** a materialization *job* rebuilds its element from raw
source and ignores upstream materializations, while an interactive *query* does substitute them. So
an element can only be materialized if its own definition is affordable from source — you cannot
build a tall stack and materialize the top of it.

So the spine was flattened. The first version had `Store Day` → `store_day_ext` (which added
all-channel sales, budget and `Prior Year Date`) → the spine joining an *alias of ext*, which meant
ext was computed twice per query and could not be materialized at all. The rebuilt version:

- `Prior Year Date` and `Fiscal Period Name` are carried down through `Store Hour` into `Store Day`,
  so **Store Day alone holds both the store key and the prior-year date**.
- `store_day_ext` and its alias are gone. The spine is a **single flat join** whose every expensive
  leg is a materialized leaf, prior-year legs included — they alias `Store Day` and
  `Daily Sales All Channels` rather than the wide element.

| Element | Materialized | Why it works |
|---|---|---|
| `daily_sales_all` | 04:00 America/Chicago | One aggregation, affordable from source |
| `store_day` | 04:00 America/Chicago | Deep but proven — completes in 30–50s |
| `store_day_perf` | no | A flat join over the two above plus small tables; substitutes their materialized tables at query time |

**Two hard operational dependencies:**

1. **The workbook is only usable against the materialized leaves.** If the upstream CSVs are
   replaced, re-run both materializations before demoing.
2. **Model edits can silently un-materialize things, and `spec update` always returns
   `success: true`.** Two ways this bit during the build: one edit that *deleted* scheduled elements
   wiped **all four** schedules on the model, including ones on elements it did not touch; and
   changing `dim_store`'s visibility invalidated `store_day`'s built table (because `Store Hour`
   joins `dim_store`) while leaving the schedule in place. So after any model change, check both:
   `materialization-schedules list` for the schedules, and `elements query get` on the published
   element grepped for `t_mat_` for the built tables. Finish model edits before setting up
   materialization where you can.

---

## What was left out, and why

**The custom AI chat element.** The workbook spec supports a `chat` element, but it requires a
workbook *agent* to attach to, and the agent API (`/v2/workbookAgents`) returns **404 on this
org** — a private beta that is not enabled. Rather than ship a broken element, the build takes the
plan's own stated contingency: Ask a Question only, with the agent system prompt held in the plan
ready to paste in once agents are enabled.

Ask a Question is genuinely ready, which was the other half of the plan's AI section: every
published element and metric carries a description, ratios name their denominator, and the duplicate
UPPER_SNAKE_CASE `D_STORE` columns are excluded, so no NL query can bind to an ambiguous field.

**The channel filter** (plan, Controls page). The spine carries retail and all-channel measures as
separate *columns*, not as a channel dimension, so a channel filter would have nothing to act on.
Pick the measure instead. This is the right shape given decision #1 above — the two bases answer
different questions and are not two slices of one.

**`INPUT_STRETCH_GOAL`** — the plan marked it a stretch, skippable for v1. Skipped.

**Row-level security.** Still not designed, as the plan noted. `Manager Chain` is the hook: a
policy on Store Key / AVP Key / RVP Key against a user attribute is all that is missing.

---

## Known simplifications

- **Budget is allocated evenly across the days of its fiscal period.** That is what lets a period
  plan roll up to a fiscal *week*, which the wireframe's headline chart needs. It ignores
  day-of-week seasonality within the period, so one week's variance is noisier than a full period's.
  It does buy one genuinely useful property: because the allocated plan is joined per store-day, a
  **partial period compares like with like** — 14 days of P10 actuals land against 14 days of P10
  plan, not against the whole period's number.
- **Three stores have actuals but no plan** (FY2025 P09: 200 stores with traffic, 197 with a
  `F_BUDGET` row; 3 with actuals and no plan, 1 with a plan and no traffic). Their sales land in the
  vs-budget numerator but not the denominator, inflating a region's variance by up to ~1.5%. Left as
  a data-coverage fact rather than papered over — a store with no plan should be visible as such.
- **Hourly charts show averages per trading day**, not a single named day as the wireframe mocked.
  Averaging over the selected period keeps the shape stable and avoids hard-coding a date that goes
  stale.
- **Grouped tables are not pre-sorted by an aggregate.** Sigma's element `sort` only reaches the
  ungrouped base level. The diverging bar chart above them already ranks stores by variance, and
  column headers re-sort interactively.
- **The action log keys on Store Name, not Store Key.** All 201 store names are distinct, and no
  control carries the key, so a Store Key column would have sat empty on every inserted row.

---

## Verification

Validated end to end, workbook → spine → source facts.

**Grain.** `store_day_perf` returns exactly **28 rows for one store × one 28-day fiscal period**, and
**304,400 rows = 200 stores × 1,522 days** overall.

**Reconciliation.** The spine's all-time all-channel net sales is **$1,114,855,652** — equal to the
dollar to `sales_activity`'s own total in the Retail Sales Activity model. No leakage, no
duplication. At FY2025 P09 the spine matches `Store Day` exactly on every measure it inherits
(5,600 store-days, 123,413 visits, 10,625 retail orders, $16,430,429 retail net sales,
$4,005,497 labour) and matches `F_BUDGET`'s period total exactly ($24,148,345) — so the day-level
budget allocation sums back to the plan it came from.

**Through the workbook.** The Executive Overview region table returns 200 stores, $23,782,585 net
sales, $24,148,345 budget, 123,413 visits — identical to the spine at the workbook's default scope.

**Manager Chain.** 200 Store Managers each with a Store Key, AVP and RVP resolved; 18 AVP and 5 RVP
rows with no Store Key. Spot-checked against an independent self-join of `D_STORE_LEADERSHIP`:
store 84 → Stephanie Campbell → Timothy Cook (AVP) → Angela Turner (RVP), which also matches the
wireframe's own fixture data.

**Headline figures at the default scope (FY2025 P09):**

| Metric | Value |
|---|---|
| Net Sales | $23,782,585 |
| vs Budget | −1.5% |
| Store Visits | 123,413 |
| Conversion Rate | 8.6% |
| Labor Cost % | 16.8% |
| YoY Sales | +10.5% |
| Avg Transaction Value | $1,546 |

### The bug this caught

The first build of the spine was silently wrong, and only the grain check found it. Sigma requires a
**`groupingId`** when referencing a grouped element — `{kind: "table", elementId: "daily_sales_all"}`
resolves to that element's *ungrouped base rows*, not its aggregate. Eleven references across the
model were missing it and the fan-outs multiplied: one store-day returned **428,400 rows instead of
1**, and company net sales read **$1.7 × 10¹⁶**.

It validates, it compiles, the generated SQL looks clean, and `spec update` returns `success: true`.
The tell is that row counts explode while every joined column shows exactly **one distinct value per
key** — each duplicate row carries the same grouped aggregate. The existing `Store Hour` element had
been doing it correctly all along, which is where the fix came from.

**Lesson worth keeping: after building any join, assert the grain** —
`SELECT COUNT(*) ... WHERE <one store> AND <one date>` must return 1.

---

## Two levels to read with care

Both are properties of the synthetic mart, not of the calculations, and both are flagged on the
workbook's notes page:

- **Conversion Rate ~8.6%** against a retail-typical 20–30%. Door traffic in `F_STORE_TRAFFIC` was
  generated independently of orders in `F_SALES`, so the two series are not calibrated to each other.
  Compare conversion store-to-store and period-to-period; do not read the level as a benchmark.
- **Average Transaction Value ~$1,546**, which is why a store turns over ~$120K on ~90 orders in a
  period. Internally consistent, just not a mass-retail basket.

---

## Defaults

Opens on **FY2025 Period 09** — the last complete fiscal period in the data (5,600 store-days =
200 stores × 28 days). P10 exists but holds only 14 of its days: the mart ends at `2025-10-18`.

---

## Spec-API notes worth keeping

Learned the hard way; the bundled `sigma-workbooks` skill is stale on several of these.

- **The workbook POST body is `{name, folderId, description, document: {…}}`** — pages, elements,
  panels, layout and settings all live under `document`. `PUT` takes `{document: {…}}`; sending a
  bare document is rejected.
- **`document.elements` is a flat array.** Page assignment comes entirely from the layout XML.
- **Layout uses `<Element>`, not `<LayoutElement>`.** A panel is addressed as `<Panel id="…">`;
  `<Page id="…">` with a panel id fails as "unknown page".
- **`description` is valid on `table` and `input-table` only.** On any chart or `kpi-chart` it makes
  the whole element fail to match its schema, and the error is the unhelpful
  `Invalid kind: "kpi-chart"` rather than anything about the field.
- **`POST /v2/workbooks/spec/verify` is the cheap iteration loop** and reports precise, indexed
  errors (`elements[28].color: Column 'rv-vsb' is referenced from both 'yAxis' and 'color'`). Use it
  before every create or update.
- **Every data-model element needs `kind: "table"`.** Omitting it returns
  `Syntax error in data model spec` with no hint, which reads like a `schemaVersion` problem.
- **A grouped element must be referenced with `groupingId`.** Omitting it silently resolves to the
  element's ungrouped base rows and fans the join out. It validates, compiles, and returns wrong
  numbers — see **The bug this caught** above.
- **A single-select list control's default goes in `value` (scalar), not `values` (array).** Sending
  `values: [2025]` on `selectionMode: "single"` is silently dropped and the workbook opens unfiltered.
- **A `spec update` on a data model can delete its materialization schedules** — it did so on the
  edit that removed two scheduled elements, including schedules on elements that edit did not touch.
  `success: true` either way. Re-check `materialization-schedules list` after every model edit.
- **A round-trip `spec get` → `spec update` silently flipped `dim_store` to hidden.** Nothing in the
  payload touched it; it was published before and hidden after, dropping `Store` from the model's
  published surface. Restored. **Diff the published-element set after any model edit** — MCP
  `describe` (type `datamodel`) lists only visible elements, which makes this a one-call check.
- **Changing an element's `visibleAsSource` invalidates downstream materializations.** Restoring
  `dim_store` dropped `store_day`'s materialized table, because `store_hour` joins `dim_store`. The
  schedule survived; only the built table went. Cheap check: `elements query get` on the published
  element and grep the SQL for `t_mat_` — if it reads `sigma_df_csv_*`, the materialization is gone.
- Button `appearance` is `outline`, not `outlined`. Chart `legend` takes either `{visibility:
  "hidden"}` or `{position: …}`, never both. A column cannot sit on both `yAxis` and the `color`
  channel.
