import json, sys

UPLOADS  = "b765b086-4e7e-426b-ac82-7d6e0cf5a71c"
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
EMP_COLS = [("employee_key","Employee Key"),("employee_name","Employee Name"),("employee_type","Employee Type"),
            ("store_key","Store Key"),("store_area","Store Area"),("store_region","Store Region"),
            ("reports_to_key","Reports To Key"),("hire_date","Hire Date"),("employment_status","Employment Status"),
            ("termination_date","Termination Date"),("tenure_years","Tenure Years"),
            ("compensation_type","Compensation Type"),("commission_rate","Commission Rate"),
            ("annual_salary","Annual Salary")]
LEAD_COLS = [("leadership_key","Leadership Key"),("employee_name","Employee Name"),("role","Role"),
             ("store_key","Store Key"),("performance_tier","Performance Tier"),("bonus_rate","Bonus Rate")]
STORE_COLS = [("store_key","Store Key"),("store_name","Store Name"),("store_city","Store City"),
              ("store_state","Store State"),("store_region","Store Region"),("store_area","Store Area"),
              ("store_type","Store Type"),("store_size","Store Size"),("store_open_date","Store Open Date"),
              ("selling_square_footage","Selling Square Footage"),("number_of_employees","Number of Employees"),
              ("latitude","Latitude"),("longitude","Longitude")]
DATE_COLS = [("date_key","Date Key"),("day_of_week_name","Day of Week Name"),("is_weekend","Is Weekend"),
             ("week_start_date","Week Start Date"),("calendar_year","Calendar Year"),
             ("calendar_month","Calendar Month"),("calendar_month_name","Calendar Month Name"),
             ("calendar_quarter","Calendar Quarter"),
             ("fiscal_year","Fiscal Year"),("fiscal_quarter","Fiscal Quarter"),("fiscal_period","Fiscal Period"),
             ("fiscal_period_name","Fiscal Period Name"),("fiscal_week_of_year","Fiscal Week of Year"),
             ("fiscal_season","Fiscal Season"),("prior_year_date","Prior Year Date")]
SA_COLS = [("order_number","Order Number"),("salesperson_key","Salesperson Key"),("store_key","Store Key"),
           ("cust_key","Cust Key"),("sale_date","Sale Date"),("activity_type","Activity Type"),
           ("channel_type","Channel Type"),("quantity","Quantity"),("amount","Amount"),("cost","Cost"),
           ("fiscal_year","Fiscal Year"),("fiscal_quarter","Fiscal Quarter"),("fiscal_period","Fiscal Period"),
           ("fiscal_period_name","Fiscal Period Name")]

MGR_DESC = ("Second reference to D_EMPLOYEE used as a role-playing self-join. The org is exactly three levels "
            "(200 Store Managers -> 18 AVPs -> 5 RVPs) so the chain is flattened with three fixed self-joins, never recursion.")

sources = [
    src("src_d_employee","SRC D_EMPLOYEE",UPLOADS,"9DI_dZiZ9x","D_EMPLOYEE.csv",EMP_COLS,
        "Full employee roster (1,840). Superset of D_SALESPERSON: the 1,617 Commission rows are byte-identical to "
        "D_SALESPERSON on key, name, store, tier and rate, and the 223 Salary rows are the leadership D_SALESPERSON omits."),
    src("src_mgr_1","Manager",UPLOADS,"9DI_dZiZ9x","D_EMPLOYEE.csv",EMP_COLS, MGR_DESC),
    src("src_mgr_2","Manager L2",UPLOADS,"9DI_dZiZ9x","D_EMPLOYEE.csv",EMP_COLS, MGR_DESC),
    src("src_mgr_3","Manager L3",UPLOADS,"9DI_dZiZ9x","D_EMPLOYEE.csv",EMP_COLS, MGR_DESC),
    src("src_d_store_leadership","SRC D_STORE_LEADERSHIP",UPLOADS,"O-JjreO6D0","D_STORE_LEADERSHIP.csv",LEAD_COLS,
        "Leadership roster (223). Carries Performance Tier and Bonus Rate, which D_EMPLOYEE lacks. NOTE: Leadership Key "
        "is a SEPARATE keyspace from Employee Key - it runs 1-223 while the same 223 people are Employee Key 1618-1840. "
        "Joined on Employee Name, which is unique in both tables."),
    src("src_store","SRC Store",SALESACT,"dim_store","Store",STORE_COLS,
        "Conformed Store dimension referenced from the Retail Sales Activity model."),
    src("src_date","SRC Date",SALESACT,"dim_date","Date",DATE_COLS,
        "Conformed Date dimension (4-5-4 fiscal) referenced from the Retail Sales Activity model."),
    src("src_sales_activity","SRC Sales Activity",SALESACT,"sales_activity","Sales Activity",SA_COLS,
        "Sales + returns fact referenced from the Retail Sales Activity model, projected to the columns needed for "
        "salesperson attribution. Every order line carries a Salesperson Key, so 100% of company net sales attribute."),
]

# ---------------------------------------------------------------- Page 2: Conformed Dimensions
dims = [
 {"id":"dim_store","name":"Store","kind":"table","visibleAsSource":True,
  "description":"Conformed Store dimension re-exposed from Retail Sales Activity so this model is self-sufficient as a source.",
  "source":{"kind":"table","elementId":"src_store"},
  "columns":[col(cid,disp,f"[SRC Store/{disp}]") for cid,disp in STORE_COLS]},
 {"id":"dim_date","name":"Date","kind":"table","visibleAsSource":True,
  "description":"Retail 4-5-4 fiscal calendar. Sigma's built-in period-over-period and DateLookback are CALENDAR-based "
                "and will not align to 4-5-4 week boundaries; use Prior Year Date for fiscal-correct comps.",
  "source":{"kind":"table","elementId":"src_date"},
  "columns":[col(cid,disp,f"[SRC Date/{disp}]") for cid,disp in DATE_COLS]},
]

