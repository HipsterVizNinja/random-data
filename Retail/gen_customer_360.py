"""Generate the Retail Customer 360 data model spec (Model 4 of DATA_MODEL_ROADMAP.md).

Usage:
    python3 gen_customer_360.py            # full spec to stdout
    python3 gen_customer_360.py --pages 1,2 # subset, for bisecting server-side errors

Publish with:
    sigma api data-models spec create --params '{"folderId": "...", ...}'
"""
import json
import sys

UPLOADS = "b765b086-4e7e-426b-ac82-7d6e0cf5a71c"
SALESACT = "8c548776-acb2-46ac-b60d-dd5a70781bd2"


def col(cid, name, formula, desc=None, fmt=None):
    c = {"id": cid, "name": name, "formula": formula}
    if desc:
        c["description"] = desc
    if fmt:
        c["format"] = fmt
    return c


USD = {"kind": "number", "formatString": "$,.2f"}
NUM0 = {"kind": "number", "formatString": ",.0f"}
NUM2 = {"kind": "number", "formatString": ",.2f"}
PCT = {"kind": "number", "formatString": ".2%"}


def src(eid, name, model, origin_elem, origin_name, cols, desc=None):
    """cols: list of (id, display) or (id, display, origin_display)."""
    columns = []
    for c in cols:
        cid, disp = c[0], c[1]
        origin = c[2] if len(c) > 2 else disp
        columns.append(col(cid, disp, f"[{origin_name}/{origin}]"))
    e = {
        "id": eid, "name": name, "kind": "table",
        "source": {"kind": "data-model", "dataModelId": model, "elementId": origin_elem},
        "columns": columns,
        "visibleAsSource": False,
    }
    if desc:
        e["description"] = desc
    return e


# ---------------------------------------------------------------- Page 1: Sources

CUSTOMER_COLS = [
    ("cust_key", "Cust Key"), ("cust_name", "Cust Name"), ("cust_address", "Cust Address"),
    ("cust_city", "Cust City"), ("cust_state", "Cust State"), ("cust_zip_code", "Cust Zip Code"),
    ("cust_county", "Cust County"), ("cust_region", "Cust Region"), ("cust_since", "Cust Since"),
    ("cust_type", "Cust Type"), ("cust_gender", "Cust Gender"), ("cust_age", "Cust Age"),
    ("age_group", "Age Group"), ("civil_status", "Civil Status"),
    ("loyalty_program", "Loyalty Program"), ("loyalty_tier", "Loyalty Tier"),
    ("downloaded_app", "Downloaded App"),
]

# Birthday fields live ONLY in the UPPER_SNAKE block of the raw upload - the Sales
# Activity conformed dimension drops them, and the clienteling plan needs them.
DCUST_COLS = [
    ("cust_key", "Cust Key", "Cust Key"),
    ("birthday_month", "Birthday Month", "BIRTHDAY_MONTH"),
    ("birthday_day", "Birthday Day", "BIRTHDAY_DAY"),
]

SA_COLS = [
    ("activity_type", "Activity Type"), ("activity_date", "Activity Date"),
    ("sale_date", "Sale Date"), ("order_number", "Order Number"),
    ("product_key", "Product Key"), ("store_key", "Store Key"), ("cust_key", "Cust Key"),
    ("salesperson_key", "Salesperson Key"), ("channel_type", "Channel Type"),
    ("quantity", "Quantity"), ("amount", "Amount"), ("cost", "Cost"),
    ("return_reason", "Return Reason"), ("restocked", "Restocked"),
    ("product_type", "Product Type"), ("product_family", "Product Family"),
    ("product_line", "Product Line"), ("product_group", "Product Group"),
]

SO_COLS = [
    ("order_number", "Order Number"), ("date", "Date"), ("date_key", "Date Key"),
    ("store_key", "Store Key"), ("cust_key", "Cust Key"),
    ("salesperson_key", "Salesperson Key"), ("channel_type", "Channel Type"),
]

REVIEW_COLS = [
    ("review_id", "Review ID", "Review ID"),
    ("product_key", "Product Key", "Product Key"),
    ("cust_key", "Cust Key", "Cust Key"),
    ("review_date", "Review Date", "Review Date"),
    ("rating", "Rating", "Rating"),
]

DATE_COLS = [
    ("date_key", "Date Key"), ("day_of_week_name", "Day of Week Name"),
    ("is_weekend", "Is Weekend"), ("week_start_date", "Week Start Date"),
    ("calendar_year", "Calendar Year"), ("calendar_month", "Calendar Month"),
    ("calendar_month_name", "Calendar Month Name"), ("calendar_quarter", "Calendar Quarter"),
    ("fiscal_year", "Fiscal Year"), ("fiscal_quarter", "Fiscal Quarter"),
    ("fiscal_period", "Fiscal Period"), ("fiscal_period_name", "Fiscal Period Name"),
    ("fiscal_week_of_year", "Fiscal Week of Year"), ("fiscal_season", "Fiscal Season"),
    ("prior_year_date", "Prior Year Date"),
]

PRODUCT_COLS = [
    ("product_key", "Product Key"), ("product_name", "Product Name"),
    ("product_type", "Product Type"), ("product_family", "Product Family"),
    ("product_line", "Product Line"), ("product_group", "Product Group"),
    ("sku_number", "Sku Number"), ("price", "Price"),
    ("product_status", "Product Status"), ("vendor_key", "Vendor Key"),
]

STORE_COLS = [
    ("store_key", "Store Key"), ("store_name", "Store Name"), ("store_city", "Store City"),
    ("store_state", "Store State"), ("store_region", "Store Region"),
    ("store_area", "Store Area"), ("store_type", "Store Type"), ("store_size", "Store Size"),
    ("latitude", "Latitude"), ("longitude", "Longitude"),
]

SP_COLS = [
    ("salesperson_key", "Salesperson Key"), ("salesperson_name", "Salesperson Name"),
    ("store_key", "Store Key"), ("tier", "Tier"), ("commission_rate", "Commission Rate"),
    ("employment_status", "Employment Status"), ("hire_date", "Hire Date"),
    ("tenure_years", "Tenure Years"), ("termination_date", "Termination Date"),
]

