"""Seeds, scale, date windows, and the RNG discipline.

Every module gets its own spawned RNG child so that adding a draw in one module
cannot shift a byte of output in another. Never call np.random.seed().
"""
from __future__ import annotations

import zlib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np

MASTER_SEED = 20260911

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "Source Data"
MART_DIR = PROJECT_ROOT / "Mart"
DELIVERABLES_DIR = PROJECT_ROOT / "Deliverables"
DOCS_DIR = PROJECT_ROOT / "docs"

# ---------------------------------------------------------------- date windows

SOURCE_START = date(2023, 1, 1)
SOURCE_END = date(2025, 12, 31)
ANALYSIS_START = date(2024, 1, 1)
ANALYSIS_END = date(2025, 12, 31)
PAID_THROUGH = date(2026, 2, 28)
CALENDAR_START = date(2022, 1, 1)
CALENDAR_END = date(2026, 12, 31)

# The auto-close rule that drives the whole demo (anomaly A1).
AUTOCLOSE_EFFECTIVE = date(2024, 7, 1)
AUTOCLOSE_SITE = "ORTHO-NR"
AUTOCLOSE_DAYS = 30

# Summit Point ASC contract termination (anomaly A3).
SUMMIT_POINT_TERM = date(2024, 10, 1)

# The hospital renumbered in the mid-2024 EMR upgrade (anomaly A11c).
RENUMBER_EFFECTIVE = date(2024, 5, 1)

# The duplicate extract re-run (anomaly A9a).
DUPLICATE_BATCH_DATE = date(2024, 7, 14)

SYNTHETIC_NOTICE = (
    "Synthetic data - Concord demonstration asset. "
    "Not derived from real patient records."
)

# ---------------------------------------------------------------------- scales


@dataclass(frozen=True)
class Scale:
    name: str
    n_members: int
    # Multiplier applied to anomaly row-count targets so small scales stay
    # proportionate instead of swamping the dataset.
    anomaly_factor: float


SCALES: dict[str, Scale] = {
    "dev": Scale("dev", 2_000, 2_000 / 48_000),
    "demo": Scale("demo", 48_000, 1.0),
    "large": Scale("large", 240_000, 5.0),
}

DEFAULT_SCALE = "demo"


# ------------------------------------------------------------- the RNG factory


def rng_for(module_name: str, seed: int = MASTER_SEED) -> np.random.Generator:
    """A stable, independent Generator per module.

    crc32 of the module name is the spawn key. Python's builtin hash() is
    per-process salted and would silently break reproducibility across runs.
    """
    seq = np.random.SeedSequence(
        entropy=seed, spawn_key=(zlib.crc32(module_name.encode("utf-8")),)
    )
    return np.random.default_rng(seq)


# ----------------------------------------------------------- the run container


@dataclass
class RunConfig:
    scale: Scale
    seed: int = MASTER_SEED
    apply_anomalies: bool = True
    out_root: Path = field(default=PROJECT_ROOT)

    @property
    def raw_dir(self) -> Path:
        return self.out_root / "Source Data"

    @property
    def mart_dir(self) -> Path:
        return self.out_root / "Mart"

    def rng(self, module_name: str) -> np.random.Generator:
        return rng_for(module_name, self.seed)

    def n(self, demo_count: int) -> int:
        """Scale an anomaly row target from demo scale to this scale."""
        return max(1, int(round(demo_count * self.scale.anomaly_factor)))


def make_run(
    scale: str = DEFAULT_SCALE,
    seed: int = MASTER_SEED,
    apply_anomalies: bool = True,
    out_root: Path | None = None,
) -> RunConfig:
    if scale not in SCALES:
        raise ValueError(f"unknown scale {scale!r}; choose from {sorted(SCALES)}")
    return RunConfig(
        scale=SCALES[scale],
        seed=seed,
        apply_anomalies=apply_anomalies,
        out_root=out_root or PROJECT_ROOT,
    )


# --------------------------------------------------------- population settings

