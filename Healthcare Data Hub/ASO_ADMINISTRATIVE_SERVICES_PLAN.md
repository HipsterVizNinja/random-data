# Administrative Services Only — Sigma Build Plan

A Sigma workbook that runs Meridian Health Plan's self-funded book: nine employer clients,
about 24,000 covered lives, and the four numbers a third-party administrator is paid to get right —
what the plan cost, what the client was billed, what stop-loss gave back, and whether the
rate was ever adequate.

Planning document. **Nothing is built in Sigma from this pass.** Companion wireframe:
[aso_administrative_services_wireframe.html](aso_administrative_services_wireframe.html)
— six pages, every figure measured, `?theme=light` and `#page` deep links for review.

> **The dataset was extended to support this.** Healthcare Data Hub had one ASO plan code and
> no ASO economics. This pass added a sixth source system (`raw_aso`) and nine mart tables,
> and fixed two defects in the shipped data that the ASO layer made visible.
> [§17](#17-what-this-build-changed-in-the-dataset) records both.

Every figure in this plan is measured from the shipped `demo` build (seed 20260911), not
transcribed from a design. They come from `Validation/aso_book.py`, which is committed —
the provider incentive plan learned that lesson the hard way, and
[§16](#16-verification) says how to reproduce each one, and
[§19](#19-reference-figures) lists them.

---

## 1. Context

[Healthcare Data Hub](README.md) is a synthetic healthcare dataset: six source systems,
41 mart tables, twelve planted data-quality defects. Its first application,
[Provider Incentive Program](PROVIDER_INCENTIVE_PROGRAM_PLAN.md), looked at the
**provider** side of Meridian's business — who gets paid a shared-savings bonus.

This one looks at the other side. Meridian does not only insure risk; it also **administers
plans it does not insure**. Nine of its seventeen employer clients are self-funded: they pay
Meridian to adjudicate claims, rent its network, manage utilization and place stop-loss cover,
and then they fund every claim dollar out of their own bank accounts. That is Administrative
Services Only, and it is a different business with a different scoreboard.

The distinction that makes it worth building: **in a fully-insured book a reporting error
misleads. In a self-funded book it moves money.** A wrong denominator sets a rate the client
collects for twelve months. A wrong fee basis bills a client twice what the contract says. A
duplicate claim line does not produce a bad chart, it produces a wire. Every one of those is
in the data and measurable.

### Scope decisions, confirmed

| Decision | Choice |
|---|---|
| **Audience** | The **TPA**, looking across a book. A single client's own view is a drill-down inside the same workbook, not a second app — the book view is the superset and the interesting findings are cross-client. |
| **Grain** | The **client**, never the enrollment group. One client holds two group ids. Reasoning in [§4](#4-why-the-grain-is-the-client-and-not-the-group). |
| **Where logic lives** | A new Sigma **data model**, `Meridian ASO`. The workbook is presentation-only, as in Provider Incentive Program. |
| **Contract years** | **CY2024** complete, **CY2025 YTD through September** in flight. October–December 2025 displays and never scores. Reasoning in [§8](#8-runout-and-why-the-scored-window-stops-at-september). |
| **Denominators** | Both ship. `fct_member_month` is the only sanctioned PMPM denominator; the naive span-sum ships beside it because the rate was set over it. Reasoning in [§5](#5-two-denominators-and-neither-is-optional) and [§6](#6-the-renewal-priced-over-a-double-counted-denominator). |
| **Pharmacy** | Out of scope, and **no PBM administration fee is modeled**. Reasoning in [§15](#15-explicit-non-goals). |

---

## 2. What an ASO engagement is

An employer that self-funds buys four things and insures none of them.

| What the client buys | How it is priced | Where it lives |
|---|---|---|
| Claim adjudication and plan administration | **PEPM** — per *employee* per month | `aso_fee_schedule`, `fee_code = ADMIN` |
| Network access — the right to the payer's contracted rates | PMPM | `fee_code = NETWORK_ACCESS` |
| Care management and utilization review | PMPM | `fee_code = CARE_MGMT` |
| Stop-loss cover, specific and aggregate | PMPM, passed through to the carrier | `fee_code = ISL_PREMIUM`, `ASL_PREMIUM` |

And it funds the claims themselves, dollar for dollar, weekly, out of its own account.

So the scoreboard has four lines rather than one:

```
  paid claims                     what the plan actually spent
− specific stop-loss received     what the carrier gave back (RECEIVED, not entitled)
+ administration and premium      what Meridian and the carrier were paid
= net plan cost                   what the client experienced
```

against a **budget** that somebody set from last year's experience, twelve months before any
of it happened. The gap between net plan cost and budget is the conversation, and every
component of it is a place a number can be wrong.

---

## 3. The findings the app exists to surface

Three, ranked by how much money moves and how hard each is to see. All three are measured
from the shipped build, and all three are the kind of error that survives review because the
number it produces looks reasonable.

### 3.1 A renewal priced over a denominator the enrollment feed double counted

**$1,015,333 of budget that one client never collected.**

Kellerman Industries was acquired in April 2024. Its members moved from `KELL-4471` to
`NLK-KELL-01` — and the old group's spans were never terminated, so for the rest of 2024 the
same members are enrolled twice in the enrollment extract.

`fct_member_month` is immune: it builds member-months from the gaps-and-islands **union** of
a member's coverage, so an overlap counts once. But a rate-setting analyst does not work from
`fct_member_month`. They work from the enrollment feed, and they **sum spans**:

| | Member-months, CY2024 |
|---|---|
| Enrollment feed, spans summed | 24,992 |
| True, coverage union | 22,089 |
| **Overstatement** | **+13.14%** |

The 2025 rate is prior-year paid claims over prior-year member-months, trended 7.2% and
loaded 2.0% for margin. Over the inflated denominator that is **$456.82 PMPM**. Over the
correct one it is **$516.86** — the rate was set **11.62% below** what the client's own
experience supported, and the plan therefore collected **$1,015,333 less** than adequate
across the scored window.

**The isolation is the point.** Every other client priced on experience sits within
**0.050%** of its repriced rate. A denominator error spread evenly across a book is a scaling
factor nobody has to find. One that lands on a single client, in the year after an
acquisition, is the kind that decides a renewal.

And note what the variance report says on its own: Kellerman comes in **$1,090,128 under
budget** for the scored window. The client looks like it had a good year. It had a good year
against a budget that was never adequate, and the page has to say both.

### 3.2 An administration fee billed on lives instead of contracts

**$7,295,841 in CY2024 alone, a factor of 2.223×.**

Plan administration is priced **PEPM** — per employee per month. Network access, care
management and both stop-loss premiums are priced **PMPM** — per member per month. One fee
schedule, two denominators, and in this book the average contract covers **2.224 lives**.

| CY2024 administration fee | |
|---|---|
| On contract-months, as the contract says | $5,967,404 |
| On member-months | $13,263,245 |
| **Overstatement** | **$7,295,841 (2.223×)** |

The overstatement factor and the lives-per-contract figure are the same number to three
decimal places, because that is precisely what the error is. Across the full 2023–2025 window
it is **$20,720,874**.

This is the least interesting defect intellectually and the most likely to happen. Nothing in
a wide fee table stops it. The layer is built so that it takes effort to get wrong: the fee
schedule ships long with `fee_basis` on every row, the contract denominator is its own table,
and the settlement fact carries the wrong answer beside the right one so the gap is a
subtraction.

### 3.3 A re-driven claims extract that funded claims which do not exist

**$1,142,264 wired across 163 weeks for 1,361 claim lines that were never real.**

Anomaly A9a is a duplicate extract: an adjudication feed re-driven on 14 July 2024, loading
2,840 claim lines twice. In the mart it is a de-duplication step and a footnote — the business
key catches it, `fct_claim_line` is clean, and a data-quality report counts the rows.

In a self-funded book it is a **wire**. The funding system draws weekly against the
adjudication extract *as it landed*, so `aso_funding_request` requested money for the
duplicates and the clients paid it.

| | |
|---|---|
| Drawn, 2023–2025 | $316,080,916 |
| Reconciled against the de-duplicated mart | $314,938,653 |
| **Over-funded** | **$1,142,264 across 163 weeks, 1,361 claim lines** |
| Worst single week | CL-KELL, week ending 2024-07-30: drew $608,056, owed $371,700 |
| Concentration | **99.0% falls in July–October 2024** |
| Weeks under-funded | **0** — the error runs one way only |

The smear is the realistic part and the reason nobody caught it. The duplicates adjudicated
over about four months, so the over-draw spread across 163 wires rather than landing in one
reconcilable lump. Zero weeks under-fund, which is the signature: a timing difference goes
both ways and a duplicate does not.

**Why this matters more than the other two:** a duplicate-row count in a data-quality report
does not make anyone act. Money leaving a client's bank account on a Wednesday does. This is
the clearest case the dataset contains for why a data-quality defect is a finance problem.

### 3.4 And the one that is not about money moving, yet

Two stop-loss failures worth a page of their own, from
[§7](#7-stop-loss-three-ways-a-recovery-goes-missing):

- **19 filings declined for late submission**, $1,481,248 the client absorbs rather than the
  carrier. Invisible in any report that sums what a plan was *entitled* to.
- **4 filings claimed across two people**, $116,468 assembled from the TPA's
  resolved-identity report over an MDM over-match. The filing ties to the resolved identity
  perfectly. The carrier will not pay it, and nothing on the row looks wrong.
- A further **8 filings, $1,219,753**, sit on a durable key that carries two member ids but
  are **correctly scoped** to one of them. Those are not over-claims. Folding them into the
  figure above — which an earlier draft of this plan did — overstates the defect roughly
  tenfold, and the distinction is exactly the kind a settlement workbook has to get right:
  `filing_identity_basis` says how the filing was *assembled*,
  `member_ids_on_durable_key` says what the identity graph *looks like*, and only the first
  one means money was over-claimed.

---

## 4. Why the grain is the client and not the group

The enrollment feed carries `group_id`. The ASO contract is written with a `client_id`. Those
are not the same thing, and one client in this book proves it.

**Kellerman Industries** was acquired in April 2024. Meridian's enrollment system did what
enrollment systems do: it opened a new group id, `NLK-KELL-01`, and moved the members across
from `KELL-4471`. One client, one contract, one stop-loss policy, two group ids.

A book rolled up by `group_id` therefore reports Kellerman as **two clients**, and gets three
things wrong for both of them:

1. **The fee.** The administration fee is priced on a size tier. Split in two, neither half
   qualifies for the tier the contract was written at.
2. **The denominator.** Spans exist under both ids for part of 2024, so the halves do not
   simply add up — [§6](#6-the-renewal-priced-over-a-double-counted-denominator).
3. **The stop-loss accumulation.** The specific deductible accumulates against a *member*
   under a *policy*. A member whose claims sit half under each group id crosses neither
   half's deductible and the filing never happens.

`dim_employer_group` therefore carries both keys on every row, so the app can join either way
without re-deriving the mapping, and the data model's published dimension keys on
`client_id`. The group id stays available because enrollment reconciliation genuinely needs
it — it is just never the aggregation key.

**The rule for the workbook:** no measure aggregates on `group_id`. There is one exception,
an enrollment reconciliation page whose entire purpose is to show the two ids side by side
during the acquisition window.

---

## 5. Two denominators, and neither is optional

An ASO fee schedule uses two denominators and the difference between them is a factor of
about 2.2.

- **PMPM — per member per month.** Lives. Network access, care management and both stop-loss
  premiums are consumed by every covered life, so they are priced this way.
- **PEPM — per employee per month.** Contracts. Plan administration is priced per *employee*,
  because administering a family is not 2.2 times the work of administering an individual.

In this book the average contract covers **2.224 lives**. So an administration fee joined to
member-months reads **2.223× its true size** — measured, not assumed, and the two figures are
the same number twice because that is exactly what the error is.

The layer is built to make that hard to get wrong and easy to prove:

| Guard | How |
|---|---|
| `aso_fee_schedule` ships **long**, one row per fee component | `fee_basis` travels on the row. A wide table with `admin_fee_pepm` beside `network_fee_pmpm` invites one join to member-months and one wrong answer |
| `fct_aso_contract_month` supplies the contract denominator | Subscriber-months by coverage tier, credited only where the **subscriber** was covered |
| `fct_aso_settlement_month` ships the error as a column | `fee_admin_amount_on_member_months` sits beside `fee_admin_amount`, so the gap is a subtraction rather than an argument |

The contract denominator has its own trap, and it is the reason it is a table rather than a
column. A contract-month is credited only where the **subscriber** was covered that month.
A dependent enrolled in a month the subscriber was not is a data problem, not a contract, and
counting it inflates every per-employee fee in the book. `ASO-04` asserts contract-months
never exceed member-months, which is the weakest form of that check and still catches the
common way of getting it wrong.

### Coverage tier, and why it is recoverable at all

`person_code` is the key: `01` is the subscriber, `02` the spouse, `03` and up the children.

| Composition in the month | Tier |
|---|---|
| `01` alone | `EE` |
| `01` + `02` | `EE_SPOUSE` |
| `01` + `03`… | `EE_CHILD` |
| `01` + `02` + `03`… | `FAMILY` |

`aso_budget_rate` prices each tier off an employee-only rate and a tier factor
(1.00 / 2.10 / 1.85 / 2.95). The employee-only rate is **solved**, not chosen, so that the
tiered rates billed against the projected contract mix raise exactly the expected claims the
contract states:

```
  Σ over tiers   factor(t) × contract_months(t) × base   =   expected_claims_pmpm × member_months
```

which is how rate tiering actually works, and which makes the rate card reconcile to the
contract by construction rather than by coincidence. Where the enrollment mix drifts away
from the projection the rates go quietly inadequate — a real and usually unnoticed source of
ASO deficit, and one the app can now show.

---

## 6. The renewal priced over a double-counted denominator

The mechanism in full, because this is the finding and it has to survive being challenged.

**Step 1 — the acquisition creates a duplicate.** Kellerman is acquired 1 April 2024.
Enrollment opens `NLK-KELL-01` and migrates the members. For 23% of Kellerman's members the
`KELL-4471` span is **never terminated**, so it runs on in parallel to the end of their
coverage. Both spans are live, in the same feed, under the same subscriber id.

**Step 2 — the correct denominator is immune.** `fct_member_month` merges each member's spans
into contiguous islands before intersecting them with calendar months, so a member covered
twice in a month contributes one member-month. This is why `fct_member_month` is the only
sanctioned PMPM denominator in the mart, and it has been since before this layer existed.

**Step 3 — the rate-setting analyst does not use it.** They use the enrollment extract,
because that is what underwriting is given, and they sum spans. CY2024 reads 24,992
member-months against a true 22,089 — **13.14% too many.**

**Step 4 — the rate is a ratio, so it inherits the error inverted.** Prior-year paid claims
over an inflated denominator produces a PMPM that is too *low*:

```
  rate as set   = paid ÷ 24,992 × 1.072 × 1.02  =  $456.82 PMPM
  rate repriced = paid ÷ 22,089 × 1.072 × 1.02  =  $516.86 PMPM
                                                   ─────────
                                          11.62% below truth
```

**Step 5 — the client under-collects for twelve months.** Across the scored window
(202501–202509, 16,911 member-months) that is **$1,015,333** of budget never collected.

**Step 6 — and the variance report absolves it.** Kellerman's actual claims come in at
$392.36 PMPM, comfortably under the $456.82 it budgeted. The variance report shows a
**$1,090,128 favourable** position. Nobody asks a question about a client that is under
budget.

### Why the layer ships both numbers rather than just the right one

`aso_client_contract` carries `expected_claims_pmpm` — the rate **as it was set**, over the
denominator the analyst actually had — beside
`expected_claims_pmpm_on_true_denominator`, the same arithmetic over the coverage union.

That is deliberate and it is the difference between a workbook that asserts and one that
proves. A layer that shipped only the correct figure could *say* the rate was mispriced. One
that ships both turns it into a subtraction, on one row, that a client's broker can check.

`fct_aso_settlement_month` does the same at monthly grain: `member_months`,
`naive_member_months`, and `member_month_overstatement` as the difference.

---

## 7. Stop-loss: three ways a recovery goes missing

Specific stop-loss (ISL) reimburses the plan for one member's claims above a deductible.
Aggregate stop-loss (ASL) responds when the plan's *total* claims exceed an attachment point,
here 125% of expected claims — so the client carries a 25% corridor on its own first.

The specific side is where the money is, and where three separate things go wrong. Each is
modeled, each is realistic, and none of them shows up in a report that sums what the plan was
*entitled* to.

### 7.1 The policy year is not the benefit year

Coverage spans break at **calendar** year boundaries, because plan design is priced by
calendar benefit year. But the stop-loss policy year starts in the client's **renewal**
month, and two of nine clients renew off-cycle:

| Client | Renewal month | Policy year |
|---|---|---|
| Northlake Public Schools | July | 1 Jul – 30 Jun |
| City of Northlake | October | 1 Oct – 30 Sep |
| The other seven | January | calendar |

The deductible accumulates over *that* window. A member-level recovery aggregated by
calendar year is therefore right for seven clients and wrong for two — which is the hardest
shape of error to notice, because it reconciles almost everywhere.

`fct_aso_stop_loss_claimant` is at **policy-year** grain and carries `policy_year_label`
(`2024-07-01..2025-06-30`) as well as `policy_year`. The label exists so the workbook cannot
quietly display "2024" next to a number that does not mean 2024.

### 7.2 The contract basis decides whether runout is covered

`isl_contract_basis` is either `PAID_12_12` or `PAID_12_15`.

- **12/12** covers claims incurred *and paid* inside the twelve policy months.
- **12/15** allows three further months of paid runout.

A 12/12 client loses cover on a December admission that adjudicates in February. Paid lag in
this dataset is lognormal around a 23-day median, so that is not a corner case — it is most of
a December inpatient stay. Four of the nine clients are on 12/12, which is the cheaper
election and the one a CFO takes when the broker presents both.

The filing table applies this literally: claims are matched into the policy year on **service**
date and then tested against the contract's paid window. `covered_paid_amount` is what counts
toward the deductible; `policy_year_paid_amount` is everything incurred in the year. Where
they differ, the gap is uncovered by contract rather than by accident, and both columns ship
so an analyst can see which.

### 7.3 A laser is a named member, not a big number

Two clients carry a **lasered** member: a known high-cost case carved out at 2.5× the ordinary
deductible as the price of the carrier renewing at all.

The laser is applied to the member named on `aso_stop_loss_policy.lasered_member_id`, selected
from **2023** experience and applied from the 2024 renewal forward — because that is the
sequence. A carrier names a member at the renewal that follows the year it saw. Selecting the
largest claimant *per year* would make the exclusion move around, which is not a thing that
happens and would make the whole table read as noise.

Consequence worth putting on the page: a lasered member who clears the ordinary deductible but
not the carve-out generates **no filing at all**. The claim sits in the client's own costs with
no recovery row anywhere to explain it. That is exactly what the carrier sold, and it is
invisible unless the page joins filings to the policy rather than only listing filings.

### 7.4 And the one that is a data defect

Some filings were assembled from the TPA's **resolved-identity** large-claimant report, which
sums every member id behind one master person id. Where the master data management run
**over-matched** — twins, a Jr/Sr pair on the same subscriber — that is two genuinely
different people on one stop-loss filing.

This is the over-match defect the dataset has always carried, arriving somewhere it costs
money. And it is nastier here than in a cost distribution, because the filing **ties to the
resolved identity perfectly**. Nothing about the row looks wrong.

Two columns are needed to find it, and they are not the same test:

| Column | Says | Means |
|---|---|---|
| `filing_identity_basis` | how the filing was **assembled** | `MASTER_PERSON_ID` = the amount sums every member id behind one master person |
| `member_ids_on_durable_key` | what the identity graph **looks like** | `> 1` = the MDM run collapsed two member ids onto this durable key |

**Only the first one means money was over-claimed.** A filing on `MEMBER_ID` basis whose
durable key happens to carry two ids is correctly scoped — the member crossed the deductible
on their own, and their identity is separately entangled. It belongs in a review queue, not
in an over-claim total. The measured split is 4 filings against 8, and $116,468 against
$1,219,753, so conflating them is a tenfold error in the direction of alarm.

`fct_aso_stop_loss_claimant` ships the count rather than a flag because a count is what the
data supports; a flag saying "this is wrong" would be the answer key leaking into the mart.

---

## 8. Runout, and why the scored window stops at September

The same discipline the provider incentive plan applies, for the same reason and with sharper
consequences.

`fct_claims_lag_triangle` derives completion factors by chain ladder from the paid dates
actually present, rather than trusting a planted constant. December 2025 is about 27%
complete. A client shown a favourable December will ask why it reversed in March, and on a
self-funded plan that reversal is a funding call, not a footnote.

So: **CY2024 is complete and scores. CY2025 scores through September.** October through
December 2025 display, with the completion factor visible, and never enter a variance.

`fct_aso_settlement_month` carries `completion_factor_derived`, `claims_runout_complete_flag`,
`incurred_estimate_amount` and `ibnr_estimate_amount` on every row, so the incurred view is a
column rather than a workbook formula. A useful confirmation that the wiring is right: IBNR
for CY2024 computes to **exactly $0.00**, because every month of 2024 is fully developed.

---

## 9. What the dataset gained

A sixth source system and nine mart tables. The source system earns its place the way the
other five do: it is the only one that knows what the plan sponsor *pays* to have its plan
run, what it gets back when a member blows through a deductible, and whether last Wednesday's
wire cleared. Claims know the medical dollars. Enrollment knows the denominator. Neither of
them knows the fee schedule.

### `Source Data/raw_aso` — Meridian administrative services

| Table | Grain | What only it knows |
|---|---|---|
| `aso_client_contract` | client × contract year | The deal, and the rate *as it was set* |
| `aso_fee_schedule` | client × contract year × fee component | The price, and the basis it is priced on |
| `aso_stop_loss_policy` | client × policy year | The risk transfer, with its own year boundaries |
| `aso_budget_rate` | client × contract year × coverage tier | The rate card |
| `aso_funding_request` | client × funding week | The cash |
| `aso_stop_loss_filing` | client × member × policy year | The recoveries |

### `Mart/` — the serving layer

| Table | Grain |
|---|---|
| `dim_employer_group` | one employer group, carrying `client_id` as well as `group_id` |
| `aso_client_contract`, `aso_fee_schedule`, `aso_stop_loss_policy`, `aso_budget_rate` | conformed and typed, pass-through |
| `fct_aso_contract_month` | client × month × coverage tier — the PEPM denominator |
| `fct_aso_settlement_month` | client × month — **the table the app sits on** |
| `fct_aso_stop_loss_claimant` | one filing, with the durable key on it |
| `fct_aso_funding_week` | client × funding week, request beside reconciliation |

### Ordering, which is load-bearing

`aso.py` runs **last in the generator, after the anomaly stage.** That is not tidiness. The
funding system draws against the adjudication extract *as it arrived*, so the week whose
extract was re-driven funds the duplicates. Building weekly funding from a clean claim feed
would silently repair the defect and remove the only consequence of it that anybody outside
the data team ever feels.

`build_aso_layer` runs after `build_contract_layer` in the mart, because it consumes the
derived completion factor that layer hangs on `dim_date`.

---

## 10. Data model: `Meridian ASO`

A second Sigma data model, alongside `Northlake VBC`. Not a shared one: the two answer to
different owners, and an ASO client's finance team must never be one filter away from another
client's claims.

### Sources consumed

| Table | Role |
|---|---|
| `fct_aso_settlement_month` | The spine. Client × month, every measure's numerator and denominator |
| `fct_aso_contract_month` | Contract-months by tier — the PEPM denominator and the tier mix |
| `dim_employer_group` | Client and group, sector, size tier, broker, renewal month |
| `aso_client_contract` | The rate as set, and the rate repriced |
| `aso_fee_schedule` | Fee components and their bases |
| `aso_stop_loss_policy` | Deductible, coinsurance, contract basis, attachment, laser |
| `aso_budget_rate` | Tier rate card |
| `fct_aso_stop_loss_claimant` | Filings, with `member_ids_on_durable_key` |
| `fct_aso_funding_week` | Weekly draw against weekly reconciliation |
| `dim_date` | Completion factor and the runout-complete flag |
| `fct_claim_line` + `dim_diagnosis` / `dim_facility` / `dim_service_line` | Drill-through only, never an aggregation path |

### Hidden build steps

Hidden because nobody should be able to filter them away:

1. **Client-grain rollup.** Group ids collapse to `client_id` before anything aggregates.
2. **ASO-only restriction.** Fully-insured clients are excluded at the source, not by a
   default filter somebody can clear.
3. **Scored-window flag.** `is_scored = claims_runout_complete_flag AND year_month <= 202509`.
4. **Rate reprice.** `expected_claims_pmpm_on_true_denominator` joined through so the
   mispricing is a column, not an analysis.

### Published

`ASO Client Month` (the spine), `ASO Contract Month`, `ASO Client`, `ASO Stop Loss`,
`ASO Funding`. Five published elements, each with a one-line description naming its
denominator, because the denominator is the thing this book gets wrong.

---

## 11. Measures, build-ready

Written against the published elements. Every fee measure names its denominator in the
measure name, so a PEPM figure cannot be mistaken for a PMPM one on a chart axis.

### Denominators

| Measure | Formula |
|---|---|
| `Member Months` | `Sum([Member Months])` |
| `Contract Months` | `Sum([Subscriber Months])` |
| `Lives Per Contract` | `[Member Months] / NullIf([Contract Months], 0)` |
| `Member Months (Enrollment Feed)` | `Sum([Naive Member Months])` — the naive span-sum, for the reconciliation page only |
| `Denominator Overstatement %` | `100 * ([Member Months (Enrollment Feed)] / NullIf([Member Months], 0) - 1)` |

### Cost

| Measure | Formula |
|---|---|
| `Paid Claims` | `Sum([Paid Claims Amount])` |
| `Paid PMPM` | `[Paid Claims] / NullIf([Member Months], 0)` |
| `Allowed` | `Sum([Allowed Amount])` |
| `Network Savings` | `Sum([Network Savings Amount])` |
| `Network Discount %` | `100 * (1 - [Allowed] / NullIf(Sum([Billed Amount]), 0))` |
| `Member Liability` | `Sum([Member Liability Amount])` |
| `Incurred Estimate` | `Sum([Incurred Estimate Amount])` |
| `IBNR` | `Sum([Ibnr Estimate Amount])` |

### Fees — each on its own denominator

| Measure | Formula |
|---|---|
| `Admin Fee` | `Sum([Fee Admin Amount])` |
| `Admin Fee PEPM` | `[Admin Fee] / NullIf([Contract Months], 0)` |
| `Total Fees` | `Sum([Total Fee Amount])` |
| `Total Fees PEPM` | `[Total Fees] / NullIf([Contract Months], 0)` |
| `Admin Load %` | `100 * [Total Fees] / NullIf([Paid Claims], 0)` |
| `Admin Fee (Wrong Denominator)` | `Sum([Fee Admin Amount On Member Months])` — reconciliation page only |
| `Fee Overstatement` | `[Admin Fee (Wrong Denominator)] - [Admin Fee]` |

### Stop-loss

| Measure | Formula |
|---|---|
| `ISL Entitled` | `Sum([Reimbursement Entitled Amount])` |
| `ISL Received` | `Sum([Reimbursement Received Amount])` |
| `ISL Shortfall` | `[ISL Entitled] - [ISL Received]` |
| `Filings On Collapsed Identity` | `CountIf([Member Ids On Durable Key] > 1)` |
| `Late Filing Loss` | `SumIf([Reimbursement Entitled Amount], [Filing Status] = "DENIED_LATE_FILING")` |

### Budget and settlement

| Measure | Formula |
|---|---|
| `Budget` | `Sum([Budget Amount])` from `ASO Contract Month` |
| `Expected Claims` | `Sum([Expected Claims Amount])` |
| `Expected Claims (Repriced)` | `Sum([Expected Claims Amount Repriced])` |
| `Claims Variance` | `[Paid Claims] - [Expected Claims]` |
| `Budget Shortfall From Denominator` | `[Expected Claims (Repriced)] - [Expected Claims]` |
| `Net Plan Cost` | `Sum([Net Plan Cost Amount])` |
| `Net Plan Cost PMPM` | `[Net Plan Cost] / NullIf([Member Months], 0)` |

### Funding

| Measure | Formula |
|---|---|
| `Drawn` | `Sum([Claims Funded Amount])` |
| `Reconciled` | `Sum([Reconciled Paid Amount])` |
| `Over-Funded` | `Sum([Overfunded Amount])` |
| `Over-Funded Lines` | `Sum([Overfunded Claim Lines])` |

---

## 12. Workbook pages

Six pages. The book view first, because the audience is the TPA and the cross-client
comparison is where the findings are.

### Page 1 — Book of business

The landing page. One row per client, sorted by net plan cost.

- **Trust header** (see below), pinned top.
- KPI row: `Net Plan Cost`, `Paid PMPM`, `Total Fees PEPM`, `Admin Load %`, `ISL Received`,
  `Member Months` — each with the scored window stated in the subtitle, not the tooltip.
- Client table: lives, contracts, `Lives Per Contract`, paid PMPM, fee PEPM, admin load %,
  net PMPM, claims variance %, and a **rate adequacy** column.
- Scatter: paid PMPM (x) against claims variance % (y), bubble sized by member-months. A
  client that is expensive *and* over budget is a different conversation from one that is
  expensive and priced for it.

The rate adequacy column is the one that earns the page. It is the only place in the book
where Kellerman separates from its peers.

### Page 2 — Client detail

Parameterised on one client. Everything a plan sponsor's finance team asks.

- Cost waterfall: billed → network savings → allowed → member liability → COB → paid claims →
  ISL received → fees → net plan cost.
- Paid PMPM by month against `Expected Claims` PMPM, with the unscored months greyed and the
  completion factor on a secondary axis.
- Enrollment: member-months and contract-months by month, tier mix as a stacked area.
- Fee schedule table, straight from `aso_fee_schedule`, with `fee_basis` as a visible column.
- Stop-loss summary: deductible, coinsurance, contract basis, attachment point, and whether a
  laser applies.

### Page 3 — Rate adequacy and renewal

The finding page.

- For each client, `Expected Claims PMPM` as set against `Expected Claims (Repriced)`, as a
  dumbbell chart. Eight clients are a dot. One is a line.
- `Denominator Overstatement %` by client and month, which is where the 13.1% shows up and
  where it is obviously confined to one client from April 2024.
- `Budget Shortfall From Denominator`, in dollars, for the scored window.
- The renewal recommendation table: current rate, trended actual, and the rate the
  reconciliation supports.

### Page 4 — Stop-loss

- Claimant table: member, policy year *label*, covered paid, effective deductible, entitled,
  received, shortfall, filing status, `member_ids_on_durable_key`.
- Waterfall: entitled → late-filing denials → laser exclusions → received.
- Distribution of member-year paid claims against each client's deductible, so the
  near-misses are visible. A client whose claimants cluster just under the deductible is
  buying the wrong deductible.
- Policy terms table, including the two off-cycle policy years, labelled as date ranges.

### Page 5 — Funding and cash

- Weekly `Drawn` against `Reconciled`, by client, as a line pair.
- `Over-Funded` by week as bars. Jul–Oct 2024 is a wall.
- Funding status counts: funded, funded late, short funded.
- Table of the worst weeks, with `Over-Funded Lines` beside the dollars, because the line
  count is what makes it a data problem rather than a timing difference.

### Page 6 — Enrollment reconciliation

The only page permitted to aggregate on `group_id`, and it says so in its subtitle.

- Member-months from `fct_member_month` against the enrollment feed's span-sum, by group and
  month.
- The two Kellerman group ids side by side through the acquisition window.
- Overlap reasons from `fct_eligibility_span.overlap_reason`, counted.

### The trust header

Four figures, on every page, above the fold:

```
  Scored through 2025-09  ·  claims 100% complete  ·  9 clients, 23,969 avg lives
  Denominator: fct_member_month (union, not span-sum)  ·  Fees: PEPM on contracts, PMPM on lives
```

The second line exists because both halves of it are things this app gets right and most
ASO reporting gets wrong. Stating them is cheap and it pre-empts the two questions a
knowledgeable audience asks first.

---

## 13. Input tables

Three, all client-scoped.

| Input table | Grain | Purpose |
|---|---|---|
| `renewal_decision` | client × contract year | Proposed rate, effective date, decision, decided by, rationale. The rate adequacy page writes here |
| `filing_review` | filing key | Reviewer, review status, note. Where a collapsed-identity filing gets flagged and withdrawn before the carrier denies it |
| `funding_exception` | client × funding week | Acknowledged, credited, or disputed, with a note. The over-funded weeks need a disposition |

Each carries `decided_by` and `decided_at`, defaulted from the Sigma user and the current
timestamp. None of them recomputes anything; they record what a human decided in front of the
number, which is the only defensible use of an input table in a settlement workbook.

---

## 14. AI layer

### 14.1 Ask a Question

Scoped to `ASO Client Month` and `ASO Contract Month` only. Not to the stop-loss or funding
elements: both carry member-level detail and a natural-language surface over them is a
disclosure risk that buys very little.

Suggested questions seeded to steer away from the traps rather than into them:

- "Net plan cost PMPM by client for 2024"
- "Which clients ran over expected claims in the scored window"
- "Admin fee PEPM by size tier"
- "Member-month overstatement by client"

### 14.2 The agent: `Renewal Defence`

The same shape as `Payout Defence` in the provider incentive plan, and for the same reason: a
client presented with a rate increase will push back, and the defensible answer is a chain of
figures rather than a confident tone.

**What it gets:** the five published elements, `Validation/aso_book.py` output as a reference
table, and the three input tables.

**What it is for:** answering "why is my renewal going up" and "why did my variance move" with
the decomposition attached — trend, enrollment mix, large claimants, stop-loss recovery, and
rate adequacy — in that order, with dollars on each.

**System prompt, the load-bearing parts:**

- Never quote a figure from an unscored month. If asked about Q4 2025, say it is
  *n*% complete and give the scored window instead.
- Always state the denominator. A PEPM figure and a PMPM figure differ by about 2.2× in this
  book and the difference is not a rounding question.
- When a variance is favourable against a rate, check `Budget Shortfall From Denominator`
  before agreeing the client had a good year.
- Never aggregate on `group_id`. If a question names a group id, resolve it to the client and
  say so.
- For a stop-loss question, check `filing_identity_basis` before quoting an entitlement, and
  do not treat `member_ids_on_durable_key > 1` as an over-claim on its own — a filing on
  `MEMBER_ID` basis is correctly scoped even when the durable key is entangled.
- Decline member-level questions that are not about a filing already under review.

**Acceptance tests.** The agent must independently produce: the $1,015,333 Kellerman figure
with its cause; the 2.223× fee factor with both denominators named; the 163 over-funded
weeks attributed to the July 2024 extract; and a refusal to score December 2025.

---

## 15. Explicit non-goals

Named so the omissions read as decisions rather than gaps.

**Pharmacy, and therefore no PBM administration fee.** Real ASO reporting runs roughly a
quarter pharmacy and a real fee schedule carries a PBM line. Inventing one would be fee
revenue with no claims behind it, and nothing in the mart would reconcile against it. The line
is absent and the absence is stated. This is the single largest fidelity gap in the layer and
the one to close first if the app is ever built for real.

**Plan design does not drive adjudication.** Member liability follows a benefit-year reset
curve rather than an accumulator against a real deductible, so each self-funded sponsor offers
one plan design. A second design would be a label with no economics behind it, and there is
therefore no plan-design slice on any page. Deductible and out-of-pocket maximum are carried
on `dim_coverage_plan` as descriptive attributes only.

**No accumulator fact.** Deductible and out-of-pocket accrual per member is derivable from
claim lines but is not modeled as a fact, for the same reason: without adjudication responding
to it, an accumulator would be a running total that changes nothing.

**Aggregate stop-loss is terms only.** `aso_stop_loss_policy` carries the attachment point,
the corridor and monthly accommodation, and the app can show how close a client runs to
attachment. No ASL settlement is computed. Aggregate cover on a book this size responds
rarely, and computing a settlement nobody triggers would be arithmetic theatre.

**No COBRA population modeling beyond the flat fee.** COBRA spans exist in
`fct_eligibility_span` and the admin fee is charged, but COBRA members are not separately
rated or reported.

**No terminal liability or runout-administration settlement.** A client that terminates owes
runout administration. No client terminates in this window.

**One TPA, one network.** No comparison of Meridian's discount against a rival network, which
is a real ASO sales conversation and needs a second network's contracted rates to be anything
other than invented.

---

## 16. Verification

Every figure in [§3](#3-the-findings-the-app-exists-to-surface) and
[§19](#19-reference-figures) reproduces from:

```sh
python Validation/aso_book.py            # every figure this plan quotes
python Validation/aso_book.py --json     # the same, machine-readable
```

The layer's structural claims are asserted rather than described, in
`Validation/expectations.yml` under `aso:` and checked by `check_aso` in
`Validation/validate.py`:

| Check | Asserts | Severity |
|---|---|---|
| `ASO-01` | The self-funded book is nine clients | ERROR |
| `ASO-02` | No member-month crosses the funding boundary | ERROR |
| `ASO-03` | No household spans two employers' plans | ERROR |
| `ASO-04` | Contract-months never exceed member-months | ERROR |
| `ASO-05` | Admin fee on member-months overstates by the family factor | EXPECTED, banded |
| `ASO-06` | Fee components tie to the fee total | ERROR |
| `ASO-07` | Net plan cost = paid − recovered + fees | ERROR |
| `ASO-08` | Monthly ISL allocation ties to the filings | ERROR |
| `ASO-09` | The mispriced client's rate sits below truth | EXPECTED, banded |
| `ASO-10` | Every other client's rate is clean | ERROR |
| `ASO-11` | The stop-loss layer has claimants in it | ERROR |
| `ASO-12` | Late filings are declined and cost the client | EXPECTED |
| `ASO-13` | Some filings are claimed across two people | EXPECTED |
| `ASO-13b` | Every over-claimed filing rolled up more than one member id | ERROR |
| `ASO-13c` | Entangled durable keys are reported separately, not as over-claims | INFO |
| `ASO-14` | The re-driven extract over-funded a client | EXPECTED |
| `ASO-15` | The over-funding is material | EXPECTED |

The split is the argument: the structural facts are ERRORs because a client is either
self-funded or it is not, and the planted defects assert as EXPECTED **with a magnitude**,
because a planted defect nobody can find is indistinguishable from one that is not there.

The full chain, which any change to the generators needs in order:

```sh
python Generators/build.py --scale demo
python Build/build_mart.py
python Build/build_docs.py
python Build/verify_keys.py
python Validation/validate.py
python Validation/aso_book.py
python Generators/build.py --scale demo --verify
```

---

## 17. What this build changed in the dataset

### Added — the ASO layer

A sixth source system, `raw_aso`, with six tables, and nine mart tables. Inventory in
[§9](#9-what-the-dataset-gained). The mart goes from 34 tables to 41.

### Fixed — funding type was a property of the member

Before this pass, `dim_coverage_plan` carried one `ASO` plan code and **17 of 18 employer
groups had members enrolled on both the fully-insured and the self-funded plan at the same
time.** An employer is self-funded or it is not; the plan belongs to the sponsor, not the
member. "Show me my self-funded book" returned a slice of every client instead of a set of
clients, which is not an ASO book at all.

Funding is now assigned at the **client** level, and plan election is constrained by it. Nine
of seventeen clients are self-funded, carrying about 61% of the commercial book — close to the
national share of covered workers in self-funded plans, and the figure follows from the
selection rule rather than being dialled in: self-funding correlates with size and with
sector, and public employers and health systems self-fund at almost any size.

### Fixed — employer group and plan election were drawn per member

This one was found by building the ASO layer on top of it, and it is the more interesting of
the two.

`group_id` and the plan election were drawn **once per member**. A spouse and a child on the
same subscriber contract could therefore sit in two different employers' plans, on two
different plan designs. That cannot happen: an employer group enrolls an *employee* and the
family comes with the contract.

It was invisible for as long as every measure in the mart was at member grain. It surfaced the
moment something needed to count **contracts**. The diagnostic that exposed it: of the 33
over-matched identity pairs in the crosswalk — twins and Jr/Sr pairs, all of them by
construction in the same household — **all 33 shared a subscriber id and only 2 shared a
group id.**

Both draws are now per household. Two consequences worth knowing:

- The enrollment weight now governs the share of **contracts** rather than the share of
  lives, which is how a book of business is actually sized. Member counts still land in
  proportion, because family size is drawn independently of the group.
- Two kinds of household still legitimately straddle two group ids, and neither is a defect:
  an acquired client holds two ids either side of its acquisition, and a member who turns 65
  leaves the employer plan for individual Medicare Advantage while their family stays.
  `ASO-03` therefore asserts at **client** grain with individual enrollment excluded.

This is the third defect of this shape the dataset has produced — unnormalized risk scores,
a runout that contradicted its own paid dates, and now a household that was not a household.
All three were invisible until something *derived* a number that depended on them. The lesson
holds: derive and assert agreement rather than planting a constant.

### Retuned — two population multipliers

Moving group and plan election to household grain changed which members hold coverage in which
months. The clinical generator reads member-months as its input, so utilization moved with it,
and two Medicare bands went out:

| Constant | Was | Now | Why |
|---|---|---|---|
| `ELDERLY_ED_MULTIPLIER` | 1.95 | 1.70 | MA ED per 1000 came out at 554.7 against a 400–520 band |
| `ELDERLY_ADMIT_MULTIPLIER` | 1.26 | 1.17 | MA admissions per 1000 came out at 264.1 against a 200–260 band |

Stated plainly because it is dataset tuning and the alternative was widening the bands to
accommodate the perturbation, which is the wrong direction. Both constants exist for exactly
this purpose — the comment above them already said they are the dials that "lift the 65+
cohort onto its own benchmark band" — and both move the 65+ cohort only, so the commercial
figures barely notice.

### Fixed — a runout assertion that contradicted its own design

`check_runout` asserted a flat `ratio < 0.90` for each of the last three service months.
`RUNOUT_COMPLETENESS` puts October 2025 at **94%** complete, so a correctly built October
reads about 94% of its de-trended prior-year month and fails a 90% threshold *by
construction*. It only ever passed on that month's own volume noise, and it stopped passing
the moment a population constant moved. The same flat threshold was meanwhile trivially
satisfied by December at 27%.

The assertion is now against the **designed completeness** for each month, within the 10pp
tolerance the expectations file already stated. That is consistent, and strictly stronger: it
catches a curve that has drifted in either direction. Observed against designed:

| Service month | Designed | Observed |
|---|---|---|
| 2025-10 | 94% | 93.6% |
| 2025-11 | 81% | 76.9% |
| 2025-12 | 27% | 33.4% |

This is the fourth defect of the "invisible until something derived it" shape, and the only
one of the four that was in the *validation suite* rather than the data.

### Unaffected

Every anomaly A1 through A12 still asserts at its stated size. The provider incentive
program's headline is untouched in kind, though its absolute figures move with any rebuild;
`Validation/scorecard.py` reproduces them.

---

## 18. Open items before any build

1. **Confirm the audience.** This plan assumes the TPA. If the first real viewer is a single
   employer's HR and finance team, page 1 becomes page 2 and the cross-client scatter comes
   out entirely — a client must never see a peer named.
2. **Row-level security is not designed here.** A client-scoped deployment needs it before
   anything is shared, and `client_id` is the obvious key, but the user attribute mapping is
   a deployment decision rather than a modeling one.
3. **Decide whether the PBM gap is acceptable** for the intended demonstration. A quarter of
   real ASO spend is missing and a knowledgeable audience will ask within ten minutes.
   [§15](#15-explicit-non-goals) is the answer; whether it is a *good enough* answer depends
   on the room.
4. **The network discount figure is inherited and high.** 65.99% off billed for CY2024. It
   follows from the claims generator's billed-to-allowed ratio, which predates this layer.
   It is defensible for a hospital-weighted book and it is at the top of the plausible range;
   do not make it a headline.
5. **Aggregate stop-loss responds for nobody.** Worth a decision on whether to show
   attachment proximity at all, given nothing crosses it.

## 19. Reference figures

Everything below reproduces from `python Validation/aso_book.py` against the `demo` build,
seed 20260911.

### The book

9 self-funded clients across 10 enrollment groups. 27,646 distinct members over the window;
25,611 covered at some point in CY2024; **23,969 average covered lives** on **10,776 average
contracts**.

### CY2024, complete

| Client | Lives (mm) | Contracts | Lives/contract | Paid claims | Paid PMPM | Fees | Fee PEPM | Load % | Net PMPM | Var % |
|---|---|---|---|---|---|---|---|---|---|---|
| Brightwater Manufacturing | 53,371 | 23,633 | 2.258 | $20,348,473 | $381.27 | $2,175,974 | $92.07 | 10.69 | $405.05 | −7.14 |
| Northlake Public Schools | 43,305 | 19,488 | 2.222 | $16,340,787 | $377.34 | $1,756,737 | $90.14 | 10.75 | $392.46 | −5.72 |
| Fairmont Logistics | 34,663 | 15,210 | 2.279 | $15,371,077 | $443.45 | $1,764,662 | $116.02 | 11.48 | $427.40 | +9.69 |
| City of Northlake | 35,624 | 16,255 | 2.192 | $13,987,120 | $392.64 | $1,809,614 | $111.33 | 12.94 | $430.34 | −5.48 |
| Sableworks Technology | 29,748 | 13,380 | 2.223 | $10,778,002 | $362.32 | $1,530,544 | $114.39 | 14.20 | $385.05 | −10.98 |
| Kellerman Industries | 22,089 | 9,984 | 2.212 | $10,162,708 | $460.08 | $1,417,104 | $141.94 | 13.94 | $426.29 | +4.52 |
| Harbor Trust Financial | 25,880 | 12,029 | 2.151 | $10,027,968 | $387.48 | $1,350,621 | $112.28 | 13.47 | $404.88 | +9.89 |
| Northlake Health Partners | 25,190 | 11,174 | 2.254 | $8,434,326 | $334.83 | $1,289,092 | $115.37 | 15.28 | $363.71 | −11.92 |
| Cornerstone Utilities | 17,763 | 8,158 | 2.177 | $6,768,509 | $381.05 | $1,147,523 | $140.67 | 16.95 | $401.51 | +8.49 |

Fee PEPM rises as size falls, which is the fee curve working: administration is priced on a
size tier and the smaller clients also carry higher stop-loss premium against a lower
deductible. Admin load runs 10.7% to 17.0% of paid claims.

### CY2024 cost waterfall, whole book

| | |
|---|---|
| Billed | $471,160,116 |
| Network savings | $311,360,435 |
| **Allowed** | **$159,799,681** |
| Member liability (deductible, copay, coinsurance) | $46,832,159 |
| Coordination of benefits | $748,551 |
| **Paid claims** | **$112,218,971** |
| Specific stop-loss received | $10,060,049 |
| Administration, network, care management, premium | $14,241,871 |
| **Net plan cost** | **$116,400,792** |
| IBNR | **$0.00** — every month of 2024 is fully developed |

Network discount reads **66.08%** off billed. See
[§18](#18-open-items-before-any-build) item 4: that figure is inherited from the claims
generator and sits at the top of the plausible range. Do not headline it.

### Specific stop-loss, all three policy years

| | |
|---|---|
| Filings | 267 across 9 clients |
| Entitled | $24,968,462 |
| Received | $16,592,373 |
| Shortfall | $8,376,089 |
| Reimbursed / pending / declined | 181 / 67 / 19 |
| Declined for late filing | 19 filings, **$1,481,248** the client absorbs |
| Claimed across two people | 4 filings, **$116,468** assembled from the resolved identity |
| On an entangled durable key | 8 filings, $1,219,753 — correctly scoped, worth reviewing |

Deductibles are $100,000 (small), $150,000 (mid) and $200,000 (large). Five clients are on a
12/15 paid basis and four on 12/12.

### Weekly funding

| | |
|---|---|
| Funding weeks | 1,413 |
| Drawn | $316,080,916 |
| Reconciled | $314,938,653 |
| Over-funded | **$1,142,264** across **163 weeks**, **1,361 claim lines** |
| Concentration | 99.0% in July–October 2024 |
| Under-funded weeks | 0 |

### The mispricing

| | |
|---|---|
| Client | Kellerman Industries (`CL-KELL`), contract year 2025 |
| Prior-year member-months, enrollment feed | 24,992 |
| Prior-year member-months, true | 22,089 (**+13.14%**) |
| Rate as set | $456.82 PMPM |
| Rate on the true denominator | $516.86 PMPM (**11.62% below truth**) |
| Actual, 202501–202509 | $392.36 PMPM on 16,911 member-months |
| Variance as reported | **−$1,090,128** (favourable) |
| Variance against a sound rate | −$2,105,460 |
| **Budget never collected** | **$1,015,333** |
| Worst other client's rate miss | **0.050%** |