sources = [
    src("src_customer", "SRC Customer", SALESACT, "dim_customer", "Customer", CUSTOMER_COLS,
        "Conformed Customer dimension referenced from the Retail Sales Activity model."),
    src("src_d_customer", "SRC D_CUSTOMER", UPLOADS, "yFGiy5uRHR", "D_CUSTOMER.csv", DCUST_COLS,
        "Raw customer upload, projected to the BIRTHDAY fields only. These live solely in the "
        "UPPER_SNAKE block of D_CUSTOMER and are not carried by the conformed Customer dimension, "
        "so they are picked up here and grafted on."),
    src("src_sales_activity", "SRC Sales Activity", SALESACT, "sales_activity", "Sales Activity", SA_COLS,
        "Sales + returns order-line fact referenced from the Retail Sales Activity model."),
    src("src_sales_orders", "SRC Sales Orders", SALESACT, "sales_orders", "Sales Orders", SO_COLS,
        "Order-grain fact referenced from the Retail Sales Activity model. Used for the "
        "primary-store and primary-salesperson mode calculations, where order counts must not "
        "be inflated by line counts."),
    src("src_product_review", "SRC F_PRODUCT_REVIEW", UPLOADS, "8OmwpZp7XK", "F_PRODUCT_REVIEW.csv", REVIEW_COLS,
        "Product review ledger. Verified Purchase is deliberately NOT projected: it is 'Y' for all "
        "137,944 rows and carries zero information."),
    src("src_date", "SRC Date", SALESACT, "dim_date", "Date", DATE_COLS,
        "Conformed Date dimension (4-5-4 fiscal) referenced from the Retail Sales Activity model."),
    src("src_product", "SRC Product", SALESACT, "dim_product", "Product", PRODUCT_COLS,
        "Conformed Product dimension referenced from the Retail Sales Activity model."),
    src("src_store", "SRC Store", SALESACT, "dim_store", "Store", STORE_COLS,
        "Conformed Store dimension referenced from the Retail Sales Activity model."),
    src("src_salesperson", "SRC Salesperson", SALESACT, "dim_salesperson", "Salesperson", SP_COLS,
        "Conformed Salesperson dimension referenced from the Retail Sales Activity model."),
]

# ---------------------------------------------------------------- Page 2: Conformed Dimensions

dim_customer = {
    "id": "dim_customer", "name": "Customer", "kind": "table", "visibleAsSource": True,
    "description": (
        "One row per customer (4,972). The conformed Customer dimension from Retail Sales Activity, "
        "extended with BIRTHDAY_MONTH and BIRTHDAY_DAY from the raw upload. "
        "Beware: birthday is null for 2,559 of 4,972 customers (51%) - any birthday campaign built "
        "on this reaches at most half the base, so always report the covered population alongside it. "
        "Note also that 105 of these customers have never transacted; see Customer Profile."
    ),
    "source": {
        "kind": "join",
        "primarySource": {"kind": "table", "elementId": "src_customer"},
        "joins": [
            {"joinType": "left-outer",
             "left": {"kind": "table", "elementId": "src_customer"},
             "right": {"kind": "table", "elementId": "src_d_customer"},
             "columns": [{"left": "[Cust Key]", "right": "[Cust Key]"}]},
        ],
    },
    "columns": [col(cid, disp, f"[SRC Customer/{disp}]") for cid, disp in CUSTOMER_COLS] + [
        col("birthday_month", "Birthday Month", "[SRC D_CUSTOMER/Birthday Month]",
            "Birth month, 1-12. NULL for 2,559 of 4,972 customers.", NUM0),
        col("birthday_day", "Birthday Day", "[SRC D_CUSTOMER/Birthday Day]",
            "Day of birth month, 1-31. NULL for the same 2,559 customers as Birthday Month.", NUM0),
        col("has_birthday", "Has Birthday",
            "If(IsNull([SRC D_CUSTOMER/Birthday Month]), \"N\", \"Y\")",
            "'Y' when a birthday is on file. Use this as the denominator guard on any birthday campaign."),
    ],
}

dim_date = {
    "id": "dim_date", "name": "Date", "kind": "table", "visibleAsSource": True,
    "description": (
        "Retail 4-5-4 fiscal calendar. Sigma's built-in period-over-period and DateLookback are "
        "CALENDAR-based and will not align to 4-5-4 week boundaries; use Prior Year Date for "
        "fiscal-correct comps."
    ),
    "source": {"kind": "table", "elementId": "src_date"},
    "columns": [col(cid, disp, f"[SRC Date/{disp}]") for cid, disp in DATE_COLS],
}

dim_product = {
    "id": "dim_product", "name": "Product", "kind": "table", "visibleAsSource": True,
    "description": "Conformed Product dimension, re-exposed so this model is self-sufficient as a source.",
    "source": {"kind": "table", "elementId": "src_product"},
    "columns": [col(cid, disp, f"[SRC Product/{disp}]") for cid, disp in PRODUCT_COLS],
}

dim_store = {
    "id": "dim_store", "name": "Store", "kind": "table", "visibleAsSource": True,
    "description": (
        "Conformed Store dimension: 200 selling stores plus the Central Warehouse (Store Key 9999). "
        "The warehouse appears here because web orders are transacted against it."
    ),
    "source": {"kind": "table", "elementId": "src_store"},
    "columns": [col(cid, disp, f"[SRC Store/{disp}]") for cid, disp in STORE_COLS],
}

dim_salesperson = {
    "id": "dim_salesperson", "name": "Salesperson", "kind": "table", "visibleAsSource": True,
    "description": (
        "Conformed Salesperson dimension (1,617 commissioned associates). Tier is SENIORITY, not a "
        "volume threshold, and Commission Rate varies within tier - do not read tier as a rate band."
    ),
    "source": {"kind": "table", "elementId": "src_salesperson"},
    "columns": [col(cid, disp, f"[SRC Salesperson/{disp}]") for cid, disp in SP_COLS],
}

dims = [dim_customer, dim_date, dim_product, dim_store, dim_salesperson]

# ---------------------------------------------------------------- Page 3: Customer Build (hidden)

# The whole model is anchored to the dataset's own last sale date rather than Today().
# This is the As Of Date convention from the roadmap: the data is a static extract ending
# 2025-10-18, so Today() would read every customer as long-churned.
as_of = {
    "id": "as_of", "name": "As Of", "kind": "table", "visibleAsSource": False,
    "description": (
        "Single-row element carrying the model-wide As Of Date = the latest Sale Date in the fact "
        "(2025-10-18). Recency and tenure are measured against this, NEVER against Today(): this is "
        "a static extract, so Today() would report every customer as churned. Join Key is a constant "
        "1 whose only job is to broadcast that one date onto every customer row."
    ),
    "source": {"kind": "table", "elementId": "src_sales_activity"},
    "columns": [
        col("join_key", "Join Key", "1", "Constant 1. Cross-join handle only.", NUM0),
        col("as_of_date", "As Of Date", "Max([SRC Sales Activity/Sale Date])",
            "Latest Sale Date present in the fact. The anchor for all recency and tenure math."),
    ],
    "groupings": [{"id": "g_asof", "groupBy": ["join_key"], "calculations": ["as_of_date"]}],
}

