#!/usr/bin/env python3
"""Build and publish "Retail Sales Activity" as a Tableau published data source.

A Tableau replica of the Sigma data model of the same name
(8c548776-acb2-46ac-b60d-dd5a70781bd2, playground org): the Sales Activity fact
-- sale and return lines unioned at order-line grain -- with the five conformed
dimensions it uses left-joined onto it, and the model's 18 metrics as calculated
fields. The dimensions are joined rather than related: Tableau Cloud mis-binds a
hand-written object graph of three or more related tables (see tdsbuild.
Datasource.joins), and joining is what the Sigma element does anyway -- it
left-joins the same five dimensions into one flattened fact.

The metric descriptions are imported from describe_sales_activity_metrics.py so
Sigma and Tableau document the metrics from one source. Every figure they quote
is re-verified against the extract by --verify before anything is published.

Usage:
    python3 tableau/build_sales_activity.py            # build the .tdsx only
    python3 tableau/build_sales_activity.py --publish  # build, verify, publish
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hyperwrite
import prep_sales_activity as prep
import tdsbuild
from tdsbuild import Calc, Col, Table

from describe_sales_activity_metrics import METRIC_DESCRIPTIONS

PROJECT_ID = "d0162af7-0be2-4fed-9a3a-b43d8ada2443"   # Retail, concorddemo site
DS_NAME = "Retail Sales Activity"
BUILD_DIR = os.environ.get("RETAIL_TABLEAU_BUILD_DIR", "/tmp/retail_tableau")

MONEY, UNITS, PCT, RATIO = "$#,##0.00", "#,##0", "0.00%", "#,##0.00"

DS_DESCRIPTION = (
    "Sale and return lines in one fact at order-line grain, with the conformed "
    "Date, Product, Store, Customer and Salesperson dimensions left-joined on. "
    "Tableau replica of the Sigma data model of the same name. Activity Type "
    "separates sales from returns -- Transaction Type does not. Returns are "
    "dated by Activity Date (when the refund happened); group by Sale Date to "
    "age one back to the period that sold it."
)

# ---------------------------------------------------------------- fact ----
FACT = [
    Col("Activity Type", "string", desc=(
        "Sale or Return. This, not Transaction Type, is what separates the two "
        "sides of the fact. Return rows carry a negative Quantity, Amount and Cost, "
        "so a plain Sum over the fact is already net of returns.")),
    Col("Activity Date", "date", desc=(
        "When the activity happened: the order date on a sale line, the refund date "
        "on a return line. This is the column related to the Date dimension, so a "
        "return falls in the period that refunded it.")),
    Col("Sale Date", "date", desc=(
        "Date of the originating order, carried on both sale and return lines. "
        "Group by this instead of Activity Date to age a return back to the period "
        "that sold it.")),
    Col("Sale Timestamp", "datetime", desc=(
        "Timestamp of the originating order. Selling hours run 09:00-20:00.")),
    Col("Order Number", "integer", desc=(
        "Order the line belongs to. A return line inherits the order number of the "
        "sale it reverses, so returns never create orders of their own.")),
    Col("Product Key", "integer", desc="Relates to the Product dimension."),
    Col("Store Key", "integer", desc=(
        "Selling store, from the originating order. Relates to the Store dimension. "
        "Key 9999 is the warehouse, which carries the web orders.")),
    Col("Cust Key", "integer", desc="Relates to the Customer dimension."),
    Col("Salesperson Key", "integer", desc="Relates to the Salesperson dimension."),
    Col("Channel Type", "string", desc=(
        "Retail, Web, BOPIS or BOSS, from the originating order.")),
    Col("Transaction Type", "string", desc=(
        "Order-level flag from the source system. NOT the sale/return split: it "
        "marks $11.9M of positive-amount sale lines as 'Return' and is unrelated to "
        "the returns ledger. Use Activity Type.")),
    Col("Purchase Method", "string", desc="Tender used on the originating order."),
    Col("Quantity", "integer", "measure", fmt=UNITS, desc=(
        "Units, negative on return lines. Sums to Net Units; summed over sale lines "
        "only it is Gross Units.")),
    Col("Amount", "real", "measure", fmt=MONEY, desc=(
        "Line revenue, negative on return lines. Sums to Net Sales.")),
    Col("Cost", "real", "measure", fmt=MONEY, desc=(
        "Cost of goods, negative on return lines. On a return it is derived from the "
        "matched sale line -- returned units times that line's unit cost -- not from "
        "the returns feed, which carries no cost.")),
    Col("Return Reason", "string", desc="Why the item came back; null on sale lines."),
    Col("Restocked", "string", desc=(
        "Whether returned goods went back into stock; null on sale lines.")),
    Col("Gross Margin", "real", "measure", fmt=MONEY, desc=(
        "Amount minus Cost at line grain. Merchandise margin only -- no labour, "
        "occupancy, markdown or freight.")),
]

# ---------------------------------------------------------- dimensions ----
DATE = [
    Col("Date Key", "date", desc="Grain of the dimension: one row per calendar day."),
    Col("Day of Week Name", "string"), Col("Day of Week Number", "integer"),
    Col("Day of Month", "integer"), Col("Day of Year", "integer"),
    Col("Week Start Date", "date"), Col("Is Weekend", "string"),
    Col("Calendar Year", "integer"), Col("Calendar Month", "integer"),
    Col("Calendar Month Name", "string"), Col("Calendar Quarter", "integer"),
    Col("Fiscal Year", "integer", desc=(
        "Retail 4-5-4 fiscal year. The fact spans FY2021-FY2025.")),
    Col("Fiscal Quarter", "integer"), Col("Fiscal Period", "integer"),
    Col("Fiscal Period Name", "string"), Col("Fiscal Week of Year", "integer"),
    Col("Fiscal Week of Period", "integer"), Col("Fiscal Year Day Number", "integer"),
    Col("Is 53rd Week", "string"), Col("Fiscal Season", "string"),
    Col("Fiscal Year Start Date", "date"), Col("Fiscal Year End Date", "date"),
    Col("Fiscal Quarter Start Date", "date"), Col("Fiscal Quarter End Date", "date"),
    Col("Fiscal Period Start Date", "date"), Col("Fiscal Period End Date", "date"),
    Col("Fiscal Season Start Date", "date"), Col("Fiscal Season End Date", "date"),
    Col("Fiscal Quarter Day Number", "integer"), Col("Fiscal Period Day Number", "integer"),
    Col("Fiscal Season Day Number", "integer"),
    Col("Prior Year Date", "date", desc=(
        "Same fiscal weekday one year back -- the correct comparison date for a "
        "4-5-4 calendar, where the same calendar date lands on a different weekday.")),
]

PRODUCT = [
    Col("Product Key", "integer"), Col("Product Name", "string"),
    Col("Product Type", "string"), Col("Product Family", "string"),
    Col("Product Line", "string"), Col("Product Group", "string"),
    Col("Sku Number", "string"),
    Col("Price", "real", "measure", fmt=MONEY, agg="Avg", desc=(
        "List price. Realised price per unit is AUR, which runs below this after "
        "markdowns and returns.")),
    Col("Product Status", "string"), Col("Vendor Key", "integer"),
]

STORE = [
    Col("Store Key", "integer", desc=(
        "201 locations: 200 selling stores plus key 9999, the warehouse that "
        "carries every web order. Filter 9999 out for store-level reporting.")),
    Col("Store Name", "string"), Col("Store Address", "string"),
    Col("Store City", "string", semantic_role="[City].[Name]"),
    Col("Store State", "string", semantic_role="[State].[Name]"),
    Col("Store Zip Code", "string", semantic_role="[ZipCode].[Name]"),
    Col("Store County", "string"), Col("Store Region", "string"),
    Col("Store Area", "string"), Col("Store Type", "string"),
    Col("Store Size", "string"), Col("Store Open Date", "datetime"),
    Col("Last Layout Update", "datetime"),
    Col("Selling Square Footage", "integer", "measure", fmt=UNITS, agg="Sum"),
    Col("Total Square Footage", "integer", "measure", fmt=UNITS, agg="Sum"),
    Col("Number of Employees", "integer", "measure", fmt=UNITS, agg="Sum"),
    Col("Online Ordering", "string"),
    Col("Latitude", "real", "measure", agg="Avg"),
    Col("Longitude", "real", "measure", agg="Avg"),
    Col("Weekday Open Hour", "integer"), Col("Weekday Close Hour", "integer"),
    Col("Sunday Open Hour", "integer"), Col("Sunday Close Hour", "integer"),
]

CUSTOMER = [
    Col("Cust Key", "integer", desc=(
        "The roster holds only 4,972 customers, 4,867 of whom ever buy. Every "
        "per-customer metric therefore runs far above real-world retail.")),
    Col("Cust Name", "string"), Col("Cust Address", "string"),
    Col("Cust City", "string", semantic_role="[City].[Name]"),
    Col("Cust State", "string", semantic_role="[State].[Name]"),
    Col("Cust Zip Code", "string", semantic_role="[ZipCode].[Name]"),
    Col("Cust County", "string"), Col("Cust Region", "string"),
    Col("Cust Since", "datetime"), Col("Cust Type", "string"),
    Col("Cust Gender", "string"),
    Col("Cust Age", "integer", "measure", fmt=UNITS, agg="Avg"),
    Col("Age Group", "string"), Col("Civil Status", "string"),
    Col("Loyalty Program", "integer"), Col("Loyalty Tier", "string"),
    Col("Downloaded App", "integer"),
]

SALESPERSON = [
    Col("Salesperson Key", "integer"), Col("Salesperson Name", "string"),
    Col("Store Key", "integer", desc="Home store of the salesperson."),
    Col("Tier", "string"), Col("Hire Date", "datetime"),
    Col("Employment Status", "string"), Col("Termination Date", "datetime"),
    Col("Tenure Years", "real", "measure", fmt=RATIO, agg="Avg"),
    Col("Commission Rate", "real", "measure", fmt="0.00%", agg="Avg"),
]

# ------------------------------------------------------------- metrics ----
def _desc(metric_id):
    return METRIC_DESCRIPTIONS[("sales_activity", metric_id)]


METRICS = [
    Calc("Gross Sales", 'SUM(IIF([Activity Type] = "Sale", [Amount], 0))',
         fmt=MONEY, desc=_desc("m_gross_sales")),
    Calc("Returns", 'SUM(IIF([Activity Type] = "Return", -[Amount], 0))',
         fmt=MONEY, desc=_desc("m_returns")),
    Calc("Net Sales", "SUM([Amount])", fmt=MONEY, desc=_desc("m_net_sales")),
    Calc("Return Rate %", "[Returns] / [Gross Sales]", fmt=PCT,
         desc=_desc("m_return_rate")),
    Calc("Gross Units", 'SUM(IIF([Activity Type] = "Sale", [Quantity], 0))',
         dtype="integer", fmt=UNITS, desc=_desc("m_gross_units")),
    Calc("Net Units", "SUM([Quantity])", dtype="integer", fmt=UNITS,
         desc=_desc("m_net_units")),
    Calc("Net Cost", "SUM([Cost])", fmt=MONEY, desc=_desc("m_net_cost")),
    Calc("Net Gross Margin", "SUM([Amount]) - SUM([Cost])", fmt=MONEY,
         desc=_desc("m_net_gross_margin")),
    Calc("Net Margin %", "[Net Gross Margin] / [Net Sales]", fmt=PCT,
         desc=_desc("m_net_margin")),
    Calc("Order Count", 'COUNTD(IIF([Activity Type] = "Sale", [Order Number], NULL))',
         dtype="integer", fmt=UNITS, desc=_desc("m_order_count")),
    Calc("Customer Count", 'COUNTD(IIF([Activity Type] = "Sale", [Cust Key], NULL))',
         dtype="integer", fmt=UNITS, desc=_desc("m_customer_count")),
    Calc("AOV", "[Net Sales] / [Order Count]", fmt=MONEY, desc=_desc("m_aov")),
    Calc("Gross AOV", "[Gross Sales] / [Order Count]", fmt=MONEY,
         desc=_desc("m_gross_aov")),
    Calc("UPT", "[Net Units] / [Order Count]", fmt=RATIO, desc=_desc("m_upt")),
    Calc("Frequency", "[Order Count] / [Customer Count]", fmt=RATIO,
         desc=_desc("m_frequency")),
    Calc("Spend per Customer", "[Net Sales] / [Customer Count]", fmt=MONEY,
         desc=_desc("m_spend_per_customer")),
    Calc("AUR", "[Net Sales] / [Net Units]", fmt=MONEY, desc=_desc("m_aur")),
    Calc("AUC", "[Net Cost] / [Net Units]", fmt=MONEY, desc=_desc("m_auc")),
]


TABLES = [("Sales Activity", FACT), ("Date", DATE), ("Product", PRODUCT),
          ("Store", STORE), ("Customer", CUSTOMER), ("Salesperson", SALESPERSON)]


def build():
    os.makedirs(BUILD_DIR, exist_ok=True)
    print("preparing frames from the source CSVs ...", flush=True)
    activity = prep.build_activity()
    dims = prep.build_dims()

    hyper = os.path.join(BUILD_DIR, "retail_sales_activity.hyper")
    print("writing extract ...", flush=True)
    frames = {"Sales Activity": activity, **dims}
    hyperwrite.write_hyper(hyper, [(name, columns, frames[name])
                                   for name, columns in TABLES])
    print(f"  {os.path.getsize(hyper) / 1e6:.0f} MB", flush=True)

    datasource = tdsbuild.Datasource(
        name=DS_NAME,
        hyper_file=hyper,
        tables=[Table(name, columns) for name, columns in TABLES],
        joins=[
            ("Sales Activity", "Activity Date", "Date", "Date Key"),
            ("Sales Activity", "Product Key", "Product", "Product Key"),
            ("Sales Activity", "Store Key", "Store", "Store Key"),
            ("Sales Activity", "Cust Key", "Customer", "Cust Key"),
            ("Sales Activity", "Salesperson Key", "Salesperson", "Salesperson Key"),
        ],
        calcs=METRICS,
    )
    # No folders: a <folder> element of any kind stops Tableau Pulse reading the
    # data source (see tdsbuild.Datasource._folders). The joined model already
    # groups fields by source table in the data pane, so little is lost.
    datasource.drill_paths = [
        ("Product Hierarchy", [datasource.dsname("Product", c) for c in
                               ("Product Type", "Product Family", "Product Line",
                                "Product Name")]),
        ("Store Hierarchy", [datasource.dsname("Store", c) for c in
                             ("Store Region", "Store Area", "Store State",
                              "Store City", "Store Name")]),
        ("Fiscal Calendar", [datasource.dsname("Date", c) for c in
                             ("Fiscal Year", "Fiscal Quarter", "Fiscal Period",
                              "Fiscal Week of Year")]),
    ]
    tdsx = os.path.join(BUILD_DIR, f"{DS_NAME}.tdsx")
    datasource.write_tdsx(tdsx)
    print(f"built {tdsx} ({os.path.getsize(tdsx) / 1e6:.0f} MB)")
    return tdsx


def main():
    tdsx = build()
    if "--publish" not in sys.argv:
        print("dry run; pass --publish to publish to the Retail project")
        return
    import publish
    import tabapi
    token, site_id, _ = tabapi.signin()
    started = time.time()
    response = publish.publish(token, site_id, PROJECT_ID, DS_NAME, tdsx,
                               description=DS_DESCRIPTION)
    print(response.status_code, response.text[:800])
    print(f"published in {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
