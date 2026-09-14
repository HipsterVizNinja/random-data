"""Generate the Retail Inventory & Replenishment data model spec.

Emits JSON on stdout for POST /v2/dataModels/spec (create) or
PUT /v2/dataModels/{id}/spec (update).

The one hard problem in this model is that F_INVENTORY_SNAPSHOT is a sparse
change log, not a position table: 5,954,664 rows describing 220,296
store-product pairs across a perfectly regular 218-week Sunday spine. A pair
only gets a row in a week where something changed (median 13 of 218 weeks), so
any metric computed per row is weighted by CHANGE FREQUENCY, not by TIME.
That is not a rounding difference - row-weighted stockout reads 23.46% while
the true time-weighted figure is 3.19%, because stockouts get resolved quickly
and are therefore wildly over-represented in a change log.

The fix is last-value-carried-forward, built here in two steps:

  1. inv_changes_base sorts by Store, Product, Effective Start Date and uses
     Lead() to find each row's successor. Sigma's Lead() takes no partition
     argument - it orders by the element's `sort` and nothing else - so the
     partition is enforced by guarding on the next row belonging to the same
     store-product pair. That yields Weeks In Force per change.
  2. inv_weekly_base cross-joins those changes to the 218-week spine and keeps
     the weeks each change is actually in force, materialising the dense
     position: exactly 220,296 x 218 = 48,024,528 store-product-weeks.

Every figure in the element descriptions below was verified against the source
CSVs before the model was published.
"""

import json

UPLOADS = "b765b086-4e7e-426b-ac82-7d6e0cf5a71c"
SALESACT = "8c548776-acb2-46ac-b60d-dd5a70781bd2"

# The inventory week spine: 218 consecutive Sundays, 2021-08-15 .. 2025-10-12.
# WEEK_END is exclusive - the Sunday after the last spine week.
WEEK0 = "2021-08-15"
WEEK_END = "2025-10-19"
NWEEKS = 218
# Trailing-13-week window used for current velocity (weeks 205..217).
L13_START = NWEEKS - 13

USD = {"kind": "number", "formatString": "$,.2f"}
NUM0 = {"kind": "number", "formatString": ",.0f"}
NUM2 = {"kind": "number", "formatString": ",.2f"}
PCT = {"kind": "number", "formatString": ".2%"}


def col(cid, name, formula, desc=None, fmt=None):
    c = {"id": cid, "name": name, "formula": formula}
    if desc:
        c["description"] = desc
    if fmt:
        c["format"] = fmt
    return c


def met(mid, name, formula, desc, fmt=None):
    """Every published metric carries a description - `desc` is deliberately required."""
    assert desc, f"metric {mid} has no description"
    m = {"id": mid, "name": name, "formula": formula, "description": desc}
    if fmt:
        m["format"] = fmt
    return m


def src(eid, name, model, origin_elem, origin_name, cols, desc=None):
    e = {
        "id": eid, "name": name, "kind": "table",
        "source": {"kind": "data-model", "dataModelId": model, "elementId": origin_elem},
        "columns": [col(cid, disp, f"[{origin_name}/{disp}]") for cid, disp in cols],
        "visibleAsSource": False,
    }
    if desc:
        e["description"] = desc
    return e


def passthrough(eid, name, source_name, cols):
    return [col(cid, disp, f"[{source_name}/{disp}]") for cid, disp in cols]


def lj(left, right, pairs, right_grouping=None):
    r = {"kind": "table", "elementId": right}
    if right_grouping:
        r["groupingId"] = right_grouping
    return {
        "joinType": "left-outer",
        "left": {"kind": "table", "elementId": left},
        "right": r,
        "columns": [{"left": f"[{a}]", "right": f"[{b}]"} for a, b in pairs],
    }


# ------------------------------------------------------------------ Page 1: Sources
SNAP_COLS = [("store_key", "Store Key"), ("product_key", "Product Key"),
             ("effective_start_date", "Effective Start Date"), ("qty_on_hand", "Qty On Hand"),
             ("qty_in_transit", "Qty In Transit"), ("qty_reorder_point", "Qty Reorder Point")]
ADJ_COLS = [("store_key", "Store Key"), ("product_key", "Product Key"),
            ("adjustment_date", "Adjustment Date"), ("adjustment_quantity", "Adjustment Quantity"),
            ("adjustment_reason", "Adjustment Reason")]
PO_COLS = [("po_number", "PO Number"), ("vendor_key", "Vendor Key"), ("product_key", "Product Key"),
           ("order_date", "Order Date"), ("expected_receipt_date", "Expected Receipt Date"),
           ("actual_receipt_date", "Actual Receipt Date"), ("order_quantity", "Order Quantity"),
           ("unit_cost", "Unit Cost"), ("po_status", "PO Status")]
VENDOR_COLS = [("vendor_key", "Vendor Key"), ("vendor_name", "Vendor Name"),
               ("vendor_contact_email", "Vendor Contact Email"), ("lead_time_days", "Lead Time Days"),
               ("payment_terms", "Payment Terms"), ("vendor_rating", "Vendor Rating"),
               ("vendor_since", "Vendor Since")]
PRODUCT_COLS = [("product_key", "Product Key"), ("product_name", "Product Name"),
                ("product_type", "Product Type"), ("product_family", "Product Family"),
                ("product_line", "Product Line"), ("product_group", "Product Group"),
                ("sku_number", "Sku Number"), ("price", "Price"),
                ("product_status", "Product Status"), ("vendor_key", "Vendor Key")]
STORE_COLS = [("store_key", "Store Key"), ("store_name", "Store Name"), ("store_city", "Store City"),
              ("store_state", "Store State"), ("store_region", "Store Region"),
              ("store_area", "Store Area"), ("store_type", "Store Type"), ("store_size", "Store Size"),
              ("selling_square_footage", "Selling Square Footage"),
              ("total_square_footage", "Total Square Footage"),
              ("latitude", "Latitude"), ("longitude", "Longitude")]
DATE_COLS = [("date_key", "Date Key"), ("day_of_week_name", "Day of Week Name"),
             ("is_weekend", "Is Weekend"), ("week_start_date", "Week Start Date"),
             ("calendar_year", "Calendar Year"), ("calendar_month", "Calendar Month"),
             ("calendar_month_name", "Calendar Month Name"), ("calendar_quarter", "Calendar Quarter"),
             ("fiscal_year", "Fiscal Year"), ("fiscal_quarter", "Fiscal Quarter"),
             ("fiscal_period", "Fiscal Period"), ("fiscal_period_name", "Fiscal Period Name"),
             ("fiscal_week_of_year", "Fiscal Week of Year"), ("fiscal_season", "Fiscal Season"),
             ("prior_year_date", "Prior Year Date")]
SA_COLS = [("store_key", "Store Key"), ("product_key", "Product Key"), ("sale_date", "Sale Date"),
           ("activity_type", "Activity Type"), ("channel_type", "Channel Type"),
           ("quantity", "Quantity"), ("amount", "Amount"), ("cost", "Cost")]

sources = [
    src("src_snapshot", "SRC F_INVENTORY_SNAPSHOT", UPLOADS, "GhsoE2qPVa",
        "F_INVENTORY_SNAPSHOT.csv", SNAP_COLS,
        "Sparse change log, 5,954,664 rows. One row per store-product only in weeks where the "
        "position changed - NOT a weekly position table. Never aggregate it directly."),
    src("src_adjustment", "SRC F_INVENTORY_ADJUSTMENT", UPLOADS, "zHwedhbPcB",
        "F_INVENTORY_ADJUSTMENT.csv", ADJ_COLS),
    src("src_po", "SRC F_PURCHASE_ORDER", UPLOADS, "r36SsUuGNG", "F_PURCHASE_ORDER.csv", PO_COLS),
    src("src_vendor", "SRC D_VENDOR", UPLOADS, "hlYHC0B_rD", "D_VENDOR.csv", VENDOR_COLS),
    src("src_product", "SRC Product", SALESACT, "dim_product", "Product", PRODUCT_COLS,
        "Conformed Product dimension referenced from the Retail Sales Activity model."),
    src("src_store", "SRC Store", SALESACT, "dim_store", "Store", STORE_COLS,
        "Conformed Store dimension referenced from the Retail Sales Activity model."),
    src("src_date", "SRC Date", SALESACT, "dim_date", "Date", DATE_COLS,
        "Conformed Date dimension (4-5-4 fiscal) referenced from the Retail Sales Activity model."),
    src("src_sales_activity", "SRC Sales Activity", SALESACT, "sales_activity", "Sales Activity", SA_COLS,
        "Sales + returns fact referenced from the Retail Sales Activity model, projected to the "
        "columns needed for demand velocity. Returns carry negative Quantity, Amount and Cost, so "
        "plain sums are already net."),
]

