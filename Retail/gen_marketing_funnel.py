import json

UPLOADS  = "b765b086-4e7e-426b-ac82-7d6e0cf5a71c"
SALESACT = "8c548776-acb2-46ac-b60d-dd5a70781bd2"
FOLDER   = "0883a1b1-700d-4ee8-878f-db648d4e51fa"

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
    e = {"id": eid, "name": name, "kind": "table",
         "source": {"kind": "data-model", "dataModelId": model, "elementId": origin_elem},
         "columns": [col(cid, disp, f"[{origin_name}/{disp}]") for cid, disp in cols],
         "visibleAsSource": False}
    if desc: e["description"] = desc
    return e

# ------------------------------------------------------------------ Page 1: Sources
WT_COLS   = [("date_key","Date Key"),("traffic_source","Traffic Source"),("web_visits","Web Visits")]
MS_COLS   = [("date_key","Date Key"),("traffic_source","Traffic Source"),("spend","Spend")]
PROMO_COLS= [("promotion_key","Promotion Key"),("promotion_name","Promotion Name"),
             ("promotion_type","Promotion Type"),("start_date","Start Date"),("end_date","End Date"),
             ("discount_percent","Discount Percent"),("channel","Channel")]
MD_COLS   = [("product_key","Product Key"),("effective_start_date","Effective Start Date"),
             ("price","Price"),("discount_percent","Discount Percent"),("promotion_key","Promotion Key"),
             ("product_name","Product Name"),("product_family","Product Family"),
             ("promotion_name","Promotion Name"),("promotion_type","Promotion Type")]
DATE_COLS = [("date_key","Date Key"),("day_of_week_name","Day of Week Name"),("day_of_week_number","Day of Week Number"),
             ("is_weekend","Is Weekend"),("week_start_date","Week Start Date"),
             ("calendar_year","Calendar Year"),("calendar_month","Calendar Month"),("calendar_month_name","Calendar Month Name"),
             ("calendar_quarter","Calendar Quarter"),
             ("fiscal_year","Fiscal Year"),("fiscal_quarter","Fiscal Quarter"),("fiscal_period","Fiscal Period"),
             ("fiscal_period_name","Fiscal Period Name"),("fiscal_week_of_year","Fiscal Week of Year"),
             ("fiscal_season","Fiscal Season"),("prior_year_date","Prior Year Date")]
SA_COLS   = [("sale_date","Sale Date"),("activity_type","Activity Type"),("channel_type","Channel Type"),
             ("order_number","Order Number"),("cust_key","Cust Key"),
             ("quantity","Quantity"),("amount","Amount"),("cost","Cost")]

sources = [
 src("src_f_web_traffic","SRC F_WEB_TRAFFIC",UPLOADS,"lXFXBVuiME","F_WEB_TRAFFIC.csv",WT_COLS,
     "Daily web sessions by acquisition source. 9,132 rows = 1,522 days x 6 sources, exactly co-grained with F_MARKETING_SPEND."),
 src("src_f_marketing_spend","SRC F_MARKETING_SPEND",UPLOADS,"sHQCXTMbCb","F_MARKETING_SPEND.csv",MS_COLS,
     "Daily media spend by source. Same 9,132 keys as F_WEB_TRAFFIC, so the two join 1:1 with no orphans on either side."),
 src("src_date","SRC Date",SALESACT,"dim_date","Date",DATE_COLS,
     "Conformed Date dimension (4-5-4 fiscal) referenced from the Retail Sales Activity model."),
 src("src_promotion","SRC Promotion",SALESACT,"dim_promotion","Promotion",PROMO_COLS,
     "52 promotions with start/end dates, referenced from the Retail Sales Activity model."),
 src("src_markdowns","SRC Markdowns",SALESACT,"markdowns","Markdowns",MD_COLS,
     "Product price-change ledger referenced from the Retail Sales Activity model."),
 src("src_sales_activity","SRC Sales Activity",SALESACT,"sales_activity","Sales Activity",SA_COLS,
     "Sales + returns fact referenced from the Retail Sales Activity model, projected to the columns needed for daily digital revenue."),
]

# ------------------------------------------------------------------ Page 2: Conformed Dimensions
PAID = ('[SRC F_WEB_TRAFFIC/Traffic Source] = "Paid Search" or [SRC F_WEB_TRAFFIC/Traffic Source] = "Social" '
        'or [SRC F_WEB_TRAFFIC/Traffic Source] = "Email" or [SRC F_WEB_TRAFFIC/Traffic Source] = "Referral"')
PAID_MEDIA = ('[SRC F_WEB_TRAFFIC/Traffic Source] = "Paid Search" '
              'or [SRC F_WEB_TRAFFIC/Traffic Source] = "Social"')
OWNED = ('[SRC F_WEB_TRAFFIC/Traffic Source] = "Email" '
         'or [SRC F_WEB_TRAFFIC/Traffic Source] = "Referral"')
GROUP_F = f'If({PAID_MEDIA}, "Paid Media", If({OWNED}, "Owned & Earned", "Free"))'