# ---------------------------------------------------------------- Page 3: Org Build (hidden)
direct_reports = {
 "id":"direct_reports","name":"Direct Reports","kind":"table","visibleAsSource":False,
 "description":"Count of direct reports per manager, from D_EMPLOYEE grouped by Reports To Key. Feeds Span of Control.",
 "source":{"kind":"table","elementId":"src_d_employee"},
 "columns":[
   col("manager_key","Manager Key","[SRC D_EMPLOYEE/Reports To Key]"),
   col("direct_reports","Direct Reports","CountDistinct([SRC D_EMPLOYEE/Employee Key])",fmt=NUM0),
 ],
 "groupings":[{"id":"g_dr","groupBy":["manager_key"],"calculations":["direct_reports"]}],
}

ORG_LEVEL = ('If([SRC D_EMPLOYEE/Employee Type] = "RVP", 1, '
             'If([SRC D_EMPLOYEE/Employee Type] = "AVP", 2, '
             'If([SRC D_EMPLOYEE/Employee Type] = "Store Manager", 3, 4)))')

org_flat = {
 "id":"org_flat","name":"Org Flat","kind":"table","visibleAsSource":False,
 "description":"D_EMPLOYEE flattened against itself three times to resolve the full reporting chain.",
 "source":{"kind":"join","primarySource":{"kind":"table","elementId":"src_d_employee"},
   "joins":[
     {"joinType":"left-outer","left":{"kind":"table","elementId":"src_d_employee"},
      "right":{"kind":"table","elementId":"src_mgr_1"},
      "columns":[{"left":"[Reports To Key]","right":"[Employee Key]"}]},
     {"joinType":"left-outer","left":{"kind":"table","elementId":"src_mgr_1"},
      "right":{"kind":"table","elementId":"src_mgr_2"},
      "columns":[{"left":"[Reports To Key]","right":"[Employee Key]"}]},
     {"joinType":"left-outer","left":{"kind":"table","elementId":"src_mgr_2"},
      "right":{"kind":"table","elementId":"src_mgr_3"},
      "columns":[{"left":"[Reports To Key]","right":"[Employee Key]"}]},
     {"joinType":"left-outer","left":{"kind":"table","elementId":"src_d_employee"},
      "right":{"kind":"table","elementId":"src_d_store_leadership"},
      "columns":[{"left":"[Employee Name]","right":"[Employee Name]"}]},
     {"joinType":"left-outer","left":{"kind":"table","elementId":"src_d_employee"},
      "right":{"kind":"table","elementId":"dim_store"},
      "columns":[{"left":"[Store Key]","right":"[Store Key]"}]},
     {"joinType":"left-outer","left":{"kind":"table","elementId":"src_d_employee"},
      "right":{"kind":"table","elementId":"direct_reports","groupingId":"g_dr"},
      "columns":[{"left":"[Employee Key]","right":"[Manager Key]"}]},
   ]},
 "columns":[
   col("employee_key","Employee Key","[SRC D_EMPLOYEE/Employee Key]"),
   col("employee_name","Employee Name","[SRC D_EMPLOYEE/Employee Name]"),
   col("employee_type","Employee Type","[SRC D_EMPLOYEE/Employee Type]"),
   col("org_level","Org Level",ORG_LEVEL),
   col("store_key","Store Key","[SRC D_EMPLOYEE/Store Key]"),
   col("reports_to_key","Reports To Key","[SRC D_EMPLOYEE/Reports To Key]"),
   col("hire_date","Hire Date","[SRC D_EMPLOYEE/Hire Date]"),
   col("employment_status","Employment Status","[SRC D_EMPLOYEE/Employment Status]"),
   col("termination_date","Termination Date","[SRC D_EMPLOYEE/Termination Date]"),
   col("tenure_years_raw","Tenure Years (As Reported)","[SRC D_EMPLOYEE/Tenure Years]"),
   col("compensation_type","Compensation Type","[SRC D_EMPLOYEE/Compensation Type]"),
   col("commission_rate","Commission Rate","[SRC D_EMPLOYEE/Commission Rate]"),
   col("annual_salary","Annual Salary","[SRC D_EMPLOYEE/Annual Salary]"),
   col("manager_key","Manager Key","[Manager/Employee Key]"),
   col("manager_name","Manager Name","[Manager/Employee Name]"),
   col("manager_l2_name","Manager L2 Name","[Manager L2/Employee Name]"),
   col("manager_l3_name","Manager L3 Name","[Manager L3/Employee Name]"),
   col("sm_key","Store Manager Key",
       'If([SRC D_EMPLOYEE/Compensation Type] = "Commission", [Manager/Employee Key], '
       'If([SRC D_EMPLOYEE/Employee Type] = "Store Manager", [SRC D_EMPLOYEE/Employee Key], Null))'),
   col("sm_name","Store Manager",
       'If([SRC D_EMPLOYEE/Compensation Type] = "Commission", [Manager/Employee Name], '
       'If([SRC D_EMPLOYEE/Employee Type] = "Store Manager", [SRC D_EMPLOYEE/Employee Name], Null))',
       "The Store Manager this person rolls up to. Store Managers are their own; AVPs and RVPs sit above the store layer and are null."),
   col("avp_name","AVP",
       'If([SRC D_EMPLOYEE/Compensation Type] = "Commission", [Manager L2/Employee Name], '
       'If([SRC D_EMPLOYEE/Employee Type] = "Store Manager", [Manager/Employee Name], '
       'If([SRC D_EMPLOYEE/Employee Type] = "AVP", [SRC D_EMPLOYEE/Employee Name], Null)))'),
   col("rvp_name","RVP",
       'If([SRC D_EMPLOYEE/Compensation Type] = "Commission", [Manager L3/Employee Name], '
       'If([SRC D_EMPLOYEE/Employee Type] = "Store Manager", [Manager L2/Employee Name], '
       'If([SRC D_EMPLOYEE/Employee Type] = "AVP", [Manager/Employee Name], [SRC D_EMPLOYEE/Employee Name])))'),
   col("performance_tier","Leader Performance Tier","[SRC D_STORE_LEADERSHIP/Performance Tier]",
       "Only populated for the 223 leaders; D_EMPLOYEE carries no performance tier for associates."),
   col("bonus_rate","Leader Bonus Rate","[SRC D_STORE_LEADERSHIP/Bonus Rate]",fmt=PCT),
   col("leadership_key","Leadership Key","[SRC D_STORE_LEADERSHIP/Leadership Key]",
       "D_STORE_LEADERSHIP's own key (1-223). Distinct from Employee Key (1618-1840 for the same people)."),
   col("direct_reports","Direct Reports","Coalesce([Direct Reports/Direct Reports], 0)",
       "Headcount reporting directly to this person. 0 for individual contributors.",NUM0),
   col("store_name","Store Name","[Store/Store Name]"),
   col("store_city","Store City","[Store/Store City]"),
   col("store_state","Store State","[Store/Store State]"),
   col("store_type","Store Type","[Store/Store Type]"),
   col("store_size","Store Size","[Store/Store Size]"),
   col("region","Region","Coalesce([Store/Store Region], [SRC D_EMPLOYEE/Store Region])",
       "Store region for anyone assigned to a store; the employee's own region for AVPs and RVPs, who have no store."),
   col("area","Area","Coalesce([Store/Store Area], [SRC D_EMPLOYEE/Store Area])"),
 ],
}