# ------------------------------------------------------------------ Page 2: Conformed Dimensions
product_cost = {
    "id": "product_cost", "name": "Product Cost", "kind": "table", "visibleAsSource": False,
    "description": "Quantity-weighted average unit cost per product, derived from every purchase "
                   "order line. All 1,096 products are covered. This is the only true unit cost in "
                   "the mart - D_PRODUCT carries retail Price only - so it is what values inventory.",
    "source": {"kind": "table", "elementId": "src_po"},
    "columns": [
        col("product_key", "Product Key", "[SRC F_PURCHASE_ORDER/Product Key]"),
        col("po_units", "PO Units Ordered", "Sum([SRC F_PURCHASE_ORDER/Order Quantity])", fmt=NUM0),
        col("po_cost_value", "PO Cost Value",
            "Sum([SRC F_PURCHASE_ORDER/Order Quantity] * [SRC F_PURCHASE_ORDER/Unit Cost])", fmt=USD),
    ],
    "groupings": [{"id": "g_pcost", "groupBy": ["product_key"],
                   "calculations": ["po_units", "po_cost_value"]}],
}

dim_product = {
    "id": "dim_product", "name": "Product", "kind": "table", "visibleAsSource": True,
    "description": "1,096 products with the ragged Type > Family > Line > Group hierarchy inherited "
                   "from Retail Sales Activity, enriched with Avg Unit Cost from purchase orders and "
                   "vendor attributes. Every store carries every product - the assortment is complete "
                   "by construction - so a missing store-product pair means a data gap, not a "
                   "merchandising decision.",
    "source": {"kind": "join", "primarySource": {"kind": "table", "elementId": "src_product"},
               "joins": [
                   lj("src_product", "product_cost", [("Product Key", "Product Key")], "g_pcost"),
                   lj("src_product", "src_vendor", [("Vendor Key", "Vendor Key")]),
               ]},
    "columns": passthrough("dim_product", "Product", "SRC Product", PRODUCT_COLS) + [
        col("avg_unit_cost", "Avg Unit Cost",
            "[Product Cost/PO Cost Value] / [Product Cost/PO Units Ordered]",
            "Quantity-weighted average cost paid across all purchase orders for this product. "
            "Mean across the assortment is $223.95.", USD),
        col("vendor_name", "Vendor Name", "[SRC D_VENDOR/Vendor Name]"),
        col("vendor_lead_time_days", "Vendor Lead Time Days", "[SRC D_VENDOR/Lead Time Days]",
            "Lead time the vendor quotes, in days. Compare against actual PO receipt timing in "
            "Purchase Orders rather than trusting it.", NUM0),
        col("vendor_rating", "Vendor Rating", "[SRC D_VENDOR/Vendor Rating]", fmt=NUM2),
    ],
}

dim_store = {
    "id": "dim_store", "name": "Store", "kind": "table", "visibleAsSource": True,
    "description": "200 selling stores plus the Central Warehouse (Store Key 9999). The warehouse IS "
                   "present in the inventory snapshot - unlike the Retail Store Operations model, "
                   "which covers 200 stores only - so filter it out explicitly for store-level "
                   "in-stock reporting. It also has no sales, so its Weeks of Supply is undefined.",
    "source": {"kind": "table", "elementId": "src_store"},
    "columns": passthrough("dim_store", "Store", "SRC Store", STORE_COLS),
}

dim_date = {
    "id": "dim_date", "name": "Date", "kind": "table", "visibleAsSource": True,
    "description": "Retail 4-5-4 fiscal calendar. Sigma's built-in period-over-period and DateLookback "
                   "are CALENDAR-based and will not align to 4-5-4 week boundaries; use Prior Year "
                   "Date for fiscal-correct comps.",
    "source": {"kind": "table", "elementId": "src_date"},
    "columns": passthrough("dim_date", "Date", "SRC Date", DATE_COLS),
}

dim_vendor = {
    "id": "dim_vendor", "name": "Vendor", "kind": "table", "visibleAsSource": True,
    "description": "20 vendors with quoted lead time, payment terms and rating. Vendors reach "
                   "inventory only through Product - purchase orders carry no Store Key, so vendor "
                   "performance cannot be attributed to a store.",
    "source": {"kind": "table", "elementId": "src_vendor"},
    "columns": passthrough("dim_vendor", "Vendor", "SRC D_VENDOR", VENDOR_COLS),
}

# ------------------------------------------------------------------ Page 3: Position Build (hidden)
inv_changes_base = {
    "id": "inv_changes_base", "name": "Inventory Changes Base", "kind": "table",
    "visibleAsSource": False,
    "description": "The change log with each row's period of validity resolved. Sorted by Store Key, "
                   "Product Key, Effective Start Date so that Lead() - which in Sigma orders by the "
                   "element sort and accepts no partition argument - returns the next row overall; the "
                   "same-pair guard turns that into the next row FOR THIS PAIR. Weeks In Force then "
                   "runs to the next change, or to the end of the 218-week horizon (2025-10-19 "
                   "exclusive) for the final row of each pair. Sum of Weeks In Force = 48,024,528 = "
                   "220,296 pairs x 218 weeks exactly.",
    "source": {"kind": "table", "elementId": "src_snapshot"},
    "columns": [
        col("store_key", "Store Key", "[SRC F_INVENTORY_SNAPSHOT/Store Key]"),
        col("product_key", "Product Key", "[SRC F_INVENTORY_SNAPSHOT/Product Key]"),
        col("effective_start_date", "Effective Start Date",
            "[SRC F_INVENTORY_SNAPSHOT/Effective Start Date]"),
        col("qty_on_hand", "Qty On Hand", "[SRC F_INVENTORY_SNAPSHOT/Qty On Hand]", fmt=NUM0),
        col("qty_in_transit", "Qty In Transit", "[SRC F_INVENTORY_SNAPSHOT/Qty In Transit]", fmt=NUM0),
        col("qty_reorder_point", "Qty Reorder Point",
            "[SRC F_INVENTORY_SNAPSHOT/Qty Reorder Point]", fmt=NUM0),
        col("week_index", "Week Index",
            f'Floor(DateDiff("day", Date("{WEEK0}"), [Effective Start Date]) / 7)',
            f"0-based week on the {NWEEKS}-week Sunday spine beginning {WEEK0}.", NUM0),
        col("next_effective_date", "Next Effective Date",
            "If(Lead([Store Key]) = [Store Key] and Lead([Product Key]) = [Product Key], "
            "Lead([Effective Start Date]), Null)",
            "The next change date for this same store-product pair; null on a pair's final row."),
        col("effective_end_date", "Effective End Date",
            f'Coalesce([Next Effective Date], Date("{WEEK_END}"))',
            "Exclusive end of this position's validity."),
        col("weeks_in_force", "Weeks In Force",
            'DateDiff("day", [Effective Start Date], [Effective End Date]) / 7',
            "Number of weeks this position stayed in effect. THE weighting factor: averaging any "
            "inventory measure across change-log rows without it weights by how often a pair changed "
            "rather than by time, which is how row-weighted stockout reads 23.46% against a true "
            "3.19%.", NUM0),
        col("is_current", "Is Current Position", "IsNull([Next Effective Date])",
            "True on the last change per pair - the position still standing at 2025-10-12. "
            "Exactly 220,296 rows are true."),
        col("join_key", "Join Key", "1",
            "Constant used to cross-join the week spine. Not meaningful on its own."),
    ],
    "sort": [{"columnId": "store_key", "direction": "ascending"},
             {"columnId": "product_key", "direction": "ascending"},
             {"columnId": "effective_start_date", "direction": "ascending"}],
}

week_spine = {
    "id": "week_spine", "name": "Week Spine", "kind": "table", "visibleAsSource": False,
    "description": "The 218 distinct inventory weeks, 2021-08-15 to 2025-10-12, every one exactly 7 "
                   "days after the last - verified, no gaps. Weeks are Sunday-start.",
    "source": {"kind": "table", "elementId": "src_snapshot"},
    "columns": [
        col("week_start_date", "Week Start Date", "[SRC F_INVENTORY_SNAPSHOT/Effective Start Date]"),
        col("spine_week_index", "Spine Week Index",
            f'Floor(DateDiff("day", Date("{WEEK0}"), [Week Start Date]) / 7)', fmt=NUM0),
        col("spine_join_key", "Join Key", "1"),
    ],
    "groupings": [{"id": "g_spine",
                   "groupBy": ["week_start_date", "spine_week_index", "spine_join_key"],
                   "calculations": []}],
}

