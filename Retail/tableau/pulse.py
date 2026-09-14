"""Tableau Pulse metric definition API (create / list / delete)."""
import json

import requests

import tabapi

BASE = "/api/-/pulse"


def _url(path):
    return f"{tabapi.SERVER}{BASE}{path}"


def list_definitions(token, view="DEFINITION_VIEW_BASIC"):
    out, params = [], {"view": view, "page_size": 100}
    while True:
        r = requests.get(_url("/definitions"), headers=tabapi.hdr(token), params=params)
        r.raise_for_status()
        body = r.json()
        out.extend(body.get("definitions", []))
        token_next = body.get("next_page_token")
        if not token_next:
            return out
        params["page_token"] = token_next


def create_definition(token, body):
    r = requests.post(_url("/definitions"),
                      headers={**tabapi.hdr(token), "Content-Type": "application/json"},
                      data=json.dumps(body))
    return r


def update_definition(token, definition_id, body):
    r = requests.put(_url(f"/definitions/{definition_id}"),
                     headers={**tabapi.hdr(token), "Content-Type": "application/json"},
                     data=json.dumps(body))
    return r


def delete_definition(token, definition_id):
    return requests.delete(_url(f"/definitions/{definition_id}"), headers=tabapi.hdr(token))


def create_metric(token, definition_id, specification=None):
    """A definition needs at least one metric (the unfiltered default) to be usable."""
    body = {"definition_id": definition_id,
            "specification": specification or {"filters": [],
                                               "measurement_period": {
                                                   "granularity": "GRANULARITY_BY_MONTH",
                                                   "range": "RANGE_CURRENT_PARTIAL"},
                                               "comparison": {
                                                   "comparison": "TIME_COMPARISON_PREVIOUS_PERIOD"}}}
    return requests.post(_url("/metrics"),
                         headers={**tabapi.hdr(token), "Content-Type": "application/json"},
                         data=json.dumps(body))