# --- tenure corrections live on org_flat (they need only hire/termination dates, not the fact window)
org_flat["columns"].extend([
  col("tenure_years_at_exit","Tenure Years at Exit",
      'If(IsNull([SRC D_EMPLOYEE/Termination Date]), Null, '
      'DateDiff("day", [SRC D_EMPLOYEE/Hire Date], [SRC D_EMPLOYEE/Termination Date]) / 365.25)',
      "Actual years served, hire to termination. Null for active employees.",NUM2),
  col("tenure_years","Tenure Years",
      'If(IsNull([SRC D_EMPLOYEE/Termination Date]), [SRC D_EMPLOYEE/Tenure Years], '
      'DateDiff("day", [SRC D_EMPLOYEE/Hire Date], [SRC D_EMPLOYEE/Termination Date]) / 365.25)',
      "Corrected tenure: as-reported for active employees, hire-to-termination for leavers. USE THIS, not Tenure Years (As Reported).",NUM2),
  col("window_key","Window Key","1",
      "Constant join key used to attach the fact-window bounds. Not analytically meaningful."),
])

dim_org = {
 "id":"dim_org","name":"Org","kind":"table","visibleAsSource":True,
 "description":("One row per employee (1,840) with the full reporting chain flattened: Associate -> Store Manager -> AVP -> RVP. "
   "The hierarchy is exactly three levels deep (200 SMs, 18 AVPs, 5 RVPs), so it is flattened with three fixed self-joins "
   "rather than recursion. Reports To Key resolves inside D_EMPLOYEE's own keyspace and is null only for the 5 RVPs. "
   "TRAP: the source Tenure Years column measures hire-to-today for EVERY employee, including the 406 who have left - it keeps "
   "accruing after termination and overstates leaver tenure by 2.53 years on average. Use the corrected Tenure Years column; "
   "the raw value is retained as Tenure Years (As Reported). "
   "D_SALESPERSON is not sourced: its 1,617 rows are provably identical to the Compensation Type = 'Commission' subset of this element."),
 "source":{"kind":"table","elementId":"org_flat"},
 "columns":[col(c["id"], c["name"], f'[Org Flat/{c["name"]}]', c.get("description"), c.get("format"))
            for c in org_flat["columns"] if c["id"] != "window_key"],
 "metrics":[
   {"id":"m_o_employees","name":"Employees","formula":"CountDistinct([Employee Key])","format":NUM0},
   {"id":"m_o_terminated","name":"Terminated","formula":'CountDistinct(If([Employment Status] = "Terminated", [Employee Key], Null))',"format":NUM0},
   {"id":"m_o_attrition","name":"Attrition Rate %","formula":"[Metrics/Terminated] / [Metrics/Employees]","format":PCT},
   {"id":"m_o_span","name":"Span of Control","formula":"Sum([Direct Reports]) / CountDistinct(If([Direct Reports] > 0, [Employee Key], Null))",
    "description":"Average number of direct reports, across people who actually manage someone.","format":NUM2},
   {"id":"m_o_tenure","name":"Avg Tenure Years","formula":"Avg([Tenure Years])","format":NUM2},
   {"id":"m_o_tenure_exit","name":"Avg Tenure at Exit","formula":"Avg([Tenure Years at Exit])","format":NUM2},
   {"id":"m_o_salary","name":"Annual Salary","formula":"Sum([Annual Salary])","format":USD},
 ],
}

# ---------------------------------------------------------------- Page 4: Sales Build (hidden)
sales_window = {
 "id":"sales_window","name":"Sales Window","kind":"table","visibleAsSource":False,
 "description":("Single-row element holding the first and last date in the sales fact. Recency and exposure are measured against "
   "this, never against Today() - the dataset is static and ends 2025-10-18, so Today() would read every employee as inactive."),
 "source":{"kind":"table","elementId":"src_sales_activity"},
 "columns":[
   col("window_key","Window Key","1"),
   col("window_start","Window Start","Min([SRC Sales Activity/Sale Date])"),
   col("window_end","Window End","Max([SRC Sales Activity/Sale Date])"),
 ],
 "groupings":[{"id":"g_win","groupBy":["window_key"],"calculations":["window_start","window_end"]}],
}