sales_week = {
    "id": "sales_week", "name": "Sales Week", "kind": "table", "visibleAsSource": False,
    "description": "Sales activity collapsed to Store Key x Product Key x inventory week. MANDATORY "
                   "pre-aggregation - joining raw order lines to the weekly position would fan it out. "
                   "Sale dates span 2021-08-19 to 2025-10-18, landing entirely inside weeks 0-217, so "
                   "nothing falls off either end of the spine.",
    "source": {"kind": "table", "elementId": "src_sales_activity"},
    "columns": [
        col("store_key", "Store Key", "[SRC Sales Activity/Store Key]"),
        col("product_key", "Product Key", "[SRC Sales Activity/Product Key]"),
        col("sale_week_index", "Sale Week Index",
            f'Floor(DateDiff("day", Date("{WEEK0}"), [SRC Sales Activity/Sale Date]) / 7)', fmt=NUM0),
        col("net_units", "Net Units", "Sum([SRC Sales Activity/Quantity])", fmt=NUM0),
        col("retail_net_units", "Retail Net Units",
            'Sum(If([SRC Sales Activity/Channel Type] = "Retail", [SRC Sales Activity/Quantity], 0))',
            fmt=NUM0),
        col("net_sales", "Net Sales", "Sum([SRC Sales Activity/Amount])", fmt=USD),
        col("net_cogs", "Net COGS", "Sum([SRC Sales Activity/Cost])", fmt=USD),
    ],
    "groupings": [{"id": "g_sales_week",
                   "groupBy": ["store_key", "product_key", "sale_week_index"],
                   "calculations": ["net_units", "retail_net_units", "net_sales", "net_cogs"]}],
}

pair_velocity = {
    "id": "pair_velocity", "name": "Pair Velocity", "kind": "table", "visibleAsSource": False,
    "description": "Lifetime and trailing demand per store-product pair, for Weeks of Supply on the "
                   "current position. Only 142,355 of the 220,296 carried pairs ever sold a unit.",
    "source": {"kind": "table", "elementId": "src_sales_activity"},
    "columns": [
        col("store_key", "Store Key", "[SRC Sales Activity/Store Key]"),
        col("product_key", "Product Key", "[SRC Sales Activity/Product Key]"),
        col("lifetime_net_units", "Lifetime Net Units", "Sum([SRC Sales Activity/Quantity])", fmt=NUM0),
        col("units_l13w", "Units L13W",
            f'Sum(If(Floor(DateDiff("day", Date("{WEEK0}"), [SRC Sales Activity/Sale Date]) / 7) '
            f">= {L13_START}, [SRC Sales Activity/Quantity], 0))", fmt=NUM0),
        col("units_l52w", "Units L52W",
            f'Sum(If(Floor(DateDiff("day", Date("{WEEK0}"), [SRC Sales Activity/Sale Date]) / 7) '
            f">= {NWEEKS - 52}, [SRC Sales Activity/Quantity], 0))", fmt=NUM0),
    ],
    "groupings": [{"id": "g_velocity", "groupBy": ["store_key", "product_key"],
                   "calculations": ["lifetime_net_units", "units_l13w", "units_l52w"]}],
}

inv_weekly_base = {
    "id": "inv_weekly_base", "name": "Inventory Weekly Base", "kind": "table",
    "visibleAsSource": False,
    "description": "The carry-forward itself: every change cross-joined to the week spine, keeping "
                   "only the weeks it was actually in force. Turns 5,954,664 sparse changes into "
                   "48,024,528 dense store-product-weeks. The In Force filter is what makes the cross "
                   "join a range join - without it this is 1.3 billion rows.",
    "source": {"kind": "join", "primarySource": {"kind": "table", "elementId": "inv_changes_base"},
               "joins": [{"joinType": "inner",
                          "left": {"kind": "table", "elementId": "inv_changes_base"},
                          "right": {"kind": "table", "elementId": "week_spine",
                                    "groupingId": "g_spine"},
                          "columns": [{"left": "[Join Key]", "right": "[Join Key]"}]}]},
    "columns": [
        col("store_key", "Store Key", "[Inventory Changes Base/Store Key]"),
        col("product_key", "Product Key", "[Inventory Changes Base/Product Key]"),
        col("week_start_date", "Week Start Date", "[Week Spine/Week Start Date]"),
        col("week_index", "Week Index", "[Week Spine/Spine Week Index]", fmt=NUM0),
        col("qty_on_hand", "Qty On Hand", "[Inventory Changes Base/Qty On Hand]", fmt=NUM0),
        col("qty_in_transit", "Qty In Transit", "[Inventory Changes Base/Qty In Transit]", fmt=NUM0),
        col("qty_reorder_point", "Qty Reorder Point",
            "[Inventory Changes Base/Qty Reorder Point]", fmt=NUM0),
        col("position_since", "Position Since", "[Inventory Changes Base/Effective Start Date]",
            "The change date whose position is being carried into this week."),
        col("weeks_carried", "Weeks Carried",
            "[Week Spine/Spine Week Index] - [Inventory Changes Base/Week Index]",
            "How many weeks the position has already been unchanged at this week. 0 in the week it "
            "changed.", NUM0),
        col("in_force", "In Force",
            "[Week Spine/Spine Week Index] >= [Inventory Changes Base/Week Index] and "
            "[Week Spine/Spine Week Index] < [Inventory Changes Base/Week Index] + "
            "[Inventory Changes Base/Weeks In Force]"),
    ],
    "filters": [{"id": "f_in_force", "columnId": "in_force", "kind": "list",
                 "state": "enabled", "mode": "include", "values": [True]}],
}