dim_traffic_source = {
 "id":"dim_traffic_source","name":"Traffic Source","kind":"table","visibleAsSource":True,
 "description":"The six web acquisition sources. Direct and Organic Search carry ZERO spend on all 1,522 days - they are free traffic and together supply 2,148,437 visits (44.4% of all sessions). Any cost-per-visit or ROAS figure that averages them in with paid media is diluted by design; slice by Is Paid Source or Source Group to avoid it.",
 "source":{"kind":"table","elementId":"src_f_web_traffic"},
 "columns":[
   col("traffic_source","Traffic Source","[SRC F_WEB_TRAFFIC/Traffic Source]"),
   col("is_paid_source","Is Paid Source",f"If({PAID}, True, False)",
       "True for Paid Search, Social, Email and Referral, all of which record spend on every day. False for Direct and Organic Search, which record $0 on every day."),
   col("source_group","Source Group",GROUP_F,
       "Paid Media (Paid Search, Social - $1.50M of the $1.56M total spend), Owned & Earned (Email, Referral), Free (Direct, Organic Search)."),
   col("lifetime_visits","Lifetime Visits","Sum([SRC F_WEB_TRAFFIC/Web Visits])",
       "All-time sessions from this source, for sizing only.",NUM0),
 ],
 "groupings":[{"id":"g_source","groupBy":["traffic_source","is_paid_source","source_group"],
               "calculations":["lifetime_visits"]}],
}

dim_date = {
 "id":"dim_date","name":"Date","kind":"table","visibleAsSource":True,
 "description":"Retail 4-5-4 fiscal calendar. Sigma's built-in period-over-period and DateLookback are CALENDAR-based and will not align to 4-5-4 week boundaries; use Prior Year Date for fiscal-correct comps. Wider than the funnel window (web traffic runs 2021-08-19 to 2025-10-18).",
 "source":{"kind":"table","elementId":"src_date"},
 "columns":[col(cid,disp,f"[SRC Date/{disp}]") for cid,disp in DATE_COLS]}

dim_promotion = {
 "id":"dim_promotion","name":"Promotion","kind":"table","visibleAsSource":True,
 "description":"52 promotions: 37 Seasonal, 15 Flash Sale; 40 tagged Channel = All and 12 Web-only. Discounts run 10-34%. They cover 288 of the 1,522 funnel days and overlap two-deep on 16 of those days - which is why Promo Day rolls promotions up to one row per date before they reach any fact.",
 "source":{"kind":"table","elementId":"src_promotion"},
 "columns":[col(cid,disp,f"[SRC Promotion/{disp}]") for cid,disp in PROMO_COLS]}

dims = [dim_date, dim_traffic_source, dim_promotion]

# ------------------------------------------------------------------ Page 3: Daily Build (hidden)
DIGITAL = '[SRC Sales Activity/Channel Type] <> "Retail"'
SALE    = '[SRC Sales Activity/Activity Type] = "Sale"'
RETURN  = '[SRC Sales Activity/Activity Type] = "Return"'

digital_daily = {
 "id":"digital_daily","name":"Digital Daily","kind":"table","visibleAsSource":False,
 "description":"Sales Activity collapsed to one row per SALE DATE. MANDATORY pre-aggregation - joining line-grain Sales Activity to a day spine would fan the funnel out 4.9M ways. Dated by Sale Date, not Activity Date, so a return lands on the day of the order that produced it: revenue and returns on a given day are one cohort, which is what a spend-driven ROAS needs. All-time totals still tie exactly to the Retail Sales Activity model; only the day-by-day distribution of returns differs.",
 "source":{"kind":"table","elementId":"src_sales_activity"},
 "columns":[
   col("sale_date","Sale Date","[SRC Sales Activity/Sale Date]"),
   col("digital_gross_sales","Digital Gross Sales",f'Sum(If({SALE} and {DIGITAL}, [SRC Sales Activity/Amount], 0))',
       "Web + BOPIS + BOSS gross sales for orders placed this day.",USD),
   col("digital_returns","Digital Returns",f'Sum(If({RETURN} and {DIGITAL}, -[SRC Sales Activity/Amount], 0))',
       "Refunds against digital orders placed this day, whenever the refund was actually processed.",USD),
   col("digital_net_sales","Digital Net Sales",f'Sum(If({DIGITAL}, [SRC Sales Activity/Amount], 0))',
       "Digital gross sales less cohort returns.",USD),
   col("digital_cost","Digital Cost",f'Sum(If({DIGITAL}, [SRC Sales Activity/Cost], 0))',fmt=USD),
   col("digital_units","Digital Units",f'Sum(If({DIGITAL}, [SRC Sales Activity/Quantity], 0))',fmt=NUM0),
   col("web_gross_sales","Web Gross Sales",f'Sum(If({SALE} and [SRC Sales Activity/Channel Type] = "Web", [SRC Sales Activity/Amount], 0))',
       "Pure-play Web channel only, excluding BOPIS and BOSS.",USD),
   col("total_gross_sales","Total Gross Sales",f'Sum(If({SALE}, [SRC Sales Activity/Amount], 0))',
       "All channels including Retail. Present only as the denominator for Digital Mix %.",USD),
   col("digital_orders","Digital Orders",f'CountDistinct(If({SALE} and {DIGITAL}, [SRC Sales Activity/Order Number], Null))',
       "Distinct Web + BOPIS + BOSS orders placed this day.",NUM0),
   col("web_orders","Web Orders",f'CountDistinct(If({SALE} and [SRC Sales Activity/Channel Type] = "Web", [SRC Sales Activity/Order Number], Null))',
       "Distinct pure-play Web orders placed this day. This is the numerator behind the 2.54% baseline web conversion rate.",NUM0),
   col("digital_customers","Digital Customers",f'CountDistinct(If({SALE} and {DIGITAL}, [SRC Sales Activity/Cust Key], Null))',fmt=NUM0),
 ],
 "groupings":[{"id":"g_digital","groupBy":["sale_date"],
   "calculations":["digital_gross_sales","digital_returns","digital_net_sales","digital_cost","digital_units",
                   "web_gross_sales","total_gross_sales","digital_orders","web_orders","digital_customers"]}],
}

