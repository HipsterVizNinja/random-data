#!/usr/bin/env python3
"""Attach a description to every published metric in Retail Sales Activity.

Retail Sales Activity predates the gen_*.py generators, so its spec lives only
in Sigma. This script round-trips it: fetch the spec, apply METRIC_DESCRIPTIONS
keyed by (element id, metric id), assert nothing published is left undocumented,
and PUT it back.

Every figure quoted in a description was verified against the live model on
2026-09-13 (model version 26). Re-run the queries in VERIFIED_AGAINST before
trusting them if the underlying CSVs change.

Usage:
    python3 describe_sales_activity_metrics.py          # write body, dry run
    python3 describe_sales_activity_metrics.py --publish
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

DATA_MODEL_ID = "8c548776-acb2-46ac-b60d-dd5a70781bd2"

# Elements exposed as data sources, per MCP describe (type "datamodel").
# In the spec round-trip, hidden elements carry visibleAsSource: false and
# published ones simply omit the key -- absent means visible, so republishing
# the spec unchanged preserves exposure.
PUBLISHED_ELEMENTS = {
    "dim_date", "dim_product", "dim_store", "dim_customer",
    "dim_salesperson", "dim_promotion",
    "sales_activity", "sales_orders", "budget", "markdowns",
}

VERIFIED_AGAINST = """
Company-wide, FY2021-FY2025, no filters (Sigma MCP query against the model):
  Gross Sales    1,178,971,663.73    Net Units        8,584,150
  Returns           64,116,011.81    Net Cost       895,884,767.32
  Net Sales      1,114,855,651.92    Net Gross Mgn  218,970,884.60
  Return Rate %          5.4383%     Net Margin %        19.6412%
  Gross Units        9,045,207       Order Count        717,747
  Customer Count         4,867       AOV              1,553.27
  Gross AOV          1,642.60        UPT                  11.96
  Frequency            147.47        Spend/Customer 229,064.24
  AUR                  129.87        AUC                 104.36
  Budget Sales   1,149,361,279.30    Budget Units       700,141

Budget Units is an order plan, not a unit plan -- budget units / actual orders
by fiscal year: 0.976, 0.975, 0.974, 0.976, 0.976, while budget units / actual
net units drifts 0.084 -> 0.078. Store 6 / FY2021 / period 8: budget units 28,
actual orders 28, actual units 320.

Activity Type, not Transaction Type, separates sales from returns:
  Sale/Purchase  1,167,035,172.72   Sale/Return    11,936,491.01  (positive!)
  Return/Purchase  -63,506,418.61   Return/Return    -609,593.20
