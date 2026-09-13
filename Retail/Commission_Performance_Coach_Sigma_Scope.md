# Commission & Performance Coach — Sigma AI Data App Scope

## Context
This is a POC pulled from the Retail data mart brainstorm (see [[retail-data-mart-project]]). The goal: a Sigma workbook that lets salespeople and their managers self-serve on commission performance, with an AI layer for natural-language Q&A. Scoping decisions below were made with Sean via clarifying questions. **This is documentation only — nothing gets built in Sigma from this pass.**

**Key data finding:** `D_SALESPERSON.Tier` (Cashier → Ambassador → Senior Ambassador → Lead) is a role/seniority level, not a sales-volume-triggered tier, and `Commission Rate` varies *within* a Tier (e.g. Ambassador ranges 2.0%–3.5%). There is no existing sales-threshold table that promotes someone between tiers. Per Sean's decision, the app will **not** invent synthetic tier thresholds — instead it coaches on **commission-dollar pacing at the salesperson's current rate** ("sell $X more this period → earn $Y more commission"), which uses the data as-is.

## Scope decisions (confirmed with Sean)
- **Audience:** Role-based, single app — a salesperson sees only their own performance; a Store Manager/AVP/RVP sees their team/store rollup. Row-level security keyed off `Store Key` (and eventually `Reports To Key` for AVP/RVP rollups).
- **Tables in scope:** `D_SALESPERSON`, `F_SALES`, `F_POINT_OF_SALE_master`, `D_STORE`, `D_STORE_LEADERSHIP` (for manager identity/role only — Store Leadership bonus tiers themselves are **out of scope** for this POC).
- **Pacing window:** Rolling 30-day and rolling 90-day sales, computed from `F_SALES.Date` (no fiscal-calendar dependency for this app).
- **Out of scope for this POC:** synthetic tier-threshold table, Store Leadership bonus-tier coaching, fiscal 4-5-4 alignment.

