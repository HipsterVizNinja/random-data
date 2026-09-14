"""Rebuild the Sigma Retail Sales Activity model's tables from the source CSVs.

Mirrors the Sigma element chain exactly: pos_agg / ret_agg -> sale_lines +
return_lines -> activity_base, plus the six conformed dimensions' column picks.
"""
import numpy as np
import pandas as pd

SRC = "/Users/seanmiller/Documents/GitHub/random-data/Retail"


def build_activity():
    pos = pd.read_csv(f"{SRC}/F_POINT_OF_SALE_master.csv")
    pos_agg = (pos.groupby(["Order Number", "Product Key"], as_index=False)
                  .agg({"Sales Quantity": "sum", "Sales Amount": "sum",
                        "Cost Amount": "sum"}))
    del pos

    ret = pd.read_csv(f"{SRC}/F_RETURNS.csv", parse_dates=["Return Date"])
    ret_agg = (ret.groupby(["Order Number", "Product Key"], as_index=False)
                  .agg({"Return Date": "min", "Return Quantity": "sum",
                        "Refund Amount": "sum", "Return Reason": "max",
                        "Restocked": "max"}))
    del ret

    sales = pd.read_csv(f"{SRC}/F_SALES.csv", parse_dates=["Date", "Date Key"])
    order_attrs = ["Order Number", "Date Key", "Date", "Store Key", "Cust Key",
                   "Salesperson Key", "Channel Type", "Transaction Type",
                   "Purchase Method"]
    sales = sales[order_attrs]

    # --- sale lines: pos_agg LEFT JOIN F_SALES on Order Number -------------
    s = pos_agg.merge(sales, on="Order Number", how="left")
    sale_lines = pd.DataFrame({
        "Activity Type": "Sale",
        "Activity Date": s["Date Key"],
        "Sale Date": s["Date Key"],
        "Sale Timestamp": s["Date"],
        "Order Number": s["Order Number"],
        "Product Key": s["Product Key"],
        "Store Key": s["Store Key"],
        "Cust Key": s["Cust Key"],
        "Salesperson Key": s["Salesperson Key"],
        "Channel Type": s["Channel Type"],
        "Transaction Type": s["Transaction Type"],
        "Purchase Method": s["Purchase Method"],
        "Quantity": s["Sales Quantity"],
        "Amount": s["Sales Amount"],
        "Cost": s["Cost Amount"],
        "Return Reason": pd.Series([None] * len(s), dtype=object),
        "Restocked": pd.Series([None] * len(s), dtype=object),
    })
    del s

    # --- return lines: ret_agg LEFT JOIN F_SALES, LEFT JOIN pos_agg -------
    r = (ret_agg.merge(sales, on="Order Number", how="left")
                .merge(pos_agg[["Order Number", "Product Key", "Sales Quantity",
                                "Cost Amount"]],
                       on=["Order Number", "Product Key"], how="left"))
    pos_qty, pos_cost = r["Sales Quantity"], r["Cost Amount"]
    # Sigma: If(pos qty = 0, 0, -ret qty * pos cost / pos qty); an unmatched
    # sale line leaves the comparison null, so the cost stays null.
    unit_cost = np.where(pos_qty.notna() & (pos_qty == 0), 0.0,
                         -r["Return Quantity"] * pos_cost / pos_qty.replace(0, np.nan))
    return_lines = pd.DataFrame({
        "Activity Type": "Return",
        "Activity Date": r["Return Date"],
        "Sale Date": r["Date Key"],
        "Sale Timestamp": r["Date"],
        "Order Number": r["Order Number"],
        "Product Key": r["Product Key"],
        "Store Key": r["Store Key"],
        "Cust Key": r["Cust Key"],
        "Salesperson Key": r["Salesperson Key"],
        "Channel Type": r["Channel Type"],
        "Transaction Type": r["Transaction Type"],
        "Purchase Method": r["Purchase Method"],
        "Quantity": -r["Return Quantity"],
        "Amount": -r["Refund Amount"],
        "Cost": unit_cost,
        "Return Reason": r["Return Reason"],
        "Restocked": r["Restocked"],
    })
    del r, ret_agg, pos_agg, sales

    activity = pd.concat([sale_lines, return_lines], ignore_index=True)
    activity["Gross Margin"] = activity["Amount"] - activity["Cost"]
    for key in ("Order Number", "Product Key", "Store Key", "Cust Key",
                "Salesperson Key", "Quantity"):
        activity[key] = activity[key].astype("Int64")
    return activity


DIM_DATE_COLS = [
    "Date Key", "Day of Week Name", "Day of Week Number", "Day of Month",
    "Day of Year", "Week Start Date", "Is Weekend", "Calendar Year",
    "Calendar Month", "Calendar Month Name", "Calendar Quarter", "Fiscal Year",
    "Fiscal Quarter", "Fiscal Period", "Fiscal Period Name",
    "Fiscal Week of Year", "Fiscal Week of Period", "Fiscal Year Day Number",
    "Is 53rd Week", "Fiscal Season", "Fiscal Year Start Date",
    "Fiscal Year End Date", "Fiscal Quarter Start Date", "Fiscal Quarter End Date",
    "Fiscal Period Start Date", "Fiscal Period End Date",
    "Fiscal Season Start Date", "Fiscal Season End Date",
    "Fiscal Quarter Day Number", "Fiscal Period Day Number",
    "Fiscal Season Day Number", "Prior Year Date",
]
# "Date Key" is a date too, it just does not end in "Date".
DATE_DATE_COLS = ["Date Key"] + [c for c in DIM_DATE_COLS if c.endswith("Date")]

