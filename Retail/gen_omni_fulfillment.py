import json

SALESACT = "8c548776-acb2-46ac-b60d-dd5a70781bd2"

def col(cid, name, formula, desc=None, fmt=None):
    c = {"id": cid, "name": name, "formula": formula}
    if desc: c["description"] = desc
    if fmt: c["format"] = fmt
    return c

def met(mid, name, formula, fmt, desc):
    return {"id": mid, "name": name, "formula": formula, "format": fmt, "description": desc}

USD  = {"kind": "number", "formatString": "$,.2f"}
NUM0 = {"kind": "number", "formatString": ",.0f"}
NUM2 = {"kind": "number", "formatString": ",.2f"}
PCT  = {"kind": "number", "formatString": ".2%"}

def src(eid, name, model, origin_elem, origin_name, cols, desc=None):
    e = {
        "id": eid, "name": name, "kind": "table",
        "source": {"kind": "data-model", "dataModelId": model, "elementId": origin_elem},
        "columns": [col(cid, disp, f"[{origin_name}/{disp}]") for cid, disp in cols],
        "visibleAsSource": False,
    }
    if desc: e["description"] = desc
    return e

# ---------------------------------------------------------------- Page 1: Sources
ORDER_COLS = [("order_number","Order Number"),("date","Date"),("date_key","Date Key"),
              ("store_key","Store Key"),("cust_key","Cust Key"),("salesperson_key","Salesperson Key"),
              ("channel_type","Channel Type"),("transaction_type","Transaction Type"),
              ("purchase_method","Purchase Method"),
              ("transaction_location_key","Transaction Location Key"),
              ("fulfillment_location_key","Fulfillment Location Key"),
              ("salesperson_name","Salesperson Name"),("salesperson_tier","Tier")]

ACTIVITY_COLS = [("order_number","Order Number"),("activity_type","Activity Type"),
                 ("quantity","Quantity"),("amount","Amount"),("cost","Cost"),
                 ("product_key","Product Key")]

STORE_COLS = [("store_key","Store Key"),("store_name","Store Name"),("store_city","Store City"),
              ("store_state","Store State"),("store_region","Store Region"),("store_area","Store Area"),
              ("store_type","Store Type"),("store_size","Store Size"),
              ("selling_square_footage","Selling Square Footage"),("online_ordering","Online Ordering"),
              ("latitude","Latitude"),("longitude","Longitude")]

DATE_COLS = [("date_key","Date Key"),("day_of_week_name","Day of Week Name"),
             ("is_weekend","Is Weekend"),("week_start_date","Week Start Date"),
             ("calendar_year","Calendar Year"),("calendar_month","Calendar Month"),
             ("calendar_month_name","Calendar Month Name"),("calendar_quarter","Calendar Quarter"),
             ("fiscal_year","Fiscal Year"),("fiscal_quarter","Fiscal Quarter"),
             ("fiscal_period","Fiscal Period"),("fiscal_period_name","Fiscal Period Name"),
             ("fiscal_week_of_year","Fiscal Week of Year"),("fiscal_season","Fiscal Season"),
             ("prior_year_date","Prior Year Date")]

CUST_COLS = [("cust_key","Cust Key"),("cust_name","Cust Name"),("cust_city","Cust City"),
             ("cust_state","Cust State"),("cust_region","Cust Region"),("cust_type","Cust Type"),
             ("age_group","Age Group"),("loyalty_program","Loyalty Program"),
             ("loyalty_tier","Loyalty Tier"),("downloaded_app","Downloaded App")]

sources = [
    src("src_sales_orders","SRC Sales Orders",SALESACT,"sales_orders","Sales Orders",ORDER_COLS,
        "Order-grain fact referenced from the Retail Sales Activity model (717,747 orders). Carries the routing keys this model exists to interpret."),
    src("src_sales_activity","SRC Sales Activity",SALESACT,"sales_activity","Sales Activity",ACTIVITY_COLS,
        "Order-LINE grain sales and returns fact referenced from Retail Sales Activity (4.9M lines). Projected to the columns needed for order-level dollars. Must be pre-aggregated to order grain before joining."),
    src("src_store","SRC Store",SALESACT,"dim_store","Store",STORE_COLS,
        "Conformed Store dimension referenced from the Retail Sales Activity model."),
    src("src_date","SRC Date",SALESACT,"dim_date","Date",DATE_COLS,
        "Conformed Date dimension (4-5-4 fiscal) referenced from the Retail Sales Activity model."),
    src("src_customer","SRC Customer",SALESACT,"dim_customer","Customer",CUST_COLS,
        "Conformed Customer dimension referenced from the Retail Sales Activity model."),
]

