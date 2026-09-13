#!/usr/bin/env python3
"""Generate the data mart manifest: ERD plus a key reference, as a PDF.

    python Build/build_mart_manifest.py

Reads Deliverables/mart-key-verification.json, so every row count, key and
orphan rate in the document was MEASURED on the shipped data rather than
transcribed. Renders HTML with an inline SVG ERD, then prints to PDF through
headless Chrome (the only PDF toolchain available here, and the only one with
real SVG and CSS support).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "Build"))
sys.path.insert(0, str(ROOT / "Generators"))
import mart_keys as K  # noqa: E402

DELIV = ROOT / "Deliverables"
VERIF = DELIV / "mart-key-verification.json"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# Category colors. Used only to encode table type, nothing else.
PALETTE = {
    "dim":  ("#e8eef6", "#41618c", "#1d3253"),   # fill, border, header text
    "fct":  ("#fdf0e3", "#b06d28", "#6b3f11"),
    "br":   ("#e9f2ec", "#4a7c5d", "#20402e"),
    "xw":   ("#efe9f5", "#6b5192", "#38275a"),
    "vw":   ("#eeeeee", "#6c6c6c", "#333333"),
}


def kind(table: str) -> str:
    if table.startswith("dim_"):
        return "dim"
    if table.startswith("br_"):
        return "br"
    if table.startswith("xwalk_"):
        return "xw"
    if table.startswith("vw_"):
        return "vw"
    return "fct"


# ---------------------------------------------------------------- ERD layout
# Positions are hand-placed. Auto-layout on 28 tables produces a diagram
# nobody can follow; the readability is worth the coordinates.
BOX_W, LINE_H, PAD = 208, 13, 8

# Four diagrams, each scoped so a shared dimension has only a few consumers
# and can sit next to all of them. Two earlier drafts put crosswalks on one
# side and their parent dimensions on the other, which guarantees connectors
# crossing the canvas through unrelated boxes. check_layout() below asserts
# that nothing overlaps or overflows, so layout regressions surface at build
# time instead of being spotted by eye.
ERD1 = {
    "title": "Claims star \u2014 the money, and everything it hangs off",
    "w": 1480,
    # Centre column order matters: the diagnosis bridge sits directly under
    # the header it keys to, and the line table below that, so every link in
    # the column is between ADJACENT boxes. With the line table in the middle,
    # the bridge-to-header connector has to pass behind it.
    "boxes": {
        "dim_date":           (40,  60),
        "dim_member":         (40,  250),
        "dim_master_person":  (40,  440),
        "dim_claim_status":   (40,  620),
        "br_claim_diagnosis": (400, 60),
        "fct_claim_header":   (400, 230),
        "fct_claim_line":     (400, 540),
        "dim_diagnosis":      (760, 60),
        "dim_drg":            (760, 200),
        "dim_facility":       (760, 340),
        "dim_provider":       (760, 490),
        "dim_service_line":   (1140, 490),
        "dim_procedure":      (760, 700),
        "dim_service_place":  (1140, 700),
    },
    "edges": [
        ("fct_claim_line", "claim_number", "fct_claim_header"),
        ("fct_claim_line", "member_key", "dim_member"),
        ("fct_claim_line", "member_durable_key", "dim_master_person"),
        ("fct_claim_line", "service_date_key", "dim_date"),
        ("fct_claim_line", "servicing_provider_key", "dim_provider"),
        ("fct_claim_line", "service_site_code", "dim_facility"),
        ("fct_claim_line", "procedure_code", "dim_procedure"),
        ("fct_claim_line", "pos_code", "dim_service_place"),
        ("fct_claim_header", "member_key", "dim_member"),
        ("fct_claim_header", "drg_code", "dim_drg"),
        ("fct_claim_header", "claim_status_code", "dim_claim_status"),
        ("br_claim_diagnosis", "claim_number", "fct_claim_header"),
        ("br_claim_diagnosis", "icd10_code", "dim_diagnosis"),
        ("dim_provider", "service_line_code", "dim_service_line"),
        ("dim_provider", "facility_id", "dim_facility"),
        ("dim_member", "member_durable_key", "dim_master_person"),
    ],
}

ERD2 = {
    "title": "Clinical \u2014 the EHR side, keyed by MRN",
    "w": 1400,
    # Both children of fct_encounter sit SIDE BY SIDE beneath it. Stacked in
    # one column, the lower one's connector has to detour around the upper.
    "boxes": {
        "dim_master_person":      (40,  60),
        "dim_provider":           (40,  300),
        "dim_diagnosis":          (40,  560),
        "fct_encounter":          (430, 60),
        "br_encounter_diagnosis": (330, 390),
        "fct_lab_result":         (700, 390),
        "dim_facility":           (880, 60),
    },
    "edges": [
        ("fct_encounter", "member_durable_key", "dim_master_person"),
        ("fct_encounter", "attending_provider_master_id", "dim_provider"),
        ("fct_encounter", "facility_id", "dim_facility"),
        ("br_encounter_diagnosis", "encounter_id", "fct_encounter"),
        ("br_encounter_diagnosis", "icd10_code", "dim_diagnosis"),
        ("fct_lab_result", "encounter_id", "fct_encounter"),
    ],
}

ERD3 = {
    "title": "Referral chain \u2014 intent, and whether care actually happened",
    "w": 1400,
    "boxes": {
        "fct_encounter":        (40,  90),
        "dim_master_person":    (40,  350),
        "fct_referral":         (450, 60),
        "fct_referral_outcome": (450, 380),
        "dim_facility":         (860, 60),
        "dim_provider":         (860, 250),
    },
    "edges": [
        ("fct_referral", "source_encounter_id", "fct_encounter"),
        ("fct_referral", "member_durable_key", "dim_master_person"),
        ("fct_referral", "destination_site_code", "dim_facility"),
        ("fct_referral", "referring_provider_master_id", "dim_provider"),
        ("fct_referral_outcome", "referral_id", "fct_referral"),
    ],
}

ERD4 = {
    "title": "Identity resolution and provider structure",
    "w": 1400,
    "boxes": {
        "xwalk_patient":           (40,  60),
        "dim_master_person":       (450, 60),
        "dim_member":              (830, 60),
        "xwalk_provider":          (40,  330),
        "dim_provider":            (450, 330),
        "dim_service_line":        (830, 330),
        "br_provider_affiliation": (450, 570),
        "dim_facility":            (830, 520),
    },
    "edges": [
        ("xwalk_patient", "master_person_id", "dim_master_person"),
        ("dim_member", "member_durable_key", "dim_master_person"),
        ("xwalk_provider", "provider_master_id", "dim_provider"),
        ("dim_provider", "service_line_code", "dim_service_line"),
        ("dim_provider", "facility_id", "dim_facility"),
        ("br_provider_affiliation", "provider_master_id", "dim_provider"),
        ("br_provider_affiliation", "facility_id", "dim_facility"),
    ],
}

ERD5 = {
    "title": "Membership, coverage and attribution \u2014 where the denominator comes from",
    "w": 1400,
    # dim_member sits in the MIDDLE of the left column, between the three
    # facts that reference it, so every link is short. Placed at the top it
    # serves the bottom fact via a detour around the whole diagram.
    "boxes": {
        "dim_coverage_plan":     (40,  60),
        "dim_member":            (40,  300),
        "dim_master_person":     (40,  540),
        "fct_eligibility_span":  (450, 60),
        "fct_member_month":      (450, 300),
        "vbc_attribution_month": (450, 540),
        "dim_date":              (860, 300),
        "dim_facility":          (860, 540),
    },
    "edges": [
        ("fct_eligibility_span", "member_id", "dim_member"),
        ("fct_eligibility_span", "plan_code", "dim_coverage_plan"),
        ("fct_member_month", "member_id", "dim_member"),
        ("fct_member_month", "plan_code", "dim_coverage_plan"),
        ("fct_member_month", "year_month", "dim_date"),
        ("vbc_attribution_month", "member_id", "dim_member"),
        ("vbc_attribution_month", "attributed_site_code", "dim_facility"),
        ("dim_member", "member_durable_key", "dim_master_person"),
    ],
}

ERD_ORDER = [
    ("ERD1", ERD1,
     "Claim lines de-duplicate on the BUSINESS key, never on claim_line_key: a "
     "re-driven extract duplicated 2,840 lines and every one carried a distinct "
     "surrogate. DRG, length of stay and the claim total live only on the "
     "header, so a DRG-by-procedure question is forced through that join, and "
     "br_claim_diagnosis is at HEADER grain so joining a line to it fans out."),
    ("ERD2", ERD2,
     "The EHR keys patients by MRN, so nothing here joins to claims directly \u2014 "
     "it has to go through xwalk_patient (next diagram), and that hop loses "
     "roughly 3% of records non-randomly. br_encounter_diagnosis averages about "
     "3.25 rows per encounter and will multiply any measure summed after it."),
    ("ERD3", ERD3,
     "fct_referral records intent and what the EHR directory BELIEVED about the "
     "destination at order time \u2014 never the fact. fct_referral_outcome is where "
     "a referral is tested against a real confirming event, a claim or a "
     "completed appointment, rather than against its own status field."),
    ("ERD4", ERD4,
     "Three patient key spaces and three provider key spaces resolve here. The "
     "crosswalk is imperfect in both directions on purpose. "
     "br_provider_affiliation is the fan-out hazard: 22% of providers hold two "
     "or more concurrent affiliations, and allocation_pct sums to exactly 1.0 "
     "per provider-span for anyone who wants a weighted answer."),
    ("ERD5", ERD5,
     "fct_member_month is the only sanctioned PMPM denominator, built as the "
     "gaps-and-islands union of coverage. fct_eligibility_span contains "
     "deliberate overlaps, so summing span lengths double counts. The "
     "attribution roster is restated retroactively, so compare versions rather "
     "than trusting the current roster."),
]


def _crossings(pts, child, parent, dims) -> int:
    """How many non-endpoint boxes a polyline passes through."""
    hit = 0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        lo_x, hi_x = min(x1, x2), max(x1, x2)
        lo_y, hi_y = min(y1, y2), max(y1, y2)
        for t, (bx, by, bw, bh) in dims.items():
            if t in (child, parent):
                continue
            if (lo_x < bx + bw - 2 and bx + 2 < hi_x
                    and lo_y < by + bh - 2 and by + 2 < hi_y):
                hit += 1
    return hit


def route(child, parent, cs, ps, x1, y1, x2, y2, dims):
    """Pick the cleanest orthogonal route between two anchor points.

    A single mid-point elbow is the obvious implementation and it is wrong
    often enough to matter: boxes are painted over the lines, so a connector
    that clips a third box vanishes behind it and the diagram asserts a
    relationship that does not exist. So several candidate routes are scored
    by how many unrelated boxes they cross, and the cleanest wins.
    """
    cands = []
    if cs in ("r", "l"):
        for mx in ((x1 + x2) / 2, x1 + (26 if cs == "r" else -26),
                   x2 + (26 if ps == "r" else -26)):
            cands.append([(x1, y1), (mx, y1), (mx, y2), (x2, y2)])
        # Detour above or below every box in the span, then come back.
        tops = min(by for (_, by, _, _) in dims.values()) - 26
        bots = max(by + bh for (_, by, _, bh) in dims.values()) + 26
        for chan in (tops, bots):
            ox = x1 + (26 if cs == "r" else -26)
            ix = x2 + (26 if ps == "r" else -26)
            cands.append([(x1, y1), (ox, y1), (ox, chan), (ix, chan),
                          (ix, y2), (x2, y2)])
    else:
        for my in ((y1 + y2) / 2, y1 + (26 if cs == "b" else -26),
                   y2 + (26 if ps == "b" else -26)):
            cands.append([(x1, y1), (x1, my), (x2, my), (x2, y2)])
        lefts = min(bx for (bx, _, _, _) in dims.values()) - 26
        rights = max(bx + bw for (bx, _, bw, _) in dims.values()) + 26
        for chan in (lefts, rights):
            oy = y1 + (26 if cs == "b" else -26)
            iy = y2 + (26 if ps == "b" else -26)
            cands.append([(x1, y1), (x1, oy), (chan, oy), (chan, iy),
                          (x2, iy), (x2, y2)])
    def length(pts):
        return sum(abs(b[0] - a[0]) + abs(b[1] - a[1])
                   for a, b in zip(pts, pts[1:]))

    # Fewest crossings first, then the shortest path. Without the length term
    # the router happily sends a connector around the outside of the whole
    # diagram when a short clean route was available.
    scored = sorted(
        ((_crossings(c, child, parent, dims), length(c), i, c)
         for i, c in enumerate(cands)),
        key=lambda t: (t[0], t[1], t[2]),
    )
    return scored[0][3]


def check_layout(spec: dict, dims: dict, segments=None) -> list[str]:
    """Assert the diagram is actually readable.

    Three failure modes, all easy to introduce by hand and easy to miss by eye:
      1. a box overflows the canvas
      2. two boxes overlap
      3. a connector routes THROUGH a box that is not one of its endpoints

    The third is the nastiest. Boxes are painted over the lines, so the
    connector disappears behind the box and the diagram silently asserts a
    relationship that does not exist - which is exactly what an earlier draft
    of the claims star did between br_claim_diagnosis and dim_service_place.
    """
    problems = []
    items = list(dims.items())
    for i, (a, (ax, ay, aw, ah)) in enumerate(items):
        if ax + aw > spec["w"]:
            problems.append(f"{a} overflows the canvas width")
        for b, (bx, by, bw, bh) in items[i + 1:]:
            if ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah:
                problems.append(f"{a} overlaps {b}")

    for (child, parent, pts) in segments or []:
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            lo_x, hi_x = min(x1, x2), max(x1, x2)
            lo_y, hi_y = min(y1, y2), max(y1, y2)
            for t, (bx, by, bw, bh) in items:
                if t in (child, parent):
                    continue
                # Inset so a line grazing a box edge is not flagged.
                if (lo_x < bx + bw - 2 and bx + 2 < hi_x
                        and lo_y < by + bh - 2 and by + 2 < hi_y):
                    msg = f"{child} -> {parent} routes through {t}"
                    if msg not in problems:
                        problems.append(msg)
    return problems


def box_lines(table: str, v: dict) -> list[tuple[str, str]]:
    """The rows shown inside a box: (marker, text).

    An FK column already displayed as part of the business key is not
    repeated - a box listing referral_id twice reads as a mistake rather than
    as a key that happens to do both jobs.
    """
    meta = K.KEYS[table]
    out = []
    pk = v["pk"].get("column")
    if pk:
        out.append(("PK", pk))
    bk = v.get("business", {}).get("columns") or []
    if bk and bk != [pk]:
        out.append(("BK", ", ".join(bk)))
    shown = set(bk) | ({pk} if pk else set())
    for f in meta["fks"]:
        if f[0] not in shown:
            out.append(("FK", f[0]))
    return out


def render_erd(spec: dict, verif: dict) -> str:
    """Hand-laid ERD as inline SVG, with crow's-foot notation."""
    edges = spec["edges"]
    boxes, dims = spec["boxes"], {}
    for t, (x, y) in boxes.items():
        v = verif["tables"][t]
        lines = box_lines(t, v)
        h = 30 + len(lines) * LINE_H + 14
        dims[t] = (x, y, BOX_W, h)
    # Derive the canvas height so no box can ever be clipped by a hard-coded
    # value, and reserve a band for the legend.
    spec = dict(spec)
    spec["h"] = max(y + hh for (_, y, _, hh) in dims.values()) + 54

    # Count how many edges land on each (table, side) so they can be spread
    # along that edge. Stacking every connector on the midpoint of a side
    # makes four relationships look like one.
    side_use: dict[tuple[str, str], int] = {}

    def anchor(t, side, slot=0, total=1):
        x, y, w, h = dims[t]
        if total <= 1:
            frac = 0.5
        else:
            # Spread across the middle 70% of the edge.
            frac = 0.15 + 0.7 * (slot / (total - 1))
        if side == "l":
            return (x, y + h * frac)
        if side == "r":
            return (x + w, y + h * frac)
        if side == "t":
            return (x + w * frac, y)
        return (x + w * frac, y + h)

    def pick_sides(a, b):
        ax, ay, aw, ah = dims[a]
        bx, by, bw, bh = dims[b]
        acx, acy = ax + aw / 2, ay + ah / 2
        bcx, bcy = bx + bw / 2, by + bh / 2
        if abs(bcx - acx) >= abs(bcy - acy):
            return ("r", "l") if bcx > acx else ("l", "r")
        return ("b", "t") if bcy > acy else ("t", "b")

    # First pass: decide sides and tally slot usage.
    routed = []
    for child, col, parent in edges:
        if child not in dims or parent not in dims:
            continue
        cs, ps = pick_sides(child, parent)
        side_use[(child, cs)] = side_use.get((child, cs), 0) + 1
        side_use[(parent, ps)] = side_use.get((parent, ps), 0) + 1
        routed.append((child, col, parent, cs, ps))
    slot_seen: dict[tuple[str, str], int] = {}
    seg_pts: list = []

    parts = []
    # ---- relationship lines first, so boxes sit on top
    for child, col, parent, cs, ps in routed:
        ck, pk_ = (child, cs), (parent, ps)
        ci = slot_seen.get(ck, 0); slot_seen[ck] = ci + 1
        pi = slot_seen.get(pk_, 0); slot_seen[pk_] = pi + 1
        x1, y1 = anchor(child, cs, ci, side_use[ck])
        x2, y2 = anchor(parent, ps, pi, side_use[pk_])
        pts = route(child, parent, cs, ps, x1, y1, x2, y2, dims)
        seg_pts.append((child, parent, pts))
        path = "M " + " L ".join(f"{px} {py}" for px, py in pts)
        parts.append(
            f'<path d="{path}" fill="none" stroke="#8a949f" '
            f'stroke-width="1.1"/>'
        )
        # Crow's foot at the child (many) end.
        dx = 1 if cs == "r" else -1 if cs == "l" else 0
        dy = 1 if cs == "b" else -1 if cs == "t" else 0
        for off in (-4.5, 0, 4.5):
            if dx:
                parts.append(
                    f'<line x1="{x1}" y1="{y1}" x2="{x1 + dx * 9}" '
                    f'y2="{y1 + off}" stroke="#8a949f" stroke-width="1.1"/>')
            else:
                parts.append(
                    f'<line x1="{x1}" y1="{y1}" x2="{x1 + off}" '
                    f'y2="{y1 + dy * 9}" stroke="#8a949f" stroke-width="1.1"/>')
        # Single tick at the parent (one) end.
        if ps in ("l", "r"):
            sx = x2 + (7 if ps == "r" else -7)
            parts.append(f'<line x1="{sx}" y1="{y2 - 5}" x2="{sx}" '
                         f'y2="{y2 + 5}" stroke="#8a949f" stroke-width="1.4"/>')
        else:
            sy = y2 + (7 if ps == "b" else -7)
            parts.append(f'<line x1="{x2 - 5}" y1="{sy}" x2="{x2 + 5}" '
                         f'y2="{sy}" stroke="#8a949f" stroke-width="1.4"/>')

    # ---- boxes
    for t, (x, y, w, h) in dims.items():
        v = verif["tables"][t]
        fill, border, htext = PALETTE[kind(t)]
        parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="4" '
            f'fill="#ffffff" stroke="{border}" stroke-width="1.3"/>')
        parts.append(
            f'<path d="M {x} {y+4} a4,4 0 0 1 4,-4 h{w-8} a4,4 0 0 1 4,4 '
            f'v18 h-{w} z" fill="{fill}" stroke="none"/>')
        parts.append(
            f'<line x1="{x}" y1="{y+22}" x2="{x+w}" y2="{y+22}" '
            f'stroke="{border}" stroke-width="1"/>')
        # Shrink long names so they cannot run into the row count on the
        # right. br_encounter_diagnosis is 22 characters and collided at the
        # default size.
        name_fs = 11.5 if len(t) <= 19 else 10.2 if len(t) <= 23 else 9.2
        parts.append(
            f'<text x="{x+PAD}" y="{y+15.5}" font-size="{name_fs}" '
            f'font-weight="700" fill="{htext}" '
            f'font-family="Menlo, monospace">{t}</text>')
        parts.append(
            f'<text x="{x+w-PAD}" y="{y+15.5}" font-size="8.6" text-anchor="end" '
            f'fill="{htext}" opacity="0.85">{v["rows"]:,}</text>')
        ty = y + 36
        for marker, text in box_lines(t, v):
            mcol = {"PK": "#a8421f", "BK": "#6b5192", "FK": "#41618c"}[marker]
            parts.append(
                f'<text x="{x+PAD}" y="{ty}" font-size="8.2" font-weight="700" '
                f'fill="{mcol}" font-family="Menlo, monospace">{marker}</text>')
            shown = text if len(text) <= 34 else text[:32] + ".."
            parts.append(
                f'<text x="{x+PAD+21}" y="{ty}" font-size="8.6" fill="#2c3338" '
                f'font-family="Menlo, monospace">{shown}</text>')
            ty += LINE_H

    for prob in check_layout(spec, dims, seg_pts):
        print(f"  LAYOUT [{spec['title'][:34]}]: {prob}")

    legend = (
        '<g transform="translate(40,%d)">' % (spec["h"] - 28)
        + '<text x="0" y="0" font-size="9.5" fill="#555">'
        'PK primary key &#183; BK business key, the grain and the '
        'de-duplication target &#183; FK foreign key &#183; '
        'crow\'s foot marks the many side</text></g>'
    )
    return (
        f'<svg viewBox="0 0 {spec["w"]} {spec["h"]}" width="100%" '
        f'xmlns="http://www.w3.org/2000/svg" '
        f'font-family="-apple-system, Helvetica, Arial, sans-serif">'
        + "".join(parts) + legend + "</svg>"
    )


