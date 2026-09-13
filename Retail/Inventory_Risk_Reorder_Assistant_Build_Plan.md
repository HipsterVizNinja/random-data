# Inventory Risk & Reorder Assistant — Sigma Build Plan (POC)

## Context

Sean is building a synthetic retail data mart in Sigma (flat CSVs, 200MB/file cap) and wants a
POC Sigma AI Data App to show clients. Of 5 pitched ideas he picked **Inventory Risk & Reorder
Assistant**. This document is the **build plan only** — no Sigma workbook is being created yet.
Deliverable: data sources, calculated-field formulas, page layout, and the system prompt for the
embedded Sigma AI agent, ready to hand to whoever builds it (or to build from later).

Decisions locked in with Sean:
- **AI approach:** a risk dashboard with Sigma AI (Ask-a-Question) enabled over it, **plus** a
  Sigma input table + action-driven reorder approval workflow — planners see a suggested reorder
  quantity, can edit it, and approve/reject it, writing to a persisted recommendations table.
- **Risk logic:** reorder-point breach **plus** days-to-stockout (sales velocity + vendor lead
  time), not just a static `Qty On Hand <= Reorder Point` flag.
- **Scope:** one workbook, three pages — risk list, Store/Product drill-down, and a reorder
  approval queue built on a Sigma input table.

## Data sources (verified against the actual CSVs)

| Table | Key columns used |
|---|---|
| [F_INVENTORY_SNAPSHOT.csv](F_INVENTORY_SNAPSHOT.csv) | `Store Key, Product Key, Effective Start Date, Qty On Hand, Qty In Transit, Qty Reorder Point` — ~5.95M rows, change-log, 2021-08-15 → 2025-10-12. Take the latest `Effective Start Date` per Store+Product for "current position." |
| [F_POINT_OF_SALE_master.csv](F_POINT_OF_SALE_master.csv) | `Order Number, Product Key, Sales Quantity, Sales Amount, Cost Amount` — line-item grain, join to `F_SALES` for Store+Date. |
| [F_SALES.csv](F_SALES.csv) | `Order Number, Store Key, Date, Date Key, ...` — header-level, no dollar amounts. |
| [D_VENDOR.csv](D_VENDOR.csv) | `Vendor Key, Vendor Name, Lead Time Days, Vendor Rating, Payment Terms`. |
| [D_PRODUCT.csv](D_PRODUCT.csv) | `Product Key, Product Name, Product Type/Family/Line/Group, Price, Product Status, Vendor Key`. |
| [D_STORE.csv](D_STORE.csv) | Use Title Case columns only: `Store Key, Store Name, Store Region, Store State, Store Type` (file has duplicate UPPER_SNAKE columns — known data debt, not cleaned here). |
| [F_PURCHASE_ORDER.csv](F_PURCHASE_ORDER.csv) | `PO Number, Vendor Key, Product Key, Order Date, Expected Receipt Date, Actual Receipt Date, Order Quantity, Unit Cost, PO Status` — **Product-level only, no Store Key** — call this granularity gap out in the UI. |

Excluded: `F_INVENTORY_ADJUSTED.csv` (product-level snapshot, no Store Key — inconsistent with the
store-level risk model; flag as a separate data-model gap for Sean if it matters later).

## Calculated fields (build these as Sigma calculated columns)

**1. Current Position** (per Store Key + Product Key) — filter `F_INVENTORY_SNAPSHOT` to the max
`Effective Start Date` per Store+Product group:
```
Current Position =
  Window: Rank() OVER (PARTITION BY [Store Key],[Product Key] ORDER BY [Effective Start Date] DESC) = 1
```
Yields per-row `Qty On Hand`, `Qty In Transit`, `Qty Reorder Point` as of "now."

