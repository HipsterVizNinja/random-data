"""Query a published data source through the VizQL Data Service."""
import requests

import tabapi


def query(token, luid, query_body):
    r = requests.post(f"{tabapi.SERVER}/api/v1/vizql-data-service/query-datasource",
                      headers={**tabapi.hdr(token), "Content-Type": "application/json"},
                      json={"datasource": {"datasourceLuid": luid}, "query": query_body})
    r.raise_for_status()
    return r.json()["data"]
