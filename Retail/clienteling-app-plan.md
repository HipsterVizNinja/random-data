# Clienteling Data App POC — Scope

## Context
Sean is building a synthetic retail data mart for Sigma demos (flat CSVs, 200MB/file ceiling, `D_`/`F_` naming conventions — see `retail-data-mart-project` memory). The Clienteling app was flagged earlier as a future idea, backed by `D_CUSTOMER` (loyalty program/tier) and `D_SALESPERSON`. Sean has now decided to scope it, with constraints confirmed via clarifying questions:
- **Persona scope**: flexible enough for both a salesperson-facing view and a manager-facing view; no single-persona commitment.
- **Tables**: reuse existing tables only — no new fact/dimension tables this round.
- **Data generation**: none — this is a schema/workbook-spec design exercise only.
- **This pass**: produce the full Sigma build plan — calculated fields and the AI agent's system prompt instructions — but do **not** build anything in Sigma yet.

## Prerequisite data issue to flag to Sean (not fixed in this pass, just called out)
`D_CUSTOMER.csv` and `D_STORE.csv` both have messy headers: original mixed-case columns, a duplicate redundant UPPERCASE column set, plus newly appended columns. Specifically for Clienteling:
- Loyalty info lives in the **appended** `LOYALTY_TIER` / `LOYALTY_PROGRAM` columns, not the original `Loyalty Program` column — and in the 2-row sample seen, values didn't align cleanly between the original and duplicate sets (nulls in one where the other is populated).
- This plan uses `LOYALTY_TIER` / `LOYALTY_PROGRAM` (the appended fields) as the source of truth since they carry the richer values (e.g. `at_risk`) — confirm this is correct before building.

## Available source tables (confirmed via directory scan)
| Table | Relevant fields for Clienteling |
|---|---|
| `D_CUSTOMER.csv` | `Cust Key`, `Cust Name`, demographics (age/gender/civil status), `Cust Since`, `LOYALTY_TIER`, `LOYALTY_PROGRAM`, `DOWNLOADED_APP`, `BIRTHDAY_MONTH`/`BIRTHDAY_DAY` |
| `D_SALESPERSON.csv` | `Salesperson Key`, `Salesperson Name`, `Store Key`, `Tier`, `Commission Rate`, `Tenure Years`, `Employment Status` |
| `F_SALES.csv` | order header: `Order Number`, `Cust Key`, `Store Key`, `Salesperson Key`, `Date Key`, `Channel Type`, `Purchase Method` (no dollar amount — header only) |
| `F_POINT_OF_SALE_master.csv` | line-item detail — `Sales Amount`/`Cost Amount`/`Sales Quantity` per product, joined via `Order Number` |
| `D_PRODUCT.csv` | product attributes for recommendation/affinity narratives |
| `F_PRODUCT_REVIEW.csv` | customer sentiment — usable for AI-generated customer notes |
| `D_STORE.csv` / `D_STORE_LEADERSHIP.csv` | store and management context for the manager persona |
| `D_DATE.csv` | fiscal calendar for recency/tenure framing |

No new tables needed.

## Data model / joins
Base table: `D_CUSTOMER` → `F_SALES` (on `Cust Key`) → `F_POINT_OF_SALE_master` (on `Order Number`, pre-aggregated to order grain to avoid line-item fan-out) → `D_SALESPERSON` (on `Salesperson Key`, filter `Employment Status = 'Active'`) → `D_STORE` / `D_STORE_LEADERSHIP` (on `Store Key`).
- `F_SALES.Date Key` → `D_DATE.Date Key` (recency/tenure framing, "Cust Since" vs. as-of date)
- `F_PRODUCT_REVIEW` joins on `Cust Key` (and/or `Order Number`/`Product Key`) for sentiment — confirm attribution field before building

## Sigma calculated fields (build-ready)

