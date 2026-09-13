import json

UPLOADS = "b765b086-4e7e-426b-ac82-7d6e0cf5a71c"
SALESACT = "8c548776-acb2-46ac-b60d-dd5a70781bd2"

def col(cid, name, formula, desc=None, fmt=None):
    c = {"id": cid, "name": name, "formula": formula}
    if desc: c["description"] = desc
    if fmt: c["format"] = fmt
    return c

USD = {"kind": "number", "formatString": "$,.2f"}
NUM0 = {"kind": "number", "formatString": ",.0f"}
NUM2 = {"kind": "number", "formatString": ",.2f"}
PCT = {"kind": "number", "formatString": ".2%"}

def src(eid, name, model, origin_elem, origin_name, cols, desc=None):
    """cols: list of (id, display) -> formula [origin_name/display]"""
    e = {
        "id": eid, "name": name, "kind": "table",
        "source": {"kind": "data-model", "dataModelId": model, "elementId": origin_elem},
        "columns": [col(cid, disp, f"[{origin_name}/{disp}]") for cid, disp in cols],
        "visibleAsSource": False,
    }
    if desc: e["description"] = desc
    return e

# ---------------------------------------------------------------- Page 1: Sources
LABOR_COLS = [("store_key","Store Key"),("date_key","Date Key"),("hour","Hour"),
              ("scheduled_staff_count","Scheduled Staff Count"),("actual_staff_count","Actual Staff Count"),
              ("labor_cost","Labor Cost")]
TRAFFIC_COLS = [("store_key","Store Key"),("date_key","Date Key"),("hour","Hour"),("store_visits","Store Visits")]
SALES_COLS = [("order_number","Order Number"),("cust_key","Cust Key"),("store_key","Store Key"),
              ("transaction_type","Transaction Type"),("date","Date"),("purchase_method","Purchase Method"),
              ("date_key","Date Key"),("salesperson_key","Salesperson Key"),("channel_type","Channel Type"),
              ("transaction_location_key","Transaction Location Key"),("fulfillment_location_key","Fulfillment Location Key")]
TIME_COLS = [("hour","Hour"),("hour_label","Hour Label"),("daypart","Daypart"),
             ("is_typical_business_hour","Is Typical Business Hour")]
LEAD_COLS = [("leadership_key","Leadership Key"),("employee_name","Employee Name"),("role","Role"),
             ("store_key","Store Key"),("store_area","Store Area"),("store_region","Store Region"),
             ("reports_to_key","Reports To Key"),("hire_date","Hire Date"),("tenure_years","Tenure Years"),
             ("annual_salary","Annual Salary"),("performance_tier","Performance Tier"),("bonus_rate","Bonus Rate")]
BUDGET_COLS = [("store_key","Store Key"),("fiscal_year","Fiscal Year"),("fiscal_period","Fiscal Period"),
               ("budget_sales_amount","Budget Sales Amount"),("budget_units","Budget Units")]
STORE_COLS = [("store_key","Store Key"),("store_name","Store Name"),("store_city","Store City"),
              ("store_state","Store State"),("store_region","Store Region"),("store_area","Store Area"),
              ("store_type","Store Type"),("store_size","Store Size"),("store_open_date","Store Open Date"),
              ("selling_square_footage","Selling Square Footage"),("total_square_footage","Total Square Footage"),
              ("number_of_employees","Number of Employees"),("online_ordering","Online Ordering"),
              ("latitude","Latitude"),("longitude","Longitude"),
              ("weekday_open_hour","Weekday Open Hour"),("weekday_close_hour","Weekday Close Hour"),
              ("sunday_open_hour","Sunday Open Hour"),("sunday_close_hour","Sunday Close Hour")]
DATE_COLS = [("date_key","Date Key"),("day_of_week_name","Day of Week Name"),("day_of_week_number","Day of Week Number"),
             ("is_weekend","Is Weekend"),("week_start_date","Week Start Date"),
             ("calendar_year","Calendar Year"),("calendar_month","Calendar Month"),("calendar_month_name","Calendar Month Name"),
             ("calendar_quarter","Calendar Quarter"),
             ("fiscal_year","Fiscal Year"),("fiscal_quarter","Fiscal Quarter"),("fiscal_period","Fiscal Period"),
             ("fiscal_period_name","Fiscal Period Name"),("fiscal_week_of_year","Fiscal Week of Year"),
             ("fiscal_season","Fiscal Season"),("prior_year_date","Prior Year Date")]