# ---------------------------------------------------------------- Page 2: Conformed Dimensions
dims = [
 {"id":"dim_store","name":"Store","kind":"table","visibleAsSource":True,
  "description":"200 selling stores plus the Central Warehouse (Store Key 9999). The warehouse row is nearly empty upstream: it has NO latitude, longitude, city, state or region. That is why this model ships no fulfilment-distance metric - see the Fulfillment Orders description.",
  "source":{"kind":"table","elementId":"src_store"},
  "columns":[col(cid,disp,f"[SRC Store/{disp}]") for cid,disp in STORE_COLS]},

 {"id":"dim_fulfilling_location","name":"Fulfilling Location","kind":"table","visibleAsSource":False,
  "description":"ROLE-PLAYING ALIAS of the Store dimension, used only for the second (fulfilment-side) join on Fulfillment Location Key. Hidden as a source on purpose: it is not a separate concept, it is Store seen through a different foreign key. Every column it contributes to Fulfillment Orders is prefixed 'Fulfilling Location ...' so no downstream chart can confuse it with the selling store.",
  "source":{"kind":"table","elementId":"src_store"},
  "columns":[col(cid,disp,f"[SRC Store/{disp}]") for cid,disp in STORE_COLS]},

 {"id":"dim_date","name":"Date","kind":"table","visibleAsSource":True,
  "description":"Retail 4-5-4 fiscal calendar. Sigma's built-in period-over-period and DateLookback are CALENDAR-based and will not align to 4-5-4 week boundaries; use Prior Year Date for fiscal-correct comps.",
  "source":{"kind":"table","elementId":"src_date"},
  "columns":[col(cid,disp,f"[SRC Date/{disp}]") for cid,disp in DATE_COLS]},

 {"id":"dim_customer","name":"Customer","kind":"table","visibleAsSource":True,
  "description":"4,972 customers. Carries state, city, region and county but NO latitude or longitude, so customer-to-fulfilment distance is not computable. Region and state matching is the available locality proxy.",
  "source":{"kind":"table","elementId":"src_customer"},
  "columns":[col(cid,disp,f"[SRC Customer/{disp}]") for cid,disp in CUST_COLS]},
]

# ---------------------------------------------------------------- Page 3: Order Build (hidden)
order_amounts = {
 "id":"order_amounts","name":"Order Amounts","kind":"table","visibleAsSource":False,
 "description":"Sales Activity collapsed from 4.9M order LINES to one row per order (717,747). MANDATORY pre-aggregation: joining raw Sales Activity to the order-grain fact would fan every order out to its line count. Verified to produce exactly 717,747 rows, matching Sales Orders 1:1, and to tie to the published all-time totals (Gross $1,178,971,663.73 / Returns $64,116,011.81).",
 "source":{"kind":"table","elementId":"src_sales_activity"},
 "columns":[
   col("order_number","Order Number","[SRC Sales Activity/Order Number]"),
   col("gross_sales","Gross Sales","Sum(If([SRC Sales Activity/Activity Type] = \"Sale\", [SRC Sales Activity/Amount], 0))","Sale lines only, before returns.",USD),
   col("returns_amount","Returns","Sum(If([SRC Sales Activity/Activity Type] = \"Return\", -[SRC Sales Activity/Amount], 0))","Refunded value as a POSITIVE number. Return lines are stored negative upstream and are sign-flipped here so Returns reads as a positive magnitude.",USD),
   col("net_sales","Net Sales","Sum([SRC Sales Activity/Amount])","Gross sales less returns.",USD),
   col("net_cost","Net Cost","Sum([SRC Sales Activity/Cost])",fmt=USD),
   col("gross_units","Gross Units","Sum(If([SRC Sales Activity/Activity Type] = \"Sale\", [SRC Sales Activity/Quantity], 0))",fmt=NUM0),
   col("net_units","Net Units","Sum([SRC Sales Activity/Quantity])",fmt=NUM0),
   col("line_count","Order Lines","Count([SRC Sales Activity/Order Number])","Number of activity lines on the order. Present so the pre-aggregation fan-out can be audited directly.",NUM0),
   col("distinct_products","Distinct Products","CountDistinct([SRC Sales Activity/Product Key])",fmt=NUM0),
 ],
 "groupings":[{"id":"g_order","groupBy":["order_number"],
   "calculations":["gross_sales","returns_amount","net_sales","net_cost","gross_units",
                   "net_units","line_count","distinct_products"]}],
}

# ---------------------------------------------------------------- Page 4: Omnichannel Fulfillment
SO = "[SRC Sales Orders/"
FUL_KEY = SO + "Fulfillment Location Key]"
CHAN    = SO + "Channel Type]"

pattern_formula = (
  f'If({CHAN} = "Retail", "In-Store", '
  f'If({CHAN} = "Web" and {FUL_KEY} = 9999, "Ship-from-DC", '
  f'If({CHAN} = "Web", "Ship-from-Store", {CHAN})))'
)