employee_sales = {
 "id":"employee_sales","name":"Employee Sales Agg","kind":"table","visibleAsSource":False,
 "description":("Sales Activity collapsed to one row per Salesperson Key. MANDATORY pre-aggregation: joining the 4.9M-row "
   "activity fact straight onto the employee spine would fan it out. Returns carry negative Amount, so Sum(Amount) is net."),
 "source":{"kind":"table","elementId":"src_sales_activity"},
 "columns":[
   col("salesperson_key","Salesperson Key","[SRC Sales Activity/Salesperson Key]"),
   col("net_sales","Net Sales","Sum([SRC Sales Activity/Amount])",fmt=USD),
   col("gross_sales","Gross Sales",'Sum(If([SRC Sales Activity/Activity Type] = "Sale", [SRC Sales Activity/Amount], 0))',fmt=USD),
   col("returns_amount","Returns",'Sum(If([SRC Sales Activity/Activity Type] = "Return", -[SRC Sales Activity/Amount], 0))',fmt=USD),
   col("net_cost","Net Cost","Sum([SRC Sales Activity/Cost])",fmt=USD),
   col("net_units","Net Units","Sum([SRC Sales Activity/Quantity])",fmt=NUM0),
   col("orders","Orders","CountDistinct([SRC Sales Activity/Order Number])",fmt=NUM0),
   col("customers","Customers","CountDistinct([SRC Sales Activity/Cust Key])",fmt=NUM0),
   col("retail_net_sales","Retail Net Sales",'Sum(If([SRC Sales Activity/Channel Type] = "Retail", [SRC Sales Activity/Amount], 0))',fmt=USD),
   col("digital_net_sales","Digital Net Sales",'Sum(If([SRC Sales Activity/Channel Type] = "Retail", 0, [SRC Sales Activity/Amount]))',
       "Web, BOPIS and BOSS sales credited to this associate. Digital orders still carry the Salesperson Key of an associate at the crediting store.",USD),
   col("first_sale_date","First Sale Date","Min([SRC Sales Activity/Sale Date])"),
   col("last_sale_date","Last Sale Date","Max([SRC Sales Activity/Sale Date])"),
 ],
 "groupings":[{"id":"g_emp","groupBy":["salesperson_key"],
   "calculations":["net_sales","gross_sales","returns_amount","net_cost","net_units","orders","customers",
                   "retail_net_sales","digital_net_sales","first_sale_date","last_sale_date"]}],
}

period_agg = {
 "id":"period_agg","name":"Employee Period Agg","kind":"table","visibleAsSource":False,
 "description":"Sales Activity collapsed to Salesperson Key x Fiscal Year x Fiscal Period.",
 "source":{"kind":"table","elementId":"src_sales_activity"},
 "columns":[
   col("salesperson_key","Salesperson Key","[SRC Sales Activity/Salesperson Key]"),
   col("fiscal_year","Fiscal Year","[SRC Sales Activity/Fiscal Year]"),
   col("fiscal_period","Fiscal Period","[SRC Sales Activity/Fiscal Period]"),
   col("fiscal_period_name","Fiscal Period Name","[SRC Sales Activity/Fiscal Period Name]"),
   col("net_sales","Net Sales","Sum([SRC Sales Activity/Amount])",fmt=USD),
   col("gross_sales","Gross Sales",'Sum(If([SRC Sales Activity/Activity Type] = "Sale", [SRC Sales Activity/Amount], 0))',fmt=USD),
   col("returns_amount","Returns",'Sum(If([SRC Sales Activity/Activity Type] = "Return", -[SRC Sales Activity/Amount], 0))',fmt=USD),
   col("net_units","Net Units","Sum([SRC Sales Activity/Quantity])",fmt=NUM0),
   col("orders","Orders Touched","CountDistinct([SRC Sales Activity/Order Number])",
       "Distinct orders with ANY activity in this period, sale or return. NOT additive across periods.",NUM0),
   col("orders_sold","Orders Sold",'CountDistinct(If([SRC Sales Activity/Activity Type] = "Sale", [SRC Sales Activity/Order Number], Null))',
       "Distinct orders PLACED in this period. Additive across periods; sums to 717,747.",NUM0),
 ],
 "groupings":[{"id":"g_per","groupBy":["salesperson_key","fiscal_year","fiscal_period","fiscal_period_name"],
   "calculations":["net_sales","gross_sales","returns_amount","net_units","orders","orders_sold"]}],
}

# ---------------------------------------------------------------- Page 5: Employee Base (hidden)
HIRE = "[Org Flat/Hire Date]"; TERM = "[Org Flat/Termination Date]"
WS = "[Sales Window/Window Start]"; WE = "[Sales Window/Window End]"
ACT_START = f"If({HIRE} > {WS}, {HIRE}, {WS})"
ACT_END   = f"If(IsNull({TERM}), {WE}, If({TERM} < {WE}, {TERM}, {WE}))"
ACT_DAYS  = f'If(DateDiff("day", {ACT_START}, {ACT_END}) < 0, 0, DateDiff("day", {ACT_START}, {ACT_END}))'

ORG_PASS = [c for c in org_flat["columns"] if c["id"] != "window_key"]