# ------------------------------------------------------------------ Page 4: Inventory Position
WEEKLY_METRICS = [
    met("m_w_pair_weeks", "Store-Product-Weeks", "Count([Store Key])",
        "The denominator for every rate in this element: one per store, product and week in "
        "selection. 48,024,528 unfiltered.", NUM0),
    met("m_w_weeks", "Weeks in Selection", "CountDistinct([Week Start Date])",
        "Distinct inventory weeks in the current selection. 218 unfiltered.", NUM0),
    met("m_w_oh_unit_weeks", "On Hand Unit-Weeks", "Sum([Qty On Hand])",
        "Units multiplied by weeks held. A stock-and-time quantity, not a unit count - divide by "
        "Store-Product-Weeks to get an average position. 262,103,096 unfiltered.", NUM0),
    met("m_w_avg_on_hand", "Avg On Hand Units",
        "[Metrics/On Hand Unit-Weeks] / [Metrics/Store-Product-Weeks]",
        "Units on hand for one store and one product at any moment, averaged over the weeks in "
        "selection. 5.458 unfiltered. A per-SKU figure - for a company position use Avg Inventory "
        "Units.", NUM2),
    met("m_w_avg_in_transit", "Avg In Transit Units",
        "Sum([Qty In Transit]) / [Metrics/Store-Product-Weeks]",
        "Units inbound to a store for a product at any moment, averaged per store-SKU. 0.46 "
        "unfiltered, against 5.46 on hand - inbound stock is a twelfth of standing stock. In transit "
        "is NOT included in on hand; add the two for a total owned position.", NUM2),
    met("m_w_avg_inv_units", "Avg Inventory Units",
        "[Metrics/On Hand Unit-Weeks] / [Metrics/Weeks in Selection]",
        "Total units standing in inventory at any moment across the whole selection - a "
        "balance-sheet-style position, not a per-SKU figure. 1,202,308 unfiltered.", NUM0),
    met("m_w_avg_inv_cost", "Avg Inventory at Cost",
        "Sum([On Hand At Cost]) / [Metrics/Weeks in Selection]",
        "Total inventory value held at any moment across the selection, at quantity-weighted PO unit "
        "cost. About $261.8M unfiltered, which squares with the $260.5M standing position in "
        "Inventory Current. This is the denominator for Turns and GMROI - both need a TOTAL "
        "inventory value, never a per-SKU average.", USD),
    met("m_w_avg_inv_cost_per_sku", "Avg Inventory at Cost per Store-SKU",
        "Sum([On Hand At Cost]) / [Metrics/Store-Product-Weeks]",
        "Average inventory value carried by one store for one product. $1,188.48 unfiltered. A unit "
        "economics figure - do not use it as the denominator of Turns or GMROI.", USD),
    met("m_w_inv_cost_total", "Inventory at Cost (Dollar-Weeks)",
        "Sum([On Hand At Cost])",
        "Dollars multiplied by weeks held. Use Avg Inventory at Cost for a readable position.",
        USD),
    met("m_w_in_stock", "In-Stock %",
        "Sum([Is In Stock Week]) / [Metrics/Store-Product-Weeks]",
        "Share of store-product-weeks with any stock on hand. 96.81% unfiltered.", PCT),
    met("m_w_stockout", "Stockout Rate %",
        "Sum([Is Stockout Week]) / [Metrics/Store-Product-Weeks]",
        "Share of store-product-weeks at zero on hand. 3.19% unfiltered. This is the honest number; "
        "the change log's row-weighted 23.46% is an artefact of stockouts being fixed quickly and so "
        "appearing disproportionately often as changes.", PCT),
    met("m_w_below_rop", "Below Reorder Point %",
        "Sum([Is Below Reorder Point Week]) / [Metrics/Store-Product-Weeks]",
        "Share of store-product-weeks at or under the reorder point, stockouts included. 6.57% "
        "unfiltered.", PCT),
    met("m_w_replen_gap", "Replenishment Gap Units", "Sum([Replenishment Gap Units])",
        "Units needed to lift every at-or-below-reorder-point position back to its reorder point.",
        NUM0),
    met("m_w_net_units", "Net Units Sold", "Sum([Net Units])",
        "Units sold net of returns in this store-product-week. Null weeks are genuine zero-sales "
        "weeks.", NUM0),
    met("m_w_retail_units", "Retail Net Units Sold", "Sum([Retail Net Units])",
        "Units sold in store, net of returns, excluding web, BOPIS and BOSS orders credited to the "
        "store. 6,473,369 of 8,584,150 unfiltered - 75.4% of demand walks in. The remaining quarter "
        "still depletes physical stock when a store fulfils it, which this fact cannot see: "
        "fulfilment location lives on Sales Orders, not on the activity line.", NUM0),
    met("m_w_net_sales", "Net Sales", "Sum([Net Sales])",
        "Sales net of returns for this store-product-week, every channel. $1,114,855,651.92 "
        "unfiltered, which ties exactly to the Retail Sales Activity model - this fact neither "
        "duplicates nor drops a dollar.", USD),
    met("m_w_net_cogs", "Net COGS", "Sum([Net COGS])",
        "Cost of the units sold, net of returns. $895,884,767.32 unfiltered. This is cost of goods "
        "SOLD - for the cost of goods HELD use Avg Inventory at Cost.", USD),
    met("m_w_gross_margin", "Gross Margin", "[Metrics/Net Sales] - [Metrics/Net COGS]",
        "Net sales less net COGS. $218,970,884.60 unfiltered, a 19.64% margin rate.", USD),
    met("m_w_avg_weekly_units", "Avg Weekly Units Sold",
        "[Metrics/Net Units Sold] / [Metrics/Store-Product-Weeks]",
        "Units sold per store-product per week - the demand rate behind Weeks of Supply. 0.179 "
        "unfiltered, i.e. an average store sells a given SKU about once every 5.6 weeks. Counts "
        "zero-sales weeks in the denominator, which is what makes it a rate rather than an average "
        "of the weeks that happened to sell.", NUM2),
    met("m_w_wos", "Weeks of Supply",
        "[Metrics/Avg On Hand Units] / [Metrics/Avg Weekly Units Sold]",
        "How many weeks the average position would last at the average demand rate. Undefined where "
        "nothing sold, which includes the Central Warehouse and the 35% of pairs that never sold.",
        NUM2),
    met("m_w_sell_through", "Sell-Through %",
        "[Metrics/Net Units Sold] / ([Metrics/Net Units Sold] + [Metrics/Avg Inventory Units])",
        "Units sold against units sold plus average stock held, both as totals. Rises with the length "
        "of the window by definition, so only compare it across equal-length periods.", PCT),
    met("m_w_turns", "Inventory Turns (Annualized)",
        "([Metrics/Net COGS] / [Metrics/Avg Inventory at Cost]) * (52 / [Metrics/Weeks in Selection])",
        "COGS over average inventory at cost, scaled to a year by the weeks actually in selection, so "
        "it stays comparable under any date filter. 0.82 turns a year unfiltered - low, and consistent "
        "with a third of the assortment never selling.", NUM2),
    met("m_w_gmroi", "GMROI", "[Metrics/Gross Margin] / [Metrics/Avg Inventory at Cost]",
        "Gross margin dollars returned per dollar of inventory held, over the weeks in selection. "
        "0.84 unfiltered.", NUM2),
]

inventory_weekly = {
    "id": "inventory_weekly", "name": "Inventory Weekly", "kind": "table", "visibleAsSource": True,
    "description": "THE fact: one row per Store x Product x Week, 48,024,528 rows (220,296 "
                   "store-product pairs x 218 weeks, a complete rectangle). Built by carrying the "
                   "sparse change log forward across the weeks each position stayed in force, then "
                   "left-joining that week's sales. Because every row is exactly one week, plain "
                   "counts and averages here are time-weighted and correct - which is the whole point "
                   "of the element. Two things to know: the Central Warehouse (Store Key 9999) is "
                   "included and has inventory but no sales, so exclude it for store-level reporting; "
                   "and a null Net Units is a real zero-sales week, not missing data.",
    "source": {"kind": "join", "primarySource": {"kind": "table", "elementId": "inv_weekly_base"},
               "joins": [
                   lj("inv_weekly_base", "sales_week",
                      [("Store Key", "Store Key"), ("Product Key", "Product Key"),
                       ("Week Index", "Sale Week Index")], "g_sales_week"),
                   lj("inv_weekly_base", "dim_product", [("Product Key", "Product Key")]),
                   lj("inv_weekly_base", "dim_store", [("Store Key", "Store Key")]),
                   lj("inv_weekly_base", "dim_date", [("Week Start Date", "Date Key")]),
               ]},
    "columns": [
        col("store_key", "Store Key", "[Inventory Weekly Base/Store Key]"),
        col("product_key", "Product Key", "[Inventory Weekly Base/Product Key]"),
        col("week_start_date", "Week Start Date", "[Inventory Weekly Base/Week Start Date]",
            "Sunday that starts this inventory week."),
        col("week_index", "Week Index", "[Inventory Weekly Base/Week Index]", fmt=NUM0),
        col("qty_on_hand", "Qty On Hand", "[Inventory Weekly Base/Qty On Hand]",
            "Units on hand for the whole week, carried forward from the last change.", NUM0),
        col("qty_in_transit", "Qty In Transit", "[Inventory Weekly Base/Qty In Transit]", fmt=NUM0),
        col("qty_reorder_point", "Qty Reorder Point",
            "[Inventory Weekly Base/Qty Reorder Point]", fmt=NUM0),
        col("position_since", "Position Since", "[Inventory Weekly Base/Position Since]"),
        col("weeks_carried", "Weeks Carried", "[Inventory Weekly Base/Weeks Carried]",
            "Weeks since this position last changed. High values on a zero position mean a long-dead "
            "stockout.", NUM0),
        col("is_stockout_week", "Is Stockout Week",
            "If([Inventory Weekly Base/Qty On Hand] = 0, 1, 0)", fmt=NUM0),
        col("is_in_stock_week", "Is In Stock Week",
            "If([Inventory Weekly Base/Qty On Hand] > 0, 1, 0)", fmt=NUM0),
        col("is_below_rop_week", "Is Below Reorder Point Week",
            "If([Inventory Weekly Base/Qty On Hand] <= [Inventory Weekly Base/Qty Reorder Point], "
            "1, 0)",
            "1 when on hand is at or under the reorder point. Stockouts count here too.", NUM0),
        col("replenishment_gap_units", "Replenishment Gap Units",
            "If([Inventory Weekly Base/Qty On Hand] <= [Inventory Weekly Base/Qty Reorder Point], "
            "[Inventory Weekly Base/Qty Reorder Point] - [Inventory Weekly Base/Qty On Hand], 0)",
            fmt=NUM0),
        col("on_hand_at_cost", "On Hand At Cost",
            "[Inventory Weekly Base/Qty On Hand] * [Product/Avg Unit Cost]", fmt=USD),
        col("on_hand_at_retail", "On Hand At Retail",
            "[Inventory Weekly Base/Qty On Hand] * [Product/Price]", fmt=USD),
        col("net_units", "Net Units", "[Sales Week/Net Units]",
            "Units sold net of returns this week. Null means no sales activity that week.", NUM0),
        col("retail_net_units", "Retail Net Units", "[Sales Week/Retail Net Units]", fmt=NUM0),
        col("net_sales", "Net Sales", "[Sales Week/Net Sales]", fmt=USD),
        col("net_cogs", "Net COGS", "[Sales Week/Net COGS]", fmt=USD),
        col("product_name", "Product Name", "[Product/Product Name]"),
        col("product_type", "Product Type", "[Product/Product Type]"),
        col("product_family", "Product Family", "[Product/Product Family]"),
        col("product_line", "Product Line", "[Product/Product Line]"),
        col("product_group", "Product Group", "[Product/Product Group]"),
        col("sku_number", "Sku Number", "[Product/Sku Number]"),
        col("product_status", "Product Status", "[Product/Product Status]"),
        col("avg_unit_cost", "Avg Unit Cost", "[Product/Avg Unit Cost]", fmt=USD),
        col("price", "Price", "[Product/Price]", fmt=USD),
        col("vendor_key", "Vendor Key", "[Product/Vendor Key]"),
        col("vendor_name", "Vendor Name", "[Product/Vendor Name]"),
        col("vendor_lead_time_days", "Vendor Lead Time Days", "[Product/Vendor Lead Time Days]",
            fmt=NUM0),
        col("store_name", "Store Name", "[Store/Store Name]"),
        col("store_city", "Store City", "[Store/Store City]"),
        col("store_state", "Store State", "[Store/Store State]"),
        col("store_region", "Store Region", "[Store/Store Region]"),
        col("store_area", "Store Area", "[Store/Store Area]"),
        col("store_type", "Store Type", "[Store/Store Type]"),
        col("store_size", "Store Size", "[Store/Store Size]"),
        col("is_warehouse", "Is Warehouse", "[Inventory Weekly Base/Store Key] = 9999",
            "True for the Central Warehouse (9999), which holds inventory but records no sales. "
            "Exclude it from store-level in-stock and Weeks of Supply reporting."),
        col("fiscal_year", "Fiscal Year", "[Date/Fiscal Year]"),
        col("fiscal_quarter", "Fiscal Quarter", "[Date/Fiscal Quarter]"),
        col("fiscal_period", "Fiscal Period", "[Date/Fiscal Period]"),
        col("fiscal_period_name", "Fiscal Period Name", "[Date/Fiscal Period Name]"),
        col("fiscal_week_of_year", "Fiscal Week of Year", "[Date/Fiscal Week of Year]"),
        col("fiscal_season", "Fiscal Season", "[Date/Fiscal Season]"),
        col("calendar_year", "Calendar Year", "[Date/Calendar Year]"),
        col("calendar_month_name", "Calendar Month Name", "[Date/Calendar Month Name]"),
        col("calendar_quarter", "Calendar Quarter", "[Date/Calendar Quarter]"),
        col("prior_year_date", "Prior Year Date", "[Date/Prior Year Date]"),
    ],
    "metrics": WEEKLY_METRICS,
}

