#!/usr/bin/env python3
"""Create the Retail Sales Activity model's 18 metrics as Tableau Pulse metrics.

Every definition points at the published "Retail Sales Activity" data source and
carries the same description the metric has in Sigma, so a Pulse follower reads
exactly what a Sigma user reads.

Two kinds of definition are used, because Pulse's basic specification can only
express one field under one aggregation (with filters):

  BASIC     the eight additive metrics -- a row-level field, an aggregation, and
            for the sale-only ones a filter on Activity Type.
  VIZ_STATE the ten that are ratios or re-signed sums. Pulse lists the data
            source's aggregate calculated fields and will even accept one in a
            basic specification, but it then fails to compute the value
            (error 400928), so these carry the formula in a viz state instead --
            the same shape Pulse's own UI writes for a calculation-backed metric.

The data stops on 2025-10-19, so every definition carries an offset_from_today
that moves Pulse's "today" to the end of the data. That offset is a fixed number
of days, so re-run this script periodically (or before a demo) to refresh it.

Usage:
    python3 tableau/build_pulse_metrics.py            # show the plan
    python3 tableau/build_pulse_metrics.py --publish  # create or update, then verify
    python3 tableau/build_pulse_metrics.py --verify   # verify what is published
    python3 tableau/build_pulse_metrics.py --delete   # remove them again
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pulse
import pulse_bundle
import tabapi
import vds
import vizstate

from describe_sales_activity_metrics import METRIC_DESCRIPTIONS

DATASOURCE = "242c1eb7-254a-42cc-a819-51c8f77b0b49"   # Retail Sales Activity
TIME_FIELD = "Activity Date"

CURRENCY, NUMBER, PERCENT = ("NUMBER_FORMAT_TYPE_CURRENCY", "NUMBER_FORMAT_TYPE_NUMBER",
                             "NUMBER_FORMAT_TYPE_PERCENT")
UP, DOWN = "SENTIMENT_TYPE_UP_IS_GOOD", "SENTIMENT_TYPE_DOWN_IS_GOOD"

DIMENSIONS = ["Store Region", "Store Area", "Store State", "Store Name", "Store Type",
              "Product Type", "Product Family", "Product Line", "Channel Type",
              "Purchase Method", "Cust Region", "Loyalty Tier", "Age Group", "Tier"]
GRANULARITIES = ["GRANULARITY_BY_DAY", "GRANULARITY_BY_WEEK", "GRANULARITY_BY_MONTH",
                 "GRANULARITY_BY_QUARTER", "GRANULARITY_BY_YEAR"]

SALE_ONLY = [{"field": "Activity Type", "operator": "OPERATOR_EQUAL",
              "categorical_values": [{"string_value": "Sale"}]}]

# Sale-line order and customer counts, spelled the way the model spells them.
SALE_ORDERS = 'COUNTD(IIF([Activity Type] = "Sale", [Order Number], NULL))'
SALE_CUSTOMERS = 'COUNTD(IIF([Activity Type] = "Sale", [Cust Key], NULL))'
GROSS_SALES = 'SUM(IIF([Activity Type] = "Sale", [Amount], 0))'
RETURNS = 'SUM(IIF([Activity Type] = "Return", -[Amount], 0))'


class Metric:
    def __init__(self, name, metric_id, fmt, sentiment, field=None, aggregation=None,
                 filters=(), formula=None, units=None):
        self.name = name
        self.description = METRIC_DESCRIPTIONS[("sales_activity", metric_id)]
        self.fmt = fmt
        self.sentiment = sentiment
        self.field = field
        self.aggregation = aggregation
        self.filters = list(filters)
        self.formula = formula
        self.units = units or ("", "")

    @property
    def kind(self):
        return "viz_state" if self.formula else "basic"

    def specification(self):
        if self.formula:
            spec = {"viz_state_specification": {
                "viz_state_string": vizstate.viz_state(self.formula, TIME_FIELD,
                                                       caption=self.name)}}
        else:
            spec = {"basic_specification": {
                "measure": {"field": self.field, "aggregation": self.aggregation},
                "time_dimension": {"field": TIME_FIELD},
                "filters": self.filters}}
        return {"datasource": {"id": DATASOURCE}, **spec, "is_running_total": False}

    def extension_options(self, offset):
        return {"allowed_dimensions": DIMENSIONS,
                "allowed_granularities": GRANULARITIES,
                "offset_from_today": offset}

    def representation_options(self):
        return {"type": self.fmt,
                "number_units": {"singular_noun": self.units[0], "plural_noun": self.units[1]},
                "sentiment_type": self.sentiment,
                "row_level_id_field": {"identifier_col": "Order Number"},
                "row_level_entity_names": {"entity_name_singular": "order line",
                                           "entity_name_plural": "order lines"},
                "row_level_name_field": {"name_col": "Order Number"},
                "currency_code": "CURRENCY_CODE_USD"}

    def body(self, offset):
        return {"name": self.name,
                "description": self.description,
                "specification": self.specification(),
                "extension_options": self.extension_options(offset),
                "representation_options": self.representation_options(),
                "insights_options": {"show_insights": True, "settings": []},
                "comparisons": {"comparisons": [
                    {"compare_config": {"comparison": "TIME_COMPARISON_PREVIOUS_PERIOD"}, "index": 0},
                    {"compare_config": {"comparison": "TIME_COMPARISON_YEAR_AGO_PERIOD"}, "index": 1}]}}


METRICS = [
    # --- additive: a field, an aggregation, and for sale-only metrics a filter --
    Metric("Net Sales", "m_net_sales", CURRENCY, UP, field="Amount",
           aggregation="AGGREGATION_SUM"),
    Metric("Gross Sales", "m_gross_sales", CURRENCY, UP, field="Amount",
           aggregation="AGGREGATION_SUM", filters=SALE_ONLY),
    Metric("Net Cost", "m_net_cost", CURRENCY, DOWN, field="Cost",
           aggregation="AGGREGATION_SUM"),
    Metric("Net Gross Margin", "m_net_gross_margin", CURRENCY, UP, field="Gross Margin",
           aggregation="AGGREGATION_SUM"),
    Metric("Net Units", "m_net_units", NUMBER, UP, field="Quantity",
           aggregation="AGGREGATION_SUM", units=("unit", "units")),
    Metric("Gross Units", "m_gross_units", NUMBER, UP, field="Quantity",
           aggregation="AGGREGATION_SUM", filters=SALE_ONLY, units=("unit", "units")),
    Metric("Order Count", "m_order_count", NUMBER, UP, field="Order Number",
           aggregation="AGGREGATION_COUNT_DISTINCT", filters=SALE_ONLY,
           units=("order", "orders")),
    Metric("Customer Count", "m_customer_count", NUMBER, UP, field="Cust Key",
           aggregation="AGGREGATION_COUNT_DISTINCT", filters=SALE_ONLY,
           units=("customer", "customers")),
    # --- ratios and re-signed sums: the model's formula, carried in a viz state -
    Metric("Returns", "m_returns", CURRENCY, DOWN, formula=RETURNS),
    Metric("Return Rate %", "m_return_rate", PERCENT, DOWN,
           formula=f"{RETURNS} / {GROSS_SALES}"),
    Metric("Net Margin %", "m_net_margin", PERCENT, UP,
           formula="(SUM([Amount]) - SUM([Cost])) / SUM([Amount])"),
    Metric("AOV", "m_aov", CURRENCY, UP, formula=f"SUM([Amount]) / {SALE_ORDERS}"),
    Metric("Gross AOV", "m_gross_aov", CURRENCY, UP,
           formula=f"{GROSS_SALES} / {SALE_ORDERS}"),
    Metric("UPT", "m_upt", NUMBER, UP, formula=f"SUM([Quantity]) / {SALE_ORDERS}"),
    Metric("Frequency", "m_frequency", NUMBER, UP,
           formula=f"{SALE_ORDERS} / {SALE_CUSTOMERS}"),
    Metric("Spend per Customer", "m_spend_per_customer", CURRENCY, UP,
           formula=f"SUM([Amount]) / {SALE_CUSTOMERS}"),
    Metric("AUR", "m_aur", CURRENCY, UP, formula="SUM([Amount]) / SUM([Quantity])"),
    Metric("AUC", "m_auc", CURRENCY, DOWN, formula="SUM([Cost]) / SUM([Quantity])"),
]


def data_offset(token):
    """Days between today and the last day of data, so Pulse's 'today' lands there."""
    rows = vds.query(token, DATASOURCE,
                     {"fields": [{"fieldCaption": TIME_FIELD, "function": "MAX",
                                  "fieldAlias": "last"}]})
    last = dt.date.fromisoformat(rows[0]["last"][:10])
    return (dt.date.today() - last).days, last