employee_base = {
 "id":"employee_base","name":"Employee Base","kind":"table","visibleAsSource":False,
 "description":"Org spine joined to per-employee sales and to the fact-window bounds. Feeds both the tier benchmark and the published performance element.",
 "source":{"kind":"join","primarySource":{"kind":"table","elementId":"org_flat"},
   "joins":[
     {"joinType":"left-outer","left":{"kind":"table","elementId":"org_flat"},
      "right":{"kind":"table","elementId":"employee_sales","groupingId":"g_emp"},
      "columns":[{"left":"[Employee Key]","right":"[Salesperson Key]"}]},
     {"joinType":"left-outer","left":{"kind":"table","elementId":"org_flat"},
      "right":{"kind":"table","elementId":"sales_window","groupingId":"g_win"},
      "columns":[{"left":"[Window Key]","right":"[Window Key]"}]},
   ]},
 "columns":[col(c["id"], c["name"], f'[Org Flat/{c["name"]}]', c.get("description"), c.get("format")) for c in ORG_PASS] + [
   col("net_sales","Net Sales","Coalesce([Employee Sales Agg/Net Sales], 0)",fmt=USD),
   col("gross_sales","Gross Sales","Coalesce([Employee Sales Agg/Gross Sales], 0)",fmt=USD),
   col("returns_amount","Returns","Coalesce([Employee Sales Agg/Returns], 0)",fmt=USD),
   col("net_cost","Net Cost","Coalesce([Employee Sales Agg/Net Cost], 0)",fmt=USD),
   col("net_units","Net Units","Coalesce([Employee Sales Agg/Net Units], 0)",fmt=NUM0),
   col("orders","Orders","Coalesce([Employee Sales Agg/Orders], 0)",fmt=NUM0),
   col("customers","Customers","Coalesce([Employee Sales Agg/Customers], 0)",fmt=NUM0),
   col("retail_net_sales","Retail Net Sales","Coalesce([Employee Sales Agg/Retail Net Sales], 0)",fmt=USD),
   col("digital_net_sales","Digital Net Sales","Coalesce([Employee Sales Agg/Digital Net Sales], 0)",fmt=USD),
   col("first_sale_date","First Sale Date","[Employee Sales Agg/First Sale Date]"),
   col("last_sale_date","Last Sale Date","[Employee Sales Agg/Last Sale Date]"),
   col("window_start","Window Start",WS),
   col("window_end","Window End",WE),
   col("active_start","Active Start",ACT_START),
   col("active_end","Active End",ACT_END),
   col("active_days","Active Days",ACT_DAYS,
       "Days this person was employed AND inside the sales-fact window. The correct exposure denominator: all-time sales "
       "otherwise just measure how long someone has been present.",NUM0),
   col("commission_earned","Commission Earned","Coalesce([Employee Sales Agg/Net Sales], 0) * Coalesce([Org Flat/Commission Rate], 0)",
       "Net sales times this employee's own commission rate. Leadership is salaried and earns none.",USD),
   col("recency_days","Recency Days",f'DateDiff("day", [Employee Sales Agg/Last Sale Date], {WE})',
       "Days between this associate's last sale and the END OF THE FACT WINDOW, not today.",NUM0),
 ],
}

tier_benchmark = {
 "id":"tier_benchmark","name":"Tier Benchmark","kind":"table","visibleAsSource":False,
 "description":"Pooled sales rate per Employee Type, used as the peer baseline for Attainment Index.",
 "source":{"kind":"table","elementId":"employee_base"},
 "columns":[
   col("employee_type","Employee Type","[Employee Base/Employee Type]"),
   col("tier_net_sales","Tier Net Sales","Sum([Employee Base/Net Sales])",fmt=USD),
   col("tier_active_days","Tier Active Days","Sum([Employee Base/Active Days])",fmt=NUM0),
   col("tier_headcount","Tier Headcount","CountDistinct([Employee Base/Employee Key])",fmt=NUM0),
 ],
 "groupings":[{"id":"g_tier","groupBy":["employee_type"],
   "calculations":["tier_net_sales","tier_active_days","tier_headcount"]}],
}

# ---------------------------------------------------------------- Page 6: Workforce (exposed)
BASE_PASS = [c for c in employee_base["columns"] if c["id"] not in ("window_key",)]

perf_metrics = [
 {"id":"m_p_employees","name":"Employees","formula":"CountDistinct([Employee Key])","format":NUM0},
 {"id":"m_p_associates","name":"Associates","formula":'CountDistinct(If([Compensation Type] = "Commission", [Employee Key], Null))',
  "description":"Commissioned selling associates only (1,617 of 1,840). Leadership is salaried and sells nothing.","format":NUM0},
 {"id":"m_p_selling","name":"Selling Associates","formula":"CountDistinct(If([Orders] > 0, [Employee Key], Null))",
  "description":"Associates with at least one attributed order (1,522). The other 95 are almost all leavers who exited before the fact window opened.","format":NUM0},
 {"id":"m_p_net_sales","name":"Net Sales","formula":"Sum([Net Sales])","format":USD},
 {"id":"m_p_gross_sales","name":"Gross Sales","formula":"Sum([Gross Sales])","format":USD},
 {"id":"m_p_returns","name":"Returns","formula":"Sum([Returns])","format":USD},
 {"id":"m_p_return_rate","name":"Return Rate %","formula":"[Metrics/Returns] / [Metrics/Gross Sales]","format":PCT},
 {"id":"m_p_margin","name":"Gross Margin","formula":"Sum([Net Sales]) - Sum([Net Cost])","format":USD},
 {"id":"m_p_orders","name":"Orders","formula":"Sum([Orders])","format":NUM0},
 {"id":"m_p_units","name":"Net Units","formula":"Sum([Net Units])","format":NUM0},
 {"id":"m_p_commission","name":"Commission Earned","formula":"Sum([Commission Earned])","format":USD},
 {"id":"m_p_eff_rate","name":"Effective Commission Rate %","formula":"[Metrics/Commission Earned] / [Metrics/Net Sales]",
  "description":"Blended commission cost per dollar of net sales. Differs from the average of Commission Rate because rate varies within tier.","format":PCT},
 {"id":"m_p_sales_per_assoc","name":"Sales per Associate","formula":"[Metrics/Net Sales] / [Metrics/Selling Associates]","format":USD},
 {"id":"m_p_active_days","name":"Active Days","formula":"Sum([Active Days])",
  "description":"Employed days inside the fact window, ALL employees including salaried leadership.","format":NUM0},
 {"id":"m_p_assoc_active_days","name":"Associate Active Days","formula":'Sum(If([Compensation Type] = "Commission", [Active Days], 0))',
  "description":"Active days for commissioned associates only. The correct denominator for productivity: leadership accrues "
                "active days but can never be attributed a sale, so including them silently deflates any rate.","format":NUM0},
 {"id":"m_p_sales_per_day","name":"Net Sales per Active Day","formula":"[Metrics/Net Sales] / [Metrics/Associate Active Days]",
  "description":"THE productivity metric. Divides by time actually worked inside the fact window, so it is not distorted by "
                "tenure or by mid-window hires and leavers, and divides only by commissioned associates' days. Sales per Associate "
                "is not comparable across tenure bands; this is.","format":USD},
 {"id":"m_p_aov","name":"Avg Order Value","formula":"[Metrics/Net Sales] / [Metrics/Orders]","format":USD},
 {"id":"m_p_orders_per_day","name":"Orders per Active Day","formula":"[Metrics/Orders] / [Metrics/Associate Active Days]","format":NUM2},
 {"id":"m_p_terminated","name":"Terminated","formula":'CountDistinct(If([Employment Status] = "Terminated", [Employee Key], Null))',"format":NUM0},
 {"id":"m_p_attrition","name":"Attrition Rate %","formula":"[Metrics/Terminated] / [Metrics/Employees]",
  "description":"22.07% company-wide, but that blends two very different populations: associate attrition is 25.11% and "
                "leadership attrition is exactly 0%. Always split by Compensation Type before quoting this.","format":PCT},
 {"id":"m_p_span","name":"Span of Control","formula":"Sum([Direct Reports]) / CountDistinct(If([Direct Reports] > 0, [Employee Key], Null))","format":NUM2},
 {"id":"m_p_tenure","name":"Avg Tenure Years","formula":"Avg([Tenure Years])","format":NUM2},
 {"id":"m_p_tenure_exit","name":"Avg Tenure at Exit","formula":"Avg([Tenure Years at Exit])","format":NUM2},
 {"id":"m_p_salary","name":"Annual Salary","formula":"Sum([Annual Salary])","format":USD},
]