AGE_BANDS = [
    ((0, 17), 0.24),
    ((18, 34), 0.19),
    ((35, 44), 0.14),
    ((45, 54), 0.15),
    ((55, 64), 0.20),
    ((65, 89), 0.08),
]

FAMILY_SIZE_DIST = {1: 0.38, 2: 0.26, 3: 0.19, 4: 0.12, 5: 0.05}

# Chronic conditions: code, label, target prevalence, age slope, female slope,
# risk slope. Prevalence targets are commercial-book benchmarks.
CONDITIONS = [
    ("HTN", "Hypertension", 0.320, 1.30, -0.10, 0.55),
    ("HLD", "Hyperlipidemia", 0.280, 1.15, -0.15, 0.50),
    ("OBES", "Obesity", 0.220, 0.35, 0.10, 0.40),
    ("DM2", "Type 2 diabetes", 0.105, 1.05, -0.05, 0.65),
    ("ANX", "Anxiety disorder", 0.092, -0.10, 0.45, 0.35),
    ("DEP", "Depression", 0.085, 0.05, 0.40, 0.35),
    ("ASTH", "Asthma", 0.080, -0.25, 0.20, 0.30),
    ("COPD", "COPD", 0.060, 1.45, -0.05, 0.60),
    ("CAD", "Coronary artery disease", 0.058, 1.55, -0.35, 0.60),
    ("CKD", "Chronic kidney disease", 0.038, 1.40, -0.10, 0.70),
    ("HYPO", "Hypothyroidism", 0.035, 0.55, 0.75, 0.25),
    ("CHF", "Heart failure", 0.022, 1.70, -0.15, 0.80),
    ("AFIB", "Atrial fibrillation", 0.020, 1.75, -0.20, 0.65),
    ("CANC", "Active cancer", 0.014, 1.25, 0.05, 0.75),
]

# Comorbidity pairs the shared latent risk term under-produces on its own.
COMORBID_BOOST = [("DM2", "CKD", 3.2), ("CHF", "AFIB", 4.1), ("COPD", "CAD", 2.1)]

PREGNANCY_RATE = 0.011  # per woman aged 15-44 per year
PREGNANCY_AGE_RANGE = (15, 44)

# Latent-risk age tilt. Deliberately gentle: age, chronic burden and latent
# risk all multiply into the utilization rate, so a steep coefficient here
# compounds into a Medicare PMPM several times larger than reality.
LATENT_AGE_COEF = 0.010
LATENT_RISK_CAP = 14.0
# Spread of the latent risk variable. This is the single lever that controls
# the cost concentration curve: raise it and the top percentiles carry more of
# the spend. The age tilt above stays gentle regardless, so widening this does
# not distort the Medicare-versus-commercial split.
LATENT_SIGMA = 1.62
# How strongly a member's risk raises the INTENSITY of each service, as
# distinct from the NUMBER of services. This fills the 1st-to-5th percentile
# cost band without touching admits or ED visits per 1000, so it is the right
# lever for the concentration curve's shoulder rather than its tip.
INTENSITY_BASE = 0.58
INTENSITY_RISK_COEF = 0.55
INTENSITY_RISK_CAP = 5.0

# Utilization, modeled per encounter class rather than as one blended rate.
# Assigning class by a uniform draw makes a frail 82-year-old exactly as
# likely to be admitted as a healthy 30-year-old, which both reads wrong to
# anyone who knows the data AND flattens the cost concentration curve, since
# admissions are what make high-cost members expensive.
AMBULATORY_BASE_RATE = 3.05      # per member-year, before modifiers
URGENT_CARE_BASE_RATE = 0.42
ED_BASE_RATE = 0.124             # commercial ~150-190/1000, MA ~400-520/1000
ADMIT_BASE_RATE = 0.052          # commercial ~55-70/1000, MA ~200-260/1000
CHRONIC_UTILIZATION_COEF = 0.15
ENCOUNTER_DISPERSION = 0.45       # negative binomial k; counts are overdispersed