promo_day = {
 "id":"promo_day","name":"Promo Day","kind":"table","visibleAsSource":False,
 "description":"Promotions exploded onto the calendar by a RANGE join (Date Key between Start Date and End Date), then collapsed to one row per date. The collapse is mandatory: 16 dates have two promotions running at once, so joining Promotion straight onto a day-grain fact would double those days' visits, spend and revenue.",
 "source":{"kind":"join","primarySource":{"kind":"table","elementId":"dim_date"},
   "joins":[{"joinType":"left-outer","left":{"kind":"table","elementId":"dim_date"},
             "right":{"kind":"table","elementId":"dim_promotion"},
             "columns":[{"left":"[Date Key]","right":"[Start Date]","op":">="},
                        {"left":"[Date Key]","right":"[End Date]","op":"<="}]}]},
 "columns":[
   col("date_key","Date Key","[Date/Date Key]"),
   col("active_promotions","Active Promotions","CountDistinct([Promotion/Promotion Key])",
       "0, 1 or 2. Two promotions overlap on 16 of the 288 promotional days.",NUM0),
   col("max_discount_percent","Max Discount Percent","Max([Promotion/Discount Percent])",
       "Deepest discount advertised this day, 10-34%.",NUM0),
   col("promotion_name","Promotion Name","Max([Promotion/Promotion Name])",
       "The promotion running this day. On the 16 dates where Active Promotions = 2 this shows only one of them - check Active Promotions before reading it as the whole story."),
   col("promotion_type","Promotion Type","Max([Promotion/Promotion Type])","Flash Sale or Seasonal, with the same one-of-two caveat as Promotion Name."),
   col("promotion_channel","Promotion Channel","Max([Promotion/Channel])","All or Web."),
 ],
 "groupings":[{"id":"g_promo_day","groupBy":["date_key"],
   "calculations":["active_promotions","max_discount_percent","promotion_name","promotion_type","promotion_channel"]}],
}

markdown_day = {
 "id":"markdown_day","name":"Markdown Day","kind":"table","visibleAsSource":False,
 "description":"The product price-change ledger collapsed to one row per effective date. 6,051 rows across 1,490 dates, but only 1,118 are genuine markdowns: the other 4,933 carry Discount Percent = 0 and are price RESETS back to full price. Counting all 6,051 as markdowns overstates promotional pressure five-fold.",
 "source":{"kind":"table","elementId":"src_markdowns"},
 "columns":[
   col("effective_start_date","Effective Start Date","[SRC Markdowns/Effective Start Date]"),
   col("price_changes","Price Changes","Count([SRC Markdowns/Product Key])",
       "Every price change effective this day, markdowns and resets alike.",NUM0),
   col("markdowns","Markdowns",'Sum(If([SRC Markdowns/Discount Percent] > 0, 1, 0))',
       "Price changes that actually cut price. Exactly the rows carrying a Promotion Key.",NUM0),
   col("price_resets","Price Resets",'Sum(If([SRC Markdowns/Discount Percent] = 0, 1, 0))',
       "Returns to full price. 4,933 of the 6,051 ledger rows.",NUM0),
   col("max_markdown_percent","Max Markdown Percent","Max([SRC Markdowns/Discount Percent])",fmt=NUM0),
   col("products_marked_down","Products Marked Down",'CountDistinct(If([SRC Markdowns/Discount Percent] > 0, [SRC Markdowns/Product Key], Null))',fmt=NUM0),
 ],
 "groupings":[{"id":"g_markdown_day","groupBy":["effective_start_date"],
   "calculations":["price_changes","markdowns","price_resets","max_markdown_percent","products_marked_down"]}],
}