cust_activity = {
    "id": "cust_activity", "name": "Customer Activity", "kind": "table", "visibleAsSource": False,
    "description": (
        "Sales Activity collapsed to one row per customer. MANDATORY pre-aggregation: joining the "
        "4.9M-row order-line fact straight onto the customer dimension would fan the profile out. "
        "Dated by Sale Date, not Activity Date, so a return is charged back to the order that "
        "generated it and first/last purchase mean what they say. Returns carry negative Amount, so "
        "Sum(Amount) is already net."
    ),
    "source": {"kind": "table", "elementId": "src_sales_activity"},
    "columns": [
        col("cust_key", "Cust Key", "[SRC Sales Activity/Cust Key]"),
        col("join_key", "Join Key", "1", "Constant 1. Handle for the As Of cross join.", NUM0),
        col("first_purchase_date", "First Purchase Date", "Min([SRC Sales Activity/Sale Date])"),
        col("last_purchase_date", "Last Purchase Date", "Max([SRC Sales Activity/Sale Date])"),
        col("orders", "Orders",
            "CountDistinct(If([SRC Sales Activity/Activity Type] = \"Sale\", [SRC Sales Activity/Order Number], Null))",
            "Distinct purchase orders. Return rows are excluded so a returned order is not counted twice.", NUM0),
        col("returned_orders", "Returned Orders",
            "CountDistinct(If([SRC Sales Activity/Activity Type] = \"Return\", [SRC Sales Activity/Order Number], Null))",
            "Distinct orders that had at least one line come back.", NUM0),
        col("lifetime_net_sales", "Lifetime Net Sales", "Sum([SRC Sales Activity/Amount])", None, USD),
        col("lifetime_gross_sales", "Lifetime Gross Sales",
            "Sum(If([SRC Sales Activity/Activity Type] = \"Sale\", [SRC Sales Activity/Amount], 0))", None, USD),
        col("lifetime_returns", "Lifetime Returns",
            "Sum(If([SRC Sales Activity/Activity Type] = \"Return\", -[SRC Sales Activity/Amount], 0))",
            "Refund dollars, expressed positive.", USD),
        col("lifetime_net_units", "Lifetime Net Units", "Sum([SRC Sales Activity/Quantity])", None, NUM0),
        col("lifetime_gross_units", "Lifetime Gross Units",
            "Sum(If([SRC Sales Activity/Activity Type] = \"Sale\", [SRC Sales Activity/Quantity], 0))", None, NUM0),
        col("lifetime_net_cost", "Lifetime Net Cost", "Sum([SRC Sales Activity/Cost])", None, USD),
        col("return_units", "Return Units",
            "Sum(If([SRC Sales Activity/Activity Type] = \"Return\", -[SRC Sales Activity/Quantity], 0))", None, NUM0),
        col("distinct_stores", "Distinct Stores", "CountDistinct([SRC Sales Activity/Store Key])", None, NUM0),
        col("distinct_products", "Distinct Products", "CountDistinct([SRC Sales Activity/Product Key])", None, NUM0),
        col("distinct_salespeople", "Distinct Salespeople", "CountDistinct([SRC Sales Activity/Salesperson Key])", None, NUM0),
        col("retail_net_sales", "Retail Net Sales",
            "Sum(If([SRC Sales Activity/Channel Type] = \"Retail\", [SRC Sales Activity/Amount], 0))", None, USD),
        col("web_net_sales", "Web Net Sales",
            "Sum(If([SRC Sales Activity/Channel Type] = \"Web\", [SRC Sales Activity/Amount], 0))", None, USD),
        col("bopis_net_sales", "BOPIS Net Sales",
            "Sum(If([SRC Sales Activity/Channel Type] = \"BOPIS\", [SRC Sales Activity/Amount], 0))", None, USD),
        col("boss_net_sales", "BOSS Net Sales",
            "Sum(If([SRC Sales Activity/Channel Type] = \"BOSS\", [SRC Sales Activity/Amount], 0))", None, USD),
        col("retail_orders", "Retail Orders",
            "CountDistinct(If([SRC Sales Activity/Activity Type] = \"Sale\" and [SRC Sales Activity/Channel Type] = \"Retail\", [SRC Sales Activity/Order Number], Null))",
            None, NUM0),
        col("digital_orders", "Digital Orders",
            "CountDistinct(If([SRC Sales Activity/Activity Type] = \"Sale\" and [SRC Sales Activity/Channel Type] <> \"Retail\", [SRC Sales Activity/Order Number], Null))",
            "Web, BOPIS and BOSS orders combined.", NUM0),
    ],
    "groupings": [{
        "id": "g_cust",
        "groupBy": ["cust_key", "join_key"],
        "calculations": [
            "first_purchase_date", "last_purchase_date", "orders", "returned_orders",
            "lifetime_net_sales", "lifetime_gross_sales", "lifetime_returns",
            "lifetime_net_units", "lifetime_gross_units", "lifetime_net_cost", "return_units",
            "distinct_stores", "distinct_products", "distinct_salespeople",
            "retail_net_sales", "web_net_sales", "bopis_net_sales", "boss_net_sales",
            "retail_orders", "digital_orders",
        ],
    }],
}

cust_reviews_agg = {
    "id": "cust_reviews_agg", "name": "Customer Reviews Agg", "kind": "table", "visibleAsSource": False,
    "description": (
        "Reviews collapsed to one row per reviewing customer (4,442 of 4,972). Rating Points is the "
        "SUM of ratings, not the average: averaging a per-customer average would weight a one-review "
        "customer the same as a hundred-review customer, so the rollup metric divides Rating Points "
        "by Reviews instead."
    ),
    "source": {"kind": "table", "elementId": "src_product_review"},
    "columns": [
        col("cust_key", "Cust Key", "[SRC F_PRODUCT_REVIEW/Cust Key]"),
        col("reviews", "Reviews", "Count([SRC F_PRODUCT_REVIEW/Review ID])", None, NUM0),
        col("rating_points", "Rating Points", "Sum([SRC F_PRODUCT_REVIEW/Rating])",
            "Sum of star ratings. Divide by Reviews for a correctly weighted average at any rollup.", NUM0),
        col("first_review_date", "First Review Date", "Min([SRC F_PRODUCT_REVIEW/Review Date])"),
        col("last_review_date", "Last Review Date", "Max([SRC F_PRODUCT_REVIEW/Review Date])"),
        col("promoter_reviews", "Promoter Reviews",
            "Sum(If([SRC F_PRODUCT_REVIEW/Rating] >= 4, 1, 0))", "Ratings of 4 or 5.", NUM0),
        col("detractor_reviews", "Detractor Reviews",
            "Sum(If([SRC F_PRODUCT_REVIEW/Rating] <= 2, 1, 0))", "Ratings of 1 or 2.", NUM0),
    ],
    "groupings": [{
        "id": "g_rev", "groupBy": ["cust_key"],
        "calculations": ["reviews", "rating_points", "first_review_date", "last_review_date",
                         "promoter_reviews", "detractor_reviews"],
    }],
}