inventory_current = {
    "id": "inventory_current", "name": "Inventory Current", "kind": "table", "visibleAsSource": True,
    "description": "The position standing at 2025-10-12: exactly one row per store-product pair, "
                   "220,296 rows, being each pair's final change carried to the end of the horizon. "
                   "This is the replenishment worklist - 7,239 pairs sit at zero and 14,178 at or "
                   "below their reorder point. Weeks of Supply uses trailing-13-week demand, which is "
                   "null for the 35% of pairs that have never sold anything and for the Central "
                   "Warehouse.",
    "source": {"kind": "join", "primarySource": {"kind": "table", "elementId": "inv_changes_base"},
               "joins": [
                   lj("inv_changes_base", "pair_velocity",
                      [("Store Key", "Store Key"), ("Product Key", "Product Key")], "g_velocity"),
                   lj("inv_changes_base", "dim_product", [("Product Key", "Product Key")]),
                   lj("inv_changes_base", "dim_store", [("Store Key", "Store Key")]),
               ]},
    "columns": [
        col("store_key", "Store Key", "[Inventory Changes Base/Store Key]"),
        col("product_key", "Product Key", "[Inventory Changes Base/Product Key]"),
        col("position_since", "Position Since", "[Inventory Changes Base/Effective Start Date]",
            "When this position was last touched. An old date on a zero position is a stale stockout."),
        col("weeks_at_position", "Weeks At Position", "[Inventory Changes Base/Weeks In Force]",
            "Weeks this position has stood unchanged through 2025-10-12.", NUM0),
        col("qty_on_hand", "Qty On Hand", "[Inventory Changes Base/Qty On Hand]", fmt=NUM0),
        col("qty_in_transit", "Qty In Transit", "[Inventory Changes Base/Qty In Transit]", fmt=NUM0),
        col("qty_reorder_point", "Qty Reorder Point",
            "[Inventory Changes Base/Qty Reorder Point]", fmt=NUM0),
        col("is_current", "Is Current Position", "[Inventory Changes Base/Is Current Position]"),
        col("is_stockout", "Is Stockout", "If([Inventory Changes Base/Qty On Hand] = 0, 1, 0)",
            fmt=NUM0),
        col("is_below_rop", "Is Below Reorder Point",
            "If([Inventory Changes Base/Qty On Hand] <= "
            "[Inventory Changes Base/Qty Reorder Point], 1, 0)", fmt=NUM0),
        col("replenishment_gap_units", "Replenishment Gap Units",
            "If([Inventory Changes Base/Qty On Hand] <= "
            "[Inventory Changes Base/Qty Reorder Point], [Inventory Changes Base/Qty Reorder Point] "
            "- [Inventory Changes Base/Qty On Hand], 0)", fmt=NUM0),
        col("on_hand_at_cost", "On Hand At Cost",
            "[Inventory Changes Base/Qty On Hand] * [Product/Avg Unit Cost]", fmt=USD),
        col("on_hand_at_retail", "On Hand At Retail",
            "[Inventory Changes Base/Qty On Hand] * [Product/Price]", fmt=USD),
        col("lifetime_net_units", "Lifetime Net Units", "[Pair Velocity/Lifetime Net Units]", fmt=NUM0),
        col("units_l13w", "Units L13W", "[Pair Velocity/Units L13W]",
            "Net units sold in the trailing 13 weeks (weeks 205-217).", NUM0),
        col("units_l52w", "Units L52W", "[Pair Velocity/Units L52W]", fmt=NUM0),
        col("avg_weekly_units_l13w", "Avg Weekly Units L13W",
            "[Pair Velocity/Units L13W] / 13", fmt=NUM2),
        col("is_never_sold", "Is Never Sold",
            "If(IsNull([Pair Velocity/Lifetime Net Units]) or "
            "[Pair Velocity/Lifetime Net Units] = 0, 1, 0)",
            "1 for a carried store-product pair with no net units sold in four years: 77,941 pairs with no "
            "sales activity at all, plus 258 whose sales were entirely returned. 78,199 of "
            "220,296 pairs - dead assortment tying up stock.", NUM0),
        col("product_name", "Product Name", "[Product/Product Name]"),
        col("product_type", "Product Type", "[Product/Product Type]"),
        col("product_family", "Product Family", "[Product/Product Family]"),
        col("product_line", "Product Line", "[Product/Product Line]"),
        col("product_group", "Product Group", "[Product/Product Group]"),
        col("sku_number", "Sku Number", "[Product/Sku Number]"),
        col("product_status", "Product Status", "[Product/Product Status]"),
        col("avg_unit_cost", "Avg Unit Cost", "[Product/Avg Unit Cost]", fmt=USD),
        col("price", "Price", "[Product/Price]", fmt=USD),
        col("vendor_key", "Vendor Key", "[Product/Vendor Key]"),
        col("vendor_name", "Vendor Name", "[Product/Vendor Name]"),
        col("vendor_lead_time_days", "Vendor Lead Time Days", "[Product/Vendor Lead Time Days]",
            fmt=NUM0),
        col("store_name", "Store Name", "[Store/Store Name]"),
        col("store_city", "Store City", "[Store/Store City]"),
        col("store_state", "Store State", "[Store/Store State]"),
        col("store_region", "Store Region", "[Store/Store Region]"),
        col("store_area", "Store Area", "[Store/Store Area]"),
        col("store_type", "Store Type", "[Store/Store Type]"),
        col("is_warehouse", "Is Warehouse", "[Inventory Changes Base/Store Key] = 9999"),
    ],
    "filters": [{"id": "f_current", "columnId": "is_current", "kind": "list",
                 "state": "enabled", "mode": "include", "values": [True]}],
    "metrics": [
        met("m_c_pairs", "Store-Product Pairs", "Count([Store Key])",
            "220,296 unfiltered - every one of 201 locations carries every one of 1,096 products.",
            NUM0),
        met("m_c_on_hand", "On Hand Units", "Sum([Qty On Hand])",
            "Units standing in inventory at 2025-10-12, summed across pairs. 1,194,313 unfiltered. "
            "A point-in-time position, so it does not respond to a date filter - for a position over "
            "time use Avg Inventory Units on Inventory Weekly.", NUM0),
        met("m_c_on_hand_cost", "On Hand at Cost", "Sum([On Hand At Cost])",
            "Standing inventory valued at quantity-weighted PO unit cost. $260,485,156.88 unfiltered, "
            "within 0.5% of the $261.8M four-year average on Inventory Weekly - the position has "
            "been remarkably flat.", USD),
        met("m_c_on_hand_retail", "On Hand at Retail", "Sum([On Hand At Retail])",
            "Standing inventory valued at D_PRODUCT list price rather than cost. $557,028,794.50 "
            "unfiltered. Sticker value of stock on the floor, not expected revenue - it takes no "
            "account of markdowns, and a third of it will never sell.", USD),
        met("m_c_in_transit", "In Transit Units", "Sum([Qty In Transit])",
            "Units on their way to a store as of 2025-10-12. 110,366 unfiltered, about 9% of the "
            "1,194,313 already on hand. Not counted in On Hand Units.", NUM0),
        met("m_c_stockouts", "Stocked Out Pairs", "Sum([Is Stockout])",
            "Store-product pairs sitting at zero on hand right now. 7,239 unfiltered. A count of "
            "pairs, not of lost units - a stockout on a dead SKU costs nothing and one on a mover "
            "costs a sale every week, so read it beside Units L13W.", NUM0),
        met("m_c_stockout_rate", "Stockout Rate %",
            "[Metrics/Stocked Out Pairs] / [Metrics/Store-Product Pairs]",
            "3.29% unfiltered - a point-in-time reading, close to the 3.19% time-weighted rate over "
            "the full horizon.", PCT),
        met("m_c_below_rop", "Pairs Below Reorder Point", "Sum([Is Below Reorder Point])",
            "Pairs at or under their reorder point, the 7,239 already at zero INCLUDED. 14,178 "
            "unfiltered, so roughly half the replenishment queue has already run out rather than "
            "merely running low.", NUM0),
        met("m_c_reorder_now", "Reorder Now %",
            "[Metrics/Pairs Below Reorder Point] / [Metrics/Store-Product Pairs]",
            "Share of store-product pairs at or under their reorder point right now, stockouts "
            "included. 6.44% unfiltered. This is the replenishment queue as a rate; it says nothing "
            "about urgency, since a flagged pair with no demand will never sell through.", PCT),
        met("m_c_replen_gap", "Replenishment Gap Units", "Sum([Replenishment Gap Units])",
            "Units required to bring every below-reorder-point pair back to its reorder point.", NUM0),
        met("m_c_never_sold", "Never Sold Pairs", "Sum([Is Never Sold])",
            "Pairs with no net units sold across the whole four years: 77,941 with no sales activity "
            "at all plus 258 whose sales were entirely returned. 78,199 unfiltered, holding $184.8M "
            "at cost in the 200 selling stores - and reorder points, being velocity-based, flag "
            "almost none of it.", NUM0),
        met("m_c_never_sold_pct", "Never Sold %",
            "[Metrics/Never Sold Pairs] / [Metrics/Store-Product Pairs]",
            "35.50% unfiltered. Stock carried in stores that has not moved on net in four years.", PCT),
        met("m_c_units_l13w", "Units L13W", "Sum([Units L13W])",
            "Net units sold in the trailing 13 weeks (spine weeks 205-217, ending 2025-10-18). "
            "681,262 unfiltered. The demand signal behind Weeks of Supply; a fixed window, so it does "
            "not respond to a date filter.", NUM0),
        met("m_c_avg_weekly_units", "Avg Weekly Units L13W", "Sum([Units L13W]) / 13",
            "Units L13W spread over 13 weeks - the current run rate. 52,404.77 a week unfiltered. "
            "Divides by a constant 13, so it stays a weekly rate at every grouping level.", NUM2),
        met("m_c_wos", "Weeks of Supply",
            "[Metrics/On Hand Units] / [Metrics/Avg Weekly Units L13W]",
            "Current stock divided by the trailing-13-week weekly run rate. 22.79 weeks unfiltered. "
            "Undefined wherever recent demand is zero - the Central Warehouse and the 78,199 "
            "never-sold pairs - so a null here means no velocity, not no stock. Grouping by store or "
            "product recomputes it from that group's totals, which is the correct behaviour.", NUM2),
    ],
}