DIM_PRODUCT_COLS = ["Product Key", "Product Name", "Product Type", "Product Family",
                    "Product Line", "Product Group", "Sku Number", "Price",
                    "Product Status", "Vendor Key"]

DIM_STORE_COLS = ["Store Key", "Store Name", "Store Address", "Store City",
                  "Store State", "Store Zip Code", "Store County", "Store Region",
                  "Store Area", "Store Type", "Store Size", "Store Open Date",
                  "Last Layout Update", "Selling Square Footage",
                  "Total Square Footage", "Number of Employees", "Online Ordering",
                  "Latitude", "Longitude", "Weekday Open Hour", "Weekday Close Hour",
                  "Sunday Open Hour", "Sunday Close Hour"]

DIM_CUSTOMER_COLS = ["Cust Key", "Cust Name", "Cust Address", "Cust City",
                     "Cust State", "Cust Zip Code", "Cust County", "Cust Region",
                     "Cust Since", "Cust Type", "Cust Gender", "Cust Age",
                     "Age Group", "Civil Status", "Loyalty Program",
                     "LOYALTY_TIER", "DOWNLOADED_APP"]

DIM_SALESPERSON_COLS = ["Salesperson Key", "Salesperson Name", "Store Key", "Tier",
                        "Hire Date", "Employment Status", "Termination Date",
                        "Tenure Years", "Commission Rate"]


def _zip(series):
    """Source zips arrive as floats; render them as 5-character strings."""
    return series.map(lambda v: "" if pd.isna(v) else f"{int(float(v)):05d}")


def build_dims():
    date = pd.read_csv(f"{SRC}/D_DATE.csv", parse_dates=DATE_DATE_COLS)[DIM_DATE_COLS]

    product = pd.read_csv(f"{SRC}/D_PRODUCT.csv")[DIM_PRODUCT_COLS]
    product["Product Key"] = product["Product Key"].astype("Int64")
    product["Vendor Key"] = product["Vendor Key"].astype("Int64")

    store = pd.read_csv(f"{SRC}/D_STORE.csv", parse_dates=["Store Open Date",
                                                           "Last Layout Update"])
    store = store[DIM_STORE_COLS].copy()
    store["Store Zip Code"] = _zip(store["Store Zip Code"])
    for key in ("Store Key", "Number of Employees", "Selling Square Footage",
                "Total Square Footage", "Weekday Open Hour", "Weekday Close Hour",
                "Sunday Open Hour", "Sunday Close Hour"):
        store[key] = store[key].astype("Int64")

    customer = pd.read_csv(f"{SRC}/D_CUSTOMER.csv", parse_dates=["Cust Since"])
    customer = customer[DIM_CUSTOMER_COLS].copy()
    customer = customer.rename(columns={"LOYALTY_TIER": "Loyalty Tier",
                                        "DOWNLOADED_APP": "Downloaded App"})
    customer["Cust Zip Code"] = _zip(customer["Cust Zip Code"])
    customer["Cust Key"] = customer["Cust Key"].astype("Int64")
    customer["Cust Age"] = customer["Cust Age"].astype("Int64")
    customer["Loyalty Program"] = customer["Loyalty Program"].astype("Int64")
    customer["Downloaded App"] = customer["Downloaded App"].astype("Int64")

    sp = pd.read_csv(f"{SRC}/D_SALESPERSON.csv",
                     parse_dates=["Hire Date", "Termination Date"])[DIM_SALESPERSON_COLS]
    sp["Salesperson Key"] = sp["Salesperson Key"].astype("Int64")
    sp["Store Key"] = sp["Store Key"].astype("Int64")

    return {"Date": date, "Product": product, "Store": store,
            "Customer": customer, "Salesperson": sp}


if __name__ == "__main__":
    act = build_activity()
    print("activity rows:", len(act))
    sale = act["Activity Type"] == "Sale"
    ret = act["Activity Type"] == "Return"
    checks = {
        "Gross Sales": act.loc[sale, "Amount"].sum(),
        "Returns": -act.loc[ret, "Amount"].sum(),
        "Net Sales": act["Amount"].sum(),
        "Gross Units": act.loc[sale, "Quantity"].sum(),
        "Net Units": act["Quantity"].sum(),
        "Net Cost": act["Cost"].sum(),
        "Net Gross Margin": act["Amount"].sum() - act["Cost"].sum(),
        "Order Count": act.loc[sale, "Order Number"].nunique(),
        "Customer Count": act.loc[sale, "Cust Key"].nunique(),
    }
    expected = {"Gross Sales": 1178971663.73, "Returns": 64116011.81,
                "Net Sales": 1114855651.92, "Gross Units": 9045207,
                "Net Units": 8584150, "Net Cost": 895884767.32,
                "Net Gross Margin": 218970884.60, "Order Count": 717747,
                "Customer Count": 4867}
    for k, v in checks.items():
        e = expected[k]
        ok = abs(float(v) - e) <= max(0.05, abs(e) * 1e-9)
        print(f"  {k:<18} {float(v):>20,.2f}   expected {e:>20,.2f}   {'OK' if ok else 'MISMATCH'}")
    for name, df in build_dims().items():
        print(f"dim {name:<12} {len(df):>6} rows, {len(df.columns)} cols")