def publish(token, offset):
    existing = {d["metadata"]["name"]: d["metadata"]["id"]
                for d in pulse.list_definitions(token)}
    for metric in METRICS:
        body = metric.body(offset)
        if metric.name in existing:
            r = pulse.update_definition(token, existing[metric.name], body)
            action, definition_id = "updated", existing[metric.name]
        else:
            r = pulse.create_definition(token, body)
            definition_id = (r.json().get("definition", {}).get("metadata", {}).get("id")
                             if r.status_code < 300 else None)
            action = "created"
        if r.status_code >= 300:
            print(f"  {metric.name:<20} {action} FAILED {r.status_code} {r.text[:120]}")
            continue
        # Creating a definition already creates its default (unfiltered) metric;
        # asking for another one comes back 409, which is not a problem.
        m = pulse.create_metric(token, definition_id)
        note = ("" if m.status_code < 300 else
                "" if m.status_code == 409 else f" (default metric {m.status_code})")
        print(f"  {metric.name:<20} {action} {definition_id}{note}")


def verify(token, offset, last_day):
    """Compare every Pulse value against the data source itself for the same month."""
    month = (last_day.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
    end = last_day.replace(day=1) - dt.timedelta(days=1)
    rows = vds.query(token, DATASOURCE, {
        "fields": [{"fieldCaption": m.name} for m in METRICS],
        "filters": [{"field": {"fieldCaption": TIME_FIELD}, "filterType": "QUANTITATIVE_DATE",
                     "quantitativeFilterType": "RANGE", "minDate": month.isoformat(),
                     "maxDate": end.isoformat()}]})
    expected = rows[0]
    print(f"  verifying against the data source for {month:%b %Y}")
    failures = 0
    for metric in METRICS:
        try:
            value, period = pulse_bundle.ban(token, metric.specification(),
                                             metric.extension_options(offset),
                                             metric.representation_options(),
                                             name=metric.name)
        except RuntimeError as exc:
            print(f"  {metric.name:<20} FAILED {exc}")
            failures += 1
            continue
        want = expected[metric.name]
        ok = value is not None and abs(value - want) <= max(abs(want) * 1e-9, 5e-7)
        failures += 0 if ok else 1
        print(f"  {metric.name:<20} {metric.kind:<10} {period}  pulse={value:>18,.4f}  "
              f"model={want:>18,.4f}  {'ok' if ok else 'MISMATCH'}")
    return failures


def delete(token):
    existing = {d["metadata"]["name"]: d["metadata"]["id"]
                for d in pulse.list_definitions(token)}
    for metric in METRICS:
        if metric.name in existing:
            r = pulse.delete_definition(token, existing[metric.name])
            print(f"  {metric.name:<20} deleted {r.status_code}")


def main():
    token, _, _ = tabapi.signin()
    offset, last_day = data_offset(token)
    print(f"data ends {last_day}; offset_from_today = {offset} days")
    if "--delete" in sys.argv:
        delete(token)
        return
    if "--publish" in sys.argv:
        print("publishing definitions ...")
        publish(token, offset)
    if "--publish" in sys.argv or "--verify" in sys.argv:
        print("verifying ...")
        failures = verify(token, offset, last_day)
        print("all 18 metrics match the model" if not failures
              else f"{failures} metric(s) did not match")
        return
    for metric in METRICS:
        detail = (metric.formula if metric.formula
                  else f"{metric.aggregation.replace('AGGREGATION_', '')}([{metric.field}])"
                       + (" where Activity Type = Sale" if metric.filters else ""))
        print(f"  {metric.name:<20} {metric.kind:<10} {detail}")


if __name__ == "__main__":
    main()