SA_COLS = [("store_key","Store Key"),("sale_date","Sale Date"),("sale_timestamp","Sale Timestamp"),
           ("activity_type","Activity Type"),("channel_type","Channel Type"),
           ("quantity","Quantity"),("amount","Amount"),("cost","Cost")]

sources = [
    src("src_f_labor","SRC F_LABOR",UPLOADS,"jU63b1LbRX","F_LABOR.csv",LABOR_COLS),
    src("src_f_store_traffic","SRC F_STORE_TRAFFIC",UPLOADS,"qE363PAKVb","F_STORE_TRAFFIC.csv",TRAFFIC_COLS),
    src("src_f_sales","SRC F_SALES",UPLOADS,"TOhPY4-KGV","F_SALES.csv",SALES_COLS),
    src("src_d_time","SRC D_TIME",UPLOADS,"6d0QSJNwQ2","D_TIME.csv",TIME_COLS),
    src("src_d_store_leadership","SRC D_STORE_LEADERSHIP",UPLOADS,"O-JjreO6D0","D_STORE_LEADERSHIP.csv",LEAD_COLS),
    src("src_f_budget","SRC F_BUDGET",UPLOADS,"xQ5dfXHoWm","F_BUDGET.csv",BUDGET_COLS),
    src("src_store","SRC Store",SALESACT,"dim_store","Store",STORE_COLS,
        "Conformed Store dimension referenced from the Retail Sales Activity model."),
    src("src_date","SRC Date",SALESACT,"dim_date","Date",DATE_COLS,
        "Conformed Date dimension (4-5-4 fiscal) referenced from the Retail Sales Activity model."),
    src("src_sales_activity","SRC Sales Activity",SALESACT,"sales_activity","Sales Activity",SA_COLS,
        "Sales + returns fact referenced from the Retail Sales Activity model, projected to the columns needed for hourly dollars."),
]

# ---------------------------------------------------------------- Page 2: Conformed Dimensions
dims = [
 {"id":"dim_time","name":"Time","kind":"table","visibleAsSource":True,
  "description":"Hour-of-day dimension. Hours 9-20 are the only hours present in store traffic and labor.",
  "source":{"kind":"table","elementId":"src_d_time"},
  "columns":[col("hour","Hour","[SRC D_TIME/Hour]","Hour of day, 0-23. Store facts only populate 9-20."),
             col("hour_label","Hour Label","[SRC D_TIME/Hour Label]"),
             col("daypart","Daypart","[SRC D_TIME/Daypart]","Morning / Afternoon / Evening grouping of the hour."),
             col("is_typical_business_hour","Is Typical Business Hour","[SRC D_TIME/Is Typical Business Hour]")]},
 {"id":"dim_store","name":"Store","kind":"table","visibleAsSource":True,
  "description":"200 selling stores plus the Central Warehouse (Store Key 9999). Note the warehouse has NO labor or traffic rows, so Store Operations facts cover 200 stores only.",
  "source":{"kind":"table","elementId":"src_store"},
  "columns":[col(cid,disp,f"[SRC Store/{disp}]") for cid,disp in STORE_COLS]},
 {"id":"dim_date","name":"Date","kind":"table","visibleAsSource":True,
  "description":"Retail 4-5-4 fiscal calendar. Sigma's built-in period-over-period and DateLookback are CALENDAR-based and will not align to 4-5-4 week boundaries; use Prior Year Date for fiscal-correct comps.",
  "source":{"kind":"table","elementId":"src_date"},
  "columns":[col(cid,disp,f"[SRC Date/{disp}]") for cid,disp in DATE_COLS]},
 {"id":"dim_leadership","name":"Store Leadership","kind":"table","visibleAsSource":True,
  "description":"Field leadership roster: 200 Store Managers (one per store) -> 18 AVPs -> 5 RVPs. Only Store Managers carry a Store Key; AVP and RVP rows have none. Reports To Key chains upward and is null for RVPs.",
  "source":{"kind":"table","elementId":"src_d_store_leadership"},
  "columns":[col(cid,disp,f"[SRC D_STORE_LEADERSHIP/{disp}]") for cid,disp in LEAD_COLS]},
]

