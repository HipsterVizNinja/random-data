"""Ask Pulse to compute a metric's current value (the 'ban' insight bundle)."""
import json

import requests

import tabapi

NIL = "00000000-0000-0000-0000-000000000000"


def ban(token, definition_spec, extension_options, representation_options,
        granularity="GRANULARITY_BY_MONTH", rng="RANGE_LAST_COMPLETE", name="metric"):
    body = {"bundle_request": {"version": 1,
        "options": {"output_format": "OUTPUT_FORMAT_TEXT", "time_zone": "UTC",
                    "language": "LANGUAGE_EN_US", "locale": "LOCALE_EN_US"},
        "input": {"metadata": {"name": name, "metric_id": NIL, "definition_id": NIL},
                  "metric": {"definition": definition_spec,
                             "metric_specification": {
                                 "filters": [],
                                 "measurement_period": {"granularity": granularity, "range": rng},
                                 "comparison": {"comparison": "TIME_COMPARISON_PREVIOUS_PERIOD"}},
                             "extension_options": extension_options,
                             "representation_options": representation_options,
                             "insights_options": {"show_insights": True, "settings": []}}}}}
    r = requests.post(f"{tabapi.SERVER}/api/-/pulse/insights/ban",
                      headers={**tabapi.hdr(token), "Content-Type": "application/json"},
                      data=json.dumps(body))
    try:
        insight = r.json()["bundle_response"]["result"]["insight_groups"][0]["insights"][0]
    except Exception:
        raise RuntimeError(f"unparsable bundle response {r.status_code}: {r.text[:200]}")
    if "error" in insight:
        raise RuntimeError(f"Pulse could not compute the value: {insight['error']}")
    facts = insight["result"]["facts"]
    value = facts["target_period_value"]
    return (None if "raw" not in value else value["raw"],
            facts["target_time_period"]["range"])