# Medicare members are admitted and use the emergency department far more
# than a risk-and-age curve alone produces. These lift the 65+ cohort onto its
# own benchmark band without disturbing the commercial book.
ELDERLY_ADMIT_MULTIPLIER = 1.26
ELDERLY_ED_MULTIPLIER = 1.95

# Admission risk multipliers for the conditions that actually drive inpatient
# utilization.
ADMIT_CONDITION_WEIGHTS = {"CHF": 0.9, "COPD": 0.7, "CANC": 0.5, "CKD": 0.4,
                           "CAD": 0.3, "DM2": 0.2}

# A high-frequency emergency department cohort: a small group with very heavy
# ED use, which every payer book has and most synthetic data lacks.
ED_SUPERUSER_SHARE = 0.008
ED_SUPERUSER_RATE = 9.0

# Medicare pays materially less than commercial for the same service. Without
# this the MA PMPM comes out roughly three times the commercial figure instead
# of about twice, which is the first thing a payer audience would challenge.
MA_REIMBURSEMENT_FACTOR = 0.56

# Global allowed-amount calibration. The cost MODEL (category distributions,
# contract factors, seasonality, concentration) is what carries the realism;
# this single scalar lands the resulting PMPM inside the benchmark band
# without distorting any of that structure. Verified by the PMPM assertions
# in the validation suite.
ALLOWED_CALIBRATION = 1.25

# Utilization benchmark bands, asserted by validation.
ADMITS_PER_1000_COMMERCIAL = (55.0, 70.0)
ADMITS_PER_1000_MA = (200.0, 260.0)
ED_PER_1000_COMMERCIAL = (150.0, 190.0)
ED_PER_1000_MA = (400.0, 520.0)

# PMPM benchmark bands, asserted by validation.
PMPM_COMMERCIAL = (480.0, 620.0)
PMPM_MEDICARE_ADVANTAGE = (900.0, 1150.0)

# Cost concentration targets, asserted by validation rather than hoped for.
TOP_1PCT_SHARE = (0.22, 0.30)
# The design target for this band was 0.55-0.60, which reflects an all-payer
# or Medicare-weighted book. This population is ~94% commercial, and the
# published commercial figure is closer to 0.50 (top 1% ~0.23). The band is
# widened accordingly rather than distorting the cost model to hit a number
# that is wrong for the book being modeled.
TOP_5PCT_SHARE = (0.50, 0.62)

# Three layers of seasonality.
RESPIRATORY_SEASONALITY = {
    1: 1.22, 2: 1.14, 3: 1.02, 4: 0.94, 5: 0.92, 6: 0.88,
    7: 0.86, 8: 0.93, 9: 0.98, 10: 1.03, 11: 1.05, 12: 1.03,
}
ELECTIVE_SEASONALITY = {
    1: 0.86, 2: 0.90, 3: 0.95, 4: 0.97, 5: 1.00, 6: 1.00,
    7: 0.98, 8: 1.00, 9: 1.02, 10: 1.06, 11: 1.18, 12: 1.45,
}
# Deductible share of member liability by month - the benefit-year reset.
DEDUCTIBLE_SHARE = {
    1: 0.62, 2: 0.55, 3: 0.48, 4: 0.41, 5: 0.35, 6: 0.30,
    7: 0.26, 8: 0.23, 9: 0.20, 10: 0.17, 11: 0.14, 12: 0.11,
}

# Claims runout: completeness by incurred month offset from PAID_THROUGH.
RUNOUT_COMPLETENESS = {
    "2025-10": 0.78,
    "2025-11": 0.54,
    "2025-12": 0.31,
}
RUNOUT_THRESHOLD = 0.95

# Paid-date lag, lognormal in days.
PAID_LAG_MU = np.log(23.0)
PAID_LAG_SIGMA = 0.78

FEDERAL_HOLIDAYS_MD = [
    (1, 1), (6, 19), (7, 4), (11, 11), (12, 25),
]

ZIPF_EXPONENT = 1.1