def mode_pair(base_id, base_name, key_id, key_name, key_col, grouping_a, grouping_b, grouping_c,
              out_id, out_name, out_key_id, out_key_name, desc_a, desc_c):
    """Three hidden elements that resolve 'the X this customer uses most'.

    Sigma has no arg-max aggregate, so this is the explicit SQL shape: count orders per
    customer-per-X, take the per-customer maximum, then rejoin and keep the X sitting at
    that maximum. Min() breaks ties deterministically on the lowest key.
    """
    detail = {
        "id": base_id, "name": base_name, "kind": "table", "visibleAsSource": False,
        "description": desc_a,
        "source": {"kind": "table", "elementId": "src_sales_orders"},
        "columns": [
            col("cust_key", "Cust Key", "[SRC Sales Orders/Cust Key]"),
            col(key_id, key_name, f"[SRC Sales Orders/{key_col}]"),
            col("orders", "Orders", "CountDistinct([SRC Sales Orders/Order Number])", None, NUM0),
        ],
        "groupings": [{"id": grouping_a, "groupBy": ["cust_key", key_id], "calculations": ["orders"]}],
    }
    mx = {
        "id": base_id + "_max", "name": base_name + " Max", "kind": "table", "visibleAsSource": False,
        "description": f"Per-customer maximum order count across {base_name}. Step 2 of the mode calculation.",
        "source": {"kind": "table", "elementId": base_id, "groupingId": grouping_a},
        "columns": [
            col("cust_key", "Cust Key", f"[{base_name}/Cust Key]"),
            col("max_orders", "Max Orders", f"Max([{base_name}/Orders])", None, NUM0),
        ],
        "groupings": [{"id": grouping_b, "groupBy": ["cust_key"], "calculations": ["max_orders"]}],
    }
    resolved = {
        "id": out_id, "name": out_name, "kind": "table", "visibleAsSource": False,
        "description": desc_c,
        "source": {
            "kind": "join",
            "primarySource": {"kind": "table", "elementId": base_id, "groupingId": grouping_a},
            "joins": [{
                "joinType": "left-outer",
                "left": {"kind": "table", "elementId": base_id, "groupingId": grouping_a},
                "right": {"kind": "table", "elementId": base_id + "_max", "groupingId": grouping_b},
                "columns": [{"left": "[Cust Key]", "right": "[Cust Key]"}],
            }],
        },
        "columns": [
            col("cust_key", "Cust Key", f"[{base_name}/Cust Key]"),
            col(out_key_id, out_key_name,
                f"Min(If([{base_name}/Orders] = [{base_name} Max/Max Orders], [{base_name}/{key_name}], Null))",
                "Ties are broken on the lowest key so the result is deterministic.", NUM0),
            col("mode_orders", out_name + " Orders", f"Max([{base_name} Max/Max Orders])",
                "Order count at the winning key.", NUM0),
        ],
        "groupings": [{"id": grouping_c, "groupBy": ["cust_key"],
                       "calculations": [out_key_id, "mode_orders"]}],
    }
    return [detail, mx, resolved]


store_mode = mode_pair(
    "cust_store_orders", "Cust Store Orders", "store_key", "Store Key", "Store Key",
    "g_cso", "g_csm", "g_pstore", "primary_store", "Primary Store", "primary_store_key", "Primary Store Key",
    "Orders per customer per store. Step 1 of resolving each customer's home store. Built on Sales "
    "Orders, not Sales Activity, so a large basket does not outvote several small ones.",
    "Each customer's most-shopped store. Step 3: rejoin the per-store counts to the per-customer "
    "maximum and keep the store sitting at it.",
)

sp_mode = mode_pair(
    "cust_sp_orders", "Cust Salesperson Orders", "salesperson_key", "Salesperson Key", "Salesperson Key",
    "g_cspo", "g_cspm", "g_psp", "primary_salesperson", "Primary Salesperson",
    "primary_salesperson_key", "Primary Salesperson Key",
    "Orders per customer per salesperson. Step 1 of resolving each customer's regular associate.",
    "Each customer's most-frequent salesperson - the clienteling hand-off. Step 3 of the mode calculation.",
)

customer_spine = {
    "id": "customer_spine", "name": "Customer Spine", "kind": "table", "visibleAsSource": False,
    "description": (
        "The Customer dimension plus a constant Join Key. Exists purely so Customer Profile can "
        "cross-join the single As Of row without polluting the conformed Customer dimension with a "
        "meaningless key."
    ),
    "source": {"kind": "table", "elementId": "dim_customer"},
    "columns": [col(cid, disp, f"[Customer/{disp}]") for cid, disp in CUSTOMER_COLS] + [
        col("birthday_month", "Birthday Month", "[Customer/Birthday Month]", None, NUM0),
        col("birthday_day", "Birthday Day", "[Customer/Birthday Day]", None, NUM0),
        col("has_birthday", "Has Birthday", "[Customer/Has Birthday]"),
        col("join_key", "Join Key", "1", "Constant 1. Cross-join handle only.", NUM0),
    ],
}

build = [as_of, cust_activity, cust_reviews_agg, customer_spine] + store_mode + sp_mode

# ---------------------------------------------------------------- Page 4: Customer 360

# Sigma resolves column references against SOURCE elements, not against sibling columns of the
# same element, so the cadence arithmetic is composed here and inlined wherever it is needed
# rather than one column referring to another.
SPAN = ('DateDiff("day", [Customer Activity/First Purchase Date], '
        '[Customer Activity/Last Purchase Date])')
RECENCY = 'DateDiff("day", [Customer Activity/Last Purchase Date], [As Of/As Of Date])'
ORDERS = '[Customer Activity/Orders]'
CADENCE = f'({SPAN} / ({ORDERS} - 1))'
# A cadence only means something for a customer with at least two orders on at least two days.
HAS_CADENCE = f'({ORDERS} > 1 and {SPAN} > 0)'