employee_performance = {
 "id":"employee_performance","name":"Employee Performance","kind":"table","visibleAsSource":True,
 "description":("One row per employee (1,840): the flattened org plus all-time attributed sales, commission and exposure. "
   "Every order line in Sales Activity carries a Salesperson Key, so 100% of company net sales attribute here - this element "
   "ties exactly to the Sales Activity model. "
   "TRAP 1: only the 1,617 commissioned associates can sell; the 223 leaders are LEFT JOINed at zero. Filter on "
   "Compensation Type = 'Commission' before computing any per-head sales average, or leadership dilutes it. "
   "TRAP 2: 95 commissioned associates have zero attributed sales; 94 are leavers who exited before the fact window opened. "
   "Sales per Associate divides by Selling Associates for this reason. "
   "TRAP 3: all-time Net Sales is proportional to how long someone was present, so it ranks tenure, not talent. Use "
   "Net Sales per Active Day for any performance comparison. "
   "TRAP 4: digital orders (Web, BOPIS, BOSS) are credited to an associate at the crediting store even though that associate "
   "did not serve the customer - Retail Net Sales isolates genuine in-store selling."),
 "source":{"kind":"join","primarySource":{"kind":"table","elementId":"employee_base"},
   "joins":[{"joinType":"left-outer","left":{"kind":"table","elementId":"employee_base"},
             "right":{"kind":"table","elementId":"tier_benchmark","groupingId":"g_tier"},
             "columns":[{"left":"[Employee Type]","right":"[Employee Type]"}]}]},
 "columns":[col(c["id"], c["name"], f'[Employee Base/{c["name"]}]', c.get("description"), c.get("format")) for c in BASE_PASS] + [
   col("tier_sales_per_day","Tier Net Sales per Active Day",
       "[Tier Benchmark/Tier Net Sales] / [Tier Benchmark/Tier Active Days]",
       "Pooled peer baseline: every dollar sold by this employee's tier divided by every day that tier worked.",USD),
   col("own_sales_per_day","Net Sales per Active Day",
       "If([Employee Base/Active Days] > 0, [Employee Base/Net Sales] / [Employee Base/Active Days], Null)",
       "This employee's own daily selling rate. An EMPLOYEE ATTRIBUTE, not an additive measure - for a group rate use the "
       "Net Sales per Active Day metric, which pools numerator and denominator.",USD),
   col("attainment_index","Attainment Index",
       "If([Employee Base/Active Days] > 0 and [Tier Benchmark/Tier Active Days] > 0, "
       "([Employee Base/Net Sales] / [Employee Base/Active Days]) / "
       "([Tier Benchmark/Tier Net Sales] / [Tier Benchmark/Tier Active Days]), Null)",
       "Daily selling rate relative to tier peers. 1.00 is exactly at the tier baseline, 1.20 is 20% above it. "
       "Exposure-normalised, so a six-month hire and a ten-year veteran are directly comparable.",NUM2),
   col("tier_headcount","Tier Headcount","[Tier Benchmark/Tier Headcount]",fmt=NUM0),
 ],
 "metrics":perf_metrics,
}