**2. Daily Sales Velocity** (per Store Key + Product Key) — trailing 30 days from
`F_POINT_OF_SALE_master` joined through `F_SALES` on `Order Number`:
```
Trailing 30D Qty =
  SUM([Sales Quantity]) WHERE [Date] >= [As Of Date] - 30
  PARTITION BY [Store Key], [Product Key]

Daily Sales Velocity = [Trailing 30D Qty] / 30
```
Since this is static historical data (no live "today"), add an **As Of Date control** on the
workbook (default = `Max(Date)` in `F_SALES`) rather than hardcoding "today."

**3. Effective Lead Time** — join `D_PRODUCT.Vendor Key` → `D_VENDOR.Lead Time Days`:
```
Effective Lead Time = Lookup([Vendor Key] -> D_VENDOR.[Lead Time Days])
```

**4. Days of Supply**:
```
Days of Supply =
  If([Daily Sales Velocity] = 0, Null,
     ([Qty On Hand] + [Qty In Transit]) / [Daily Sales Velocity])
```
Zero-velocity rows get `Null` (flagged separately as "No Recent Sales," not treated as infinite
supply — avoids hiding dead/slow-moving stock from the story).

**5. Risk Bucket**:
```
Risk Bucket =
  Case
    When [Daily Sales Velocity] = 0 Then "No Recent Sales"
    When [Qty On Hand] + [Qty In Transit] <= [Qty Reorder Point]
         Or [Days of Supply] < [Effective Lead Time] Then "Critical"
    When [Days of Supply] < [Effective Lead Time] * 1.5 Then "Warning"
    Else "Healthy"
  End
```

**6. At-Risk Revenue Exposure** (for the KPI tile):
```
At-Risk Revenue Exposure =
  Sum(If([Risk Bucket] In ("Critical","Warning"), [Price] * [Qty Reorder Point], 0))
```
(proxy for dollars exposed to a stockout — Price × Reorder Point gap; refine once real usage
patterns are validated).

**7. Open PO Flag** (drill-down page, Product-level only):
```
Open PO Flag =
  Exists(F_PURCHASE_ORDER Where [Product Key] = [Product Key]
         And [PO Status] <> "Received")
```

**8. Suggested Reorder Qty** (feeds the reorder approval queue, target-service-level heuristic):
```
Target Days of Cover = [Effective Lead Time] * 1.5   -- simple safety-stock multiplier for the POC

Suggested Reorder Qty =
  If([Risk Bucket] In ("Critical","Warning"),
     Max(0, Round([Daily Sales Velocity] * [Target Days of Cover]
                   - ([Qty On Hand] + [Qty In Transit]))),
     0)
```
This is a starting-point heuristic (velocity × target cover, minus what's already on hand/in
transit), not a full replenishment model — good enough to seed a human-reviewed queue for a POC.

## Workbook structure (2 pages)

**Page 1 — Reorder Risk List**
- Filters: Region, Store, Product Family/Line, Risk Bucket.
- KPI row: # SKU-Stores at risk (Critical/Warning), At-Risk Revenue Exposure, avg Days of Supply
  for Critical bucket.
- Table: Store, Product, Days of Supply, Qty On Hand, Qty In Transit, Reorder Point, Effective
  Lead Time, Risk Bucket — sorted ascending by Days of Supply. Row click → Page 2.
- Sigma AI chat enabled, scoped to this workbook's data model.

**Page 2 — Store + Product Drill-Down**
- Driven by Page 1 row selection (or manual Store/Product pickers).
- Trend chart: on-hand qty + reorder point line over time (full snapshot history) vs. sales
  velocity.
- Vendor panel: Vendor Name, Effective Lead Time, Vendor Rating, Payment Terms.
- Open PO panel: any non-Received PO for this Product — with a visible note that this table is
  Product-level, not Store-level, so "already inbound" is an approximation across all stores.
- "Send to Reorder Queue" action button (see Page 3) — pushes the current Store+Product row,
  its `Suggested Reorder Qty`, and Risk Bucket into the input table backing Page 3.