profile_metrics = [
    {"id": "m_customers", "name": "Customers", "formula": "CountDistinct([Cust Key])", "format": NUM0},
    {"id": "m_purchasing_customers", "name": "Purchasing Customers",
     "formula": "CountDistinct(If([Orders] > 0, [Cust Key], Null))", "format": NUM0},
    {"id": "m_lifetime_value", "name": "Lifetime Value", "formula": "Sum([Lifetime Net Sales])", "format": USD},
    {"id": "m_avg_ltv", "name": "Avg Lifetime Value",
     "formula": "[Metrics/Lifetime Value] / [Metrics/Purchasing Customers]", "format": USD},
    {"id": "m_gross_sales", "name": "Gross Sales", "formula": "Sum([Lifetime Gross Sales])", "format": USD},
    {"id": "m_returns", "name": "Returns", "formula": "Sum([Lifetime Returns])", "format": USD},
    {"id": "m_return_rate", "name": "Return Rate %",
     "formula": "[Metrics/Returns] / [Metrics/Gross Sales]", "format": PCT},
    {"id": "m_orders", "name": "Orders", "formula": "Sum([Orders])", "format": NUM0},
    {"id": "m_net_units", "name": "Net Units", "formula": "Sum([Lifetime Net Units])", "format": NUM0},
    {"id": "m_net_cost", "name": "Net Cost", "formula": "Sum([Lifetime Net Cost])", "format": USD},
    {"id": "m_gross_margin", "name": "Gross Margin",
     "formula": "Sum([Lifetime Net Sales]) - Sum([Lifetime Net Cost])", "format": USD},
    {"id": "m_margin_pct", "name": "Margin %",
     "formula": "[Metrics/Gross Margin] / [Metrics/Lifetime Value]", "format": PCT},
    {"id": "m_aov", "name": "AOV", "formula": "[Metrics/Lifetime Value] / [Metrics/Orders]", "format": USD},
    {"id": "m_upt", "name": "UPT", "formula": "[Metrics/Net Units] / [Metrics/Orders]", "format": NUM2},
    {"id": "m_frequency", "name": "Frequency",
     "formula": "[Metrics/Orders] / [Metrics/Purchasing Customers]", "format": NUM2},
    {"id": "m_repeat_customers", "name": "Repeat Customers",
     "formula": "CountDistinct(If([Orders] > 1, [Cust Key], Null))", "format": NUM0},
    {"id": "m_repeat_rate", "name": "Repeat Rate %",
     "formula": "[Metrics/Repeat Customers] / [Metrics/Purchasing Customers]", "format": PCT},
    {"id": "m_avg_recency", "name": "Avg Recency Days", "formula": "Avg([Recency Days])", "format": NUM2},
    {"id": "m_avg_cadence", "name": "Avg Order Cadence Days",
     "formula": "Avg([Order Cadence Days])", "format": NUM2},
    {"id": "m_lapsed_customers", "name": "Lapsed Customers",
     "formula": "CountDistinct(If([Churn Risk] = \"Lapsed\", [Cust Key], Null))", "format": NUM0},
    {"id": "m_lapsed_rate", "name": "Lapsed Rate %",
     "formula": "[Metrics/Lapsed Customers] / [Metrics/Purchasing Customers]", "format": PCT},
    {"id": "m_digital_orders", "name": "Digital Orders", "formula": "Sum([Digital Orders])", "format": NUM0},
    {"id": "m_digital_mix", "name": "Digital Order Mix %",
     "formula": "[Metrics/Digital Orders] / [Metrics/Orders]", "format": PCT},
    {"id": "m_reviews", "name": "Reviews", "formula": "Sum([Reviews])", "format": NUM0},
    {"id": "m_reviewing_customers", "name": "Reviewing Customers",
     "formula": "CountDistinct(If([Reviews] > 0, [Cust Key], Null))", "format": NUM0},
    {"id": "m_avg_rating", "name": "Avg Rating Given",
     "formula": "Sum([Rating Points]) / Sum([Reviews])", "format": NUM2},
    {"id": "m_spend_per_customer", "name": "Spend per Customer",
     "formula": "[Metrics/Lifetime Value] / [Metrics/Purchasing Customers]", "format": USD},
]