inventory_changes = {
    "id": "inventory_changes", "name": "Inventory Changes", "kind": "table", "visibleAsSource": True,
    "description": "The raw change log, 5,954,664 rows, with each change's duration attached. Use it "
                   "for questions about movement rather than position: how long stockouts last, how "
                   "often a SKU turns over, which pairs are effectively frozen. DO NOT use it to "
                   "measure stock state - averaging across these rows weights by change frequency, "
                   "not time. Both weightings are exposed side by side as metrics so the gap is "
                   "visible: 23.46% row-weighted against 3.19% time-weighted stockout.",
    "source": {"kind": "join", "primarySource": {"kind": "table", "elementId": "inv_changes_base"},
               "joins": [
                   lj("inv_changes_base", "dim_product", [("Product Key", "Product Key")]),
                   lj("inv_changes_base", "dim_store", [("Store Key", "Store Key")]),
                   lj("inv_changes_base", "dim_date", [("Effective Start Date", "Date Key")]),
               ]},
    "columns": [
        col("store_key", "Store Key", "[Inventory Changes Base/Store Key]"),
        col("product_key", "Product Key", "[Inventory Changes Base/Product Key]"),
        col("effective_start_date", "Effective Start Date",
            "[Inventory Changes Base/Effective Start Date]"),
        col("effective_end_date", "Effective End Date",
            "[Inventory Changes Base/Effective End Date]", "Exclusive."),
        col("weeks_in_force", "Weeks In Force", "[Inventory Changes Base/Weeks In Force]", fmt=NUM0),
        col("week_index", "Week Index", "[Inventory Changes Base/Week Index]", fmt=NUM0),
        col("qty_on_hand", "Qty On Hand", "[Inventory Changes Base/Qty On Hand]", fmt=NUM0),
        col("qty_in_transit", "Qty In Transit", "[Inventory Changes Base/Qty In Transit]", fmt=NUM0),
        col("qty_reorder_point", "Qty Reorder Point",
            "[Inventory Changes Base/Qty Reorder Point]", fmt=NUM0),
        col("is_current", "Is Current Position", "[Inventory Changes Base/Is Current Position]"),
        col("is_stockout", "Is Stockout", "If([Inventory Changes Base/Qty On Hand] = 0, 1, 0)",
            fmt=NUM0),
        col("stockout_weeks", "Stockout Weeks",
            "If([Inventory Changes Base/Qty On Hand] = 0, [Inventory Changes Base/Weeks In Force], 0)",
            fmt=NUM0),
        col("below_rop_weeks", "Below Reorder Point Weeks",
            "If([Inventory Changes Base/Qty On Hand] <= [Inventory Changes Base/Qty Reorder Point], "
            "[Inventory Changes Base/Weeks In Force], 0)", fmt=NUM0),
        col("product_name", "Product Name", "[Product/Product Name]"),
        col("product_type", "Product Type", "[Product/Product Type]"),
        col("product_family", "Product Family", "[Product/Product Family]"),
        col("vendor_name", "Vendor Name", "[Product/Vendor Name]"),
        col("store_name", "Store Name", "[Store/Store Name]"),
        col("store_region", "Store Region", "[Store/Store Region]"),
        col("store_area", "Store Area", "[Store/Store Area]"),
        col("is_warehouse", "Is Warehouse", "[Inventory Changes Base/Store Key] = 9999"),
        col("fiscal_year", "Fiscal Year", "[Date/Fiscal Year]"),
        col("fiscal_quarter", "Fiscal Quarter", "[Date/Fiscal Quarter]"),
        col("fiscal_period", "Fiscal Period", "[Date/Fiscal Period]"),
        col("fiscal_season", "Fiscal Season", "[Date/Fiscal Season]"),
    ],
    "metrics": [
        met("m_ch_changes", "Position Changes", "Count([Store Key])",
            "Rows in the change log - the number of times a position moved. 5,954,664 unfiltered. An "
            "event count, never a stock measure: use it as a denominator only for questions about "
            "movement frequency.", NUM0),
        met("m_ch_weeks", "Weeks Covered", "Sum([Weeks In Force])",
            "48,024,528 unfiltered - the change log accounts for every store-product-week exactly "
            "once.", NUM0),
        met("m_ch_avg_gap", "Avg Weeks Between Changes",
            "[Metrics/Weeks Covered] / [Metrics/Position Changes]",
            "Weeks covered divided by changes - how long a position typically holds before it moves. "
            "8.07 unfiltered. The gap between this and the 1.10-week stockout duration is exactly why "
            "row-weighted and time-weighted rates diverge so far.", NUM2),
        met("m_ch_stockout_events", "Stockout Events", "Sum([Is Stockout])",
            "Change-log rows that landed on zero on hand - the number of times a stockout STARTED. "
            "1,396,947 unfiltered. Not the number of weeks spent stocked out, which is 1,530,108.", NUM0),
        met("m_ch_stockout_weeks", "Stockout Weeks", "Sum([Stockout Weeks])",
            "Total weeks spent at zero on hand, each change weighted by how long it held. 1,530,108 "
            "unfiltered. This is the numerator of the honest stockout rate.", NUM0),
        met("m_ch_stockout_duration", "Avg Stockout Duration (Weeks)",
            "[Metrics/Stockout Weeks] / [Metrics/Stockout Events]",
            "How long a stockout lasts once it starts - about 1.1 weeks. Short duration is exactly "
            "why row-weighted stockout rates are so badly overstated. 1.10 weeks unfiltered.", NUM2),
        met("m_ch_tw_stockout", "Stockout % (Time-Weighted)",
            "[Metrics/Stockout Weeks] / [Metrics/Weeks Covered]",
            "3.19% unfiltered. The correct figure, and the one Inventory Weekly reports.", PCT),
        met("m_ch_rw_stockout", "Stockout % (Row-Weighted - MISLEADING)",
            "[Metrics/Stockout Events] / [Metrics/Position Changes]",
            "23.46% unfiltered. Published here only to make the trap explicit: this is what you get "
            "by counting change-log rows instead of weeks, and it overstates stockout by 7.4x. Never "
            "report it.", PCT),
    ],
}