"""

# (element id, metric id) -> description
METRIC_DESCRIPTIONS = {
    # ---- Sales Activity (line grain: sale and return lines in one fact) ----
    ("sales_activity", "m_gross_sales"): (
        "Sale-line revenue before any returns are netted out. $1,178,971,663.73 "
        "company-wide across FY2021-FY2025. This is the correct denominator for "
        "Return Rate %. Sales and returns are separated by Activity Type, not by "
        "Transaction Type -- the latter flags $11.9M of positive-amount SALE lines "
        "as 'Return' and is unrelated to the returns ledger."
    ),
    ("sales_activity", "m_returns"): (
        "Returned revenue as a POSITIVE number (return rows carry a negative Amount, "
        "which the formula re-signs). $64,116,011.81 company-wide, 5.44% of Gross "
        "Sales. Returns are dated by Activity Date -- when the refund happened. "
        "Group by Sale Date instead to age a return back to the period that sold it."
    ),
    ("sales_activity", "m_net_sales"): (
        "Headline revenue, net of returns: sale and return lines summed together. "
        "$1,114,855,651.92 company-wide across FY2021-FY2025, equal to Gross Sales "
        "minus Returns. Fully additive across every dimension in the model."
    ),
    ("sales_activity", "m_return_rate"): (
        "Returns as a share of GROSS sales. 5.44% company-wide. The denominator is "
        "deliberately gross, not net: dividing by Net Sales instead reads 5.75%, "
        "because the returned dollars have already been subtracted from it."
    ),
    ("sales_activity", "m_gross_units"): (
        "Units sold before returns. 9,045,207 company-wide across FY2021-FY2025."
    ),
    ("sales_activity", "m_net_units"): (
        "Units sold net of units returned. 8,584,150 company-wide -- 461,057 units "
        "came back. This is the denominator for UPT, AUR and AUC."
    ),
    ("sales_activity", "m_net_cost"): (
        "Cost of goods net of returns. $895,884,767.32 company-wide. Return lines "
        "carry a negative Cost, so returned goods credit their cost back out."
    ),
    ("sales_activity", "m_net_gross_margin"): (
        "Gross margin in dollars, net of returns: Net Sales minus Net Cost. "
        "$218,970,884.60 company-wide. Merchandise margin only -- it carries no "
        "labour, occupancy, markdown or freight."
    ),
    ("sales_activity", "m_net_margin"): (
        "Gross margin as a share of revenue: Net Gross Margin / Net Sales. 19.64% "
        "company-wide. The denominator is Net Sales, so this is margin ON sales, "
        "not markup on cost -- the same dollars over Net Cost would read 24.44%."
    ),
    ("sales_activity", "m_order_count"): (
        "Distinct orders containing at least one sale line. 717,747 company-wide. "
        "Return-only activity never creates an order here, so refunds cannot inflate "
        "the denominator of AOV, Gross AOV or UPT. Non-additive: it recomputes at "
        "every level of rollup and must never be summed."
    ),
    ("sales_activity", "m_customer_count"): (
        "Distinct customers who bought on a sale line. 4,867 company-wide. "
        "Non-additive -- recomputed at every rollup, never summed. Note the dataset "
        "holds only 4,867 customers across five years, so every per-customer metric "
        "built on it runs far above real-world retail."
    ),
    ("sales_activity", "m_aov"): (
        "Average order value, net of returns: Net Sales / Order Count. $1,553.27 "
        "company-wide. The numerator is net of refunds but the denominator counts "
        "only sale orders, so returns pull AOV down without reducing order count. "
        "Use Gross AOV for basket size as actually rung."
    ),
    ("sales_activity", "m_gross_aov"): (
        "Average basket as rung at the till, before any later return: Gross Sales / "
        "Order Count. $1,642.60 company-wide."
    ),
    ("sales_activity", "m_upt"): (
        "Units per transaction, net of returned units: Net Units / Order Count. "
        "11.96 company-wide."
    ),
    ("sales_activity", "m_frequency"): (
        "Orders per customer: Order Count / Customer Count. 147.47 company-wide "
        "across FY2021-FY2025 -- an artefact of the dataset's 4,867-customer roster, "
        "not a real-world purchase rate. Only meaningful inside a time filter, and "
        "always recomputed rather than summed."
    ),
    ("sales_activity", "m_spend_per_customer"): (
        "Net Sales / Customer Count. $229,064.24 company-wide across FY2021-FY2025 "
        "-- inflated by the dataset's 4,867-customer roster, so read it within a "
        "period filter. Equals AOV x Frequency."
    ),
    ("sales_activity", "m_aur"): (
        "Average unit retail: Net Sales / Net Units. $129.87 company-wide. This is "
        "the realised selling price per unit after returns and markdowns, not list "
        "price -- list price lives on the Product dimension."
    ),
    ("sales_activity", "m_auc"): (
        "Average unit cost: Net Cost / Net Units. $104.36 company-wide, leaving "
        "$25.51 of margin per unit against an AUR of $129.87."
    ),
    # ---- Sales Orders (one row per order) ----
    ("sales_orders", "m_orders"): (
        "Distinct orders at order grain. 717,747, tying exactly to Order Count on "
        "Sales Activity. Use this element when slicing by order-level attributes, "
        "which would fan out over the line-grain fact. Non-additive."
    ),
    ("sales_orders", "m_customers"): (
        "Distinct customers placing orders. 4,867, tying exactly to Customer Count "
        "on Sales Activity. Non-additive -- recomputed at every rollup."
    ),
    # ---- Budget (store x fiscal period plan) ----
    ("budget", "m_budget_sales"): (
        "Planned sales. $1,149,361,279.30 company-wide against actual Net Sales of "
        "$1,114,855,651.92 -- 97.0% attainment. The plan is store x fiscal period "
        "grain and covers the 200 stores (not the Central Warehouse) across all four "
        "channels, so join on Store Key + Fiscal Year + Fiscal Period and never to a "
        "finer grain than a period."
    ),
    ("budget", "m_budget_units"): (
        "Plans TRANSACTIONS, not units, despite the name. 700,141 company-wide, "
        "tracking actual Order Count at 97.5% in every one of the five fiscal years "
        "while amounting to only ~8% of actual Net Units. Compare it to Order Count; "
        "comparing it to Net Units reads as 8% attainment and is wrong."
    ),
}


# (element id, column id) -> description, for columns whose existing text is
# contradicted by a metric description above. Budget Units was documented as a
# unit plan; it is an order plan (see VERIFIED_AGAINST).
COLUMN_DESCRIPTIONS = {
    ("budget", "budget_units"): (
        "Planned TRANSACTION count for this store and fiscal period, despite the "
        "name -- it tracks actual order count at ~97.5% every fiscal year and is "
        "only ~8% of actual units. Compare to Order Count, not Net Units."
    ),
}


def sigma(*args, body=None):
    """Run the Sigma CLI against the playground profile.

    SIGMA_* env vars in ~/.claude/settings.json point at a different org and win
    over -p, so they are stripped per call.
    """
    cmd = ["env", "-u", "SIGMA_CLIENT_ID", "-u", "SIGMA_CLIENT_SECRET",
           "-u", "SIGMA_BASE_URL", "sigma", "-p", "playground", "api", *args]
    if body:
        cmd += ["--body", f"@{body}"]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"sigma CLI failed:\n{out.stdout}\n{out.stderr}")
    return out.stdout


def main():
    publish = "--publish" in sys.argv

    org = json.loads(sigma("whoami", "get"))
    assert org["organizationId"] == "b724be11-9ac7-4afb-9ad4-fdfa6575bafb", \
        f"expected playground org, got {org['organizationId']}"

    spec = json.loads(sigma("data-models", "spec", "get",
                            "--params", json.dumps({"dataModelId": DATA_MODEL_ID})))

    applied, cols_applied, missing = 0, 0, []
    for page in spec["pages"]:
        for element in page["elements"]:
            eid = element.get("id")
            for column in element.get("columns") or []:
                key = (eid, column.get("id"))
                if key in COLUMN_DESCRIPTIONS:
                    column["description"] = COLUMN_DESCRIPTIONS[key]
                    cols_applied += 1
            for metric in element.get("metrics") or []:
                key = (eid, metric.get("id"))
                if key in METRIC_DESCRIPTIONS:
                    metric["description"] = METRIC_DESCRIPTIONS[key]
                    applied += 1
                elif eid in PUBLISHED_ELEMENTS:
                    missing.append(f"{eid}.{metric.get('id')} ({metric.get('name')})")

    # A published metric without a description is a build failure: the MCP
    # describe output is what an agent reads before choosing a metric.
    assert not missing, "published metrics lacking a description:\n  " + "\n  ".join(missing)

    unused = set(METRIC_DESCRIPTIONS) - {
        (e.get("id"), m.get("id"))
        for p in spec["pages"] for e in p["elements"] for m in (e.get("metrics") or [])
    }
    assert not unused, f"descriptions for metrics that no longer exist: {sorted(unused)}"
    assert cols_applied == len(COLUMN_DESCRIPTIONS), \
        f"applied {cols_applied} of {len(COLUMN_DESCRIPTIONS)} column descriptions"

    # PUT wants schemaVersion but not folderId; the server-side metadata from
    # the GET round-trip is not part of the spec.
    body = {
        "schemaVersion": 1,
        "kind": spec["kind"],
        "name": spec["name"],
        "description": spec.get("description", ""),
        "pages": spec["pages"],
    }

    path = Path(tempfile.gettempdir()) / "rsa_spec_described.json"
    path.write_text(json.dumps(body))
    print(f"applied {applied} metric and {cols_applied} column descriptions -> {path}")

    if not publish:
        print("dry run; pass --publish to write it back")
        return

    result = sigma("data-models", "spec", "update",
                   "--params", json.dumps({"dataModelId": DATA_MODEL_ID}),
                   body=str(path))
    print(result)


if __name__ == "__main__":
    main()