customer_profile = {
    "id": "customer_profile", "name": "Customer Profile", "kind": "table", "visibleAsSource": True,
    "description": (
        "One row per customer (4,972) - the Customer 360 spine. Every fact is LEFT JOINed onto the "
        "customer dimension, so the 105 customers who have never transacted are PRESENT with null "
        "activity rather than silently dropped; count customers with the Customers metric and buyers "
        "with Purchasing Customers, and never assume the two agree. "
        "RFM lives here as three continuous columns - Recency Days, Orders, Lifetime Net Sales - "
        "rather than as baked-in 1-5 scores: this population is extraordinarily dense (median 140 "
        "orders, 80% of customers having bought within 38 days), so any fixed score cut would be "
        "stale the moment the data moved. Cut quintiles in the workbook instead. "
        "Recency is measured against As Of Date (the latest Sale Date in the fact, 2025-10-18), "
        "NOT against Today(); this is a static extract and Today() would report every customer as "
        "churned. Churn Risk is therefore cadence-relative, not calendar-relative - see that column. "
        "A handful of columns are per-customer ratios (Customer AOV, Customer Return Rate %, "
        "Order Cadence Days, Avg Rating Given): they are attributes OF a customer and are the right "
        "thing to filter and segment on, but they must be averaged, never summed - use the "
        "corresponding metric for any rollup."
    ),
    "source": {
        "kind": "join",
        "primarySource": {"kind": "table", "elementId": "customer_spine"},
        "joins": [
            {"joinType": "left-outer",
             "left": {"kind": "table", "elementId": "customer_spine"},
             "right": {"kind": "table", "elementId": "as_of", "groupingId": "g_asof"},
             "columns": [{"left": "[Join Key]", "right": "[Join Key]"}]},
            {"joinType": "left-outer",
             "left": {"kind": "table", "elementId": "customer_spine"},
             "right": {"kind": "table", "elementId": "cust_activity", "groupingId": "g_cust"},
             "columns": [{"left": "[Cust Key]", "right": "[Cust Key]"}]},
            {"joinType": "left-outer",
             "left": {"kind": "table", "elementId": "customer_spine"},
             "right": {"kind": "table", "elementId": "cust_reviews_agg", "groupingId": "g_rev"},
             "columns": [{"left": "[Cust Key]", "right": "[Cust Key]"}]},
            {"joinType": "left-outer",
             "left": {"kind": "table", "elementId": "customer_spine"},
             "right": {"kind": "table", "elementId": "primary_store", "groupingId": "g_pstore"},
             "columns": [{"left": "[Cust Key]", "right": "[Cust Key]"}]},
            {"joinType": "left-outer",
             "left": {"kind": "table", "elementId": "customer_spine"},
             "right": {"kind": "table", "elementId": "primary_salesperson", "groupingId": "g_psp"},
             "columns": [{"left": "[Cust Key]", "right": "[Cust Key]"}]},
            {"joinType": "left-outer",
             "left": {"kind": "table", "elementId": "primary_store", "groupingId": "g_pstore"},
             "right": {"kind": "table", "elementId": "dim_store"},
             "columns": [{"left": "[Primary Store Key]", "right": "[Store Key]"}]},
            {"joinType": "left-outer",
             "left": {"kind": "table", "elementId": "primary_salesperson", "groupingId": "g_psp"},
             "right": {"kind": "table", "elementId": "dim_salesperson"},
             "columns": [{"left": "[Primary Salesperson Key]", "right": "[Salesperson Key]"}]},
        ],
    },
    "columns": [
        # --- identity
        col("cust_key", "Cust Key", "[Customer Spine/Cust Key]"),
        col("cust_name", "Cust Name", "[Customer Spine/Cust Name]"),
        col("cust_city", "Cust City", "[Customer Spine/Cust City]"),
        col("cust_state", "Cust State", "[Customer Spine/Cust State]"),
        col("cust_county", "Cust County", "[Customer Spine/Cust County]"),
        col("cust_zip_code", "Cust Zip Code", "[Customer Spine/Cust Zip Code]"),
        col("cust_region", "Cust Region", "[Customer Spine/Cust Region]"),
        col("cust_type", "Cust Type", "[Customer Spine/Cust Type]", "'Individual' (4,806) or 'Company' (166)."),
        col("cust_gender", "Cust Gender", "[Customer Spine/Cust Gender]"),
        col("cust_age", "Cust Age", "[Customer Spine/Cust Age]", None, NUM0),
        col("age_group", "Age Group", "[Customer Spine/Age Group]"),
        col("civil_status", "Civil Status", "[Customer Spine/Civil Status]"),
        col("loyalty_program", "Loyalty Program", "[Customer Spine/Loyalty Program]",
            "1 if enrolled, 0 if not. 1,958 of 4,972 are enrolled.", NUM0),
        col("loyalty_tier", "Loyalty Tier", "[Customer Spine/Loyalty Tier]",
            "'platinum_member' or 'at_risk'. Blank for 3,323 customers, who are unenrolled or untiered - "
            "blank is NOT a third tier."),
        col("downloaded_app", "Downloaded App", "[Customer Spine/Downloaded App]"),
        col("birthday_month", "Birthday Month", "[Customer Spine/Birthday Month]",
            "Birth month, 1-12. NULL for 2,559 of 4,972 customers (51%).", NUM0),
        col("birthday_day", "Birthday Day", "[Customer Spine/Birthday Day]", None, NUM0),
        col("has_birthday", "Has Birthday", "[Customer Spine/Has Birthday]",
            "'Y' when a birthday is on file. Only 2,413 customers have one - use this as the "
            "denominator on any birthday campaign."),
        col("cust_since", "Cust Since", "[Customer Spine/Cust Since]", "Date the customer record was created."),

        # --- the as-of anchor
        col("as_of_date", "As Of Date", "[As Of/As Of Date]",
            "The latest Sale Date in the fact (2025-10-18). Every recency and tenure figure on this "
            "row is measured against it, not against Today(). Null for the 105 customers with no "
            "activity, which is also why their Recency Days is null."),

        # --- RFM: recency
        col("first_purchase_date", "First Purchase Date", "[Customer Activity/First Purchase Date]"),
        col("last_purchase_date", "Last Purchase Date", "[Customer Activity/Last Purchase Date]"),
        col("recency_days", "Recency Days",
            "DateDiff(\"day\", [Customer Activity/Last Purchase Date], [As Of/As Of Date])",
            "Days from the customer's last purchase to As Of Date. The 'R' of RFM. Ranges 0-1,161; "
            "median 4, 80th percentile 38 - this base buys very frequently, so raw recency "
            "separates customers poorly. Prefer Churn Risk, which normalises recency by each "
            "customer's own cadence.", NUM0),
        col("tenure_days", "Tenure Days",
            "DateDiff(\"day\", [Customer Spine/Cust Since], [As Of/As Of Date])",
            "Days from record creation to As Of Date.", NUM0),
        col("tenure_years", "Tenure Years",
            "DateDiff(\"day\", [Customer Spine/Cust Since], [As Of/As Of Date]) / 365.25", None, NUM2),
        col("active_days", "Active Days",
            "DateDiff(\"day\", [Customer Activity/First Purchase Date], [Customer Activity/Last Purchase Date])",
            "Span from first to last purchase. Averages 1,261 days - most of the 1,522-day window.", NUM0),

        # --- RFM: frequency and monetary
        col("orders", "Orders", "[Customer Activity/Orders]",
            "Lifetime distinct purchase orders. The 'F' of RFM. Median 140, range 2-442.", NUM0),
        col("returned_orders", "Returned Orders", "[Customer Activity/Returned Orders]", None, NUM0),
        col("lifetime_net_sales", "Lifetime Net Sales", "[Customer Activity/Lifetime Net Sales]",
            "Lifetime spend net of refunds. The 'M' of RFM.", USD),
        col("lifetime_gross_sales", "Lifetime Gross Sales", "[Customer Activity/Lifetime Gross Sales]", None, USD),
        col("lifetime_returns", "Lifetime Returns", "[Customer Activity/Lifetime Returns]",
            "Refund dollars, expressed positive.", USD),
        col("lifetime_net_units", "Lifetime Net Units", "[Customer Activity/Lifetime Net Units]", None, NUM0),
        col("lifetime_net_cost", "Lifetime Net Cost", "[Customer Activity/Lifetime Net Cost]", None, USD),
        col("lifetime_gross_margin", "Lifetime Gross Margin",
            "[Customer Activity/Lifetime Net Sales] - [Customer Activity/Lifetime Net Cost]", None, USD),
        col("return_units", "Return Units", "[Customer Activity/Return Units]", None, NUM0),

        # --- per-customer ratios (attributes, not rollups)
        col("customer_aov", "Customer AOV",
            "[Customer Activity/Lifetime Net Sales] / [Customer Activity/Orders]",
            "This customer's own average order value. Segment and filter on it; do NOT sum or "
            "average it for a population figure - use the AOV metric, which divides totals.", USD),
        col("customer_upt", "Customer UPT",
            "[Customer Activity/Lifetime Net Units] / [Customer Activity/Orders]",
            "This customer's units per transaction. Attribute only - use the UPT metric for rollups.", NUM2),
        col("customer_return_rate", "Customer Return Rate %",
            "[Customer Activity/Lifetime Returns] / [Customer Activity/Lifetime Gross Sales]",
            "This customer's refunds as a share of their gross spend. Attribute only - use the "
            "Return Rate % metric for rollups. Company baseline is 5.44%.", PCT),

        # --- cadence and churn
        col("order_cadence_days", "Order Cadence Days",
            f"If({HAS_CADENCE}, {CADENCE}, Null)",
            "Average days between this customer's orders. Median 7.0; 10th percentile 5.3, 90th 75.8. "
            "Null for customers with fewer than two orders, or whose orders all fall on one day - "
            "neither has a cadence to measure. Attribute only: average it, never sum it.", NUM2),
        col("cadence_ratio", "Cadence Ratio",
            f"If({HAS_CADENCE}, {RECENCY} / {CADENCE}, Null)",
            "Recency Days divided by this customer's own Order Cadence Days. 1.0 means they are "
            "exactly due; 3.0 means they have gone three times their normal gap without buying. "
            "This is the churn signal that works on this base - absolute recency does not, because "
            "everyone buys often.", NUM2),
        col("churn_risk", "Churn Risk",
            f"If({HAS_CADENCE}, "
            f"If({RECENCY} > 3 * {CADENCE}, \"Lapsed\", "
            f"If({RECENCY} > 1.5 * {CADENCE}, \"Stretching\", \"On Cadence\")), "
            f"\"Unknown\")",
            "Cadence-relative churn band: Lapsed (past 3x their own normal gap, 657 customers), "
            "Stretching (1.5-3x, 306), On Cadence (3,903), Unknown (106). Unknown is the 105 "
            "never-transacted customers plus customer 4835, whose two orders fell on the same day - "
            "a zero-length history has no cadence to be late against, and is not evidence of churn. "
            "Deliberately NOT a calendar rule: a fixed 90-day-inactive test would flag almost nobody "
            "here, because 80% of customers bought within 38 days of the As Of Date."),
        col("is_repeat_customer", "Is Repeat Customer", "[Customer Activity/Orders] > 1"),
        col("has_purchased", "Has Purchased",
            "If(IsNull([Customer Activity/Orders]), \"N\", \"Y\")",
            "'N' for the 105 customers in the dimension who have never transacted. They are kept "
            "here on purpose so the customer base is not silently understated."),

        # --- channel behaviour
        col("retail_net_sales", "Retail Net Sales", "[Customer Activity/Retail Net Sales]", None, USD),
        col("web_net_sales", "Web Net Sales", "[Customer Activity/Web Net Sales]", None, USD),
        col("bopis_net_sales", "BOPIS Net Sales", "[Customer Activity/BOPIS Net Sales]", None, USD),
        col("boss_net_sales", "BOSS Net Sales", "[Customer Activity/BOSS Net Sales]", None, USD),
        col("retail_orders", "Retail Orders", "[Customer Activity/Retail Orders]", None, NUM0),
        col("digital_orders", "Digital Orders", "[Customer Activity/Digital Orders]",
            "Web, BOPIS and BOSS orders combined.", NUM0),
        col("customer_digital_mix", "Customer Digital Mix %",
            "[Customer Activity/Digital Orders] / [Customer Activity/Orders]",
            "This customer's share of orders placed digitally. Attribute only - use the "
            "Digital Order Mix % metric for rollups.", PCT),
        col("distinct_stores", "Distinct Stores", "[Customer Activity/Distinct Stores]", None, NUM0),
        col("distinct_products", "Distinct Products", "[Customer Activity/Distinct Products]", None, NUM0),
        col("distinct_salespeople", "Distinct Salespeople", "[Customer Activity/Distinct Salespeople]", None, NUM0),

        # --- relationships
        col("primary_store_key", "Primary Store Key", "[Primary Store/Primary Store Key]",
            "The store this customer orders from most. Ties break on the lowest store key.", NUM0),
        col("primary_store_name", "Primary Store Name", "[Store/Store Name]"),
        col("primary_store_region", "Primary Store Region", "[Store/Store Region]"),
        col("primary_store_area", "Primary Store Area", "[Store/Store Area]"),
        col("primary_store_state", "Primary Store State", "[Store/Store State]"),
        col("primary_store_orders", "Primary Store Orders", "[Primary Store/Primary Store Orders]",
            "Orders placed at the primary store. Compare with Orders to see how concentrated the "
            "relationship is.", NUM0),
        col("primary_salesperson_key", "Primary Salesperson Key",
            "[Primary Salesperson/Primary Salesperson Key]",
            "The associate who has rung this customer up most - the clienteling hand-off. Ties break "
            "on the lowest salesperson key.", NUM0),
        col("primary_salesperson_name", "Primary Salesperson Name", "[Salesperson/Salesperson Name]"),
        col("primary_salesperson_tier", "Primary Salesperson Tier", "[Salesperson/Tier]",
            "Seniority band, not a rate band."),
        col("primary_salesperson_status", "Primary Salesperson Status", "[Salesperson/Employment Status]",
            "'Terminated' here means the customer's regular associate has left - a concrete "
            "reassignment queue for clienteling."),
        col("primary_salesperson_orders", "Primary Salesperson Orders",
            "[Primary Salesperson/Primary Salesperson Orders]", None, NUM0),

        # --- voice of customer
        col("reviews", "Reviews", "[Customer Reviews Agg/Reviews]",
            "Reviews written. 4,442 of 4,972 customers have written at least one.", NUM0),
        col("rating_points", "Rating Points", "[Customer Reviews Agg/Rating Points]",
            "Sum of stars given. Exists so Avg Rating Given can be weighted correctly at rollup.", NUM0),
        col("avg_rating_given", "Avg Rating Given",
            "[Customer Reviews Agg/Rating Points] / [Customer Reviews Agg/Reviews]",
            "This customer's average star rating. Company average is 4.01. Attribute only - use the "
            "Avg Rating Given metric for rollups.", NUM2),
        col("promoter_reviews", "Promoter Reviews", "[Customer Reviews Agg/Promoter Reviews]", None, NUM0),
        col("detractor_reviews", "Detractor Reviews", "[Customer Reviews Agg/Detractor Reviews]", None, NUM0),
        col("first_review_date", "First Review Date", "[Customer Reviews Agg/First Review Date]"),
        col("last_review_date", "Last Review Date", "[Customer Reviews Agg/Last Review Date]"),
    ],
    "metrics": profile_metrics,
}