| Field name | Formula (Sigma syntax) | Notes |
|---|---|---|
| `Order Sales Amount` | `Sum(Sales Amount)` grouped by `Order Number` | Pre-aggregate at order grain before joining upward — avoids line-item fan-out on spend totals |
| `As Of Date` | Control-bound date (single-value Date control, default `Max(Date)` from `F_SALES`) | Lets the demo simulate "today" against static historical data — same pattern needed anywhere recency/rolling windows are used |
| `Lifetime Spend` | `Sum([Order Sales Amount])` grouped by `Cust Key` | |
| `Last Purchase Date` | `Max([Date])` grouped by `Cust Key` | From `F_SALES.Date` |
| `Days Since Last Purchase` | `DateDiff([Last Purchase Date], [As Of Date], "day")` | |
| `Is In Rolling 90` | `[Date] > AddDays([As Of Date], -90) AND [Date] <= [As Of Date]` | Window flag reused below |
| `Order Count (Trailing 90 Days)` | `CountDistinct(If([Is In Rolling 90], [Order Number], Null))` grouped by `Cust Key` | |
| `Primary Salesperson` | `Mode([Salesperson Key])` grouped by `Cust Key` (or top-count via a rank calc if `Mode` unavailable on ties) | "Whose customer is this" — drives the salesperson-view filter |
| `Customer Tenure (Years)` | `DateDiff([Cust Since], [As Of Date], "year")` | |
| `Upcoming Birthday Flag` | `Case When DateDiff(MakeDate(Year([As Of Date]), [Birthday Month], [Birthday Day]), [As Of Date], "day") Between 0 And 14 Then True Else False End` | Handles month/day only, wrapped to current year; refine for year-boundary wraparound (Dec→Jan) before build |
| `At-Risk Loyalty Flag` | `[LOYALTY_TIER] = "at_risk"` | |
| `Avg Review Sentiment` | `Avg([Rating])` grouped by `Cust Key` | From `F_PRODUCT_REVIEW`, pending attribution confirmation |
| `Store Loyalty Tier Mix %` | `Count(Cust Key) / Sum(Count(Cust Key)) Over (Partition By [Store Key])` grouped by `Store Key`, `LOYALTY_TIER` | Manager-view rollup |
| `Outreach Priority Score` | `(If([At-Risk Loyalty Flag], 2, 0)) + (If([Upcoming Birthday Flag], 1, 0)) + (If([Days Since Last Purchase] > 90, 1, 0))` | Simple weighted score to rank "who should I reach out to today" — tune weights during build |

## Proposed Sigma workbook structure

1. **Customer 360 (shared page)** — searchable/filterable customer list (`D_CUSTOMER` joined through to `F_POINT_OF_SALE_master`) showing `Loyalty Tier`, `Customer Tenure`, `Last Purchase Date`, `Lifetime Spend`, `Primary Salesperson`. Backbone table both personas drill into.
2. **My Customers (salesperson view)** — filtered to a selected `Salesperson Key` via `Primary Salesperson`; table sorted by `Outreach Priority Score`, surfacing at-risk loyalty, upcoming birthdays, recent purchase/review activity.
3. **Team & Store Performance (manager view)** — `D_STORE_LEADERSHIP` + `D_SALESPERSON` rolled up by store/region; `Store Loyalty Tier Mix %` and trend, tied to `Lifetime Spend`/`Order Sales Amount` for revenue context.
4. **AI Q&A layer** — Sigma AI natural-language input wired across these pages, grounded in the same tables/calculated fields above (no separate AI-only schema).

## Sigma Input Table & Actions