web_daily = {
 "id":"web_daily","name":"Web Daily","kind":"table","visibleAsSource":False,
 "description":"F_WEB_TRAFFIC and F_MARKETING_SPEND collapsed from Date x Source to one row per date, carrying the paid/free split that the day grain would otherwise lose.",
 "source":{"kind":"join","primarySource":{"kind":"table","elementId":"src_f_web_traffic"},
   "joins":[
     {"joinType":"inner","left":{"kind":"table","elementId":"src_f_web_traffic"},
      "right":{"kind":"table","elementId":"src_f_marketing_spend"},
      "columns":[{"left":"[Date Key]","right":"[Date Key]"},
                 {"left":"[Traffic Source]","right":"[Traffic Source]"}]},
   ]},
 "columns":[
   col("date_key","Date Key","[SRC F_WEB_TRAFFIC/Date Key]"),
   col("web_visits","Web Visits","Sum([SRC F_WEB_TRAFFIC/Web Visits])",fmt=NUM0),
   col("paid_visits","Paid Visits",f'Sum(If({PAID}, [SRC F_WEB_TRAFFIC/Web Visits], 0))',fmt=NUM0),
   col("free_visits","Free Visits",f'Sum(If({PAID}, 0, [SRC F_WEB_TRAFFIC/Web Visits]))',
       "Direct + Organic Search sessions - 44.4% of all traffic, acquired at zero recorded cost.",NUM0),
   col("marketing_spend","Marketing Spend","Sum([SRC F_MARKETING_SPEND/Spend])",fmt=USD),
   col("paid_media_spend","Paid Media Spend",f'Sum(If({PAID_MEDIA}, [SRC F_MARKETING_SPEND/Spend], 0))',
       "Paid Search + Social only.",USD),
   col("paid_search_spend","Paid Search Spend",'Sum(If([SRC F_WEB_TRAFFIC/Traffic Source] = "Paid Search", [SRC F_MARKETING_SPEND/Spend], 0))',fmt=USD),
   col("social_spend","Social Spend",'Sum(If([SRC F_WEB_TRAFFIC/Traffic Source] = "Social", [SRC F_MARKETING_SPEND/Spend], 0))',fmt=USD),
   col("paid_search_visits","Paid Search Visits",'Sum(If([SRC F_WEB_TRAFFIC/Traffic Source] = "Paid Search", [SRC F_WEB_TRAFFIC/Web Visits], 0))',fmt=NUM0),
   col("social_visits","Social Visits",'Sum(If([SRC F_WEB_TRAFFIC/Traffic Source] = "Social", [SRC F_WEB_TRAFFIC/Web Visits], 0))',fmt=NUM0),
   col("organic_visits","Organic Visits",'Sum(If([SRC F_WEB_TRAFFIC/Traffic Source] = "Organic Search", [SRC F_WEB_TRAFFIC/Web Visits], 0))',fmt=NUM0),
   col("direct_visits","Direct Visits",'Sum(If([SRC F_WEB_TRAFFIC/Traffic Source] = "Direct", [SRC F_WEB_TRAFFIC/Web Visits], 0))',fmt=NUM0),
   col("email_visits","Email Visits",'Sum(If([SRC F_WEB_TRAFFIC/Traffic Source] = "Email", [SRC F_WEB_TRAFFIC/Web Visits], 0))',fmt=NUM0),
   col("referral_visits","Referral Visits",'Sum(If([SRC F_WEB_TRAFFIC/Traffic Source] = "Referral", [SRC F_WEB_TRAFFIC/Web Visits], 0))',fmt=NUM0),
 ],
 "groupings":[{"id":"g_web_day","groupBy":["date_key"],
   "calculations":["web_visits","paid_visits","free_visits","marketing_spend","paid_media_spend",
                   "paid_search_spend","social_spend","paid_search_visits","social_visits",
                   "organic_visits","direct_visits","email_visits","referral_visits"]}],
}

# ------------------------------------------------------------------ Page 4: Funnel facts (visible)
DATE_ATTRS = [("day_of_week_name","Day of Week Name"),("is_weekend","Is Weekend"),
              ("week_start_date","Week Start Date"),("calendar_year","Calendar Year"),
              ("calendar_month_name","Calendar Month Name"),("calendar_quarter","Calendar Quarter"),
              ("fiscal_year","Fiscal Year"),("fiscal_quarter","Fiscal Quarter"),
              ("fiscal_period","Fiscal Period"),("fiscal_period_name","Fiscal Period Name"),
              ("fiscal_week_of_year","Fiscal Week of Year"),("fiscal_season","Fiscal Season"),
              ("prior_year_date","Prior Year Date")]

