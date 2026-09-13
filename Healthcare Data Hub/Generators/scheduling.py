"""Practice management: appointments, authorizations, and workflow configuration.

Two things here matter more than their row counts.

`pm_referral_workflow_config` is one row and it is the villain of the entire
demo: the rule that auto-closes North Ridge referrals at day 30. Nothing in
any default metric references it. It exists, it is documented in the data
dictionary, and it confirms the mechanism the moment someone suspects it.

`pm_appointment` is the SECOND independent confirmation path. If the only
evidence that a "completed" referral produced no care were the claims join,
the first skeptic in the room blames the match rate and the finding dies.
Appointments and claims agreeing kills that objection. Build it that way
deliberately.

Authorization is kept distinct from referral. Conflating the two is a tell.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

import config as C
import org


def build_scheduling(
    run: C.RunConfig, referrals: pd.DataFrame, encounters: pd.DataFrame
) -> dict[str, pd.DataFrame]:
    rng = run.rng("scheduling")
    cfg = _workflow_config()
    appts = _appointments(run, rng, referrals, encounters)
    auths = _authorizations(run, rng, referrals)
    return {
        "pm_referral_workflow_config": cfg,
        "pm_appointment": appts,
        "pm_authorization": auths,
    }


def _workflow_config() -> pd.DataFrame:
    """Site-level referral workflow rules. One row is the whole story."""
    rows = [{
        "workflow_config_key": 1,
        "rule_code": "AUTOCLOSE_30D",
        "rule_name": "Auto-close open referrals at 30 days",
        "site_code": C.AUTOCLOSE_SITE,
        "effective_date": C.AUTOCLOSE_EFFECTIVE.isoformat(),
        "expiration_date": "9999-12-31",
        "rule_parameter_days": C.AUTOCLOSE_DAYS,
        "sets_status_to": "CLOSED_COMPLETE",
        "requires_confirming_event": False,
        "configured_by": "Practice operations, site request",
        "rule_note": (
            "Requested by the site to clear a growing referral worklist. "
            "Closes the referral on elapsed time alone, with no check that an "
            "appointment or claim ever occurred."
        ),
    }]
    # A second, benign rule elsewhere, so the offending row is not the only
    # row in the table and has to actually be found.
    rows.append({
        "workflow_config_key": 2,
        "rule_code": "REMIND_14D",
        "rule_name": "Patient reminder at 14 days if referral still open",
        "site_code": "ALL",
        "effective_date": "2023-03-01",
        "expiration_date": "9999-12-31",
        "rule_parameter_days": 14,
        "sets_status_to": None,
        "requires_confirming_event": False,
        "configured_by": "Enterprise standard",
        "rule_note": "Sends a reminder. Does not change referral status.",
    })
    return pd.DataFrame(rows)


def _appointments(run, rng, ref: pd.DataFrame, enc: pd.DataFrame) -> pd.DataFrame:
    """Scheduled appointments, including the ones that were never kept.

    For a referral where care genuinely happened, a COMPLETED appointment
    exists at the destination. Where it did not, the appointment is either
    absent entirely or present as a no-show or cancellation. That is what
    makes "referral marked complete, no appointment" a detectable state.
    """
    rows = []
    if not ref.empty:
        occurred = ref["_truth_care_occurred"].to_numpy()
        placed = pd.to_datetime(ref["placed_date"])
        n = len(ref)
        lag = rng.integers(5, 80, size=n)
        appt_date = (placed + pd.to_timedelta(lag, unit="D")).clip(
            upper=pd.Timestamp(C.SOURCE_END)
        )
        u = rng.random(n)
        # Care happened: almost always a completed appointment.
        # Care did not happen: mostly no appointment at all, sometimes a
        # no-show or a cancellation.
        status = np.where(
            occurred,
            np.where(u < 0.94, "COMPLETED", "ARRIVED"),
            np.where(u < 0.58, None,
                     np.where(u < 0.80, "NO_SHOW",
                              np.where(u < 0.94, "CANCELLED", "SCHEDULED"))),
        )
        keep = status != None  # noqa: E711 - explicit None sentinel
        rows.append(pd.DataFrame({
            "referral_id": ref["referral_id"].to_numpy()[keep],
            "mrn": ref["mrn"].to_numpy()[keep],
            "site_code": ref["destination_site_code"].to_numpy()[keep],
            "appointment_date": appt_date.dt.strftime("%Y-%m-%d").to_numpy()[keep],
            "appointment_status": status[keep],
            "appointment_type": "SPECIALTY_CONSULT",
            "scheduled_by_site_code": ref["referring_site_code"].to_numpy()[keep],
        }))

    # Primary care appointments, unrelated to referrals, so the table is not
    # purely a referral shadow.
    amb = enc[enc.encounter_class == "AMBULATORY"]
    if len(amb):
        sub = amb.sample(frac=0.55, random_state=77)
        rows.append(pd.DataFrame({
            "referral_id": None,
            "mrn": sub["mrn"].to_numpy(),
            "site_code": sub["site_code"].to_numpy(),
            "appointment_date": sub["encounter_date"].to_numpy(),
            "appointment_status": rng.choice(
                ["COMPLETED", "NO_SHOW", "CANCELLED"],
                size=len(sub), p=[0.91, 0.055, 0.035],
            ),
            "appointment_type": "OFFICE_VISIT",
            "scheduled_by_site_code": sub["site_code"].to_numpy(),
        }))

    out = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    if out.empty:
        return out
    out = out.sort_values(["appointment_date", "mrn"]).reset_index(drop=True)
    out.insert(0, "appointment_id", [f"APT{i:09d}" for i in range(1, len(out) + 1)])
    return out


def _authorizations(run, rng, ref: pd.DataFrame) -> pd.DataFrame:
    """Prior authorizations. A DIFFERENT thing from a referral.

    A referral is a clinical routing decision. An authorization is the plan
    agreeing to pay. Treating them as the same object is a fast way to lose a
    healthcare audience, so both exist and they do not line up one-to-one.
    """
    if ref.empty:
        return pd.DataFrame()
    # Only procedural referrals need an authorization.
    need = ref[ref["referral_specialty_code"].isin(["SL01", "SL02", "SL03"])]
    if need.empty:
        return pd.DataFrame()
    n = len(need)
    placed = pd.to_datetime(need["placed_date"])
    req = placed + pd.to_timedelta(rng.integers(1, 14, size=n), unit="D")
    u = rng.random(n)
    status = np.where(u < 0.83, "APPROVED",
             np.where(u < 0.93, "PENDED",
             np.where(u < 0.98, "DENIED", "WITHDRAWN")))
    out = pd.DataFrame({
        "referral_id": need["referral_id"].to_numpy(),
        "mrn": need["mrn"].to_numpy(),
        "requested_date": req.dt.strftime("%Y-%m-%d").to_numpy(),
        "decision_date": (
            req + pd.to_timedelta(rng.integers(1, 21, size=n), unit="D")
        ).dt.strftime("%Y-%m-%d").to_numpy(),
        "authorization_status": status,
        "requested_site_code": need["destination_site_code"].to_numpy(),
        "units_requested": rng.integers(1, 6, size=n),
        "denial_reason": np.where(
            status == "DENIED",
            rng.choice(["Not medically necessary", "Out of network",
                        "Insufficient documentation"], size=n),
            None,
        ),
    })
    out = out.sort_values(["requested_date", "mrn"]).reset_index(drop=True)
    out.insert(0, "authorization_id", [f"AUTH{i:08d}" for i in range(1, len(out) + 1)])
    return out