An **Input Table** (Sigma-native writable table, not a new source CSV — this doesn't conflict with the "no new fact tables" constraint) closes the loop the AI chat can't on its own: whether a customer has already been contacted.

**`Outreach Log` (Input Table)**
| Column | Type | Notes |
|---|---|---|
| `Log Key` | Auto-increment / generated | Row identifier |
| `Cust Key` | Number (linked) | FK back to `D_CUSTOMER` |
| `Salesperson Key` | Number (linked) | FK back to `D_SALESPERSON`, defaults to current viewer if identity mapping exists |
| `Contact Date` | Date, default = today | |
| `Contact Method` | Dropdown: Call / Text / Email / In-Store | |
| `Outcome` | Dropdown: No Answer / Follow-up Scheduled / Purchase Made / Not Interested | |
| `Notes` | Free text | |

**Calculated fields that depend on it**
| Field name | Formula | Notes |
|---|---|---|
| `Last Contacted Date` | `Max([Contact Date])` grouped by `Cust Key`, from `Outreach Log` | |
| `Contacted in Last 7 Days` | `[Last Contacted Date] >= AddDays([As Of Date], -7)` | |
| `Outreach Priority Score` (revised) | prior formula, **minus** `If([Contacted in Last 7 Days], 3, 0)` | Recently-contacted customers drop down the ranking instead of resurfacing every session |

**Actions**
- **Log Outreach** (row-level button, My Customers page) → opens a form writing a new row to `Outreach Log` for that `Cust Key` (Contact Method, Outcome, Notes as inputs; `Salesperson Key`/`Contact Date` pre-filled).
- **Mark Contacted Today** (quick action) → one-click insert into `Outreach Log` with today's date and method from a page control, for fast logging without the full form.
- **Drill / navigate** action: clicking a customer row on Customer 360 navigates to My Customers filtered to that `Cust Key`, so a manager can jump into a specific customer's detail without re-searching.
- **Re-rank on submit**: after an `Outreach Log` write, the page re-evaluates `Outreach Priority Score` so contacted customers fall out of the top of the outreach list immediately (relies on `Contacted in Last 7 Days` above, not a separate action step).

This also gives the AI agent something new to reason over — add to its grounding fields (see updated system prompt below): `Last Contacted Date`, `Contacted in Last 7 Days`, and the ability to answer "have I already reached out to this customer?" or "who did I contact this week and what happened?" directly from `Outreach Log.Outcome`/`Notes`.

## Sigma AI agent — system prompt instructions

```
You are a clienteling assistant embedded in a Sigma workbook for retail sales associates and their managers.

Your job: help the viewer understand their (or their team's) customer relationships and answer "who should I focus on and why" questions — using ONLY the data visible to them on this workbook page. Row-level security already restricts what you can see, so never claim to know about a customer, salesperson, or store outside the current viewer's scope, even if asked directly.

Grounding rules:
- Base every answer on this workbook's fields: Lifetime Spend, Last Purchase Date, Days Since Last Purchase, Order Count (Trailing 90 Days), Primary Salesperson, Customer Tenure (Years), Upcoming Birthday Flag, At-Risk Loyalty Flag, Avg Review Sentiment, Store Loyalty Tier Mix %, Outreach Priority Score, Last Contacted Date, Contacted in Last 7 Days, and the Outreach Log (Contact Method, Outcome, Notes).
- When asked "have I already reached out to this customer" or "who did I contact this week," answer from the Outreach Log directly — cite the Contact Date, Method, and Outcome rather than just the priority score.
- Never invent a customer, transaction, product, or metric not derivable from these fields. If asked something this workbook can't answer (e.g. a customer's phone number, email, or reasons behind a review), say this view doesn't contain that information rather than guessing.
- This is synthetic demo data — LOYALTY_TIER and other fields are test values, not real customer PII. Still avoid restating full names/addresses gratuitously; only surface what's needed to answer the question.
- When asked "who should I reach out to today," rank by Outreach Priority Score and briefly explain why each customer scored the way they did (e.g. "at-risk loyalty tier + birthday this week + no purchase in 100 days").
- When a manager asks about store or team-level loyalty health, use Store Loyalty Tier Mix % and trend over time rather than listing individual customers unless asked to drill in.
- Keep answers concise (2-4 sentences) and action-oriented — suited to an associate on the floor or a manager prepping a coaching conversation. Always cite the specific number(s) behind your answer so it's traceable to a visible field on the page.
- If asked about anything outside customer relationship/purchase history (HR matters, pay, scheduling, other stores' confidential data), say that's outside what this view can answer.
```

## Open items to verify before build
- Confirm `LOYALTY_TIER`/`LOYALTY_PROGRAM` vs. the original `Loyalty Program`/duplicate uppercase columns — which is authoritative (see prerequisite issue above).
- Confirm `F_POINT_OF_SALE_master` grain aggregates cleanly to order-level before joining upward (avoid fan-out double-counting spend).
- Decide the "as-of date" mechanism for recency/tenure calcs against static historical data (control input vs. max date in the table).
- Confirm `F_PRODUCT_REVIEW` reliably attributes reviews to a `Cust Key` (needed for `Avg Review Sentiment`).
- `Upcoming Birthday Flag` needs a year-boundary edge case handled (birthdays in early January when "as of" is in late December).
- Row-level security mechanism for salesperson/manager scoping — needs a user↔identity mapping; check whether one already exists in the mart before inventing one.
- Confirm Sigma plan/tier supports Input Tables and custom Actions (button/row-level actions) — if not available, `Outreach Log` degrades to a read-only demo mockup and the "Log Outreach"/"Mark Contacted Today" actions become documentation only for this POC.
- Input Table data is workbook-local and won't survive a workbook rebuild/re-import — fine for a POC demo, but call this out to Sean if he wants outreach history to persist longer-term.

## Explicit non-goals for this round
- No new CSVs generated.
- No cleanup of `D_CUSTOMER`/`D_STORE` messy headers performed (flagged only).
- No Sigma workbook actually built — this is the build plan only.

## Next steps
- Once Sean confirms this plan, use the `sigma-workbooks` skill (with `sigma-api` for auth) to draft the actual workbook spec JSON — pages, elements, calculated fields, controls, and the AI system prompt above.

## Verification
Design/scoping deliverable — verification is Sean reviewing this plan (table mapping, calculated fields, agent instructions) before any workbook spec or data cleanup work begins.