employee_period = {
 "id":"employee_period","name":"Employee Period","kind":"table","visibleAsSource":True,
 "description":("Attributed sales at Employee x Fiscal Year x Fiscal Period - the trend companion to Employee Performance. "
   "Only periods in which an associate actually sold appear; there are no zero rows for idle periods, so a period-over-period "
   "chart must not assume a dense spine. Fiscal periods follow the 4-5-4 calendar. "
   "TRAP: an order returned in a later period appears in BOTH periods, so Orders Touched is not additive across periods - "
   "use Orders Sold, which counts only the period the order was placed in and totals 717,747. Net Sales is unaffected: "
   "the refund is a negative amount landing in the return's own period, which is the correct accounting treatment."),
 "source":{"kind":"join","primarySource":{"kind":"table","elementId":"period_agg","groupingId":"g_per"},
   "joins":[{"joinType":"left-outer","left":{"kind":"table","elementId":"period_agg","groupingId":"g_per"},
             "right":{"kind":"table","elementId":"org_flat"},
             "columns":[{"left":"[Salesperson Key]","right":"[Employee Key]"}]}]},
 "columns":[
   col("employee_key","Employee Key","[Employee Period Agg/Salesperson Key]"),
   col("employee_name","Employee Name","[Org Flat/Employee Name]"),
   col("employee_type","Employee Type","[Org Flat/Employee Type]"),
   col("employment_status","Employment Status","[Org Flat/Employment Status]"),
   col("commission_rate","Commission Rate","[Org Flat/Commission Rate]",fmt=PCT),
   col("store_key","Store Key","[Org Flat/Store Key]"),
   col("store_name","Store Name","[Org Flat/Store Name]"),
   col("region","Region","[Org Flat/Region]"),
   col("area","Area","[Org Flat/Area]"),
   col("sm_name","Store Manager","[Org Flat/Store Manager]"),
   col("avp_name","AVP","[Org Flat/AVP]"),
   col("rvp_name","RVP","[Org Flat/RVP]"),
   col("fiscal_year","Fiscal Year","[Employee Period Agg/Fiscal Year]"),
   col("fiscal_period","Fiscal Period","[Employee Period Agg/Fiscal Period]"),
   col("fiscal_period_name","Fiscal Period Name","[Employee Period Agg/Fiscal Period Name]"),
   col("net_sales","Net Sales","[Employee Period Agg/Net Sales]",fmt=USD),
   col("gross_sales","Gross Sales","[Employee Period Agg/Gross Sales]",fmt=USD),
   col("returns_amount","Returns","[Employee Period Agg/Returns]",fmt=USD),
   col("net_units","Net Units","[Employee Period Agg/Net Units]",fmt=NUM0),
   col("orders_sold","Orders Sold","[Employee Period Agg/Orders Sold]",
       "Orders this associate PLACED in this fiscal period. Use this for any multi-period order count - it is additive.",NUM0),
   col("orders","Orders Touched","[Employee Period Agg/Orders Touched]",
       "Orders with any activity in this period, including returns of orders sold in an EARLIER period. "
       "NOT ADDITIVE across periods: summing it company-wide gives 867,401 order-period pairs against only 717,747 real orders, "
       "because 149,654 orders are returned in a later period than they were sold. Correct within a single period only.",NUM0),
   col("commission_earned","Commission Earned","[Employee Period Agg/Net Sales] * Coalesce([Org Flat/Commission Rate], 0)",fmt=USD),
 ],
 "metrics":[
   {"id":"m_pp_net_sales","name":"Net Sales","formula":"Sum([Net Sales])","format":USD},
   {"id":"m_pp_gross_sales","name":"Gross Sales","formula":"Sum([Gross Sales])","format":USD},
   {"id":"m_pp_returns","name":"Returns","formula":"Sum([Returns])","format":USD},
   {"id":"m_pp_return_rate","name":"Return Rate %","formula":"[Metrics/Returns] / [Metrics/Gross Sales]","format":PCT},
   {"id":"m_pp_orders","name":"Orders Sold","formula":"Sum([Orders Sold])",
    "description":"Additive across every grouping. Ties to 717,747 company-wide.","format":NUM0},
   {"id":"m_pp_commission","name":"Commission Earned","formula":"Sum([Commission Earned])","format":USD},
   {"id":"m_pp_assoc","name":"Selling Associates","formula":"CountDistinct([Employee Key])","format":NUM0},
   {"id":"m_pp_sales_per_assoc","name":"Sales per Selling Associate","formula":"[Metrics/Net Sales] / [Metrics/Selling Associates]","format":USD},
   {"id":"m_pp_aov","name":"Avg Order Value","formula":"[Metrics/Net Sales] / [Metrics/Orders Sold]","format":USD},
 ],
}

