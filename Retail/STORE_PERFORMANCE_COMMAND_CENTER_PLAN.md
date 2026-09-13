# Store Performance Command Center — Sigma Build Plan

## Context
Sean is building a synthetic retail data mart (flat CSVs, no DB/git, uploaded to Sigma Public, 200MB/file cap) for use in client POCs. This is the build plan for the first POC idea: a **Store Performance Command Center** — a Sigma workbook blending sales, traffic, labor, and budget data with an AI layer, so store/AVP/RVP users can ask natural-language questions and get grounded answers. This plan is documentation only — **nothing gets built in Sigma from this pass.**

Confirmed scope decisions:
- Aggregate hourly data (`F_LABOR`, `F_STORE_TRAFFIC`) inside the Sigma workbook itself, not via new pre-aggregated CSVs.
- Tables: `F_SALES`, `F_POINT_OF_SALE_master`, `D_STORE`, `D_STORE_LEADERSHIP`, `D_DATE`, `F_LABOR`, `F_STORE_TRAFFIC`, `F_BUDGET`.
- AI layer: design for Sigma's native "Ask a Question" **and** a custom AI chat element/agent for guided variance coaching.

## Data model / joins (verified schemas)
- `F_SALES` — Order Number, Cust Key, Store Key, Transaction Type, Date, Purchase Method, Date Key, Salesperson Key, Channel Type, Transaction Location Key, Fulfillment Location Key — **header-only, no dollar amount**
- `F_POINT_OF_SALE_master` — Order Number, Product Key, Sales Quantity, Sales Amount, Cost Amount — **line-item grain; this is where $ actually lives.** Join `F_SALES.Order Number` → `F_POINT_OF_SALE_master.Order Number`, aggregate (sum) to order grain before joining onward to avoid fan-out double-counting.
- `F_STORE_TRAFFIC` — Store Key, Date Key, Hour, Store Visits (hourly grain, 66MB)
- `F_LABOR` — Store Key, Date Key, Hour, Scheduled Staff Count, Actual Staff Count, Labor Cost (hourly grain, 92MB)
- `F_BUDGET` — Store Key, Fiscal Year, Fiscal Period, Budget Sales Amount, Budget Units
- `D_STORE` — Store Key, Store Name, City/State/Region/Area, Store Type, Store Size, Selling/Total Sq Ft, Online Ordering, hours. **Data quality issue:** file also contains duplicate UPPER_SNAKE_CASE versions of most columns from a past merge — hide/rename these in the workbook (don't fix the source CSV in this pass) so Ask-a-Question doesn't get confused by duplicate fields.
- `D_STORE_LEADERSHIP` — Leadership Key, Employee Name, Role, Store Key, Store Area, Store Region, Reports To Key, Hire Date, Tenure Years, Annual Salary, Performance Tier, Bonus Rate. `Reports To Key` chains Store Manager → AVP → RVP.
- `D_DATE` — full 4-5-4 fiscal calendar incl. `Prior Year Date`, `Fiscal Year`/`Fiscal Period`/`Fiscal Week` — use for all fiscal-aligned trending and to join `F_BUDGET` (Fiscal Year + Fiscal Period grain).

Join keys throughout: `Store Key` + `Date Key` conform `F_STORE_TRAFFIC`, `F_LABOR`, `F_SALES`, `D_STORE`, `D_DATE`. `F_BUDGET` joins on `Store Key` + `Fiscal Year` + `Fiscal Period` (coarser grain — join at the period level, not daily).

## Calculated fields (Sigma-syntax, build-ready)

Base table: `F_SALES` → `F_POINT_OF_SALE_master` (on `Order Number`, pre-aggregated to order grain) → `D_STORE` (on `Store Key`) → `D_STORE_LEADERSHIP` (on `Store Key`, `Role = 'Store Manager'`) → `D_DATE` (on `Date Key`). `F_STORE_TRAFFIC`/`F_LABOR` join separately on `Store Key` + `Date Key`; `F_BUDGET` joins on `Store Key` + `Fiscal Year` + `Fiscal Period`.

| Field name | Formula (Sigma syntax) | Notes |
|---|---|---|
| `Order Sales Amount` | `Sum(Sales Amount)` grouped by `Order Number` | Pre-aggregate before joining to store/date to avoid line-item fan-out |
| `Order Cost Amount` | `Sum(Cost Amount)` grouped by `Order Number` | Same pre-agg pattern |
| `Total Sales` | `Sum([Order Sales Amount])` | Rolls up at whatever grain the element uses (store/day/region/fiscal period) |
| `Total Cost` | `Sum([Order Cost Amount])` | |
| `Gross Margin $` | `[Total Sales] - [Total Cost]` | |
| `Gross Margin %` | `[Gross Margin $] / NullIf([Total Sales], 0)` | |
| `In-Store Order Count` | `CountDistinct(If([Channel Type] = "Retail", [Order Number]))` | Restrict to in-store channel so it's comparable to physical traffic |
| `Total Store Visits` | `Sum([Store Visits])` | From `F_STORE_TRAFFIC` |
| `Conversion Rate` | `[In-Store Order Count] / NullIf([Total Store Visits], 0)` | |
| `Avg Transaction Value` | `[Total Sales] / NullIf(CountDistinct([Order Number]), 0)` | All channels |
| `Sales per Visit` | `[Total Sales] / NullIf([Total Store Visits], 0)` | |
| `Total Labor Cost` | `Sum([Labor Cost])` | From `F_LABOR` |
| `Labor Cost %` | `[Total Labor Cost] / NullIf([Total Sales], 0)` | |
| `Staffing Variance` | `Sum([Actual Staff Count]) - Sum([Scheduled Staff Count])` | Negative = understaffed |
| `Sales per Labor Hour` | `[Total Sales] / NullIf(Sum([Actual Staff Count]), 0)` | Proxy metric — one row per staffed hour |
| `Budget Sales` | `Sum([Budget Sales Amount])` | From `F_BUDGET`, joined at Store + Fiscal Year + Fiscal Period |
| `Sales vs Budget $` | `[Total Sales] - [Budget Sales]` | |
| `Sales vs Budget %` | `[Sales vs Budget $] / NullIf([Budget Sales], 0)` | |
| `Budget Units` | `Sum([Budget Units])` | From `F_BUDGET` |
| `Units vs Budget %` | `(Sum([Sales Quantity]) - [Budget Units]) / NullIf([Budget Units], 0)` | |
| `Prior Year Sales` | `Total Sales` re-evaluated with `[Date Key]` mapped through `D_DATE.Prior Year Date` | Sigma period-over-period pattern — join a second `D_DATE` alias on `Prior Year Date` |
| `YoY Sales %` | `([Total Sales] - [Prior Year Sales]) / NullIf([Prior Year Sales], 0)` | |
| `Manager Name` | Lookup `D_STORE_LEADERSHIP.Employee Name` where `Role = "Store Manager"` and `Store Key` matches | |
| `AVP Name` / `RVP Name` | Walk `Reports To Key` one/two levels up from the Store Manager row | See "Manager Chain" helper below if this can't chain-walk live |
| `Manager Chain` | Flattened helper reference table (`Store Key → Store Manager Key → AVP Key → RVP Key`), built once rather than resolved as a recursive live join | Powers both the Region/AVP page filters and any future RLS |

## Workbook pages
1. **Executive Overview** — KPI row (`Total Sales`, `Sales vs Budget %`, `Total Store Visits`, `Conversion Rate`, `Labor Cost %`, `YoY Sales %`); fiscal-week trend chart; region-level table with drill into Area → Store.
2. **Region / AVP View** — filtered by `Manager Chain`; sales vs. budget variance by store; traffic-to-conversion by store; labor efficiency (`Staffing Variance`, `Labor Cost %`).
3. **Store Detail** — single-store deep dive: hourly traffic/labor overlay chart, daily sales trend with `Prior Year Date` overlay, staffing-vs-traffic correlation.
4. **Controls** — Fiscal Year/Period picker, Region/Area/Store filter, channel filter.

## Input tables

Sigma input tables (user-editable, backed by their own store, not a source CSV) close the loop from "AI flags a problem" to "someone owns fixing it" — turning this from a read-only dashboard into an actual workflow app.

**`INPUT_STORE_ACTION_LOG`** — the core input table, one row per coaching/variance action item.

| Column | Type | Notes |
|---|---|---|
| `Log ID` | Auto-increment / UUID | Primary key |
| `Store Key` | Number (FK to `D_STORE`) | Pre-filled from page context when logged via action |
| `Fiscal Year` / `Fiscal Period` | Number | Pre-filled from the active `D_DATE` control |
| `Metric Flagged` | Text | e.g. "Conversion Rate", "Labor Cost %" — pre-filled when triggered from a KPI tile or the AI chat |
| `Variance Detail` | Text | Free text or AI-generated summary of what moved and why |
| `Action Taken` | Text (editable) | Manager/AVP fills this in |
| `Owner` | Text (FK-ish to `D_STORE_LEADERSHIP.Employee Name`) | Defaults to the logged-in viewer's name if identity mapping exists |
| `Status` | Dropdown: Open / In Progress / Resolved | Drives the "open items" view |
| `Escalated to AVP/RVP` | Boolean | Set via the "Escalate" action below |
| `Date Logged` | Date | Defaults to today |
| `Target Resolution Date` | Date (editable) | Optional |

**`INPUT_STRETCH_GOAL`** *(stretch, optional)* — lets an AVP/RVP enter a stretch sales goal above `F_BUDGET` for a store/period, so the Executive Overview can show "Budget vs. Stretch Goal vs. Actual" three-way. Columns: `Store Key`, `Fiscal Year`, `Fiscal Period`, `Stretch Sales Goal`, `Set By`, `Date Set`. Skip for v1 if the POC needs to stay lean — call out as a fast follow-on.

Both input tables live in Sigma itself (created via the workbook, not new source CSVs) — no changes to the mart's CSVs are needed.

## Actions

Sigma workbook actions tie the dashboard, the input tables, and the AI chat together into one flow:

1. **Drill to Store Detail** — row-click action on the Executive Overview and Region/AVP tables: sets the `Store` control to the clicked row's `Store Key` and navigates to the Store Detail page.
2. **Log Action Item** — button on the Store Detail page (and each KPI tile that's flagged as notable): opens/writes a new row to `INPUT_STORE_ACTION_LOG`, pre-filled with `Store Key`, `Fiscal Year`/`Fiscal Period` from the active controls, and `Metric Flagged` from whichever tile/chart triggered it.
3. **Mark Resolved** — row action on the `INPUT_STORE_ACTION_LOG` table: sets `Status = "Resolved"` and stamps today's date.
4. **Escalate to AVP/RVP** — row action on the action log: sets `Escalated to AVP/RVP = true`, surfacing that row on the Region/AVP View's open-items list.
5. **Reset Filters** — button that clears all page controls (Fiscal Year/Period, Region/Area/Store, Channel) back to default.
6. **AI-chat-triggered logging** — when the custom AI chat flags a >2σ variance (system prompt rule 5 below) or is asked "log this," it invokes the same **Log Action Item** action, pre-filling `Variance Detail` with its own explanation so the manager only has to review and add `Action Taken` — this is the single most demo-able moment for a client (AI notices something → one click turns it into a tracked action).

## AI layer

**Ask-a-Question readiness**
- Hide/rename the duplicate UPPER_SNAKE `D_STORE` columns so NL queries don't hit ambiguous duplicate fields.
- Add field descriptions to every calculated field above (this is what grounds NL answers correctly — e.g. clarify `Conversion Rate` uses in-store orders only, not all channels).
- Keep one conformed grain per data element that Ask-a-Question queries against (don't mix hourly and daily grain in a single element).

**Custom AI chat element — agent system prompt**

```
You are the Store Performance Command Center assistant, an AI chat
embedded in a Sigma workbook for Store Managers, AVPs, and RVPs.

Your job: help the viewer understand their store/area/region's
performance using ONLY the data fields defined in this workbook —
Total Sales, Gross Margin %, Sales vs Budget %, Units vs Budget %,
Total Store Visits, Conversion Rate, Avg Transaction Value, Sales per
Visit, Total Labor Cost, Labor Cost %, Staffing Variance, Sales per
Labor Hour, YoY Sales %, and the Manager Chain hierarchy (Store Manager
-> AVP -> RVP).

Rules:
1. Ground every answer in the workbook's fields — never estimate,
   guess, or supply a number from general retail knowledge. If the
   figure needs a grain, filter, or time window not present on the
   current page, say so and ask the viewer to adjust the filter rather
   than approximating.
2. Respect row-level access: a Store Manager only sees their own
   store's data; an AVP sees their Area; an RVP sees their Region.
   Never surface another manager's store-level detail to a lower-access
   viewer, even if asked directly.
3. When asked "why did X happen" (e.g. "why did conversion drop"),
   decompose using available drivers in this order: traffic change ->
   conversion change -> ATV change -> labor/staffing change -> budget
   context. State which driver(s) moved and by how much. Do not
   speculate about causes not observable in the data (weather,
   competitor activity, etc.) unless the viewer supplies that context.
4. Always state the fiscal period/date range and store/region scope
   your answer covers, so the viewer can verify it against the visible
   page.
5. If a metric swings more than 2 standard deviations from its
   trailing 90-day average, flag it as notable even if not directly
   asked. When you flag something notable, offer to log it as an
   action item (via the Log Action Item action) with your explanation
   pre-filled into Variance Detail — the viewer only needs to add what
   they plan to do about it.
6. Keep answers concise: lead with the number/verdict, then one to two
   sentences of driver explanation. Offer to show the relevant
   chart/page rather than restating full tables in text.
7. Never fabricate employee names, salaries, or performance tiers
   beyond what's in D_STORE_LEADERSHIP; never discuss compensation
   with anyone other than the employee themselves or their direct
   chain of command.
8. If asked about anything outside store operations/performance (HR
   complaints, scheduling disputes, other stores' confidential data),
   say that's outside what this data view can answer and suggest
   contacting the appropriate manager or HR.
9. If the viewer asks to log, escalate, or mark resolved an existing
   action item, trigger the corresponding action (Log Action Item /
   Escalate to AVP or RVP / Mark Resolved) rather than just describing
   what they should click.
```

## Open items to verify before any build
- Confirm `F_SALES.Channel Type` values (`Retail`/`Web`/`BOPIS`/`BOSS`) so `Conversion Rate` correctly scopes only in-store channels against `F_STORE_TRAFFIC` (web visits shouldn't dilute in-store conversion).
- Confirm whether `Reports To Key` chain-walking (Store Manager → AVP → RVP) works cleanly as a Sigma lookup, or needs the `Manager Chain` helper table built once instead.
- Confirm Sigma plan/tier actually supports a custom AI chat element/action — if not, the POC ships with Ask-a-Question only and the system prompt above becomes documentation for a future custom build.
- Decide row-level security mechanism for the manager-scoped chat (user ↔ Store Key / Reports-To mapping) — not yet designed here.
- Confirm whether Sigma's AI chat element can actually invoke a workbook action (trigger "Log Action Item" programmatically) — if not, the AI chat instead tells the viewer to click Log Action Item itself, with the explanation copy-pasteable.
- Confirm input tables persist correctly under Sigma Public (vs. Sigma's paid tiers) — input tables may have plan-level restrictions worth checking before assuming this works in a free/POC workspace.

## Explicit non-goals for this round
- No new CSVs generated (input tables live in Sigma, not the mart's CSV files).
- No cleanup of `D_STORE` messy/duplicate headers performed (flagged only).
- No Sigma workbook actually built — this is the build plan only.

## Next steps (when Sean is ready to build)
- Use the `sigma-api` skill to get an `SIGMA_API_TOKEN`.
- Use the `sigma-workbooks` skill to draft the actual workbook spec (pages, elements, calculated fields, controls) from this plan.
- Resolve the open items above, especially the RLS/hierarchy chain-walk, before submitting the spec.

## Verification
Design/scoping deliverable — verification is Sean reviewing this plan (table mapping, calculated fields, agent instructions) before any workbook spec work begins.