funnel_source = {
 "id":"funnel_source","name":"Funnel by Source","kind":"table","visibleAsSource":True,
 "description":"One row per Date x Traffic Source (9,132 = 1,522 days x 6 sources). Visits and spend join 1:1 with no orphans on either side. THERE IS DELIBERATELY NO REVENUE, ORDER COUNT OR CONVERSION RATE ON THIS ELEMENT. Orders in this dataset carry no traffic source, so per-source attribution is not derivable; allocating day revenue across sources by visit share would look like attribution while being an assumption. Use this element for acquisition volume, spend and efficiency-to-visit; use Funnel Day for anything that touches revenue.",
 "source":{"kind":"join","primarySource":{"kind":"table","elementId":"src_f_web_traffic"},
   "joins":[
     {"joinType":"inner","left":{"kind":"table","elementId":"src_f_web_traffic"},
      "right":{"kind":"table","elementId":"src_f_marketing_spend"},
      "columns":[{"left":"[Date Key]","right":"[Date Key]"},
                 {"left":"[Traffic Source]","right":"[Traffic Source]"}]},
     {"joinType":"left-outer","left":{"kind":"table","elementId":"src_f_web_traffic"},
      "right":{"kind":"table","elementId":"dim_traffic_source","groupingId":"g_source"},
      "columns":[{"left":"[Traffic Source]","right":"[Traffic Source]"}]},
     {"joinType":"left-outer","left":{"kind":"table","elementId":"src_f_web_traffic"},
      "right":{"kind":"table","elementId":"dim_date"},
      "columns":[{"left":"[Date Key]","right":"[Date Key]"}]},
     {"joinType":"left-outer","left":{"kind":"table","elementId":"src_f_web_traffic"},
      "right":{"kind":"table","elementId":"promo_day","groupingId":"g_promo_day"},
      "columns":[{"left":"[Date Key]","right":"[Date Key]"}]},
   ]},
 "columns":[
   col("date_key","Date Key","[SRC F_WEB_TRAFFIC/Date Key]"),
   col("traffic_source","Traffic Source","[SRC F_WEB_TRAFFIC/Traffic Source]"),
   col("web_visits","Web Visits","[SRC F_WEB_TRAFFIC/Web Visits]","Sessions from this source on this day.",NUM0),
   col("spend","Spend","[SRC F_MARKETING_SPEND/Spend]",
       "Media spend against this source on this day. Always $0 for Direct and Organic Search - free traffic, not missing data.",USD),
   col("is_paid_source","Is Paid Source","[Traffic Source/Is Paid Source]"),
   col("source_group","Source Group","[Traffic Source/Source Group]"),
   col("active_promotions","Active Promotions","Coalesce([Promo Day/Active Promotions], 0)",
       "Promotions running company-wide this day. Lets acquisition volume be sliced by promotional pressure.",NUM0),
   col("has_promotion","Has Promotion","Coalesce([Promo Day/Active Promotions], 0) > 0"),
   col("max_discount_percent","Max Discount Percent","[Promo Day/Max Discount Percent]",fmt=NUM0),
 ] + [col(cid,disp,f"[Date/{disp}]") for cid,disp in DATE_ATTRS],
 "metrics":[
   {"id":"m_s_visits","name":"Web Visits","formula":"Sum([Web Visits])","format":NUM0},
   {"id":"m_s_spend","name":"Spend","formula":"Sum([Spend])","format":USD},
   {"id":"m_s_paid_visits","name":"Paid Visits","formula":"Sum(If([Is Paid Source], [Web Visits], 0))","format":NUM0},
   {"id":"m_s_free_visits","name":"Free Visits","formula":"Sum(If([Is Paid Source], 0, [Web Visits]))","format":NUM0},
   {"id":"m_s_cpv","name":"Cost per Visit","formula":"[Metrics/Spend] / [Metrics/Web Visits]","format":USD},
   {"id":"m_s_paid_cpv","name":"Cost per Paid Visit","formula":"[Metrics/Spend] / [Metrics/Paid Visits]","format":USD},
   {"id":"m_s_paid_share","name":"Paid Visit Share %","formula":"[Metrics/Paid Visits] / [Metrics/Web Visits]","format":PCT},
 ],
}