fulfillment_metrics = [
 met("m_orders","Orders","CountDistinct([Order Number])",NUM0,
   "Distinct orders. 717,747 all-time. Counts ORDERS, not order lines - the underlying activity is 4,899,866 lines, collapsed to order grain in the hidden Order Amounts element."),
 met("m_customers","Customers","CountDistinct([Cust Key])",NUM0,
   "Distinct customers who placed at least one order. 4,867 of the 4,972 customers in the Customer dimension - the remaining 105 have never transacted."),

 met("m_instore_orders","In-Store Orders","CountDistinct(If([Fulfillment Pattern] = \"In-Store\", [Order Number], Null))",NUM0,
   "Orders rung in a store and handed over there - transaction, fulfilment and selling location all identical. 536,065 all-time, 74.7% of orders."),
 met("m_digital_orders","Digital Orders","[Metrics/Orders] - [Metrics/In-Store Orders]",NUM0,
   "Orders on any pattern other than In-Store: Ship-from-DC, Ship-from-Store, BOPIS or BOSS. 181,682 all-time. Derived as Orders minus In-Store Orders rather than counted directly, so it stays correct under any filter."),
 met("m_digital_mix","Digital Mix %","[Metrics/Digital Orders] / [Metrics/Orders]",PCT,
   "Digital Orders / Orders. 25.31% all-time - but that single figure hides the trend: digital mix has MORE THAN DOUBLED, 15.0% in FY2021 to 31.9% in FY2025. Always read this by fiscal year; the all-time number is an average over a period of rapid change and describes no actual year."),

 met("m_web_orders","Web Orders","CountDistinct(If([Channel Type] = \"Web\", [Order Number], Null))",NUM0,
   "Orders on Channel Type = 'Web' - bought online and shipped to the customer. 122,713 all-time. This is the CHANNEL, which splits across two fulfilment patterns (Ship-from-DC and Ship-from-Store). It exists chiefly as the denominator of Ship-from-Store Rate %."),
 met("m_sfs_orders","Ship-from-Store Orders","CountDistinct(If([Fulfillment Pattern] = \"Ship-from-Store\", [Order Number], Null))",NUM0,
   "Web orders a store shipped instead of the Central Warehouse. 36,952 all-time."),
 met("m_sfs_rate","Ship-from-Store Rate %","[Metrics/Ship-from-Store Orders] / [Metrics/Web Orders]",PCT,
   "THE headline metric of this model: the share of web demand fulfilled by a store rather than the DC. Ship-from-Store Orders / WEB Orders = 30.11% all-time. The denominator is web orders only, NOT all digital - BOPIS and BOSS are store-fulfilled by definition and would wash the number out. Notable finding: this rate has been flat across all five fiscal years (30.07 / 29.81 / 30.28 / 30.19 / 30.11) while web volume quintupled, so the routing policy has never actually changed."),

 met("m_bopis_orders","BOPIS Orders","CountDistinct(If([Fulfillment Pattern] = \"BOPIS\", [Order Number], Null))",NUM0,
   "Buy online, pick up in store. 38,148 all-time. Fulfilled by the selling store, transaction rung at the warehouse."),
 met("m_boss_orders","BOSS Orders","CountDistinct(If([Fulfillment Pattern] = \"BOSS\", [Order Number], Null))",NUM0,
   "Buy online, ship to store for customer collection. 20,821 all-time, the smallest of the five patterns."),
 met("m_bopis_attach","BOPIS Attach %","[Metrics/BOPIS Orders] / [Metrics/Digital Orders]",PCT,
   "BOPIS Orders / Digital Orders. 21.00% all-time. Worth watching as a lever rather than a score: BOPIS carries the LOWEST return rate of any digital pattern (7.12%, against 10.09% for ship-from-store), so shifting digital demand toward it is the cheapest available improvement to blended returns."),

 met("m_store_fulfilled","Store-Fulfilled Orders","CountDistinct(If([Is Store Fulfilled], [Order Number], Null))",NUM0,
   "Orders physically fulfilled by a store - every pattern except Ship-from-DC. 631,986 all-time. This is the denominator for both locality metrics, and the reason they exclude DC orders."),
 met("m_store_fulfill_rate","Store Fulfillment Rate %","[Metrics/Store-Fulfilled Orders] / [Metrics/Orders]",PCT,
   "Store-Fulfilled Orders / Orders. 88.05% all-time - the store network, not the DC, is the primary fulfilment engine."),
 met("m_dc_fulfilled","DC-Fulfilled Orders","[Metrics/Orders] - [Metrics/Store-Fulfilled Orders]",NUM0,
   "Orders shipped by the Central Warehouse (Store Key 9999). 85,761 all-time, every one of them a Web order - no BOPIS, BOSS or in-store order is ever DC-fulfilled."),

 met("m_in_region","In-Region Fulfilled Orders","CountDistinct(If([Is In-Region Fulfillment], [Order Number], Null))",NUM0,
   "Store-fulfilled orders where the fulfilling store sits in the customer's own region. 610,258 all-time."),
 met("m_in_region_rate","In-Region Fulfillment %","[Metrics/In-Region Fulfilled Orders] / [Metrics/Store-Fulfilled Orders]",PCT,
   "In-Region Fulfilled Orders / STORE-FULFILLED Orders. 96.56% all-time. This metric exists because true fulfilment DISTANCE is not computable from this data - the Central Warehouse has null coordinates and customers have none at all - so region matching is the honest proxy. The denominator deliberately excludes DC-fulfilled orders: the warehouse has no region upstream, and counting it would show a mass of apparent out-of-region shipping that is really just missing data."),
 met("m_in_state","In-State Fulfilled Orders","CountDistinct(If([Is In-State Fulfillment], [Order Number], Null))",NUM0,
   "Store-fulfilled orders where the fulfilling store sits in the customer's own state. 606,528 all-time."),
 met("m_in_state_rate","In-State Fulfillment %","[Metrics/In-State Fulfilled Orders] / [Metrics/Store-Fulfilled Orders]",PCT,
   "In-State Fulfilled Orders / STORE-FULFILLED Orders. 95.97% all-time. A tighter version of In-Region Fulfillment %, carrying the same DC exclusion and the same caveat about why it stands in for a distance metric."),

 met("m_cross_store","Cross-Store Fulfillment Orders (Guard)","CountDistinct(If([Is Cross-Store Fulfillment], [Order Number], Null))",NUM0,
   "DATA-QUALITY GUARD, not a KPI - do not chart this as a business measure. Counts orders where one store sold and a DIFFERENT store fulfilled. Currently 0 by construction: Selling Store Key equals Fulfilling Location Key on all 631,986 store-fulfilled orders, so true cross-store fulfilment does not occur in this dataset. It is retained so that if the source ever begins recording it, that surfaces immediately rather than silently changing the locality metrics. Any non-zero value here means this model's assumptions need revisiting."),

 met("m_gross_sales","Gross Sales","Sum([Gross Sales])",USD,
   "Sale-line value before returns. $1,178,971,663.73 all-time, tying exactly to the Retail Sales Activity model."),
 met("m_returns","Returns","Sum([Returns])",USD,
   "Refunded value, expressed as a POSITIVE number - return lines are stored negative upstream and are sign-flipped in the Order Amounts pre-aggregation. $64,116,011.81 all-time. Driven by the returns ledger, NOT by Transaction Type = 'Return', which is an unrelated order-level flag sitting on positive-amount orders."),
 met("m_net_sales","Net Sales","Sum([Net Sales])",USD,
   "Gross Sales less Returns. $1,114,855,651.92 all-time. Cross-model check: the In-Store share, $844,609,615.53, ties exactly to Retail Net Sales in the Retail Store Operations model."),
 met("m_return_rate","Return Rate %","[Metrics/Returns] / [Metrics/Gross Sales]",PCT,
   "Returns / Gross Sales. 5.44% all-time. READ THIS BY FULFILMENT PATTERN, not in aggregate. The blended rate ROSE from 5.12% (FY2021) to 5.58% (FY2025) while every individual pattern improved or held flat - in-store 4.38 to 4.12, ship-from-DC 10.36 to 9.44, ship-from-store 10.41 to 9.87. The entire increase is digital mix shift, since digital returns run about 2.4x the in-store rate. A textbook Simpson's paradox: the aggregate tells the opposite story to its components."),
 met("m_net_cost","Net Cost","Sum([Net Cost])",USD,
   "Cost of goods on net activity (sales less returns). $895,884,767.32 all-time."),
 met("m_net_margin","Net Gross Margin","Sum([Net Sales]) - Sum([Net Cost])",USD,
   "Net Sales less Net Cost. $218,970,884.60 all-time. Product margin only - it carries no labour, rent or fulfilment cost, so it is not a profit measure."),
 met("m_net_margin_pct","Net Margin %","[Metrics/Net Gross Margin] / [Metrics/Net Sales]",PCT,
   "Net Gross Margin / Net Sales. 19.64% all-time."),
 met("m_net_units","Net Units","Sum([Net Units])",NUM0,
   "Units sold net of returns. 8,584,150 all-time."),
 met("m_aov","AOV","[Metrics/Net Sales] / [Metrics/Orders]",USD,
   "Average order value: Net Sales / Orders. $1,553.27 all-time. Worth knowing that AOV barely moves across patterns - $1,471 (ship-from-store) to $1,576 (in-store), a 7% spread. Order VALUE is not where the channels differ; returns are."),
 met("m_upt","UPT","[Metrics/Net Units] / [Metrics/Orders]",NUM2,
   "Units per transaction: Net Units / Orders. 11.96 all-time."),
 met("m_digital_net_sales","Digital Net Sales","Sum(If([Fulfillment Pattern] = \"In-Store\", 0, [Net Sales]))",USD,
   "Net Sales on every pattern except In-Store. $270,246,036.39 all-time."),
 met("m_digital_sales_mix","Digital Sales Mix %","[Metrics/Digital Net Sales] / [Metrics/Net Sales]",PCT,
   "Digital Net Sales / Net Sales. 24.24% all-time. Sits slightly BELOW Digital Mix % by order count (25.31%) because digital orders carry both a marginally lower AOV and a materially higher return rate - digital wins less revenue share than it does order share."),
]