# ------------------------------------------------------------------ Page 5: Supporting Facts
SHRINK_REASONS = '[SRC F_INVENTORY_ADJUSTMENT/Adjustment Reason] = "Theft" or ' \
                 '[SRC F_INVENTORY_ADJUSTMENT/Adjustment Reason] = "Damage" or ' \
                 '[SRC F_INVENTORY_ADJUSTMENT/Adjustment Reason] = "Expiration"'

inventory_adjustments = {
    "id": "inventory_adjustments", "name": "Inventory Adjustments", "kind": "table",
    "visibleAsSource": True,
    "description": "66,088 manual adjustments at Store x Product x Date, 2021-08-19 to 2025-10-17, "
                   "netting -416,623 units. Five reasons: Theft (23,485), Damage (16,398), Cycle "
                   "Count Correction (13,228), Expiration (9,725), Other (3,252). Shrink is defined "
                   "here as Theft + Damage + Expiration, excluding count corrections, which are "
                   "bookkeeping rather than loss. This fact is DAILY while the position is weekly - "
                   "roll it up to a week before comparing the two.",
    "source": {"kind": "join", "primarySource": {"kind": "table", "elementId": "src_adjustment"},
               "joins": [
                   lj("src_adjustment", "dim_product", [("Product Key", "Product Key")]),
                   lj("src_adjustment", "dim_store", [("Store Key", "Store Key")]),
                   lj("src_adjustment", "dim_date", [("Adjustment Date", "Date Key")]),
               ]},
    "columns": [
        col("store_key", "Store Key", "[SRC F_INVENTORY_ADJUSTMENT/Store Key]"),
        col("product_key", "Product Key", "[SRC F_INVENTORY_ADJUSTMENT/Product Key]"),
        col("adjustment_date", "Adjustment Date", "[SRC F_INVENTORY_ADJUSTMENT/Adjustment Date]"),
        col("adjustment_quantity", "Adjustment Quantity",
            "[SRC F_INVENTORY_ADJUSTMENT/Adjustment Quantity]",
            "Signed: negative removes units. 60,824 of 66,088 rows are negative.", NUM0),
        col("adjustment_reason", "Adjustment Reason", "[SRC F_INVENTORY_ADJUSTMENT/Adjustment Reason]"),
        col("is_shrink", "Is Shrink", f"If({SHRINK_REASONS}, 1, 0)",
            "Theft, Damage or Expiration. Cycle Count Correction is deliberately excluded.", NUM0),
        col("shrink_units", "Shrink Units",
            f"If({SHRINK_REASONS}, -1 * [SRC F_INVENTORY_ADJUSTMENT/Adjustment Quantity], 0)",
            "Positive units lost to shrink.", NUM0),
        col("adjustment_at_cost", "Adjustment At Cost",
            "[SRC F_INVENTORY_ADJUSTMENT/Adjustment Quantity] * [Product/Avg Unit Cost]", fmt=USD),
        col("shrink_at_cost", "Shrink At Cost",
            f"If({SHRINK_REASONS}, -1 * [SRC F_INVENTORY_ADJUSTMENT/Adjustment Quantity] * "
            "[Product/Avg Unit Cost], 0)", fmt=USD),
        col("shrink_at_retail", "Shrink At Retail",
            f"If({SHRINK_REASONS}, -1 * [SRC F_INVENTORY_ADJUSTMENT/Adjustment Quantity] * "
            "[Product/Price], 0)", fmt=USD),
        col("product_name", "Product Name", "[Product/Product Name]"),
        col("product_type", "Product Type", "[Product/Product Type]"),
        col("product_family", "Product Family", "[Product/Product Family]"),
        col("vendor_name", "Vendor Name", "[Product/Vendor Name]"),
        col("store_name", "Store Name", "[Store/Store Name]"),
        col("store_region", "Store Region", "[Store/Store Region]"),
        col("store_area", "Store Area", "[Store/Store Area]"),
        col("store_state", "Store State", "[Store/Store State]"),
        col("fiscal_year", "Fiscal Year", "[Date/Fiscal Year]"),
        col("fiscal_quarter", "Fiscal Quarter", "[Date/Fiscal Quarter]"),
        col("fiscal_period", "Fiscal Period", "[Date/Fiscal Period]"),
        col("fiscal_season", "Fiscal Season", "[Date/Fiscal Season]"),
        col("week_start_date", "Week Start Date", "[Date/Week Start Date]"),
    ],
    "metrics": [
        met("m_a_events", "Adjustment Events", "Count([Store Key])",
            "Manual adjustment records. 66,088 unfiltered. Counts events, not units - one large "
            "write-off and one single-unit correction weigh the same here.", NUM0),
        met("m_a_net_units", "Net Adjustment Units", "Sum([Adjustment Quantity])",
            "Signed sum of every adjustment, shrink and count correction together. -416,623 units "
            "unfiltered - inventory written down on net. Positive adjustments exist (5,264 rows) but "
            "are far outweighed.", NUM0),
        met("m_a_shrink_events", "Shrink Events", "Sum([Is Shrink])",
            "Adjustments attributed to Theft, Damage or Expiration. 49,608 of 66,088 unfiltered. "
            "Cycle Count Correction is deliberately excluded - a count correction is bookkeeping, and "
            "folding it into shrink would inflate loss with clerical noise.", NUM0),
        met("m_a_shrink_units", "Shrink Units", "Sum([Shrink Units])",
            "Units lost to theft, damage or expiration, sign-flipped so shrink reads POSITIVE while "
            "the underlying Adjustment Quantity is negative. 371,906 unfiltered.", NUM0),
        met("m_a_shrink_cost", "Shrink at Cost", "Sum([Shrink At Cost])",
            "Shrink units valued at quantity-weighted PO unit cost - what the loss actually cost to "
            "buy. $84,589,765.07 unfiltered. The figure to use for a P&L view of shrink.", USD),
        met("m_a_shrink_retail", "Shrink at Retail", "Sum([Shrink At Retail])",
            "Shrink units valued at list price. $181,863,249 unfiltered, 2.15x the cost figure. This "
            "is forgone sticker value, not forgone profit, and it assumes every lost unit would have "
            "sold at full price - so treat it as an upper bound.", USD),
        met("m_a_adj_cost", "Net Adjustment at Cost", "Sum([Adjustment At Cost])",
            "Every adjustment at cost, shrink and count corrections together, signed. "
            "-$94,696,118.03 unfiltered. It runs $10.1M below Shrink at Cost because the excluded "
            "reasons also net negative: Cycle Count Correction -19,907 units and Other -24,810.", USD),
        met("m_a_shrink_share", "Shrink Share of Events",
            "[Metrics/Shrink Events] / [Metrics/Adjustment Events]",
            "Share of adjustment EVENTS that are shrink. 75.06% unfiltered. An event share, not a "
            "unit or dollar share - do not read it as 'three quarters of adjusted value is shrink'.",
            PCT),
    ],
}