# ---------------------------------------------------------------- Page 3: Hourly Build (hidden)
hourly_orders = {
 "id":"hourly_orders","name":"Hourly Orders","kind":"table","visibleAsSource":False,
 "description":"F_SALES collapsed to Store Key x Date Key x Hour. MANDATORY pre-aggregation: joining raw F_SALES to the hourly fact would fan it out. Retail Orders isolates in-store transactions, which is the correct numerator for conversion against door traffic.",
 "source":{"kind":"table","elementId":"src_f_sales"},
 "columns":[
   col("store_key","Store Key","[SRC F_SALES/Store Key]"),
   col("date_key","Date Key","[SRC F_SALES/Date Key]"),
   col("sale_hour","Sale Hour","Hour([SRC F_SALES/Date])","Hour of day the order was placed, parsed from the order timestamp. Retail orders span hours 9-20, matching store labor and traffic exactly."),
   col("orders","Orders","CountDistinct([SRC F_SALES/Order Number])",fmt=NUM0),
   col("retail_orders","Retail Orders","CountDistinct(If([SRC F_SALES/Channel Type] = \"Retail\", [SRC F_SALES/Order Number], Null))","In-store orders only. Web, BOPIS and BOSS orders are credited to a store but did not walk through its door, so they must be excluded from conversion.",fmt=NUM0),
   col("customers","Customers","CountDistinct([SRC F_SALES/Cust Key])",fmt=NUM0),
 ],
 "groupings":[{"id":"g_orders","groupBy":["store_key","date_key","sale_hour"],
               "calculations":["orders","retail_orders","customers"]}],
}

hourly_sales = {
 "id":"hourly_sales","name":"Hourly Sales","kind":"table","visibleAsSource":False,
 "description":"Sales Activity collapsed to Store Key x Sale Date x Hour, dated by SALE Timestamp so returns net back against the hour that originally sold the item. MANDATORY pre-aggregation before joining to the hourly fact.",
 "source":{"kind":"table","elementId":"src_sales_activity"},
 "columns":[
   col("store_key","Store Key","[SRC Sales Activity/Store Key]"),
   col("sale_date","Sale Date","[SRC Sales Activity/Sale Date]"),
   col("sale_hour","Sale Hour","Hour([SRC Sales Activity/Sale Timestamp])"),
   col("net_sales","Net Sales","Sum([SRC Sales Activity/Amount])",fmt=USD),
   col("net_cost","Net Cost","Sum([SRC Sales Activity/Cost])",fmt=USD),
   col("net_units","Net Units","Sum([SRC Sales Activity/Quantity])",fmt=NUM0),
   col("gross_sales","Gross Sales","Sum(If([SRC Sales Activity/Activity Type] = \"Sale\", [SRC Sales Activity/Amount], 0))",fmt=USD),
   col("retail_net_sales","Retail Net Sales","Sum(If([SRC Sales Activity/Channel Type] = \"Retail\", [SRC Sales Activity/Amount], 0))","In-store sales only. This is the correct numerator for any ratio measured against door traffic.",USD),
   col("retail_net_cost","Retail Net Cost","Sum(If([SRC Sales Activity/Channel Type] = \"Retail\", [SRC Sales Activity/Cost], 0))",fmt=USD),
   col("retail_net_units","Retail Net Units","Sum(If([SRC Sales Activity/Channel Type] = \"Retail\", [SRC Sales Activity/Quantity], 0))",fmt=NUM0),
 ],
 "groupings":[{"id":"g_sales","groupBy":["store_key","sale_date","sale_hour"],
               "calculations":["net_sales","net_cost","net_units","gross_sales",
                               "retail_net_sales","retail_net_cost","retail_net_units"]}],
}