**Page 3 — Reorder Approval Queue (Sigma input table + actions)**
- Backing table: a Sigma **input table** (`Reorder Recommendations`) seeded from Page 1/2 rows
  where Risk Bucket is Critical or Warning, with columns: `Store Key, Product Key, Suggested
  Reorder Qty, Approved Qty (editable), Status, Reviewed By, Reviewed At`.
- Editable grid: planner can adjust `Approved Qty` inline (Sigma input-table cell editing) before
  approving.
- Row-level **actions** (Sigma workbook actions bound to buttons/menu):
  - `Approve` — sets `Status = "Approved"`, stamps `Reviewed By` (viewer identity) and
    `Reviewed At` (now), locks the row from further edits.
  - `Reject` — sets `Status = "Rejected"`, same stamping, `Approved Qty` cleared.
  - `Send Back` — resets `Status = "Needs Review"` for re-triage.
- Filter/tab by `Status` (Needs Review / Approved / Rejected) so the queue reads like a worklist,
  not a static table.
- This queue is the record system a downstream PO-creation step (out of scope for this POC) would
  read from — approved rows are the ones a real system would turn into actual purchase orders.

## Sigma AI agent system prompt

Use this as the instructions/system prompt for the Sigma AI chat embedded on the workbook:

```
You are an inventory planning assistant for a retail data mart. You answer questions using only
the data available in this workbook: current inventory position (Qty On Hand, Qty In Transit,
Qty Reorder Point), sales velocity, vendor lead times, and risk classifications (Critical /
Warning / Healthy / No Recent Sales) computed per Store and Product.

Rules:
1. Ground every answer in the workbook's fields — do not invent numbers, thresholds, or vendor
   information not present in the data.
2. "At risk" means Risk Bucket = Critical or Warning. Always state which bucket(s) you're
   including when answering a risk question.
3. When asked "how many days until X stocks out," answer using Days of Supply, and note if it is
   Null (meaning no recent sales — flag this distinctly rather than implying zero risk).
4. When asked about reorders already in progress, note that Purchase Order data is tracked at the
   Product level only, not Store level — say so explicitly rather than implying a PO covers a
   specific store's shortfall.
5. Prefer concrete, filtered answers (store name, product name, numeric days-of-supply) over
   vague summaries. If a question spans more rows than reasonable to list, summarize counts and
   offer to narrow by region, store, or product line.
6. If asked for a business action (e.g. "how much should I reorder"), reference the workbook's
   `Suggested Reorder Qty` field as a starting-point heuristic, and point the user to the Reorder
   Approval Queue page to review, adjust, and approve/reject it — you never approve a reorder
   yourself, only surface the suggested number and direct them to the human approval step.
7. If asked "what's pending approval" or "what did I approve this week," answer from the
   `Reorder Recommendations` input table's `Status`/`Reviewed At` fields.
8. Do not answer questions unrelated to inventory/reorder planning for this data mart.
```

## Future extension (not built in this POC)

A downstream integration that takes `Approved` rows from the Reorder Recommendations input table
and actually creates purchase orders (e.g. writing to `F_PURCHASE_ORDER` or an external
procurement system) is a natural next step, but out of scope here — this POC stops at human
approval, not automated PO creation.

## Open items / risks to flag to Sean before build

- `F_INVENTORY_SNAPSHOT` is 5.95M rows — may need pre-aggregation to "latest position per
  Store+Product" before upload for performance, on top of the existing 200MB/file ceiling.
- `F_PURCHASE_ORDER` has no Store Key — Open PO Flag is an approximation, not store-specific.
- Zero-velocity SKUs need a deliberate "No Recent Sales" bucket, not silent exclusion from risk
  math, so slow-moving stock doesn't disappear from the story.
- Confirm whether Sigma AI/Ask-a-Question is spec-configurable via the API or a workbook-level
  toggle set manually post-publish — determine when this actually gets built.
