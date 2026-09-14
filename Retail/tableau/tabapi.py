"""Minimal Tableau Cloud REST client.

Credentials are not stored here: they are read at call time from the `tableau`
MCP server entry in ~/.claude.json, which already holds SERVER, SITE_NAME and
the personal access token.
"""
import json
import os

import requests

API = "3.24"


def _mcp_env():
    with open(os.path.expanduser("~/.claude.json")) as fh:
        doc = json.load(fh)
    found = {}

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "mcpServers" and isinstance(value, dict) and "tableau" in value:
                    found.update(value["tableau"].get("env", {}))
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(doc)
    if not found:
        raise SystemExit("no tableau MCP server entry found in ~/.claude.json")
    return found


ENV = _mcp_env()
SERVER = ENV["SERVER"].rstrip("/")
SITE = ENV["SITE_NAME"]


def signin():
    body = {"credentials": {"personalAccessTokenName": ENV["PAT_NAME"],
                            "personalAccessTokenSecret": ENV["PAT_VALUE"],
                            "site": {"contentUrl": SITE}}}
    r = requests.post(f"{SERVER}/api/{API}/auth/signin", json=body,
                      headers={"Accept": "application/json"})
    r.raise_for_status()
    c = r.json()["credentials"]
    return c["token"], c["site"]["id"], c["user"]["id"]


def hdr(token, accept="application/json"):
    return {"X-Tableau-Auth": token, "Accept": accept}


if __name__ == "__main__":
    token, site_id, user_id = signin()
    print("signed in to", SITE, "site_id", site_id, "user_id", user_id)