# ---------------------------------------------------------------- Page 4: Store Operations
store_hour_metrics = [
 {"id":"m_store_visits","name":"Store Visits","formula":"Sum([Store Visits])","format":NUM0},
 {"id":"m_retail_orders","name":"Retail Orders","formula":"Sum([Retail Orders])","format":NUM0},
 {"id":"m_orders","name":"Orders","formula":"Sum([Orders])","format":NUM0},
 {"id":"m_conversion_rate","name":"Conversion Rate %","formula":"[Metrics/Retail Orders] / [Metrics/Store Visits]","format":PCT},
 {"id":"m_retail_net_sales","name":"Retail Net Sales","formula":"Sum([Retail Net Sales])","format":USD},
 {"id":"m_retail_net_units","name":"Retail Net Units","formula":"Sum([Retail Net Units])","format":NUM0},
 {"id":"m_retail_gross_margin","name":"Retail Gross Margin","formula":"Sum([Retail Gross Margin])","format":USD},
 {"id":"m_net_sales","name":"Net Sales (All Channels, In-Hours)","formula":"Sum([Net Sales (All Channels, In-Hours)])","format":USD},
 {"id":"m_labor_cost","name":"Labor Cost","formula":"Sum([Labor Cost])","format":USD},
 {"id":"m_scheduled_staff","name":"Scheduled Staff","formula":"Sum([Scheduled Staff Count])","format":NUM0},
 {"id":"m_actual_staff","name":"Actual Staff","formula":"Sum([Actual Staff Count])","format":NUM0},
 {"id":"m_staffing_variance","name":"Staffing Variance","formula":"[Metrics/Actual Staff] - [Metrics/Scheduled Staff]","format":NUM0},
 {"id":"m_traffic_per_staff","name":"Traffic per Staff","formula":"[Metrics/Store Visits] / [Metrics/Actual Staff]","format":NUM2},
 {"id":"m_sales_per_visit","name":"Sales per Visit","formula":"[Metrics/Retail Net Sales] / [Metrics/Store Visits]","format":USD},
 {"id":"m_sales_per_staffed_hour","name":"Sales per Staffed Hour","formula":"[Metrics/Retail Net Sales] / [Metrics/Actual Staff]","format":USD},
 {"id":"m_labor_cost_pct","name":"Labor Cost %","formula":"[Metrics/Labor Cost] / [Metrics/Retail Net Sales]","format":PCT},
 {"id":"m_atv","name":"Avg Transaction Value","formula":"[Metrics/Retail Net Sales] / [Metrics/Retail Orders]","format":USD},
]