## Data model / joins (verified schemas)
- `F_SALES` — Order Number, Cust Key, Store Key, Transaction Type, Date, Purchase Method, Date Key, Salesperson Key, Channel Type, Transaction Location Key, Fulfillment Location Key — **header-only, no dollar amount**
- `F_POINT_OF_SALE_master` — Order Number, Product Key, Sales Quantity, Sales Amount, Cost Amount — **line-item grain; this is where $ actually lives.** Join `F_SALES.Order Number` → `F_POINT_OF_SALE_master.Order Number`, aggregate (sum) to order grain before joining onward to avoid fan-out double-counting.
- `D_SALESPERSON` — Salesperson Key, Salesperson Name, Store Key, Tier, Hire Date, Employment Status, Termination Date, Tenure Years, Commission Rate — filter `Employment Status = 'Active'`
- `D_STORE` — Store Key, Store Name, City/State/Region/Area, etc. (has duplicate UPPER_SNAKE_CASE columns from a past merge — hide/rename in workbook, don't touch source CSV)
- `D_STORE_LEADERSHIP` — Leadership Key, Employee Name, Role (`Store Manager`/`AVP`/`RVP`), Store Key, Reports To Key, Hire Date, Tenure Years, Annual Salary, Performance Tier, Bonus Rate — `Reports To Key` chains Store Manager → AVP → RVP

Join keys: `F_SALES.Order Number` → `F_POINT_OF_SALE_master.Order Number`; `F_SALES.Salesperson Key` → `D_SALESPERSON.Salesperson Key`; `D_SALESPERSON.Store Key` → `D_STORE.Store Key`; `D_SALESPERSON.Store Key` → `D_STORE_LEADERSHIP.Store Key` where `Role = 'Store Manager'` (AVP/RVP rollup via `Reports To Key` chained upward).

## Sigma calculated fields (build-ready)

Base table: `F_SALES` → `F_POINT_OF_SALE_master` (on `Order Number`, pre-aggregated to order grain) → `D_SALESPERSON` (on `Salesperson Key`, filtered Active) → `D_STORE` (on `Store Key`).

| Field name | Formula (Sigma syntax) | Notes |
|---|---|---|
| `Order Sales Amount` | `Sum(Sales Amount)` grouped by `Order Number` | Pre-aggregate at order grain before joining to salesperson to avoid line-item fan-out |
| `As Of Date` | Control-bound date (single-value Date control, default `Max(Date)` from `F_SALES`) | Lets the demo simulate "today" against static historical data |
| `Is In Rolling 30` | `[Date] > AddDays([As Of Date], -30) AND [Date] <= [As Of Date]` | Boolean flag used as a filter/window condition |
| `Is In Rolling 90` | `[Date] > AddDays([As Of Date], -90) AND [Date] <= [As Of Date]` | |
| `Is In Prior 30` | `[Date] > AddDays([As Of Date], -60) AND [Date] <= AddDays([As Of Date], -30)` | Comparison window immediately preceding the current rolling 30 |
| `Rolling 30-Day Sales` | `Sum(If([Is In Rolling 30], [Order Sales Amount], 0))` grouped by `Salesperson Key` | |
| `Rolling 90-Day Sales` | `Sum(If([Is In Rolling 90], [Order Sales Amount], 0))` grouped by `Salesperson Key` | |
| `Prior 30-Day Sales` | `Sum(If([Is In Prior 30], [Order Sales Amount], 0))` grouped by `Salesperson Key` | |
| `Rolling 30-Day Commission` | `[Rolling 30-Day Sales] * [Commission Rate]` | `Commission Rate` comes from `D_SALESPERSON` |
| `Rolling 90-Day Commission` | `[Rolling 90-Day Sales] * [Commission Rate]` | |
| `Pace vs Prior Window` | `[Rolling 30-Day Sales] - [Prior 30-Day Sales]` | Positive = trending up, negative = trending down |
| `Pace vs Prior Window %` | `([Rolling 30-Day Sales] - [Prior 30-Day Sales]) / NullIf([Prior 30-Day Sales], 0)` | Guard divide-by-zero for new hires with no prior window |
| `Target Commission Increase` (input) | Number control, user-entered (e.g. `$200`) | Drives the what-if calc below |
| `Sales Needed for Target` | `[Target Commission Increase] / NullIf([Commission Rate], 0)` | The core "coach" answer |
| `Sales Needed vs Current Pace` | `[Sales Needed for Target] - [Rolling 30-Day Sales]` | How much further they still need to go this window |
| `Tenure Band` | `Case When [Tenure Years] < 1 Then "New (<1yr)" When [Tenure Years] < 3 Then "Established (1-3yr)" Else "Veteran (3yr+)" End` | For manager-view segmentation/coaching context, not a payout driver |
| `Manager Chain` | Flattened helper reference table (`Salesperson Key → Store Manager Key → AVP Key → RVP Key`), built once rather than resolved as a recursive live join | Powers RLS scoping for AVP/RVP without recursive lookups in-workbook |

## Workbook pages
1. **My Performance** (salesperson view, filtered to their own `Salesperson Key` via row-level security)
   - KPI tiles: Rolling 30-day sales, rolling 30-day commission earned, current tier + rate, tenure
   - Trend chart: daily/weekly sales + commission over the trailing 90 days
   - "What-if" control: input for a target commission $ increase → shows required incremental sales at current rate
   - Embedded AI chat scoped to their own data
2. **Team Coach View** (Store Manager / AVP / RVP view)
   - Roster table: all salespeople in scope (via `Manager Chain`), each with tier, rate, rolling 30/90-day sales, commission earned, pace vs. prior window
   - Sort/highlight by "biggest pace decline" for coaching conversations
   - Embedded AI chat scoped to the manager's team

## Security / access model
- Row-level security policy on `Salesperson Key` = logged-in user's mapped salesperson identity (for POC, likely a simple lookup table or Sigma user attribute mapping)
- Manager view uses a broader RLS policy scoped to `Store Key` (Store Manager) or the `Reports To Key` chain (AVP/RVP) via the `Manager Chain` helper table

## AI Agent system prompt (embedded chat, both pages)

```
You are the Commission & Performance Coach, an AI assistant embedded in a Sigma workbook for retail sales staff and their managers.

Your job: help the person understand their (or their team's) sales-commission performance and answer "what do I need to do" questions — using ONLY the data visible to them in this workbook page. Row-level security already restricts what data you can see, so never claim to know about a salesperson, store, or region outside the current viewer's scope, even if asked directly.

Grounding rules:
- Base every answer on the workbook's underlying fields: Rolling 30/90-Day Sales, Rolling 30/90-Day Commission, Commission Rate, Tier, Tenure, Pace vs Prior Window, and Sales Needed for Target.
- Tiers (Cashier / Ambassador / Senior Ambassador / Lead) are role/seniority levels, not sales-volume-triggered. NEVER tell a user "sell $X to reach the next tier" — there is no such threshold in this data. If asked about tier promotion, explain that tier reflects role/tenure, not a sales target, and redirect to commission-dollar pacing instead.
- Frame coaching in commission-dollar terms: "at your current rate of R%, selling $X more in the next 30 days would earn you $Y more in commission."
- When asked "how much more do I need to sell to earn $X more," compute using Sales Needed for Target = target increase / Commission Rate, and compare it against their current Rolling 30-Day Sales pace.
- If a manager asks "who is trending down," rank by Pace vs Prior Window ascending and surface the names/stores below zero, with the magnitude of decline.
- If asked about anything outside sales/commission (e.g. HR complaints, scheduling, other stores' data, pay disputes), say that's outside what this data view can answer and suggest they contact their manager or HR.
- Keep answers concise (2-4 sentences) and always cite the specific number(s) behind your answer so the user can verify it against the visible tiles/table — never state a figure that isn't traceable to a field on this page.
- Do not speculate about future company decisions (rate changes, layoffs, reorgs) — you only reason over historical sales data.
```

## Input tables

Sigma Input Tables give this POC persistent, user-editable state instead of everything living in ephemeral page controls — this is what makes it feel like an "app," not just a dashboard.

| Input table | Columns | Written by | Purpose |
|---|---|---|---|
| `INPUT_USER_SALESPERSON_MAP` | User Email, Salesperson Key, Role (`Salesperson`/`Store Manager`/`AVP`/`RVP`) | Admin (Sean, pre-seeded) | Drives row-level security — maps a logged-in Sigma user to their `Salesperson Key` (or manager scope). Replaces the "does an identity mapping exist" open item below with a concrete, editable table. |
| `INPUT_COMMISSION_TARGET` | Salesperson Key, Target Commission Increase, Set Date, Set By | Salesperson, via the "My Performance" what-if control | Persists the target across sessions instead of resetting on every page load (currently scoped as a stateless Number control — promoting it to an input table means "Sales Needed for Target" survives a refresh and a manager can see what target a rep set for themselves). |
| `INPUT_COACHING_LOG` | Log Key, Salesperson Key, Manager Key, Coaching Date, Note, Follow-Up Date | Manager, via the "Team Coach View" action below | Lets a manager log a coaching conversation directly against a salesperson row — turns the roster table into a working coaching tool rather than a read-only report, and gives the embedded AI chat something concrete to reference ("what did we last discuss with this rep?"). |

Notes:
- Keep input tables small and workbook-scoped for the POC — no need for the 200MB Sigma Public ceiling concern here since these stay tiny (dozens to low-hundreds of rows).
- `INPUT_USER_SALESPERSON_MAP` should be seeded with a handful of demo users before any client walkthrough — this is the one input table that must exist before the RLS policies below can be wired up at all.

## Actions

| Action | Trigger | Behavior |
|---|---|---|
| **Save Target** | Button next to the "Target Commission Increase" control on My Performance | Writes/updates a row in `INPUT_COMMISSION_TARGET` for the viewer's own `Salesperson Key`, stamped with today's date — makes the what-if goal persistent instead of resetting per session |
| **Log Coaching Conversation** | Button on each row of the Team Coach View roster table | Opens a form (or inline input row) pre-filled with `Salesperson Key` + `Manager Key` from the row clicked; on submit, inserts into `INPUT_COACHING_LOG` |
| **View Rep Detail** | Row click / "View" button on Team Coach View roster | Navigation action that drills the manager into a filtered version of the My Performance page, scoped to the clicked salesperson (lets a manager see exactly what their rep sees, in context of a coaching conversation) |
| **Refresh As Of Date** | Button near the `As Of Date` control | Resets `As Of Date` to `Max(Date)` from `F_SALES` — convenience action so demo viewers don't have to manually re-pick the date each time they open the workbook |
| **Ask AI About This Rep** | Button on each Team Coach View roster row | Pre-populates the embedded AI chat with a scoped prompt ("Tell me about \[Salesperson Name]'s pacing this month") so the manager doesn't have to type it — a nice AI-app touch that ties the chat directly to table interaction |

## Open items to verify before build
- Confirm Sigma Input Table row-level write permissions can be scoped so a salesperson can only write their own row in `INPUT_COMMISSION_TARGET` (not edit peers' targets), and a manager can only write coaching-log rows for their own team
- Decide "as-of date" mechanism for rolling windows against static historical data (control input vs. max date in the table) — the "Refresh As Of Date" action above assumes `Max(Date)`, confirm that's still desired once `As Of Date` is used to drive input-table writes too
- Seed `INPUT_USER_SALESPERSON_MAP` with actual demo user emails before any client-facing walkthrough

## Next steps
- Use the `sigma-workbooks` skill (needs `SIGMA_API_TOKEN` via `sigma-api` skill) to draft the workbook spec: pages, elements, calculated fields, controls, input tables, and actions as scoped above
- Build the flattened salesperson→manager→AVP→RVP helper reference table
- Seed `INPUT_USER_SALESPERSON_MAP` and pre-create the two other input tables before wiring actions to them