# ---------------------------------------------------------------- Metric documentation
# Every published metric carries a description. The assertion below fails the build if a
# metric is ever added without one, so the published model cannot drift out of documentation.
METRIC_DESCRIPTIONS = {
 # --- Org
 "m_o_employees":"Distinct headcount on the org roster: 1,840, being 1,617 commissioned selling associates plus 223 salaried leaders.",
 "m_o_terminated":"Employees whose Employment Status is Terminated. 406 company-wide, every one of them a commissioned associate.",
 "m_o_attrition":"Terminated as a share of headcount. 22.07% company-wide, but that blends 25.11% associate attrition with exactly 0% leadership attrition - not one Store Manager, AVP or RVP has ever left. Split by Compensation Type before quoting this.",
 "m_o_span":"Average number of direct reports across people who actually manage someone; individual contributors are excluded from the denominator rather than dragging it toward zero. 8.09 for Store Managers, 11.11 for AVPs, 3.60 for RVPs.",
 "m_o_tenure":"Mean corrected tenure - hire-to-today for active employees, hire-to-termination for leavers. Built on the corrected Tenure Years column, never the as-reported one, which keeps accruing after someone has left.",
 "m_o_tenure_exit":"Mean years actually served by employees who have left, hire to termination. 2.64 years. Null for active employees, so this is a leaver-only statistic and will not move when headcount grows.",
 "m_o_salary":"Total annual salary. Only the 223 salaried leaders carry a salary; commissioned associates are null and contribute nothing, so this is a leadership payroll figure, not a company one.",
 # --- Employee Performance
 "m_p_employees":"Distinct employees on the roster, 1,840. Includes the 223 salaried leaders, who can never be attributed a sale - use Associates as the denominator for anything sales-related.",
 "m_p_associates":"Commissioned selling associates only, 1,617 of 1,840. Leadership is salaried and sells nothing.",
 "m_p_selling":"Associates with at least one attributed order, 1,522. The other 95 are almost all leavers who exited before the fact window opened and so have no sales to attribute.",
 "m_p_net_sales":"Attributed sales net of returns. $1,114,855,651.92 all-time, tying exactly to the Retail Sales Activity model: every order line carries a Salesperson Key, so 100% of company sales attribute here with no unallocated residual.",
 "m_p_gross_sales":"Attributed sales before returns. $1,178,971,663.73 all-time.",
 "m_p_returns":"Refund value attributed to the associate who SOLD the item, expressed positive. $64,116,011.81 all-time. Not the associate who processed the return - this is a selling-quality measure, not a service-desk workload.",
 "m_p_return_rate":"Returns as a share of gross sales, 5.44% company-wide. A genuine associate-quality signal, since over-promising at the point of sale surfaces here rather than in the sales number.",
 "m_p_margin":"Net sales less net cost of the goods attributed to this associate. Mix-sensitive: an associate selling higher-margin lines will lead on this while trailing on Net Sales.",
 "m_p_orders":"Distinct orders attributed, 717,747 all-time. Counted once per associate across the entire window, so unlike Employee Period's Orders Touched this is safe to aggregate at any grouping.",
 "m_p_units":"Units sold net of units returned.",
 "m_p_commission":"Each employee's net sales times their OWN commission rate, then summed. $30,839,726.62 all-time. Computed per employee before summing because the rate varies within tier - applying an average rate to total sales gives a different, wrong answer.",
 "m_p_eff_rate":"Blended commission cost per dollar of net sales, 2.77%. Differs from the average of Commission Rate because rate varies within tier and higher-rate tiers do not sell proportionally more.",
 "m_p_sales_per_assoc":"Net sales per associate who actually sold. Divides by Selling Associates rather than Associates so the 95 with no attributed sales do not deflate it. NOT comparable across tenure bands - it scales with time present, so use Net Sales per Active Day for any performance comparison.",
 "m_p_active_days":"Days employed inside the sales-fact window, summed across ALL employees including salaried leadership. Exposure, not effort. For productivity denominators use Associate Active Days instead.",
 "m_p_assoc_active_days":"Active days for commissioned associates only, 1,613,138 of 1,881,434. The correct denominator for productivity: leadership accrues active days but can never be attributed a sale, so including them silently deflates any rate.",
 "m_p_sales_per_day":"THE productivity metric, $691.11 company-wide. Divides by time actually worked inside the fact window and by commissioned associates only, so it is undistorted by tenure, by mid-window hires and leavers, and by leadership headcount. This is what shows the tenure-to-productivity curve to be flat (721/day under 1 year vs 648/day past 8), where all-time Net Sales makes it look like an 8x ramp.",
 "m_p_aov":"Net sales per attributed order, $1,553.27 company-wide. Basket size - pair with Orders per Active Day, which is transaction velocity, to see which of the two an associate actually drives.",
 "m_p_orders_per_day":"Attributed orders per commissioned associate-day, 0.44 company-wide. Transaction velocity, independent of basket size.",
 "m_p_terminated":"Employees who have left, 406 - all of them commissioned associates.",
 "m_p_attrition":"22.07% company-wide, but that blends two very different populations: associate attrition is 25.11% and leadership attrition is exactly 0%. Always split by Compensation Type before quoting this.",
 "m_p_span":"Average direct reports across people who actually manage someone, 8.23 pooled - 8.09 for Store Managers, 11.11 for AVPs, 3.60 for RVPs. Individual contributors are excluded from the denominator.",
 "m_p_tenure":"Mean corrected tenure - hire-to-today for actives, hire-to-termination for leavers. Never built on Tenure Years (As Reported), which keeps accruing after termination and overstates leaver tenure by 2.53 years.",
 "m_p_tenure_exit":"Mean years actually served by leavers, hire to termination, 2.64 years. Null for actives, so this is a leaver-only statistic.",
 "m_p_salary":"Total annual salary. Only the 223 salaried leaders carry one; associates are null and contribute nothing.",
 # --- Employee Period
 "m_pp_net_sales":"Attributed sales net of returns for the fiscal period. Sums across periods to $1,114,855,651.92. A refund lands as a negative amount in the period the RETURN happened, not the period of the original sale, which is the correct accounting treatment but means a heavy return period can show negative net sales for an associate.",
 "m_pp_gross_sales":"Attributed sales before returns, within the fiscal period.",
 "m_pp_returns":"Refund value landing in this fiscal period, expressed positive. Belongs to the period of the RETURN; the sale being refunded may sit in an earlier period.",
 "m_pp_return_rate":"Returns as a share of gross sales within the period. Noisy at this grain because a return can lag its sale by a period or more, so the numerator and denominator are not describing the same transactions - prefer a trailing multi-period window, or use the Employee Performance version for an all-time read.",
 "m_pp_orders":"Distinct orders PLACED in the period. Additive across every grouping and ties to 717,747 company-wide, unlike Orders Touched.",
 "m_pp_commission":"Period net sales times the associate's commission rate. Sums to $30,839,726.62 all-time.",
 "m_pp_assoc":"Distinct associates with attributed activity in the grouping. Only associates who actually sold appear in this element - there are no zero rows for idle periods - so this is an activity count, not a headcount. For headcount use Employee Performance.",
 "m_pp_sales_per_assoc":"Net sales divided by the associates who sold in the period. A period-local average, not a per-head productivity measure comparable across time; for that use Employee Performance's Net Sales per Active Day.",
 "m_pp_aov":"Net sales per order placed in the period, $1,553.27 company-wide. Divides by Orders Sold; dividing by Orders Touched would inflate the denominator with later-period returns and understate the value.",
}

for _el in (dim_org, employee_performance, employee_period):
    for _m in _el["metrics"]:
        if _m["id"] in METRIC_DESCRIPTIONS:
            _m["description"] = METRIC_DESCRIPTIONS[_m["id"]]
    _missing = [_m["name"] for _m in _el["metrics"] if not _m.get("description")]
    assert not _missing, f'{_el["id"]}: metrics missing a description: {_missing}'


spec = {
 "name":"Retail Workforce & Org",
 "description":("Employee-grain workforce model: the three-level field hierarchy flattened, plus attributed sales, commission "
   "and exposure-normalised productivity. Unblocks the Commission Performance Coach. Sources conformed dimensions from the "
   "Retail Sales Activity model. F_LABOR is deliberately NOT sourced here - it is Store x Date x Hour with no employee key, "
   "so it cannot reach employee grain; staffing lives in the Retail Store Operations model."),
 "pages":[
   {"id":"page_sources","name":"Sources","elements":sources},
   {"id":"page_dims","name":"Conformed Dimensions","elements":dims},
   {"id":"page_org_build","name":"Org Build","elements":[direct_reports,org_flat]},
   {"id":"page_sales_build","name":"Sales Build","elements":[sales_window,employee_sales,period_agg]},
   {"id":"page_base","name":"Employee Base","elements":[employee_base,tier_benchmark]},
   {"id":"page_workforce","name":"Workforce","elements":[dim_org,employee_performance,employee_period]},
 ],
}

if __name__ == "__main__":
    print(json.dumps(spec, indent=2))