store_hour = {
 "id":"store_hour","name":"Store Hour","kind":"table","visibleAsSource":True,
 "description":"One row per Store x Date x Hour (3,332,953). Store traffic and labor are exactly co-grained and join 1:1; orders and dollars are LEFT JOINed from pre-aggregated elements. Covers 200 selling stores - the Central Warehouse (9999) has no labor or traffic. Labor carries STAFF COUNTS, not hours, so 'per staffed hour' means per staffed store-hour. Dollar ratios use Retail Net Sales (in-store only) because they are measured against door traffic; the all-channel columns are partial by design and must not be divided by traffic. All ratios are metrics so they recompute correctly at every rollup.",
 "source":{"kind":"join","primarySource":{"kind":"table","elementId":"src_f_store_traffic"},
   "joins":[
     {"joinType":"left-outer","left":{"kind":"table","elementId":"src_f_store_traffic"},
      "right":{"kind":"table","elementId":"src_f_labor"},
      "columns":[{"left":"[Store Key]","right":"[Store Key]"},
                 {"left":"[Date Key]","right":"[Date Key]"},
                 {"left":"[Hour]","right":"[Hour]"}]},
     {"joinType":"left-outer","left":{"kind":"table","elementId":"src_f_store_traffic"},
      "right":{"kind":"table","elementId":"hourly_orders","groupingId":"g_orders"},
      "columns":[{"left":"[Store Key]","right":"[Store Key]"},
                 {"left":"[Date Key]","right":"[Date Key]"},
                 {"left":"[Hour]","right":"[Sale Hour]"}]},
     {"joinType":"left-outer","left":{"kind":"table","elementId":"src_f_store_traffic"},
      "right":{"kind":"table","elementId":"hourly_sales","groupingId":"g_sales"},
      "columns":[{"left":"[Store Key]","right":"[Store Key]"},
                 {"left":"[Date Key]","right":"[Sale Date]"},
                 {"left":"[Hour]","right":"[Sale Hour]"}]},
     {"joinType":"left-outer","left":{"kind":"table","elementId":"src_f_store_traffic"},
      "right":{"kind":"table","elementId":"dim_store"},
      "columns":[{"left":"[Store Key]","right":"[Store Key]"}]},
     {"joinType":"left-outer","left":{"kind":"table","elementId":"src_f_store_traffic"},
      "right":{"kind":"table","elementId":"dim_date"},
      "columns":[{"left":"[Date Key]","right":"[Date Key]"}]},
     {"joinType":"left-outer","left":{"kind":"table","elementId":"src_f_store_traffic"},
      "right":{"kind":"table","elementId":"dim_time"},
      "columns":[{"left":"[Hour]","right":"[Hour]"}]},
   ]},
 "columns":[
   col("store_key","Store Key","[SRC F_STORE_TRAFFIC/Store Key]"),
   col("date_key","Date Key","[SRC F_STORE_TRAFFIC/Date Key]"),
   col("hour","Hour","[SRC F_STORE_TRAFFIC/Hour]","Hour of day, 9-20."),
   col("store_visits","Store Visits","[SRC F_STORE_TRAFFIC/Store Visits]","Door counter traffic for this store-hour.",NUM0),
   col("scheduled_staff_count","Scheduled Staff Count","[SRC F_LABOR/Scheduled Staff Count]","Headcount the schedule called for. NOT hours.",NUM0),
   col("actual_staff_count","Actual Staff Count","[SRC F_LABOR/Actual Staff Count]","Headcount actually on the floor. NOT hours.",NUM0),
   col("staffing_variance","Staffing Variance","[SRC F_LABOR/Actual Staff Count] - [SRC F_LABOR/Scheduled Staff Count]","Actual minus scheduled headcount. Scheduled and actual net out almost exactly company-wide, so only per-store-hour variance carries signal.",NUM0),
   col("labor_cost","Labor Cost","[SRC F_LABOR/Labor Cost]","Wage cost for this store-hour.",USD),
   col("orders","Orders","[Hourly Orders/Orders]","All orders credited to this store in this hour, every channel.",NUM0),
   col("retail_orders","Retail Orders","[Hourly Orders/Retail Orders]","In-store orders only - the correct numerator for conversion against door traffic.",NUM0),
   col("customers","Customers","[Hourly Orders/Customers]",fmt=NUM0),
   col("retail_net_sales","Retail Net Sales","[Hourly Sales/Retail Net Sales]","In-store sales net of returns, dated by the hour of the original sale. COMPLETE: every in-store order falls inside a staffed store-hour. Use this for all traffic-based ratios.",USD),
   col("retail_net_cost","Retail Net Cost","[Hourly Sales/Retail Net Cost]",fmt=USD),
   col("retail_net_units","Retail Net Units","[Hourly Sales/Retail Net Units]",fmt=NUM0),
   col("retail_gross_margin","Retail Gross Margin","[Hourly Sales/Retail Net Sales] - [Hourly Sales/Retail Net Cost]",fmt=USD),
   col("net_sales","Net Sales (All Channels, In-Hours)","[Hourly Sales/Net Sales]","All-channel sales credited to this store that transacted during a staffed store-hour. PARTIAL BY DESIGN: digital orders placed outside trading hours have no store-hour to land on, so this runs about 9% below company net sales. Never use it as a company sales total - use the Retail Sales Activity model for that - and never divide it by door traffic.",USD),
   col("net_cost","Net Cost (All Channels, In-Hours)","[Hourly Sales/Net Cost]",fmt=USD),
   col("net_units","Net Units (All Channels, In-Hours)","[Hourly Sales/Net Units]",fmt=NUM0),
   col("gross_sales","Gross Sales (All Channels, In-Hours)","[Hourly Sales/Gross Sales]",fmt=USD),
   col("is_open_hour","Is Open Hour",
       "If([Date/Day of Week Name] = \"Sunday\", [SRC F_STORE_TRAFFIC/Hour] >= [Store/Sunday Open Hour] and [SRC F_STORE_TRAFFIC/Hour] < [Store/Sunday Close Hour], [SRC F_STORE_TRAFFIC/Hour] >= [Store/Weekday Open Hour] and [SRC F_STORE_TRAFFIC/Hour] < [Store/Weekday Close Hour])",
       "True when the store was trading this hour, per its weekday/Sunday opening hours. Currently TRUE for every row: traffic and labor are only recorded for hours a store actually trades, so the shoulder hours simply have fewer store-hours rather than closed rows. Retained as a guard in case closed-hour rows are ever loaded."),
   col("daypart","Daypart","[Time/Daypart]"),
   col("hour_label","Hour Label","[Time/Hour Label]"),
   col("store_name","Store Name","[Store/Store Name]"),
   col("store_city","Store City","[Store/Store City]"),
   col("store_state","Store State","[Store/Store State]"),
   col("store_region","Store Region","[Store/Store Region]"),
   col("store_area","Store Area","[Store/Store Area]"),
   col("store_type","Store Type","[Store/Store Type]"),
   col("store_size","Store Size","[Store/Store Size]"),
   col("selling_square_footage","Selling Square Footage","[Store/Selling Square Footage]",fmt=NUM0),
   col("day_of_week_name","Day of Week Name","[Date/Day of Week Name]"),
   col("is_weekend","Is Weekend","[Date/Is Weekend]"),
   col("week_start_date","Week Start Date","[Date/Week Start Date]"),
   col("fiscal_year","Fiscal Year","[Date/Fiscal Year]"),
   col("fiscal_quarter","Fiscal Quarter","[Date/Fiscal Quarter]"),
   col("fiscal_period","Fiscal Period","[Date/Fiscal Period]"),
   col("fiscal_period_name","Fiscal Period Name","[Date/Fiscal Period Name]"),
   col("fiscal_week_of_year","Fiscal Week of Year","[Date/Fiscal Week of Year]"),
   col("fiscal_season","Fiscal Season","[Date/Fiscal Season]"),
   col("calendar_year","Calendar Year","[Date/Calendar Year]"),
   col("calendar_month_name","Calendar Month Name","[Date/Calendar Month Name]"),
 ],
 "metrics":store_hour_metrics,
}

