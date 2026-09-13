"""Identifier minting for every key space in the hub.

Three patient identity spaces and three provider identity spaces exist on
purpose - resolving them is the point of the dataset.

NPIs are minted to DELIBERATELY FAIL the standard check digit. A valid NPI
resolves to a real clinician in the public NPPES registry, which is exactly
what a synthetic dataset must not do. Validators will flag these numbers; that
is the intended behavior and it is documented in the README.
"""
from __future__ import annotations

import numpy as np

NPI_PREFIX = "80840"


def _luhn_check_digit(payload: str) -> int:
    """Standard NPI check digit: Luhn over the 80840 prefix plus 9 digits."""
    digits = [int(c) for c in NPI_PREFIX + payload]
    total = 0
    # Double every second digit counting from the right.
    for idx, digit in enumerate(reversed(digits)):
        if idx % 2 == 0:
            doubled = digit * 2
            total += doubled - 9 if doubled > 9 else doubled
        else:
            total += digit
    return (10 - (total % 10)) % 10


def npi_is_valid(npi: str) -> bool:
    if len(npi) != 10 or not npi.isdigit():
        return False
    return _luhn_check_digit(npi[:9]) == int(npi[9])


def mint_npis(rng: np.random.Generator, count: int, valid: bool = False) -> list[str]:
    """Mint NPIs. valid=False (the default) guarantees a failing check digit."""
    out: list[str] = []
    seen: set[str] = set()
    while len(out) < count:
        body = "".join(str(d) for d in rng.integers(0, 10, size=9))
        if body[0] in "01":  # real NPIs start 1-9
            continue
        correct = _luhn_check_digit(body)
        if valid:
            check = correct
        else:
            # Any digit other than the correct one breaks validation.
            offset = int(rng.integers(1, 10))
            check = (correct + offset) % 10
        npi = body + str(check)
        if npi in seen:
            continue
        seen.add(npi)
        out.append(npi)
    return out


def mint_sequence(prefix: str, count: int, width: int = 8, start: int = 1) -> list[str]:
    return [f"{prefix}{i:0{width}d}" for i in range(start, start + count)]


def mint_member_ids(count: int) -> list[str]:
    """Payer member IDs - the eligibility and claims key space."""
    return mint_sequence("MHP", count, width=9)


def mint_mrns(rng: np.random.Generator, count: int) -> list[str]:
    """EHR medical record numbers - a separate key space, non-sequential.

    Deliberately not derivable from member_id. Drawn from a shuffled range so
    no arithmetic relationship exists between the two spaces.
    """
    pool = rng.permutation(np.arange(1_000_000, 1_000_000 + count * 4))[:count]
    return [f"RB{int(v)}" for v in pool]


def mint_subscriber_ids(count: int) -> list[str]:
    """Attribution-feed subscriber IDs.

    Shaped so they LOOK joinable to member_id and are not: same numeric core,
    different prefix, plus a two-digit person code appended downstream.
    """
    return mint_sequence("SUB", count, width=9)


def person_code(sequence_within_household: int) -> str:
    return f"{sequence_within_household:02d}"


def mint_claim_numbers(count: int, year: int) -> list[str]:
    return [f"{year}{i:09d}" for i in range(1, count + 1)]


def mint_tins(rng: np.random.Generator, count: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    while len(out) < count:
        tin = f"{int(rng.integers(20, 99))}{int(rng.integers(1000000, 9999999))}"
        if tin in seen:
            continue
        seen.add(tin)
        out.append(tin)
    return out


def mint_ccns(rng: np.random.Generator, count: int) -> list[str]:
    """CMS certification numbers, Missouri/Kansas state prefixes."""
    return [f"26{int(rng.integers(1000, 9999))}" for _ in range(count)]


# ------------------------------------------------------- malformed-id injection


def malform_npi(rng: np.random.Generator, npi: str) -> str:
    """Produce the kind of dirty NPI a real prescriber field contains."""
    mode = int(rng.integers(0, 4))
    if mode == 0:
        return npi[:-1]                      # truncated
    if mode == 1:
        return " " + npi + " "               # untrimmed
    if mode == 2:
        return npi[:5] + "-" + npi[5:]       # punctuated
    return npi.lstrip("0") or npi            # leading zero stripped by Excel