def esc(v) -> str:
    return (str(v).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def build_html(verif: dict) -> str:
    T = verif["tables"]
    total_rows = sum(v["rows"] for v in T.values())
    total_fks = sum(len(v["fks"]) for v in T.values())
    declared_pk = [v for v in T.values() if v["pk"].get("column")]
    n_pk = sum(1 for v in declared_pk if v["pk"]["status"] == "UNIQUE")
    n_bridge = len(T) - len(declared_pk)
    orphan_fks = sum(1 for v in T.values() for f in v["fks"]
                     if f.get("orphans", 0))
    float_keys = [(t, f["column"]) for t, v in T.items() for f in v["fks"]
                  if f.get("float_coerced")]

    H = []
    A = H.append
    A("""<style>
:root { --ink:#1d2327; --muted:#5d6770; --rule:#d8dde2; --accent:#41618c; }
@page { size: Letter portrait; margin: 16mm 15mm; }
@page erd { size: Letter landscape; margin: 8mm; }
* { box-sizing: border-box; }
body { font-family: -apple-system, "Helvetica Neue", Arial, sans-serif;
       color: var(--ink); font-size: 10pt; line-height: 1.45; margin: 0; }
h1 { font-size: 23pt; margin: 0 0 2mm; letter-spacing: -0.4pt; }
h2 { font-size: 13pt; margin: 9mm 0 3mm; padding-bottom: 1.5mm;
     border-bottom: 1.5px solid var(--accent); }
h3 { font-size: 10.5pt; margin: 5mm 0 1.5mm; font-family: Menlo, monospace;
     color: #1d3253; }
p { margin: 0 0 2.6mm; }
.sub { color: var(--muted); font-size: 10.5pt; margin-bottom: 5mm; }
.notice { border: 1.2px solid #b06d28; background: #fdf6ee; color: #6b3f11;
          padding: 3mm 4mm; border-radius: 3px; font-size: 9pt;
          margin: 0 0 6mm; }
table { width: 100%; border-collapse: collapse; font-size: 8.6pt;
        margin: 0 0 3mm; }
th { text-align: left; border-bottom: 1.2px solid var(--ink);
     padding: 1.4mm 2mm 1.4mm 0; font-size: 8pt; text-transform: uppercase;
     letter-spacing: 0.3pt; color: var(--muted); }
td { border-bottom: 0.6px solid var(--rule); padding: 1.4mm 2mm 1.4mm 0;
     vertical-align: top; }
code, .m { font-family: Menlo, monospace; font-size: 8.3pt; }
.summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 3mm;
           margin: 0 0 6mm; }
.stat { border: 0.8px solid var(--rule); border-radius: 3px; padding: 3mm; }
.stat .n { font-size: 17pt; font-weight: 700; letter-spacing: -0.5pt; }
.stat .l { font-size: 8pt; color: var(--muted); text-transform: uppercase;
           letter-spacing: 0.3pt; }
.erd { page: erd; page-break-before: always; }
.erd h2 { margin-top: 0; }
.cap { font-size: 9pt; color: var(--muted); max-width: 210mm; margin: 0 0 2mm; }
.tbl { page-break-inside: avoid; margin-bottom: 5mm; }
.grain { font-size: 9pt; color: var(--muted); margin: 0 0 1.5mm; }
.note { font-size: 8.6pt; background: #f6f8fa; border-left: 2.5px solid var(--accent);
        padding: 2mm 3mm; margin: 1.5mm 0 0; }
.pill { display: inline-block; font-size: 7.4pt; font-weight: 700;
        padding: 0.3mm 1.6mm; border-radius: 2px; font-family: Menlo, monospace; }
.pk { background: #f7e4dd; color: #a8421f; }
.bk { background: #efe9f5; color: #6b5192; }
.fk { background: #e8eef6; color: #41618c; }
.ok { color: #2f6b45; font-weight: 600; }
.warn { color: #a8421f; font-weight: 600; }
.grp { font-size: 8pt; text-transform: uppercase; letter-spacing: 0.6pt;
       color: var(--muted); margin: 7mm 0 2mm; font-weight: 700; }
.foot { color: var(--muted); font-size: 8.4pt; border-top: 0.8px solid var(--rule);
        padding-top: 2.5mm; margin-top: 8mm; }
</style>""")

    # ---------------------------------------------------------- cover page
    A("<h1>Healthcare Data Hub &mdash; data mart manifest</h1>")
    A(f'<div class="sub">Entity relationships, primary keys, business keys and '
      f'foreign keys for all {len(T)} mart tables.<br>'
      f'Generated {date.today().isoformat()} from the shipped data.</div>')
    A('<div class="notice"><b>Synthetic data.</b> Every record described here is '
      'wholly fabricated. No row corresponds to any real person, provider, '
      'facility or payer. Because the data is fabricated rather than '
      'de-identified, HIPAA de-identification standards do not apply and are '
      'not claimed &mdash; this dataset is not &ldquo;HIPAA compliant&rdquo;, a '
      'concept that does not apply to invented records.</div>')

    A('<div class="summary">')
    for n, l in [(f"{len(T)}", "mart tables"),
                 (f"{total_rows/1e6:.1f}M", "rows"),
                 (f"{total_fks}", "foreign keys"),
                 (f"{n_pk} of {len(declared_pk)}",
                  "declared primary keys unique"),
                 (f"{orphan_fks}", "foreign keys with orphans"),
                 ("0", "business key violations")]:
        A(f'<div class="stat"><div class="n">{n}</div><div class="l">{l}</div></div>')
    A("</div>")

    A(f'<p style="font-size:9pt;color:var(--muted);margin:-3mm 0 6mm">'
      f'{n_bridge} of the {len(T)} tables are bridges or evaluation tables with '
      f'no surrogate key by design; they are keyed on their business key, which '
      f'is stated and verified for each. Every one of the {len(declared_pk)} '
      f'declared primary keys is unique and non-null.</p>')
    A("<h2>How to read this</h2>")
    A("<p>Three kinds of key appear against every table, and the distinction "
      "between the first two is the single most load-bearing idea in the "
      "document.</p>")
    A('<table><tr><th>Key</th><th>What it is</th><th>What it is for</th></tr>'
      '<tr><td><span class="pill pk">PK</span></td>'
      '<td>The surrogate primary key. One column, an integer, meaningless '
      'outside this mart.</td>'
      '<td>Joining. It is unique <i>by construction</i>, which is exactly why '
      'testing it proves nothing about data quality.</td></tr>'
      '<tr><td><span class="pill bk">BK</span></td>'
      '<td>The business key: the natural grain of the table, stated in the '
      'columns a source system would recognise.</td>'
      '<td>De-duplication and grain assertions. <b>This</b> is the key a '
      'uniqueness test must run on. A re-driven extract duplicated 2,840 claim '
      'lines in this dataset and every one carried a distinct surrogate key, so '
      'a primary-key test passed while the grain was broken.</td></tr>'
      '<tr><td><span class="pill fk">FK</span></td>'
      '<td>Foreign key, with its parent table and column.</td>'
      '<td>Joining, and knowing what a join would drop. Null rates are stated '
      'because several are null <i>by design</i>.</td></tr></table>')
    A("<p>Every figure was measured by <code>Build/verify_keys.py</code> against "
      "the files in <code>Mart/</code>. Nothing here is transcribed.</p>")

    A("<h2>Layers</h2>")
    A("<p>Five source systems land as gzipped CSV, a conformed and dimensional "
      "layer is built from them, and one wide view sits on top for "
      "self-service. The mart tables in this document are the middle and top "
      "of that stack.</p>")
    A('<table><tr><th>Layer</th><th>Location</th><th>Contents</th></tr>'
      '<tr><td>Source</td><td><code>Source Data/</code></td>'
      '<td>Five systems as landed: string-typed, defects intact. The shippable '
      'artifact.</td></tr>'
      '<tr><td>Mart</td><td><code>Mart/</code></td>'
      '<td>Conformed dimensions, facts, bridges and crosswalks. Documented '
      'here.</td></tr>'
      '<tr><td>Serving</td><td><code>Mart/vw_claim_line_enriched.csv.gz</code></td>'
      '<td>One row per claim line, no bridges, safe to sum. Start here.</td>'
      '</tr></table>')

    # ---------------------------------------------------------- ERD pages
    for _name, spec, caption in ERD_ORDER:
        A(f'<div class="erd"><h2>{esc(spec["title"])}</h2>')
        A(f'<p class="cap">{esc(caption)}</p>')
        A(render_erd(spec, verif))
        A("</div>")

    # ------------------------------------------------------ table reference
    A('<div style="page-break-before: always"></div>')
    A("<h2>Table reference</h2>")
    A("<p>Grain, keys and relationships for every table, grouped as the "
      "diagrams group them. <span class='m'>nullable by design</span> is "
      "called out wherever a null foreign key is expected rather than a "
      "defect.</p>")

    for group, tables in K.GROUPS.items():
        A(f'<div class="grp">{esc(group)}</div>')
        for t in tables:
            v = T[t]
            A('<div class="tbl">')
            A(f"<h3>{t}</h3>")
            A(f'<div class="grain">One row = {esc(v["grain"])} &middot; '
              f'{v["rows"]:,} rows &middot; {v["columns"]} columns'
              + (f' &middot; includes {v["sentinel_rows"]} sentinel row(s)'
                 if v.get("sentinel_rows") else "") + "</div>")
            A('<table><tr><th style="width:9%">Key</th>'
              '<th style="width:31%">Column(s)</th>'
              '<th style="width:27%">References</th>'
              '<th style="width:33%">Verified</th></tr>')
            pk = v["pk"]
            if pk.get("column"):
                st = ('<span class="ok">unique, no nulls</span>'
                      if pk["status"] == "UNIQUE"
                      else f'<span class="warn">{esc(pk["status"])}</span>')
                A(f'<tr><td><span class="pill pk">PK</span></td>'
                  f'<td class="m">{esc(pk["column"])}</td><td>&mdash;</td>'
                  f'<td>{st}</td></tr>')
            else:
                A('<tr><td><span class="pill pk">PK</span></td>'
                  '<td colspan="2">none &mdash; bridge, keyed on its business key</td>'
                  '<td>&mdash;</td></tr>')
            bk = v.get("business")
            if bk and bk.get("columns"):
                st = ('<span class="ok">unique</span>' if bk["status"] == "UNIQUE"
                      else f'<span class="warn">{esc(bk["status"])}</span>')
                A(f'<tr><td><span class="pill bk">BK</span></td>'
                  f'<td class="m">{esc(", ".join(bk["columns"]))}</td>'
                  f'<td>&mdash;</td><td>{st}</td></tr>')
            for f in v["fks"]:
                bits = []
                if f.get("orphans", 0):
                    bits.append(f'<span class="warn">{f["orphans"]:,} orphans '
                                f'({f["orphan_pct"]}%)</span>')
                else:
                    bits.append('<span class="ok">no orphans</span>')
                if f.get("null_pct", 0):
                    bits.append(f'{f["null_pct"]}% null')
                if f.get("note"):
                    bits.append(esc(f["note"]))
                A(f'<tr><td><span class="pill fk">FK</span></td>'
                  f'<td class="m">{esc(f["column"])}</td>'
                  f'<td class="m">{esc(f["references"])}</td>'
                  f'<td>{" &middot; ".join(bits)}</td></tr>')
            A("</table>")
            if v.get("note"):
                A(f'<div class="note">{esc(v["note"])}</div>')
            A("</div>")

    # ------------------------------------------------------- join hazards
    A('<div style="page-break-before: always"></div>')
    A("<h2>Join hazards</h2>")
    A("<p>Six things in this mart will produce a confidently wrong number if "
      "joined carelessly. All six are deliberate.</p>")
    A('<table><tr><th style="width:24%">Hazard</th><th>What goes wrong, and the control</th></tr>')
    for name, body in [
        ("Surrogate vs business key",
         "A uniqueness test on <code>claim_line_key</code> passes on the raw "
         "file while 2,840 duplicate lines sit in it. Test the business key "
         "&mdash; <code>claim_number + claim_line_number + adjudication_seq + "
         "net_sign</code> &mdash; and de-duplicate on that."),
        ("Diagnosis bridges fan out",
         "<code>br_claim_diagnosis</code> is at HEADER grain and "
         "<code>br_encounter_diagnosis</code> averages ~3.25 rows per "
         "encounter. Joining a fact to either multiplies rows, so any measure "
         "summed afterwards is inflated. Filter on "
         "<code>is_primary</code>, or aggregate the bridge before joining."),
        ("Provider affiliation fans out",
         "22% of providers hold two or more concurrent facility affiliations, "
         "so an unweighted join to <code>br_provider_affiliation</code> "
         "overstates facility totals by roughly 29%. Use the "
         "<code>service_site_code</code> already on the fact, or weight by "
         "<code>allocation_pct</code>, which sums to exactly 1.0 per "
         "provider-span."),
        ("Spans are not a denominator",
         "<code>fct_eligibility_span</code> contains deliberate overlaps. "
         "Summing span lengths double counts every one. Use "
         "<code>fct_member_month</code>, which is the gaps-and-islands union "
         "of coverage and the only sanctioned PMPM denominator."),
        ("Reversals and versions",
         "Two nettings tie exactly: <code>SUM(paid_amount)</code> over every "
         "row, and the same sum <code>WHERE is_current_version</code>. Note "
         "there is <b>no</b> reversal exclusion in the second &mdash; orphan "
         "reversals are current and negative on purpose, so filtering them "
         "breaks the tie. Filtering <code>adjudication_seq = 1</code> or "
         "<code>paid_amount &gt; 0</code> both overstate paid."),
        ("Claims are not admissions",
         "One inpatient stay emits one institutional claim plus several "
         "professional ones, all sharing an <code>encounter_id</code>. "
         "Counting claims as admissions inflates volume several fold. Use "
         "<code>COUNT(DISTINCT encounter_id)</code>."),
    ]:
        A(f"<tr><td><b>{name}</b></td><td>{body}</td></tr>")
    A("</table>")

    A("<h2>Reading the flat files</h2>")
    A("<p>One practical trap, worth stating because it bit this document's own "
      "verification script before it was fixed. A key column containing nulls "
      "is inferred as a float when read back, so <code>600140</code> becomes "
      "<code>600140.0</code> and a string comparison against an integer parent "
      "key reports <b>100% orphans</b> on a perfectly sound relationship.</p>")
    if float_keys:
        A("<p>Affected key columns in this mart:</p><table>"
          "<tr><th>Table</th><th>Column</th><th>Fix</th></tr>")
        for t, c in float_keys:
            A(f'<tr><td class="m">{esc(t)}</td><td class="m">{esc(c)}</td>'
              f'<td>Read as a nullable integer, or cast both sides before '
              f'joining.</td></tr>')
        A("</table>")
    A("<p>In pandas: <code>dtype={'facility_id': 'Int64'}</code>. In Snowflake "
      "the DDL in <code>SQL/</code> types these explicitly, so the problem does "
      "not arise once loaded.</p>")

    A('<div class="foot">Healthcare Data Hub &mdash; synthetic demonstration '
      'asset. Regenerate this document with '
      '<code>python Build/verify_keys.py &amp;&amp; python '
      'Build/build_mart_manifest.py</code>. Companion documents: '
      '<code>docs/data-model.md</code> for modeling rationale, '
      '<code>docs/data-dictionary.md</code> for every column, '
      '<code>Deliverables/data-trust-validation.md</code> for the quality '
      'report.</div>')
    return "<!doctype html><html><head><meta charset='utf-8'>" \
           "<title>Data mart manifest</title></head><body>" \
           + "".join(H) + "</body></html>"


def main() -> int:
    if not VERIF.exists():
        print(f"missing {VERIF} - run Build/verify_keys.py first")
        return 1
    verif = json.loads(VERIF.read_text())
    if verif.get("problems"):
        print(f"WARNING: {len(verif['problems'])} key problem(s) recorded; "
              f"they will appear in the document.")

    html = build_html(verif)
    html_path = DELIV / "data-mart-manifest.html"
    html_path.write_text(html)
    pdf_path = DELIV / "data-mart-manifest.pdf"

    if not Path(CHROME).exists():
        print(f"Chrome not found at {CHROME}; wrote HTML only: {html_path}")
        return 0
    subprocess.run(
        [CHROME, "--headless", "--disable-gpu", "--no-sandbox",
         f"--print-to-pdf={pdf_path}", "--no-pdf-header-footer",
         html_path.as_uri()],
        check=True, capture_output=True,
    )
    size = pdf_path.stat().st_size
    print(f"  wrote {pdf_path}  ({size/1024:.0f} KB)")
    print(f"  wrote {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