fulfillment_orders = {
 "id":"fulfillment_orders","name":"Fulfillment Orders","kind":"table","visibleAsSource":True,
 "description":(
   "One row per order (717,747), with the omnichannel routing keys finally interpreted. "
   "Fulfillment Pattern derives five mutually exclusive routes from Channel Type and Fulfillment Location Key: "
   "In-Store (536,065), Ship-from-DC (85,761), Ship-from-Store (36,952), BOPIS (38,148), BOSS (20,821). "
   "Store is joined TWICE as a role-playing dimension - the selling/credited store on Store Key ('Selling Store ...') "
   "and the fulfilling location on Fulfillment Location Key ('Fulfilling Location ...'). "
   "TRAP 1: cross-store fulfilment does not exist in this data. Store Key EQUALS Fulfillment Location Key on every "
   "store-fulfilled order, so selling and fulfilling store diverge only when the Central Warehouse ships. "
   "'Cross-Store Fulfillment Orders (Guard)' is retained purely to detect that changing, and currently returns 0 by construction. "
   "TRAP 2: there is no fulfilment-distance metric because distance is not computable. The Central Warehouse (9999) has null "
   "latitude and longitude, customers have no coordinates at all, and store-to-store distance would be zero everywhere per Trap 1. "
   "In-Region / In-State Fulfillment % are the honest locality proxies, and both are defined only over store-fulfilled orders. "
   "TRAP 3: Transaction Location Key is 9999 for EVERY digital order (Web, BOPIS, BOSS) - it records where the sale was rung, "
   "not where the customer was, so it must never be read as a selling location for digital. "
   "TRAP 4: Transaction Type = 'Return' is an order-level flag on POSITIVE-amount orders and is unrelated to the returns ledger "
   "that drives Returns and Return Rate % here - the same gotcha documented on Sales Activity. "
   "All ratios are metrics, never row-level columns, so they recompute correctly at every rollup."
 ),
 "source":{"kind":"join","primarySource":{"kind":"table","elementId":"src_sales_orders"},
   "joins":[
     {"joinType":"left-outer","left":{"kind":"table","elementId":"src_sales_orders"},
      "right":{"kind":"table","elementId":"order_amounts","groupingId":"g_order"},
      "columns":[{"left":"[Order Number]","right":"[Order Number]"}]},
     {"joinType":"left-outer","left":{"kind":"table","elementId":"src_sales_orders"},
      "right":{"kind":"table","elementId":"dim_store"},
      "columns":[{"left":"[Store Key]","right":"[Store Key]"}]},
     {"joinType":"left-outer","left":{"kind":"table","elementId":"src_sales_orders"},
      "right":{"kind":"table","elementId":"dim_fulfilling_location"},
      "columns":[{"left":"[Fulfillment Location Key]","right":"[Store Key]"}]},
     {"joinType":"left-outer","left":{"kind":"table","elementId":"src_sales_orders"},
      "right":{"kind":"table","elementId":"dim_customer"},
      "columns":[{"left":"[Cust Key]","right":"[Cust Key]"}]},
     {"joinType":"left-outer","left":{"kind":"table","elementId":"src_sales_orders"},
      "right":{"kind":"table","elementId":"dim_date"},
      "columns":[{"left":"[Date Key]","right":"[Date Key]"}]},
   ]},
 "columns":[
   col("order_number","Order Number",SO+"Order Number]","Order identifier. Primary key of this element."),
   col("date",  "Order Timestamp",SO+"Date]"),
   col("date_key","Date Key",SO+"Date Key]"),
   col("channel_type","Channel Type",SO+"Channel Type]","Selling channel as recorded upstream: Retail, Web, BOPIS or BOSS. Fulfillment Pattern splits Web into its two real routes."),

   col("fulfillment_pattern","Fulfillment Pattern",pattern_formula,
       "THE point of this model. Five mutually exclusive routes: In-Store, Ship-from-DC, Ship-from-Store, BOPIS, BOSS. Web is the only channel that splits, on whether the fulfilling location is the Central Warehouse (9999) or a store."),
   col("fulfillment_type","Fulfillment Type",
       f'If({FUL_KEY} = 9999, "DC", "Store")',
       "Who physically shipped or handed over the goods: the Central Warehouse or a store."),
   col("is_digital","Is Digital Order",
       f'If({CHAN} = "Retail", False, True)',
       "True for Web, BOPIS and BOSS. These orders are credited to a store but were not transacted in it."),
   col("is_store_fulfilled","Is Store Fulfilled",
       f'If({FUL_KEY} = 9999, False, True)',
       "True when a store, not the Central Warehouse, fulfilled the order. This is the denominator for both locality metrics."),

   col("store_key","Selling Store Key",SO+"Store Key]","Store credited with the sale. Never 9999 - every order, digital included, is credited to a selling store."),
   col("fulfillment_location_key","Fulfilling Location Key",SO+"Fulfillment Location Key]","Store or warehouse that fulfilled the order. 9999 is the Central Warehouse."),
   col("transaction_location_key","Transaction Location Key",SO+"Transaction Location Key]","Where the sale was RUNG. 9999 for every digital order regardless of who fulfilled it, so it is not a selling location for digital - use Selling Store Key for that."),

   col("is_cross_store","Is Cross-Store Fulfillment",
       f'If({FUL_KEY} = 9999, False, If({SO}Store Key] = {FUL_KEY}, False, True))',
       "DATA-QUALITY GUARD, currently False for all 717,747 orders. One store selling and a different store shipping does not occur in this dataset; this column exists so that if it ever starts occurring it is visible immediately rather than silently changing the locality metrics."),
   col("is_in_region","Is In-Region Fulfillment",
       f'If({FUL_KEY} = 9999, False, If([Fulfilling Location/Store Region] = [Customer/Cust Region], True, False))',
       "True when the fulfilling STORE sits in the customer's own region. False for every DC-fulfilled order because the Central Warehouse has no region upstream - that is an absence of data, NOT evidence of a long ship, so always measure this over store-fulfilled orders only."),
   col("is_in_state","Is In-State Fulfillment",
       f'If({FUL_KEY} = 9999, False, If([Fulfilling Location/Store State] = [Customer/Cust State], True, False))',
       "True when the fulfilling STORE sits in the customer's own state. Same DC caveat as Is In-Region Fulfillment."),

   col("selling_store_name","Selling Store Name","[Store/Store Name]"),
   col("selling_store_city","Selling Store City","[Store/Store City]"),
   col("selling_store_state","Selling Store State","[Store/Store State]"),
   col("selling_store_region","Selling Store Region","[Store/Store Region]"),
   col("selling_store_area","Selling Store Area","[Store/Store Area]"),
   col("selling_store_type","Selling Store Type","[Store/Store Type]"),
   col("selling_store_size","Selling Store Size","[Store/Store Size]"),
   col("selling_store_online_ordering","Selling Store Online Ordering","[Store/Online Ordering]"),
   col("selling_store_latitude","Selling Store Latitude","[Store/Latitude]"),
   col("selling_store_longitude","Selling Store Longitude","[Store/Longitude]"),

   col("ful_store_name","Fulfilling Location Name","[Fulfilling Location/Store Name]","'Central Warehouse' for DC-fulfilled orders."),
   col("ful_store_city","Fulfilling Location City","[Fulfilling Location/Store City]"),
   col("ful_store_state","Fulfilling Location State","[Fulfilling Location/Store State]","Null for the Central Warehouse."),
   col("ful_store_region","Fulfilling Location Region","[Fulfilling Location/Store Region]","Null for the Central Warehouse."),
   col("ful_store_area","Fulfilling Location Area","[Fulfilling Location/Store Area]"),
   col("ful_store_type","Fulfilling Location Type","[Fulfilling Location/Store Type]","'Store' or 'Warehouse'."),
   col("ful_store_latitude","Fulfilling Location Latitude","[Fulfilling Location/Latitude]","Null for the Central Warehouse - the reason no distance metric ships with this model."),
   col("ful_store_longitude","Fulfilling Location Longitude","[Fulfilling Location/Longitude]","Null for the Central Warehouse."),

   col("gross_sales","Gross Sales","[Order Amounts/Gross Sales]",fmt=USD),
   col("returns_amount","Returns","[Order Amounts/Returns]","Refunded value as a positive number.",USD),
   col("net_sales","Net Sales","[Order Amounts/Net Sales]",fmt=USD),
   col("net_cost","Net Cost","[Order Amounts/Net Cost]",fmt=USD),
   col("net_units","Net Units","[Order Amounts/Net Units]",fmt=NUM0),
   col("order_lines","Order Lines","[Order Amounts/Order Lines]",fmt=NUM0),
   col("distinct_products","Distinct Products","[Order Amounts/Distinct Products]",fmt=NUM0),

   col("cust_key","Cust Key",SO+"Cust Key]"),
   col("cust_name","Cust Name","[Customer/Cust Name]"),
   col("cust_state","Cust State","[Customer/Cust State]"),
   col("cust_region","Cust Region","[Customer/Cust Region]"),
   col("cust_type","Cust Type","[Customer/Cust Type]"),
   col("age_group","Age Group","[Customer/Age Group]"),
   col("loyalty_tier","Loyalty Tier","[Customer/Loyalty Tier]"),
   col("downloaded_app","Downloaded App","[Customer/Downloaded App]","1 if the customer has the mobile app. Blank means unknown, not no."),

   col("salesperson_name","Salesperson Name",SO+"Salesperson Name]"),
   col("salesperson_tier","Salesperson Tier",SO+"Tier]"),
   col("purchase_method","Purchase Method",SO+"Purchase Method]"),
   col("transaction_type","Transaction Type",SO+"Transaction Type]","Order-level flag, 'Purchase' or 'Return'. NOT a signed reversal and unrelated to the returns ledger - see Trap 4 on this element."),

   col("day_of_week_name","Day of Week Name","[Date/Day of Week Name]"),
   col("is_weekend","Is Weekend","[Date/Is Weekend]"),
   col("week_start_date","Week Start Date","[Date/Week Start Date]"),
   col("fiscal_year","Fiscal Year","[Date/Fiscal Year]"),
   col("fiscal_quarter","Fiscal Quarter","[Date/Fiscal Quarter]"),
   col("fiscal_period","Fiscal Period","[Date/Fiscal Period]"),
   col("fiscal_period_name","Fiscal Period Name","[Date/Fiscal Period Name]"),
   col("fiscal_week_of_year","Fiscal Week of Year","[Date/Fiscal Week of Year]"),
   col("fiscal_season","Fiscal Season","[Date/Fiscal Season]"),
   col("prior_year_date","Prior Year Date","[Date/Prior Year Date]","Fiscal-correct prior-year comparison date. Use this rather than Sigma's calendar-based period-over-period, which will not respect 4-5-4 boundaries. NULL for 62,463 orders: all of FY2021 (the first year loaded, so no prior year exists) and the 3,399 orders in FY2023 WEEK 53 (2023-12-31 to 2024-01-06) - FY2023 is a 53-week year and FY2022 had no week 53 to compare against. That is correct 4-5-4 behaviour, not a gap, but any year-over-year chart will silently drop week 53 unless it is handled explicitly."),
   col("calendar_year","Calendar Year","[Date/Calendar Year]"),
   col("calendar_month_name","Calendar Month Name","[Date/Calendar Month Name]"),
 ],
 "metrics":fulfillment_metrics,
}