purchase_orders = {
    "id": "purchase_orders", "name": "Purchase Orders", "kind": "table", "visibleAsSource": True,
    "description": "53,589 PO lines - 53,137 Received, 452 In Transit - at Vendor x Product grain, one "
                   "line per PO number, worth $987,898,638 ordered and $979,771,037 received. KEPT "
                   "DELIBERATELY SEPARATE from the position facts: there is NO Store Key on a purchase "
                   "order, so inbound supply cannot be attributed to a store and joining this to the "
                   "store-product grain would silently fan out. Vendors look punctual in aggregate "
                   "(-0.02 days against expected) but that average hides a near-even split: 18,536 "
                   "early, 16,450 exact, 18,151 late. The spread is the signal, not the mean.",
    "source": {"kind": "join", "primarySource": {"kind": "table", "elementId": "src_po"},
               "joins": [
                   lj("src_po", "dim_vendor", [("Vendor Key", "Vendor Key")]),
                   lj("src_po", "dim_product", [("Product Key", "Product Key")]),
               ]},
    "columns": [
        col("po_number", "PO Number", "[SRC F_PURCHASE_ORDER/PO Number]"),
        col("vendor_key", "Vendor Key", "[SRC F_PURCHASE_ORDER/Vendor Key]"),
        col("product_key", "Product Key", "[SRC F_PURCHASE_ORDER/Product Key]"),
        col("order_date", "Order Date", "[SRC F_PURCHASE_ORDER/Order Date]"),
        col("expected_receipt_date", "Expected Receipt Date",
            "[SRC F_PURCHASE_ORDER/Expected Receipt Date]"),
        col("actual_receipt_date", "Actual Receipt Date",
            "[SRC F_PURCHASE_ORDER/Actual Receipt Date]", "Null while a PO is still In Transit."),
        col("order_quantity", "Order Quantity", "[SRC F_PURCHASE_ORDER/Order Quantity]", fmt=NUM0),
        col("unit_cost", "Unit Cost", "[SRC F_PURCHASE_ORDER/Unit Cost]", fmt=USD),
        col("po_status", "PO Status", "[SRC F_PURCHASE_ORDER/PO Status]"),
        col("po_value", "PO Value",
            "[SRC F_PURCHASE_ORDER/Order Quantity] * [SRC F_PURCHASE_ORDER/Unit Cost]", fmt=USD),
        col("is_received", "Is Received",
            'If([SRC F_PURCHASE_ORDER/PO Status] = "Received", 1, 0)', fmt=NUM0),
        col("days_vs_expected", "Days vs Expected",
            'If([SRC F_PURCHASE_ORDER/PO Status] = "Received", DateDiff("day", '
            "[SRC F_PURCHASE_ORDER/Expected Receipt Date], "
            "[SRC F_PURCHASE_ORDER/Actual Receipt Date]), Null)",
            "Negative is early. Null while In Transit, so it never drags the average.", NUM0),
        col("is_on_time", "Is On Time",
            'If([SRC F_PURCHASE_ORDER/PO Status] = "Received", If(DateDiff("day", '
            "[SRC F_PURCHASE_ORDER/Expected Receipt Date], "
            "[SRC F_PURCHASE_ORDER/Actual Receipt Date]) <= 0, 1, 0), Null)",
            "On time means on or before the expected date. 65.84% of received lines.", NUM0),
        col("actual_lead_time_days", "Actual Lead Time Days",
            'If([SRC F_PURCHASE_ORDER/PO Status] = "Received", DateDiff("day", '
            "[SRC F_PURCHASE_ORDER/Order Date], [SRC F_PURCHASE_ORDER/Actual Receipt Date]), Null)",
            "Order to receipt, in days. Averages 13.55 against a 13.57-day quote.", NUM0),
        col("quoted_lead_time_days", "Quoted Lead Time Days", "[Vendor/Lead Time Days]", fmt=NUM0),
        col("lead_time_variance_days", "Lead Time Variance Days",
            "[Actual Lead Time Days] - [Vendor/Lead Time Days]",
            "Actual minus quoted lead time. Positive means the vendor took longer than it promised.",
            NUM0),
        col("vendor_name", "Vendor Name", "[Vendor/Vendor Name]"),
        col("payment_terms", "Payment Terms", "[Vendor/Payment Terms]"),
        col("vendor_rating", "Vendor Rating", "[Vendor/Vendor Rating]", fmt=NUM2),
        col("vendor_since", "Vendor Since", "[Vendor/Vendor Since]"),
        col("product_name", "Product Name", "[Product/Product Name]"),
        col("product_type", "Product Type", "[Product/Product Type]"),
        col("product_family", "Product Family", "[Product/Product Family]"),
        col("sku_number", "Sku Number", "[Product/Sku Number]"),
    ],
    "metrics": [
        met("m_po_lines", "PO Lines", "Count([PO Number])", "Purchase order lines, one per PO number at Vendor x Product grain. 53,589 unfiltered. "
            "Counts orders, not stores - a PO has no Store Key.", NUM0),
        met("m_po_units", "PO Units", "Sum([Order Quantity])",
            "Units ordered across all PO lines, received and in transit. 9,289,094 unfiltered. "
            "Company-wide inbound volume only - purchase orders carry no Store Key, so this can never "
            "be broken out by store.", NUM0),
        met("m_po_value", "PO Value", "Sum([PO Value])", "Order quantity times unit cost across all lines. $987,898,638.38 ordered unfiltered, of "
            "which $979,771,036.77 has actually been received; the $8.1M difference is the 452 lines "
            "still in transit.", USD),
        met("m_po_received", "Received Lines", "Sum([Is Received])", "Lines with PO Status 'Received'. 53,137 unfiltered. The correct denominator for every "
            "timing metric here, since in-transit lines have no receipt date yet.", NUM0),
        met("m_po_in_transit", "In Transit Lines",
            "[Metrics/PO Lines] - [Metrics/Received Lines]", "Lines ordered but not yet received as of 2025-10-17. 452 unfiltered, under 1% of all "
            "lines. They carry no Actual Receipt Date, so they are excluded from on-time and lead "
            "time rather than counted as late.", NUM0),
        met("m_po_on_time", "On-Time %", "Sum([Is On Time]) / [Metrics/Received Lines]",
            "Share of received lines that arrived on or before the expected date. 65.84% unfiltered.",
            PCT),
        met("m_po_avg_vs_expected", "Avg Days vs Expected",
            "Sum([Days vs Expected]) / [Metrics/Received Lines]",
            "-0.018 days unfiltered. Punctual on average and wildly variable underneath - always pair "
            "it with the early/late split.", NUM2),
        met("m_po_avg_lead", "Avg Actual Lead Time Days",
            "Sum([Actual Lead Time Days]) / [Metrics/Received Lines]", "Order date to actual receipt date, averaged over received lines. 13.55 days unfiltered. "
            "Measures what the supply chain actually did, independent of what was promised.", NUM2),
        met("m_po_avg_quoted", "Avg Quoted Lead Time Days",
            "Sum([Quoted Lead Time Days]) / [Metrics/PO Lines]", "D_VENDOR's promised lead time, averaged across all PO lines. 13.57 days unfiltered. A "
            "vendor attribute repeated per line, so it is weighted by order count, not by value.",
            NUM2),
        met("m_po_lead_variance", "Avg Lead Time Variance Days",
            "[Metrics/Avg Actual Lead Time Days] - "
            "(Sum(If([Is Received] = 1, [Quoted Lead Time Days], 0)) / [Metrics/Received Lines])",
            "Actual minus quoted lead time across received lines. -0.018 days unfiltered: vendors "
            "hit their quoted lead time almost exactly on average. That average is close to "
            "worthless on its own - the receipts split 18,536 early, 16,450 exact and 18,151 late, so "
            "look at the distribution before concluding a vendor is reliable.", NUM2),
    ],
}

spec = {
    "name": "Retail Inventory & Replenishment",
    "description":
        "Store x Product x Week inventory model, 48,024,528 dense position-weeks carried forward from "
        "a 5,954,664-row sparse change log, joined to demand, adjustments and purchasing. Answers "
        "what a change log cannot: how much stock stood where, for how long, against what demand. "
        "The headline correction is that the true time-weighted stockout rate is 3.19%, not the "
        "23.46% a naive read of the change log reports. Sources conformed dimensions from the Retail "
        "Sales Activity model.",
    "pages": [
        {"id": "page_sources", "name": "Sources", "elements": sources},
        {"id": "page_dims", "name": "Conformed Dimensions",
         "elements": [product_cost, dim_product, dim_store, dim_date, dim_vendor]},
        {"id": "page_build", "name": "Position Build",
         "elements": [inv_changes_base, week_spine, sales_week, pair_velocity, inv_weekly_base]},
        {"id": "page_position", "name": "Inventory Position",
         "elements": [inventory_weekly, inventory_current, inventory_changes]},
        {"id": "page_support", "name": "Supporting Facts",
         "elements": [inventory_adjustments, purchase_orders]},
    ],
}

print(json.dumps(spec, indent=2))
