"""
Generates server.json per the official MCP Registry schema.
Schema: https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json
Submit via: mcp-publisher publish (https://github.com/modelcontextprotocol/registry)
"""

import json


def generate(server: dict) -> dict:
    server_id = server["id"]
    # Registry name format: io.github.<owner>/<repo> or reverse-domain
    registry_name = f"io.norric.io/{server_id}"

    payload = {
        "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
        "name": registry_name,
        "title": server["title"],
        "description": server["description_short"],
        "version": server.get("version", "1.0.0"),
        "homepage": server["homepage"],
        "repository": {"type": "git", "url": server["github_url"]},
        "remotes": [
            {
                "type": server["transport"],
                "url": server["server_url"],
                "authorization": {
                    "type": "Bearer",
                    "description": (
                        "Get a trial key at norric.io/api. "
                        "Pass as: Authorization: Bearer nrk_your_api_key"
                    ),
                },
            }
        ],
        "categories": server.get("categories", []),
        "tags": server.get("tags", []),
    }
    return payload


def render(server: dict) -> str:
    return json.dumps(generate(server), indent=2)