funnel_day = {
 "id":"funnel_day","name":"Funnel Day","kind":"table","visibleAsSource":True,
 "description":"One row per date (1,522: 2021-08-19 to 2025-10-18). The only element in this model where demand meets revenue. Visits and spend are rolled up from all six sources; digital orders and dollars are LEFT JOINed from pre-aggregated Sales Activity and are BLENDED ACROSS SOURCES BY CONSTRUCTION - no order in this dataset carries a traffic source, so every conversion, ROAS and revenue-per-visit figure here is a day-level blend and must never be read as the performance of any one channel. Every digital order date has a matching traffic row, so there are zero orphans in either direction (one traffic day, with no digital order, is genuine).",
 "source":{"kind":"join","primarySource":{"kind":"table","elementId":"web_daily","groupingId":"g_web_day"},
   "joins":[
     {"joinType":"left-outer","left":{"kind":"table","elementId":"web_daily","groupingId":"g_web_day"},
      "right":{"kind":"table","elementId":"digital_daily","groupingId":"g_digital"},
      "columns":[{"left":"[Date Key]","right":"[Sale Date]"}]},
     {"joinType":"left-outer","left":{"kind":"table","elementId":"web_daily","groupingId":"g_web_day"},
      "right":{"kind":"table","elementId":"promo_day","groupingId":"g_promo_day"},
      "columns":[{"left":"[Date Key]","right":"[Date Key]"}]},
     {"joinType":"left-outer","left":{"kind":"table","elementId":"web_daily","groupingId":"g_web_day"},
      "right":{"kind":"table","elementId":"markdown_day","groupingId":"g_markdown_day"},
      "columns":[{"left":"[Date Key]","right":"[Effective Start Date]"}]},
     {"joinType":"left-outer","left":{"kind":"table","elementId":"web_daily","groupingId":"g_web_day"},
      "right":{"kind":"table","elementId":"dim_date"},
      "columns":[{"left":"[Date Key]","right":"[Date Key]"}]},
   ]},
 "columns":[
   col("date_key","Date Key","[Web Daily/Date Key]"),
   col("web_visits","Web Visits","[Web Daily/Web Visits]","All sessions this day, every source.",NUM0),
   col("paid_visits","Paid Visits","[Web Daily/Paid Visits]",fmt=NUM0),
   col("free_visits","Free Visits","[Web Daily/Free Visits]","Direct + Organic Search - 44.4% of all sessions at zero recorded cost.",NUM0),
   col("marketing_spend","Marketing Spend","[Web Daily/Marketing Spend]",fmt=USD),
   col("paid_media_spend","Paid Media Spend","[Web Daily/Paid Media Spend]","Paid Search + Social.",USD),
   col("paid_search_spend","Paid Search Spend","[Web Daily/Paid Search Spend]",fmt=USD),
   col("social_spend","Social Spend","[Web Daily/Social Spend]",fmt=USD),
   col("paid_search_visits","Paid Search Visits","[Web Daily/Paid Search Visits]",fmt=NUM0),
   col("social_visits","Social Visits","[Web Daily/Social Visits]",fmt=NUM0),
   col("organic_visits","Organic Visits","[Web Daily/Organic Visits]",fmt=NUM0),
   col("direct_visits","Direct Visits","[Web Daily/Direct Visits]",fmt=NUM0),
   col("email_visits","Email Visits","[Web Daily/Email Visits]",fmt=NUM0),
   col("referral_visits","Referral Visits","[Web Daily/Referral Visits]",fmt=NUM0),
   col("web_orders","Web Orders","Coalesce([Digital Daily/Web Orders], 0)",
       "Pure-play Web channel orders. Pairs with Web Visits for the 2.54% baseline conversion rate.",NUM0),
   col("digital_orders","Digital Orders","Coalesce([Digital Daily/Digital Orders], 0)",
       "Web + BOPIS + BOSS. All three are placed online (transaction location 9999) and so all three are outcomes of the same web sessions - 3.76% of visits, not 2.54%.",NUM0),
   col("digital_customers","Digital Customers","Coalesce([Digital Daily/Digital Customers], 0)",fmt=NUM0),
   col("web_gross_sales","Web Gross Sales","Coalesce([Digital Daily/Web Gross Sales], 0)",fmt=USD),
   col("digital_gross_sales","Digital Gross Sales","Coalesce([Digital Daily/Digital Gross Sales], 0)",
       "Web + BOPIS + BOSS gross sales for orders placed this day.",USD),
   col("digital_returns","Digital Returns","Coalesce([Digital Daily/Digital Returns], 0)",
       "Refunds against orders placed this day (cohort-dated, not refund-dated), so they line up with the spend that drove them.",USD),
   col("digital_net_sales","Digital Net Sales","Coalesce([Digital Daily/Digital Net Sales], 0)",fmt=USD),
   col("digital_cost","Digital Cost","Coalesce([Digital Daily/Digital Cost], 0)",fmt=USD),
   col("digital_units","Digital Units","Coalesce([Digital Daily/Digital Units], 0)",fmt=NUM0),
   col("digital_gross_margin","Digital Gross Margin","Coalesce([Digital Daily/Digital Net Sales], 0) - Coalesce([Digital Daily/Digital Cost], 0)",fmt=USD),
   col("total_gross_sales","Total Gross Sales","Coalesce([Digital Daily/Total Gross Sales], 0)",
       "All channels including in-store. Present only as the denominator for Digital Mix %.",USD),
   col("active_promotions","Active Promotions","Coalesce([Promo Day/Active Promotions], 0)",fmt=NUM0),
   col("has_promotion","Has Promotion","Coalesce([Promo Day/Active Promotions], 0) > 0",
       "True on 288 of 1,522 days. Slicing this model by it shows promotional days converting at 3.79% vs 3.75% and generating 1.7% LESS revenue per day - the promotion calendar has no measurable lift in this dataset."),
   col("promotion_name","Promotion Name","[Promo Day/Promotion Name]"),
   col("promotion_type","Promotion Type","[Promo Day/Promotion Type]"),
   col("promotion_channel","Promotion Channel","[Promo Day/Promotion Channel]"),
   col("max_discount_percent","Max Discount Percent","[Promo Day/Max Discount Percent]",fmt=NUM0),
   col("price_changes","Price Changes","Coalesce([Markdown Day/Price Changes], 0)",fmt=NUM0),
   col("markdowns","Markdowns","Coalesce([Markdown Day/Markdowns], 0)","Genuine price cuts effective this day.",NUM0),
   col("price_resets","Price Resets","Coalesce([Markdown Day/Price Resets], 0)",fmt=NUM0),
   col("products_marked_down","Products Marked Down","Coalesce([Markdown Day/Products Marked Down], 0)",fmt=NUM0),
 ] + [col(cid,disp,f"[Date/{disp}]") for cid,disp in DATE_ATTRS],
 "metrics":[
   {"id":"m_d_visits","name":"Web Visits","formula":"Sum([Web Visits])","format":NUM0},
   {"id":"m_d_paid_visits","name":"Paid Visits","formula":"Sum([Paid Visits])","format":NUM0},
   {"id":"m_d_spend","name":"Marketing Spend","formula":"Sum([Marketing Spend])","format":USD},
   {"id":"m_d_paid_media_spend","name":"Paid Media Spend","formula":"Sum([Paid Media Spend])","format":USD},
   {"id":"m_d_cpv","name":"Cost per Visit","formula":"[Metrics/Marketing Spend] / [Metrics/Web Visits]","format":USD},
   {"id":"m_d_web_orders","name":"Web Orders","formula":"Sum([Web Orders])","format":NUM0},
   {"id":"m_d_digital_orders","name":"Digital Orders","formula":"Sum([Digital Orders])","format":NUM0},
   {"id":"m_d_web_conv","name":"Web Conversion Rate %","formula":"[Metrics/Web Orders] / [Metrics/Web Visits]","format":PCT},
   {"id":"m_d_digital_conv","name":"Digital Conversion Rate %","formula":"[Metrics/Digital Orders] / [Metrics/Web Visits]","format":PCT},
   {"id":"m_d_gross","name":"Digital Gross Sales","formula":"Sum([Digital Gross Sales])","format":USD},
   {"id":"m_d_returns","name":"Digital Returns","formula":"Sum([Digital Returns])","format":USD},
   {"id":"m_d_net","name":"Digital Net Sales","formula":"Sum([Digital Net Sales])","format":USD},
   {"id":"m_d_return_rate","name":"Digital Return Rate %","formula":"[Metrics/Digital Returns] / [Metrics/Digital Gross Sales]","format":PCT},
   {"id":"m_d_margin","name":"Digital Gross Margin","formula":"Sum([Digital Gross Margin])","format":USD},
   {"id":"m_d_margin_pct","name":"Digital Margin %","formula":"[Metrics/Digital Gross Margin] / [Metrics/Digital Net Sales]","format":PCT},
   {"id":"m_d_rpv","name":"Revenue per Visit","formula":"[Metrics/Digital Gross Sales] / [Metrics/Web Visits]","format":USD},
   {"id":"m_d_aov","name":"Digital AOV","formula":"[Metrics/Digital Gross Sales] / [Metrics/Digital Orders]","format":USD},
   {"id":"m_d_cac","name":"Cost per Digital Order","formula":"[Metrics/Marketing Spend] / [Metrics/Digital Orders]","format":USD},
   {"id":"m_d_roas","name":"Blended ROAS","formula":"[Metrics/Digital Gross Sales] / [Metrics/Marketing Spend]","format":NUM2},
   {"id":"m_d_net_roas","name":"Blended Net ROAS","formula":"[Metrics/Digital Net Sales] / [Metrics/Marketing Spend]","format":NUM2},
   {"id":"m_d_total_gross","name":"Total Gross Sales (All Channels)","formula":"Sum([Total Gross Sales])","format":USD},
   {"id":"m_d_digital_mix","name":"Digital Mix %","formula":"[Metrics/Digital Gross Sales] / [Metrics/Total Gross Sales (All Channels)]","format":PCT},
 ],
}

