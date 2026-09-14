"""Build the viz_state_specification Pulse uses for metrics whose measure is an
aggregate calculation (ratios), which basic_specification cannot express."""
import json

CALC = "Calculation_1"


def viz_state(formula, time_field, proxy="sqlproxy.retailsalesactivity",
              caption="Metric"):
    columns_to_add = [
        {"name": {"component": [CALC]},
         "fieldType": "FIELD_TYPE_CONTINUOUS",
         "vtagg": "VISUAL_TOTAL_AGGREGATION_VTAGG_DEFAULT",
         "pivotStrategy": "FIELD_PIVOT_STRATEGY_PIVOT_ON_KEY",
         "role": "FIELD_ROLE_MEASURE",
         "dataType": "DATA_TYPE_REAL_TYPE",
         "calc": {"formula": formula},
         "fiscalYearStart": "FISCAL_YEAR_START_JANUARY"},
        {"name": {"component": [f"usr:{CALC}:qk"]},
         "fieldType": "FIELD_TYPE_CONTINUOUS",
         "vtagg": "VISUAL_TOTAL_AGGREGATION_VTAGG_DEFAULT",
         "pivotStrategy": "FIELD_PIVOT_STRATEGY_PIVOT_ON_KEY",
         "role": "FIELD_ROLE_MEASURE",
         "dataType": "DATA_TYPE_REAL_TYPE",
         "instance": {"baseColumn": {"component": [CALC]}, "agg": "AGG_TYPE_USER"}},
        {"name": {"component": [f"yr:{time_field}:ok"]},
         "fieldType": "FIELD_TYPE_ORDINAL",
         "vtagg": "VISUAL_TOTAL_AGGREGATION_VTAGG_DEFAULT",
         "pivotStrategy": "FIELD_PIVOT_STRATEGY_PIVOT_ON_KEY",
         "role": "FIELD_ROLE_DIMENSION",
         "dataType": "DATA_TYPE_INTEGER_TYPE",
         "instance": {"baseColumn": {"component": [time_field]}, "agg": "AGG_TYPE_YEAR"}},
    ]
    state = {
        "vizState": {
            "rows": [{"fieldOnShelf": {"component": [f"usr:{CALC}:qk"]},
                      "fieldCaption": f"AGG({caption})"}],
            "columns": [{"fieldOnShelf": {"component": [f"yr:{time_field}:ok"]},
                         "fieldCaption": f"YEAR({time_field})"}],
            "filters": [],
            "defaultEncoding": {}},
        "dataModel": {
            "dataSource": [{
                "columnsToAdd": columns_to_add,
                "contextSpecification": {"sampleCount": -1,
                                         "sampleUnits": "SORT_UNITS_RECORDS",
                                         "normalization": "EXTRACT_NORMALIZATION_DENORMALIZED"},
                "name": proxy,
                "displayMemberAliases": True}],
            "filters": [],
            "levelsAndMembers": []}}
    return json.dumps(state)