store_day = {
 "id":"store_day","name":"Store Day","kind":"table","visibleAsSource":True,
 "description":"Store Hour rolled up to one row per Store x Date (365,400 potential store-days). Use this for trend and period reporting so dashboards do not scan 3.3M hourly rows. Same metric definitions as Store Hour.",
 "source":{"kind":"table","elementId":"store_hour"},
 "columns":[
   col("store_key","Store Key","[Store Hour/Store Key]"),
   col("date_key","Date Key","[Store Hour/Date Key]"),
   col("store_name","Store Name","[Store Hour/Store Name]"),
   col("store_region","Store Region","[Store Hour/Store Region]"),
   col("store_area","Store Area","[Store Hour/Store Area]"),
   col("store_type","Store Type","[Store Hour/Store Type]"),
   col("store_state","Store State","[Store Hour/Store State]"),
   col("day_of_week_name","Day of Week Name","[Store Hour/Day of Week Name]"),
   col("is_weekend","Is Weekend","[Store Hour/Is Weekend]"),
   col("week_start_date","Week Start Date","[Store Hour/Week Start Date]"),
   col("fiscal_year","Fiscal Year","[Store Hour/Fiscal Year]"),
   col("fiscal_quarter","Fiscal Quarter","[Store Hour/Fiscal Quarter]"),
   col("fiscal_period","Fiscal Period","[Store Hour/Fiscal Period]"),
   col("fiscal_week_of_year","Fiscal Week of Year","[Store Hour/Fiscal Week of Year]"),
   col("fiscal_season","Fiscal Season","[Store Hour/Fiscal Season]"),
   col("store_visits","Store Visits","Sum([Store Hour/Store Visits])",fmt=NUM0),
   col("retail_orders","Retail Orders","Sum([Store Hour/Retail Orders])",fmt=NUM0),
   col("orders","Orders","Sum([Store Hour/Orders])",fmt=NUM0),
   col("retail_net_sales","Retail Net Sales","Sum([Store Hour/Retail Net Sales])",fmt=USD),
   col("retail_net_cost","Retail Net Cost","Sum([Store Hour/Retail Net Cost])",fmt=USD),
   col("retail_net_units","Retail Net Units","Sum([Store Hour/Retail Net Units])",fmt=NUM0),
   col("net_sales","Net Sales (All Channels, In-Hours)","Sum([Store Hour/Net Sales (All Channels, In-Hours)])",fmt=USD),
   col("labor_cost","Labor Cost","Sum([Store Hour/Labor Cost])",fmt=USD),
   col("scheduled_staff_count","Scheduled Staff Count","Sum([Store Hour/Scheduled Staff Count])",fmt=NUM0),
   col("actual_staff_count","Actual Staff Count","Sum([Store Hour/Actual Staff Count])",fmt=NUM0),
   col("open_hours","Open Hours","Sum(If([Store Hour/Is Open Hour], 1, 0))","Number of trading hours this store-day.",NUM0),
 ],
 "groupings":[{"id":"g_day",
   "groupBy":["store_key","date_key","store_name","store_region","store_area","store_type","store_state",
              "day_of_week_name","is_weekend","week_start_date","fiscal_year","fiscal_quarter",
              "fiscal_period","fiscal_week_of_year","fiscal_season"],
   "calculations":["store_visits","retail_orders","orders","retail_net_sales","retail_net_cost",
                   "retail_net_units","net_sales",
                   "labor_cost","scheduled_staff_count","actual_staff_count","open_hours"]}],
 "metrics":[
   {"id":"m_d_store_visits","name":"Store Visits","formula":"Sum([Store Visits])","format":NUM0},
   {"id":"m_d_retail_orders","name":"Retail Orders","formula":"Sum([Retail Orders])","format":NUM0},
   {"id":"m_d_conversion_rate","name":"Conversion Rate %","formula":"[Metrics/Retail Orders] / [Metrics/Store Visits]","format":PCT},
   {"id":"m_d_retail_net_sales","name":"Retail Net Sales","formula":"Sum([Retail Net Sales])","format":USD},
   {"id":"m_d_net_sales","name":"Net Sales (All Channels, In-Hours)","formula":"Sum([Net Sales (All Channels, In-Hours)])","format":USD},
   {"id":"m_d_labor_cost","name":"Labor Cost","formula":"Sum([Labor Cost])","format":USD},
   {"id":"m_d_labor_cost_pct","name":"Labor Cost %","formula":"[Metrics/Labor Cost] / [Metrics/Retail Net Sales]","format":PCT},
   {"id":"m_d_sales_per_visit","name":"Sales per Visit","formula":"[Metrics/Retail Net Sales] / [Metrics/Store Visits]","format":USD},
   {"id":"m_d_atv","name":"Avg Transaction Value","formula":"[Metrics/Retail Net Sales] / [Metrics/Retail Orders]","format":USD},
 ],
}