# ------------------------------------------------------------------ Metric descriptions
# Keyed by metric id. All-time values quoted here were verified against the published
# model on 2026-09-13 and against the source CSVs before the build.
MET_DESC = {
 # ---- Funnel by Source (Date x Traffic Source) ----
 "m_s_visits":
   "Web sessions from this source on these days. 4,834,940 all-time across the six sources. "
   "This is the only volume measure in the model that is genuinely attributable to a source.",
 "m_s_spend":
   "Media spend booked against this source. $1,564,043.87 all-time. "
   "Always $0 for Direct and Organic Search - those are free traffic, not missing data - so a total "
   "across all six sources is a paid-media total even though it looks like a total for everything.",
 "m_s_paid_visits":
   "Sessions from the four sources that record spend (Paid Search, Social, Email, Referral). "
   "2,686,503 all-time, 55.6% of traffic.",
 "m_s_free_visits":
   "Sessions from Direct and Organic Search, which cost nothing on all 1,522 days. "
   "2,148,437 all-time - 44.4% of all traffic arrives free.",
 "m_s_cpv":
   "Spend divided by ALL visits, paid and free together. $0.3235 all-time. "
   "Diluted by construction: 44.4% of the denominator cost nothing. Use Cost per Paid Visit to judge "
   "media efficiency, and this only when you deliberately want blended cost of all traffic.",
 "m_s_paid_cpv":
   "Spend divided by visits from spending sources only. $0.5822 all-time - about 1.8x the blended figure. "
   "This is the honest media efficiency number. Per source: Paid Search $1.0041, Social $0.3976, "
   "Referral $0.2022, Email $0.0301.",
 "m_s_paid_share":
   "Share of sessions that came from a source with spend against it. 55.6% all-time. "
   "Falling share means growing free traffic, not falling media performance - read it alongside Spend.",

 # ---- Funnel Day (Date) ----
 "m_d_visits":
   "Web sessions this day, summed across all six sources. 4,834,940 all-time. "
   "The denominator for every conversion and per-visit metric on this element.",
 "m_d_paid_visits":
   "Sessions from Paid Search, Social, Email and Referral. 2,686,503 all-time (55.6%).",
 "m_d_spend":
   "Total media spend this day. $1,564,043.87 all-time - only 0.53% of digital revenue, which is why "
   "every ROAS metric here reads implausibly high. See Blended ROAS.",
 "m_d_paid_media_spend":
   "Paid Search + Social only. $1,501,129.55 all-time, 96.0% of total spend. "
   "Excludes Email and Referral, which record spend but behave as owned/earned channels.",
 "m_d_cpv":
   "Marketing Spend divided by Web Visits. $0.3235 all-time. Blended across paid and free traffic - "
   "for media efficiency use Cost per Paid Visit on Funnel by Source instead.",
 "m_d_web_orders":
   "Distinct orders on the pure-play Web channel, excluding BOPIS and BOSS. 122,713 all-time. "
   "Numerator of the published 2.54% baseline conversion rate.",
 "m_d_digital_orders":
   "Distinct Web + BOPIS + BOSS orders. 181,682 all-time. All three transact at location 9999, so all "
   "three are outcomes of the same web sessions - this, not Web Orders, is the true funnel outcome.",
 "m_d_web_conv":
   "Web Orders / Web Visits. 2.5380% all-time. This is the roadmap's published baseline, kept for "
   "continuity, but it understates the funnel by excluding BOPIS and BOSS. Prefer Digital Conversion Rate %.",
 "m_d_digital_conv":
   "Digital Orders / Web Visits. 3.7577% all-time - half again the web-only rate. "
   "The honest measure of what a web session is worth, because BOPIS and BOSS orders are placed online too. "
   "BLENDED ACROSS SOURCES: no order carries a traffic source, so this can never be split by channel.",
 "m_d_gross":
   "Web + BOPIS + BOSS gross sales for orders PLACED this day. $297,012,840.24 all-time. "
   "Ties exactly to the Retail Sales Activity model.",
 "m_d_returns":
   "Refunds against digital orders placed this day, wherever the refund later landed (cohort-dated, not "
   "refund-dated), so returns face the spend that bought the revenue. $26,766,803.85 all-time - identical "
   "to Sales Activity; only the day-by-day distribution differs.",
 "m_d_net":
   "Digital Gross Sales less cohort returns. $270,246,036.39 all-time.",
 "m_d_return_rate":
   "Digital Returns / Digital Gross Sales. 9.01% all-time, against 5.44% company-wide and 4.23% in-store. "
   "Digital returns run more than 2x the in-store rate - the single largest cost of digital growth.",
 "m_d_margin":
   "Digital Net Sales less digital cost of goods. $52,668,135.12 all-time. Struck AFTER returns, not before - "
   "the pre-returns figure is $57.9M, so returns cost roughly $5.2M of digital margin.",
 "m_d_margin_pct":
   "Digital Gross Margin / Digital Net Sales. 19.49% all-time.",
 "m_d_rpv":
   "Digital Gross Sales / Web Visits. $61.43 all-time. The clearest single measure of session value, and "
   "the right yardstick for judging whether a traffic push paid off. Blended across sources by construction.",
 "m_d_aov":
   "Digital Gross Sales / Digital Orders. $1,634.80 all-time, effectively identical to the in-store basket "
   "($1,645.25) - digital in this business is not a lower-value channel, only a higher-returning one.",
 "m_d_cac":
   "Marketing Spend / Digital Orders. $8.61 all-time. An acquisition cost only in the loosest sense: "
   "44.4% of traffic is free and no order is attributed to a source, so this is cost per order across all "
   "demand, not cost of a media-acquired order.",
 "m_d_roas":
   "Digital Gross Sales / Marketing Spend. 189.90x all-time. DO NOT PLAN AGAINST THIS. Recorded spend is "
   "0.53% of digital revenue, a property of the dataset rather than a business result, and the revenue is "
   "blended across paid and free traffic. Retained for completeness; use Cost per Visit and Revenue per "
   "Visit for real decisions.",
 "m_d_net_roas":
   "Digital Net Sales / Marketing Spend. 172.79x all-time. Same caveat as Blended ROAS - it is the "
   "17-point gap against the gross figure, not the level, that carries the return-rate signal.",
 "m_d_total_gross":
   "Gross sales across ALL channels including in-store. $1,178,971,663.73 all-time, tying exactly to the "
   "Retail Sales Activity model. Present only as the denominator for Digital Mix % - this model has no "
   "traffic or funnel data for in-store demand.",
 "m_d_digital_mix":
   "Digital Gross Sales / Total Gross Sales (All Channels). 25.19% all-time. "
   "Rising mix is the mechanism behind the company return rate worsening while every individual channel's "
   "return rate improves - see the Retail Omnichannel Fulfillment model.",
}

for _el in (funnel_source, funnel_day):
    for _m in _el["metrics"]:
        _d = MET_DESC.get(_m["id"])
        if _d is None:
            raise SystemExit(f"metric without description: {_el['id']}.{_m['id']}")
        _m["description"] = _d


spec = {
 "name":"Retail Marketing & Digital Funnel",
 "description":"Date x Traffic Source acquisition and daily digital conversion. The only view of demand before it becomes a transaction. KNOWN LIMIT, BY DESIGN: no order in this dataset carries a traffic source, so per-source ROAS is not derivable - spend and visits are modelled per source, revenue only per day and explicitly blended. Sources conformed dimensions from the Retail Sales Activity model.",
 "pages":[
   {"id":"page_sources","name":"Sources","elements":sources},
   {"id":"page_dims","name":"Conformed Dimensions","elements":dims},
   {"id":"page_build","name":"Daily Build","elements":[web_daily,digital_daily,promo_day,markdown_day]},
   {"id":"page_funnel","name":"Marketing Funnel","elements":[funnel_source,funnel_day]},
 ],
}

print(json.dumps(spec, indent=2))