customer_reviews = {
    "id": "customer_reviews", "name": "Customer Reviews", "kind": "table", "visibleAsSource": True,
    "description": (
        "One row per product review (137,944), joined to Customer, Product and the fiscal calendar. "
        "Covers 4,442 of 4,972 customers, 2021-08-22 to 2025-10-18, average rating 4.01. "
        "Verified Purchase is deliberately absent: it is 'Y' on every row. It is also redundant - "
        "every one of the 137,944 reviews was independently confirmed against a real purchase of "
        "that product by that customer, so a review here genuinely does imply a purchase. "
        "This element is review-grain, so summing customer attributes off it will multiply them by "
        "review count - roll customers up from Customer Profile instead."
    ),
    "source": {
        "kind": "join",
        "primarySource": {"kind": "table", "elementId": "src_product_review"},
        "joins": [
            {"joinType": "left-outer",
             "left": {"kind": "table", "elementId": "src_product_review"},
             "right": {"kind": "table", "elementId": "dim_customer"},
             "columns": [{"left": "[Cust Key]", "right": "[Cust Key]"}]},
            {"joinType": "left-outer",
             "left": {"kind": "table", "elementId": "src_product_review"},
             "right": {"kind": "table", "elementId": "dim_product"},
             "columns": [{"left": "[Product Key]", "right": "[Product Key]"}]},
            {"joinType": "left-outer",
             "left": {"kind": "table", "elementId": "src_product_review"},
             "right": {"kind": "table", "elementId": "dim_date"},
             "columns": [{"left": "[Review Date]", "right": "[Date Key]"}]},
        ],
    },
    "columns": [
        col("review_id", "Review ID", "[SRC F_PRODUCT_REVIEW/Review ID]"),
        col("cust_key", "Cust Key", "[SRC F_PRODUCT_REVIEW/Cust Key]"),
        col("product_key", "Product Key", "[SRC F_PRODUCT_REVIEW/Product Key]"),
        col("review_date", "Review Date", "[SRC F_PRODUCT_REVIEW/Review Date]"),
        col("rating", "Rating", "[SRC F_PRODUCT_REVIEW/Rating]", "Stars, 1-5.", NUM0),
        col("rating_band", "Rating Band",
            "If([SRC F_PRODUCT_REVIEW/Rating] >= 4, \"Promoter\", If([SRC F_PRODUCT_REVIEW/Rating] <= 2, \"Detractor\", \"Passive\"))",
            "Promoter (4-5), Passive (3), Detractor (1-2)."),
        col("cust_name", "Cust Name", "[Customer/Cust Name]"),
        col("cust_region", "Cust Region", "[Customer/Cust Region]"),
        col("cust_type", "Cust Type", "[Customer/Cust Type]"),
        col("age_group", "Age Group", "[Customer/Age Group]"),
        col("loyalty_tier", "Loyalty Tier", "[Customer/Loyalty Tier]"),
        col("downloaded_app", "Downloaded App", "[Customer/Downloaded App]"),
        col("product_name", "Product Name", "[Product/Product Name]"),
        col("product_type", "Product Type", "[Product/Product Type]"),
        col("product_family", "Product Family", "[Product/Product Family]"),
        col("product_line", "Product Line", "[Product/Product Line]"),
        col("product_group", "Product Group", "[Product/Product Group]", "Brand or manufacturer."),
        col("vendor_key", "Vendor Key", "[Product/Vendor Key]", None, NUM0),
        col("fiscal_year", "Fiscal Year", "[Date/Fiscal Year]"),
        col("fiscal_quarter", "Fiscal Quarter", "[Date/Fiscal Quarter]"),
        col("fiscal_period", "Fiscal Period", "[Date/Fiscal Period]"),
        col("fiscal_period_name", "Fiscal Period Name", "[Date/Fiscal Period Name]"),
        col("fiscal_season", "Fiscal Season", "[Date/Fiscal Season]"),
        col("calendar_year", "Calendar Year", "[Date/Calendar Year]"),
        col("calendar_month_name", "Calendar Month Name", "[Date/Calendar Month Name]"),
        col("week_start_date", "Week Start Date", "[Date/Week Start Date]"),
    ],
    "metrics": [
        {"id": "m_r_reviews", "name": "Reviews", "formula": "Count([Review ID])", "format": NUM0},
        {"id": "m_r_avg_rating", "name": "Avg Rating", "formula": "Avg([Rating])", "format": NUM2},
        {"id": "m_r_reviewers", "name": "Reviewers", "formula": "CountDistinct([Cust Key])", "format": NUM0},
        {"id": "m_r_promoters", "name": "Promoter Reviews",
         "formula": "Sum(If([Rating] >= 4, 1, 0))", "format": NUM0},
        {"id": "m_r_detractors", "name": "Detractor Reviews",
         "formula": "Sum(If([Rating] <= 2, 1, 0))", "format": NUM0},
        {"id": "m_r_promoter_pct", "name": "Promoter %",
         "formula": "[Metrics/Promoter Reviews] / [Metrics/Reviews]", "format": PCT},
        {"id": "m_r_detractor_pct", "name": "Detractor %",
         "formula": "[Metrics/Detractor Reviews] / [Metrics/Reviews]", "format": PCT},
        {"id": "m_r_nps_like", "name": "Promoter Less Detractor %",
         "formula": "[Metrics/Promoter %] - [Metrics/Detractor %]", "format": PCT},
    ],
}

