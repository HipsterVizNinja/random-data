# Narrative

The spec of record. Every table and every planted defect earns its place by
serving a specific moment in this story, and the validation suite asserts the
story is actually present in the data.

## The core tension

Northlake Health Partners is financially accountable for a patient panel whose
care it can only see about 60% of, and the invisible 40% is where the money
goes.

The longer version, for someone who runs a health system: you signed two-sided
risk. Your EHR knows every referral you *placed* and nothing about whether it
landed. The payer file knows every dollar spent but arrives 90 days late,
carries no clinical detail, and identifies people by a member ID that does not
tie to your medical record number. Your attribution roster — the thing that
decides whose cost counts against you — gets restated monthly and
retroactively. No single system can tell you where the leakage is, whether it
is real, or whether last quarter's improvement was performance or bookkeeping.

That framing was chosen over two alternatives. **Denial root cause across
revenue cycle** is genuinely multi-source and well funded, but the remittance
file alone answers "what was denied and why-coded", so the multi-source
argument is only about root cause — a weaker wedge, and it is back-office.
**Readmission accountability across a fragmented continuum** has regulatory
teeth, but the interesting version needs an all-payer claims feed, which
strains synthetic plausibility, and it collapses to a handful of measures.

## The people

Four stakeholders. The fourth is the one with the budget.

**Dana Whitfield, VP Network Strategy.** Asks for leakage rate by clinic group
and specialty, monthly, with referring providers ranked. Her source of truth
is the EHR referral worklist because it is the only thing she can pull
herself.

**Marcus Oyelaran, VP Finance and Value-Based Contracts.** Asks whether the
system will earn shared savings this performance year. Trusts the payer
extract and the payer's roster, because those are what the settlement is
computed from. Distrusts anything sourced from the EHR.

**Dr. Priya Raman, CMIO.** Asks which attributed patients have open care gaps,
and wants patients who have never seen her physicians taken off their panels.
Will torpedo any metric that makes her physicians look bad for reasons outside
their control.

**Ken Alvarez, Director of Enterprise Data.** Asks no business question. Asks
which of the three leakage numbers in three different decks is right, and for
something he can certify. He is the buyer, and his problem is the demo's
problem.

The cold open is those first three quoting different numbers, and Ken having
to pick one before a board meeting.

### Where they collide, and what each collision forces into the schema

| Collision | Dana | Marcus | Priya | Schema consequence |
|---|---|---|---|---|
| Who owns this patient? | Referring provider | Billing TIN | Attributed PCP | One provider dimension, role-played four ways |
| Who is in the denominator? | EHR patients with a visit | Attributed member-months | Measure-eligible population | Conformed member dimension plus a member-month fact as the only legal denominator |
| What does "this month" mean? | Service date | Incurred date with runout | Measurement year | Date dimension with service, incurred and paid roles plus a completeness factor |
| What is "orthopedics"? | EHR department | Claim taxonomy | Contract category | Service-line dimension with a deliberately imperfect crosswalk |
| Is this provider in network? | EHR pick-list | Payer file, current state | Does not care | Type-2 network contract by TIN and effective window, joined as of service date |

## The question ladder

Nine questions in ascending order of how many sources they need. The first is
answerable from one system and produces a confident wrong answer.

**Q1, one source (EHR).** *Dana:* how are our clinic groups managing
referrals? North Ridge Orthopedics posts the best closure rate and the lowest
apparent out-of-network rate of twelve groups. The naive answer has to look
like a win, not a puzzle — this is the trap being set.

**Q2, one source (claims).** *Marcus:* total allowed by service category.
First breadcrumb: a small share of claim lines land in an unmapped service
line, and someone will ask what is in there.

**Q3, one source plus reference.** *Ken:* which claims paid to providers we
have no contract with? The payer's participation flag is stored current-state,
so a naive join understates out-of-network against an as-of-service-date join.
Current-state dimensions silently rewrite history.

**Q4, two sources.** *Marcus:* PMPM trend against benchmark. The recent
quarters show an improvement that decomposes into a real component, a claims
runout component, and a roster-churn component. Requires roster restatement
history so both the original and restated views reproduce. This is the
supporting reversal, and it puts Finance's credibility on the line rather than
Network Strategy's.

Three things make the decomposition reproducible rather than assertable. Every
monthly roster version ships, so "what did we believe in September" is a
control and not an archaeology exercise. The restatement runs in both
directions, so the net effect has to be earned against retro-additions rather
than handed over by a one-sided history. And the completion factors are
derived from the paid dates by chain ladder, so the runout component is
measured on the page rather than read off a constant somebody typed.

`vbc_contract_terms` is what turns the answer into money. A minimum savings
rate, a shared-savings percentage and a high-cost truncation threshold are the
difference between "PMPM moved $48" and "the cheque moved", and only the
second one is a finding Marcus acts on. The truncation matters twice: it is
also the honest defense against the retro-termination finding, and the finding
has to survive it to be worth reporting.

**Q5, two sources.** *Priya:* are we closing HbA1c gaps? The EHR and the
claims file disagree, and neither is the superset — some tests were performed
at an external lab that returned no structured result, others have an in-house
result with no separate claim line because it was bundled. Each source is
missing a different group of people, so the union needs a documented rule.

**Q6, three sources.** *Dana:* which referring providers send patients out of
network, and what does it cost? Ranked by volume the answer is high-volume
primary care, which is expected and uninteresting. Ranked by dollars it is
three mid-volume specialists routing to Summit Point Surgery Center, whose
contract terminated 2024-10-01 while the EHR referral pick-list still reads
PAR — fourteen months stale. A governance failure with a price tag, and nobody
made a bad clinical decision.