# ---------------------------------------------------------------- Page 5: Rollup
fulfillment_day = {
 "id":"fulfillment_day","name":"Fulfillment Day","kind":"table","visibleAsSource":True,
 "description":"Fulfillment Orders rolled up to Date x Fulfillment Pattern x Selling Store (387,937 rows). Use this for trend and mix reporting so dashboards do not scan 717,747 order rows. Ties exactly to Fulfillment Orders on orders, gross, returns, net and store-fulfilled counts. Two build notes: order counts are sums of a pre-collapsed grain, so metrics use Sum([Orders]) not CountDistinct; and every ratio metric here aggregates its columns directly rather than referencing other metrics, because inside a GROUPED element a [Metrics/X] reference resolves to the like-named column and the query fails.",
 "source":{"kind":"table","elementId":"fulfillment_orders"},
 "columns":[
   col("date_key","Date Key","[Fulfillment Orders/Date Key]"),
   col("fulfillment_pattern","Fulfillment Pattern","[Fulfillment Orders/Fulfillment Pattern]"),
   col("fulfillment_type","Fulfillment Type","[Fulfillment Orders/Fulfillment Type]"),
   col("channel_type","Channel Type","[Fulfillment Orders/Channel Type]"),
   col("store_key","Selling Store Key","[Fulfillment Orders/Selling Store Key]"),
   col("selling_store_name","Selling Store Name","[Fulfillment Orders/Selling Store Name]"),
   col("selling_store_region","Selling Store Region","[Fulfillment Orders/Selling Store Region]"),
   col("selling_store_area","Selling Store Area","[Fulfillment Orders/Selling Store Area]"),
   col("day_of_week_name","Day of Week Name","[Fulfillment Orders/Day of Week Name]"),
   col("is_weekend","Is Weekend","[Fulfillment Orders/Is Weekend]"),
   col("week_start_date","Week Start Date","[Fulfillment Orders/Week Start Date]"),
   col("fiscal_year","Fiscal Year","[Fulfillment Orders/Fiscal Year]"),
   col("fiscal_quarter","Fiscal Quarter","[Fulfillment Orders/Fiscal Quarter]"),
   col("fiscal_period","Fiscal Period","[Fulfillment Orders/Fiscal Period]"),
   col("fiscal_week_of_year","Fiscal Week of Year","[Fulfillment Orders/Fiscal Week of Year]"),
   col("fiscal_season","Fiscal Season","[Fulfillment Orders/Fiscal Season]"),
   col("orders","Orders","CountDistinct([Fulfillment Orders/Order Number])",fmt=NUM0),
   col("gross_sales","Gross Sales","Sum([Fulfillment Orders/Gross Sales])",fmt=USD),
   col("returns_amount","Returns","Sum([Fulfillment Orders/Returns])",fmt=USD),
   col("net_sales","Net Sales","Sum([Fulfillment Orders/Net Sales])",fmt=USD),
   col("net_cost","Net Cost","Sum([Fulfillment Orders/Net Cost])",fmt=USD),
   col("net_units","Net Units","Sum([Fulfillment Orders/Net Units])",fmt=NUM0),
   col("store_fulfilled_orders","Store-Fulfilled Orders","CountDistinct(If([Fulfillment Orders/Is Store Fulfilled], [Fulfillment Orders/Order Number], Null))",fmt=NUM0),
   col("in_region_orders","In-Region Fulfilled Orders","CountDistinct(If([Fulfillment Orders/Is In-Region Fulfillment], [Fulfillment Orders/Order Number], Null))",fmt=NUM0),
 ],
 "groupings":[{"id":"g_day",
   "groupBy":["date_key","fulfillment_pattern","fulfillment_type","channel_type","store_key",
              "selling_store_name","selling_store_region","selling_store_area","day_of_week_name",
              "is_weekend","week_start_date","fiscal_year","fiscal_quarter","fiscal_period",
              "fiscal_week_of_year","fiscal_season"],
   "calculations":["orders","gross_sales","returns_amount","net_sales","net_cost","net_units",
                   "store_fulfilled_orders","in_region_orders"]}],
 "metrics":[
   met("m_d_orders","Orders","Sum([Orders])",NUM0,
     "Distinct orders, summed from the pre-collapsed daily grain. 717,747 all-time - ties exactly to Orders on Fulfillment Orders. Uses Sum, not CountDistinct, because each row here is already one date x pattern x store bucket."),
   met("m_d_gross_sales","Gross Sales","Sum([Gross Sales])",USD,
     "Sale-line value before returns. $1,178,971,663.73 all-time, ties exactly to Fulfillment Orders."),
   met("m_d_returns","Returns","Sum([Returns])",USD,
     "Refunded value as a positive number. $64,116,011.81 all-time, ties exactly to Fulfillment Orders."),
   met("m_d_net_sales","Net Sales","Sum([Net Sales])",USD,
     "Gross Sales less Returns. $1,114,855,651.92 all-time, ties exactly to Fulfillment Orders."),
   met("m_d_return_rate","Return Rate %","Sum([Returns]) / Sum([Gross Sales])",PCT,
     "Returns / Gross Sales. 5.44% all-time, identical to the order-grain metric. Same trap applies: read it by fulfilment pattern, because the blended rate rises on digital mix shift while every individual pattern improves. Note the formula aggregates columns directly rather than referencing other metrics - inside a grouped element a [Metrics/X] reference resolves to the like-named column and the query fails."),
   met("m_d_net_units","Net Units","Sum([Net Units])",NUM0,
     "Units sold net of returns. 8,584,150 all-time, ties exactly to Fulfillment Orders."),
   met("m_d_aov","AOV","Sum([Net Sales]) / Sum([Orders])",USD,
     "Average order value: Net Sales / Orders. $1,553.27 all-time, identical to the order-grain metric. Aggregates columns directly for the grouped-element reason noted on Return Rate %."),
   met("m_d_store_fulfilled","Store-Fulfilled Orders","Sum([Store-Fulfilled Orders])",NUM0,
     "Orders physically fulfilled by a store, every pattern except Ship-from-DC. 631,986 all-time, ties exactly to Fulfillment Orders."),
   met("m_d_store_fulfill_rate","Store Fulfillment Rate %","Sum([Store-Fulfilled Orders]) / Sum([Orders])",PCT,
     "Store-Fulfilled Orders / Orders. 88.05% all-time."),
   met("m_d_in_region","In-Region Fulfilled Orders","Sum([In-Region Fulfilled Orders])",NUM0,
     "Store-fulfilled orders where the fulfilling store sits in the customer's own region. 610,258 all-time."),
   met("m_d_in_region_rate","In-Region Fulfillment %","Sum([In-Region Fulfilled Orders]) / Sum([Store-Fulfilled Orders])",PCT,
     "In-Region Fulfilled Orders / STORE-FULFILLED Orders. 96.56% all-time, identical to the order-grain metric. The denominator excludes DC-fulfilled orders because the Central Warehouse has no region upstream; including it would read as out-of-region shipping that is really missing data. Stands in for a true distance metric, which this source data cannot support."),
 ],
}

spec = {
 "name":"Retail Omnichannel Fulfillment",
 "description":(
   "Order-grain model that interprets the omnichannel routing already encoded in Sales Orders but never given meaning: "
   "who sold the order, who fulfilled it, and how far apart those are. Five fulfilment patterns across 717,747 orders. "
   "Headline: 30.1% of web orders ship from a store rather than the DC. "
   "Store is joined twice as a role-playing dimension (selling vs fulfilling). "
   "Sources conformed dimensions from the Retail Sales Activity model."
 ),
 "pages":[
   {"id":"page_sources","name":"Sources","elements":sources},
   {"id":"page_dims","name":"Conformed Dimensions","elements":dims},
   {"id":"page_build","name":"Order Build","elements":[order_amounts]},
   {"id":"page_omni","name":"Omnichannel Fulfillment","elements":[fulfillment_orders]},
   {"id":"page_rollup","name":"Rollups","elements":[fulfillment_day]},
 ],
}

print(json.dumps(spec, indent=2))