budget = {
 "id":"budget","name":"Budget","kind":"table","visibleAsSource":True,
 "description":"Sales plan per store per fiscal period. COARSER grain than Store Day - join on Store Key + Fiscal Year + Fiscal Period, never on date.",
 "source":{"kind":"join","primarySource":{"kind":"table","elementId":"src_f_budget"},
   "joins":[{"joinType":"left-outer","left":{"kind":"table","elementId":"src_f_budget"},
             "right":{"kind":"table","elementId":"dim_store"},
             "columns":[{"left":"[Store Key]","right":"[Store Key]"}]}]},
 "columns":[
   col("store_key","Store Key","[SRC F_BUDGET/Store Key]"),
   col("fiscal_year","Fiscal Year","[SRC F_BUDGET/Fiscal Year]"),
   col("fiscal_period","Fiscal Period","[SRC F_BUDGET/Fiscal Period]"),
   col("budget_sales_amount","Budget Sales Amount","[SRC F_BUDGET/Budget Sales Amount]",fmt=USD),
   col("budget_units","Budget Units","[SRC F_BUDGET/Budget Units]",fmt=NUM0),
   col("budget_store_name","Store Name","[Store/Store Name]"),
   col("budget_store_region","Store Region","[Store/Store Region]"),
 ],
 "metrics":[
   {"id":"m_budget_sales","name":"Budget Sales","formula":"Sum([Budget Sales Amount])","format":USD},
   {"id":"m_budget_units","name":"Budget Units","formula":"Sum([Budget Units])","format":NUM0},
 ],
}

spec = {
 "name":"Retail Store Operations",
 "description":"Store x Date x Hour operations model: door traffic, labor and sales on one co-grained fact. Answers what Sales Activity structurally cannot - whether the store was staffed for the rush. Sources conformed dimensions from the Retail Sales Activity model.",
 "pages":[
   {"id":"page_sources","name":"Sources","elements":sources},
   {"id":"page_dims","name":"Conformed Dimensions","elements":dims},
   {"id":"page_build","name":"Hourly Build","elements":[hourly_orders,hourly_sales]},
   {"id":"page_ops","name":"Store Operations","elements":[store_hour,store_day]},
   {"id":"page_support","name":"Supporting Facts","elements":[budget]},
 ],
}

print(json.dumps(spec, indent=2))