**Q7, four sources. The aha.** Detailed below.

**Q8, four sources.** *Dana and Marcus together:* if we stand up orthopedics
at North Ridge, what is actually recapturable? Two things could stop you:
geography, where the patient lives closer to the out-of-network site than to
any in-network alternative, and capacity, where the system has no in-network
site that performs the procedure or no block time left to do it in.

Both are tested against real drive times and against the surgical capability
and annual case capacity recorded on `dim_facility`. **In this dataset,
neither binds** — Northlake's in-network block time comfortably exceeds the
leaked case volume, so nearly all of it is winnable.

That is the opposite of what the design expected, and it is left as it is
rather than manufacturing a constraint. The transferable part is the method:
at a larger panel, or for a service line where the system has thin
capability, the same test binds hard, and running it before promising a
recapture number is what separates an analysis from a pitch.

**Q9, five sources. Only the hub answers this.** *Ken:* give me one leakage
number for the board deck and tell me how much to trust it. The answer ships
with its denominator, an as-of date, a completeness treatment, and a footnote
disclosing the unmatched population and how it was handled. Lineage walks from
the certified number back through view, table, source column, and load batch.
This is the thing Ken buys.

## The aha moment

**The naive answer, high confidence and wrong.** North Ridge Orthopedics is
the system's best-performing clinic group on referral management: a 99%
closure rate, a 4% open rate, and an EHR-derived out-of-network referral rate
of roughly 7% against a 17% system average. Best of twelve. The obvious
recommendation is to roll out North Ridge's referral workflow everywhere and
hold the other eleven groups to their standard.

**The joined answer.** North Ridge closes referrals because a PracticeOne
scheduling rule effective 2024-07-01 auto-sets referral status to *Closed —
Complete* at day 30 regardless of whether an appointment or a claim ever
occurred. Only 38% of their "completed" referrals have a confirming event,
against a 72% system average. Their true out-of-network rate is 54%, the worst
of twelve. **The ranking inverts from 1 of 12 to 12 of 12.** The workflow
everyone was about to copy is the thing generating the leakage.

Why the leakage was invisible: North Ridge sends the overwhelming majority of
its out-of-network volume to Summit Point, which still reads PAR in the EHR
directory. On EHR data alone, their leakage is not merely understated — it is
almost entirely absent.

### What makes it discoverable rather than lucky

1. **An onset date.** The apparent metric steps change in July 2024. A monthly
   trend shows it, which is the breadcrumb that makes the find earned.
2. **A two-click path to the fingerprint.** `days_to_closure` is a stored
   column, so the time-to-closure histogram is one drag from the leakage view.
   A spike at a round number is a workflow rule, not clinical behavior.
3. **A smoking gun that exists but is not surfaced.** `closure_actor_type` and
   one row in `pm_referral_workflow_config` confirm the mechanism once
   suspected. No default metric references either.
4. **Two independent confirmations.** The referral produced no completed
   appointment *and* no professional claim. If the only evidence were the
   claims join, the first skeptic blames the match rate and the finding dies.
   Two paths kills that objection, and the dataset is built that way
   deliberately.
5. **A join that punishes carelessness.** The unmatched share of EHR records
   skews more than twice as heavily toward North Ridge patients, whose
   registration workflow does not capture the subscriber ID. A naive inner
   join deletes part of the finding and *understates* the leakage — so the
   careless analyst gets a wrong answer that still looks plausible. That is
   the second lesson hiding inside the first.

## Two cuts, one build

**The technical and executive cut — "the cost of not having a hub."** Opens on
three decks with three numbers. Emphasizes conformed dimensions as an
accountability mechanism; identity resolution with match tiering, scores, and
a stewardship queue; type-2 network status and the as-of join, which is the
most persuasive architecture argument available because it is the one that
cost real money; lineage from certified metric to source column to load batch;
and data-quality results as a release gate rather than a report. Closes on Q9.

The framing discipline that matters: **the villain is the absence of
architecture, never the client's staff.** The auto-close rule was a reasonable
local fix by someone trying to clear a worklist. It had a global cost no local
actor could see. That framing is what makes the story safe to tell in front of
people whose organization has the same rule running right now.

**The practitioner cut — five short pieces, not one long one.** Each is a
technique with a "when to use it" attached.

1. *The completion flag that lies.* Plot time-to-status before trusting any
   status field. When: any metric depending on a workflow state someone else
   configured.
2. *Your inner join deleted the finding.* Test whether join loss is random by
   profiling the unmatched against the matched. When: before reporting any
   cross-source rate.
3. *As-of joins, and why current-state dimensions rewrite history.* When: any
   attribute that can change — network status, plan, employer, price.
4. *The rate that improved because the denominator left.* Cohort-holding
   versus open panel. When: any rate where membership is decided by someone
   else's monthly file.
5. *Runout.* Never trend an incomplete measure to its right edge. When:
   claims, invoices, tickets, anything with an adjudication lag.

**Where the two cuts must diverge.** Vocabulary order: the technical cut names
the pattern first and then shows the failure; the practitioner cut shows the
failure, names the technique, and labels the pattern last, because
front-loading vocabulary loses a hands-on audience in seconds. And the
practitioner cut can say "whoever turned that rule on made your dashboard
lie." The client-facing cut cannot. Same fact, different assignment of blame,
and getting that backwards is the one thing here that damages a relationship.

**What they share:** the dataset, the seed, the load SQL, the question ladder,
the cold open, the persona names, and the generated figures in
`Deliverables/anomaly-manifest.json`.