customer_category_mix = {
    "id": "customer_category_mix", "name": "Customer Category Mix", "kind": "table", "visibleAsSource": True,
    "description": (
        "Customer x Product Type x Product Family spend (55,588 rows, 4,867 customers, 6 types, "
        "13 families), for affinity and next-best-product work. Deliberately NOT collapsed to a "
        "single 'favourite category' column on Customer Profile: a single winner hides the mix, and "
        "sorting this element by Net Sales recovers the favourite whenever it is actually wanted. "
        "DOLLARS AND UNITS ADD UP; ORDER AND CUSTOMER COUNTS DO NOT. Net Sales summed over the whole "
        "element reconciles exactly to company net sales ($1,114,855,651.92), because every order "
        "line belongs to exactly one family. Orders does not: a basket spanning three families is "
        "counted once in each, so summing Orders here gives 3,270,599 against a true 717,747 - a 4.6x "
        "overstatement. Use Orders only WITHIN a single family, and take company or customer order "
        "counts from Customer Profile. "
        "Customer attributes are deliberately not carried here; join to Customer Profile for those."
    ),
    "source": {"kind": "table", "elementId": "src_sales_activity"},
    "columns": [
        col("cust_key", "Cust Key", "[SRC Sales Activity/Cust Key]"),
        col("product_type", "Product Type", "[SRC Sales Activity/Product Type]"),
        col("product_family", "Product Family", "[SRC Sales Activity/Product Family]"),
        col("net_sales", "Net Sales", "Sum([SRC Sales Activity/Amount])", None, USD),
        col("gross_sales", "Gross Sales",
            "Sum(If([SRC Sales Activity/Activity Type] = \"Sale\", [SRC Sales Activity/Amount], 0))", None, USD),
        col("returns", "Returns",
            "Sum(If([SRC Sales Activity/Activity Type] = \"Return\", -[SRC Sales Activity/Amount], 0))", None, USD),
        col("net_units", "Net Units", "Sum([SRC Sales Activity/Quantity])", None, NUM0),
        col("orders", "Orders",
            "CountDistinct(If([SRC Sales Activity/Activity Type] = \"Sale\", [SRC Sales Activity/Order Number], Null))",
            None, NUM0),
        col("distinct_products", "Distinct Products", "CountDistinct([SRC Sales Activity/Product Key])", None, NUM0),
    ],
    "groupings": [{
        "id": "g_mix", "groupBy": ["cust_key", "product_type", "product_family"],
        "calculations": ["net_sales", "gross_sales", "returns", "net_units", "orders", "distinct_products"],
    }],
    "metrics": [
        {"id": "m_mix_net_sales", "name": "Net Sales", "formula": "Sum([Net Sales])", "format": USD},
        {"id": "m_mix_gross_sales", "name": "Gross Sales", "formula": "Sum([Gross Sales])", "format": USD},
        {"id": "m_mix_returns", "name": "Returns", "formula": "Sum([Returns])", "format": USD},
        # customer_category_mix is a GROUPED element, and [Metrics/...] references do not resolve
        # inside one - they bind to the like-named column instead and the query dies. Ratio metrics
        # on grouped elements must aggregate the columns directly.
        {"id": "m_mix_return_rate", "name": "Return Rate %",
         "formula": "Sum([Returns]) / Sum([Gross Sales])", "format": PCT},
        {"id": "m_mix_orders", "name": "Orders", "formula": "Sum([Orders])", "format": NUM0},
        {"id": "m_mix_units", "name": "Net Units", "formula": "Sum([Net Units])", "format": NUM0},
        {"id": "m_mix_customers", "name": "Customers", "formula": "CountDistinct([Cust Key])", "format": NUM0},
        {"id": "m_mix_spend_per_customer", "name": "Spend per Customer",
         "formula": "Sum([Net Sales]) / CountDistinct([Cust Key])", "format": USD},
    ],
}

PAGES = [
    {"id": "page_sources", "name": "Sources", "elements": sources},
    {"id": "page_dims", "name": "Conformed Dimensions", "elements": dims},
    {"id": "page_build", "name": "Customer Build", "elements": build},
    {"id": "page_360", "name": "Customer 360",
     "elements": [customer_profile, customer_reviews, customer_category_mix]},
]

spec = {
    "name": "Retail Customer 360",
    "description": (
        "Customer-grain model: RFM, lifetime value, channel behaviour, category affinity, "
        "primary store and associate, and voice of customer on one spine. Recency is anchored to "
        "the data's own As Of Date and churn is measured against each customer's own purchase "
        "cadence. Sources conformed dimensions from the Retail Sales Activity model."
    ),
    "pages": PAGES,
}

if __name__ == "__main__":
    pages = spec["pages"]
    if "--pages" in sys.argv:
        want = sys.argv[sys.argv.index("--pages") + 1].split(",")
        pages = [p for i, p in enumerate(spec["pages"], 1) if str(i) in want]
    print(json.dumps({**spec, "pages": pages}, indent=2))
