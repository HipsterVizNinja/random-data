import json

SALESACT = "8c548776-acb2-46ac-b60d-dd5a70781bd2"

def col(cid, name, formula, desc=None, fmt=None):
    c = {"id": cid, "name": name, "formula": formula}
    if desc: c["description"] = desc
    if fmt: c["format"] = fmt
    return c

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
 {"id":"m_orders","name":"Orders","formula":"CountDistinct([Order Number])","format":NUM0},
 {"id":"m_customers","name":"Customers","formula":"CountDistinct([Cust Key])","format":NUM0},

 {"id":"m_instore_orders","name":"In-Store Orders","formula":"CountDistinct(If([Fulfillment Pattern] = \"In-Store\", [Order Number], Null))","format":NUM0},
 {"id":"m_digital_orders","name":"Digital Orders","formula":"[Metrics/Orders] - [Metrics/In-Store Orders]","format":NUM0},
 {"id":"m_digital_mix","name":"Digital Mix %","formula":"[Metrics/Digital Orders] / [Metrics/Orders]","format":PCT},

 {"id":"m_web_orders","name":"Web Orders","formula":"CountDistinct(If([Channel Type] = \"Web\", [Order Number], Null))","format":NUM0},
 {"id":"m_sfs_orders","name":"Ship-from-Store Orders","formula":"CountDistinct(If([Fulfillment Pattern] = \"Ship-from-Store\", [Order Number], Null))","format":NUM0},
 {"id":"m_sfs_rate","name":"Ship-from-Store Rate %","formula":"[Metrics/Ship-from-Store Orders] / [Metrics/Web Orders]","format":PCT},

 {"id":"m_bopis_orders","name":"BOPIS Orders","formula":"CountDistinct(If([Fulfillment Pattern] = \"BOPIS\", [Order Number], Null))","format":NUM0},
 {"id":"m_boss_orders","name":"BOSS Orders","formula":"CountDistinct(If([Fulfillment Pattern] = \"BOSS\", [Order Number], Null))","format":NUM0},
 {"id":"m_bopis_attach","name":"BOPIS Attach %","formula":"[Metrics/BOPIS Orders] / [Metrics/Digital Orders]","format":PCT},

 {"id":"m_store_fulfilled","name":"Store-Fulfilled Orders","formula":"CountDistinct(If([Is Store Fulfilled], [Order Number], Null))","format":NUM0},
 {"id":"m_store_fulfill_rate","name":"Store Fulfillment Rate %","formula":"[Metrics/Store-Fulfilled Orders] / [Metrics/Orders]","format":PCT},
 {"id":"m_dc_fulfilled","name":"DC-Fulfilled Orders","formula":"[Metrics/Orders] - [Metrics/Store-Fulfilled Orders]","format":NUM0},

 {"id":"m_in_region","name":"In-Region Fulfilled Orders","formula":"CountDistinct(If([Is In-Region Fulfillment], [Order Number], Null))","format":NUM0},
 {"id":"m_in_region_rate","name":"In-Region Fulfillment %","formula":"[Metrics/In-Region Fulfilled Orders] / [Metrics/Store-Fulfilled Orders]","format":PCT},
 {"id":"m_in_state","name":"In-State Fulfilled Orders","formula":"CountDistinct(If([Is In-State Fulfillment], [Order Number], Null))","format":NUM0},
 {"id":"m_in_state_rate","name":"In-State Fulfillment %","formula":"[Metrics/In-State Fulfilled Orders] / [Metrics/Store-Fulfilled Orders]","format":PCT},

 {"id":"m_cross_store","name":"Cross-Store Fulfillment Orders (Guard)","formula":"CountDistinct(If([Is Cross-Store Fulfillment], [Order Number], Null))","format":NUM0},

 {"id":"m_gross_sales","name":"Gross Sales","formula":"Sum([Gross Sales])","format":USD},
 {"id":"m_returns","name":"Returns","formula":"Sum([Returns])","format":USD},
 {"id":"m_net_sales","name":"Net Sales","formula":"Sum([Net Sales])","format":USD},
 {"id":"m_return_rate","name":"Return Rate %","formula":"[Metrics/Returns] / [Metrics/Gross Sales]","format":PCT},
 {"id":"m_net_cost","name":"Net Cost","formula":"Sum([Net Cost])","format":USD},
 {"id":"m_net_margin","name":"Net Gross Margin","formula":"Sum([Net Sales]) - Sum([Net Cost])","format":USD},
 {"id":"m_net_margin_pct","name":"Net Margin %","formula":"[Metrics/Net Gross Margin] / [Metrics/Net Sales]","format":PCT},
 {"id":"m_net_units","name":"Net Units","formula":"Sum([Net Units])","format":NUM0},
 {"id":"m_aov","name":"AOV","formula":"[Metrics/Net Sales] / [Metrics/Orders]","format":USD},
 {"id":"m_upt","name":"UPT","formula":"[Metrics/Net Units] / [Metrics/Orders]","format":NUM2},
 {"id":"m_digital_net_sales","name":"Digital Net Sales","formula":"Sum(If([Fulfillment Pattern] = \"In-Store\", 0, [Net Sales]))","format":USD},
 {"id":"m_digital_sales_mix","name":"Digital Sales Mix %","formula":"[Metrics/Digital Net Sales] / [Metrics/Net Sales]","format":PCT},
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
   {"id":"m_d_orders","name":"Orders","formula":"Sum([Orders])","format":NUM0},
   {"id":"m_d_gross_sales","name":"Gross Sales","formula":"Sum([Gross Sales])","format":USD},
   {"id":"m_d_returns","name":"Returns","formula":"Sum([Returns])","format":USD},
   {"id":"m_d_net_sales","name":"Net Sales","formula":"Sum([Net Sales])","format":USD},
   {"id":"m_d_return_rate","name":"Return Rate %","formula":"Sum([Returns]) / Sum([Gross Sales])","format":PCT},
   {"id":"m_d_net_units","name":"Net Units","formula":"Sum([Net Units])","format":NUM0},
   {"id":"m_d_aov","name":"AOV","formula":"Sum([Net Sales]) / Sum([Orders])","format":USD},
   {"id":"m_d_store_fulfilled","name":"Store-Fulfilled Orders","formula":"Sum([Store-Fulfilled Orders])","format":NUM0},
   {"id":"m_d_store_fulfill_rate","name":"Store Fulfillment Rate %","formula":"Sum([Store-Fulfilled Orders]) / Sum([Orders])","format":PCT},
   {"id":"m_d_in_region","name":"In-Region Fulfilled Orders","formula":"Sum([In-Region Fulfilled Orders])","format":NUM0},
   {"id":"m_d_in_region_rate","name":"In-Region Fulfillment %","formula":"Sum([In-Region Fulfilled Orders]) / Sum([Store-Fulfilled Orders])","format":PCT},
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
