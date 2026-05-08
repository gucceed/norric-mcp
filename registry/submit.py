"""
Multi-registry MCP submission CLI.

Usage:
    python -m registry.submit <server_id>
    python -m registry.submit norric-mcp
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

# Ensure repo root is on path when run as module
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from registry import load_server, SUBMISSIONS_JSON, REGISTRY_DIR
from registry.generators import (
    official_mcp_registry,
    github_mcp_registry,
    mcp_so,
    pulsemcp,
)

REGISTRIES = {
    "official_mcp_registry": {
        "type": "github",
        "label": "Official MCP Registry (registry.modelcontextprotocol.io)",
    },
    "github_mcp_registry": {
        "type": "github",
        "label": "GitHub Awesome MCP Servers (punkpeye/awesome-mcp-servers)",
    },
    "mcp_so": {
        "type": "form",
        "label": "mcp.so (github.com/chatmcp/mcpso/issues/1)",
    },
    "pulsemcp": {
        "type": "form",
        "label": "PulseMCP (pulsemcp.com/submit)",
    },
}


def load_ledger() -> dict:
    if SUBMISSIONS_JSON.exists():
        return json.loads(SUBMISSIONS_JSON.read_text())
    return {}


def save_ledger(ledger: dict) -> None:
    SUBMISSIONS_JSON.write_text(json.dumps(ledger, indent=2))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def submit_official_mcp_registry(server: dict, ledger: dict) -> dict:
    """Generate server.json and attempt mcp-publisher submission."""
    server_json = official_mcp_registry.generate(server)
    server_json_path = REGISTRY_DIR / f"{server['id']}_server.json"
    server_json_path.write_text(json.dumps(server_json, indent=2))

    # Try mcp-publisher
    try:
        result = subprocess.run(
            ["mcp-publisher", "publish", "--file", str(server_json_path)],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            pr_url = result.stdout.strip().split()[-1] if result.stdout.strip() else "submitted"
            return {"status": "submitted", "pr_url": pr_url, "submitted_at": now_iso()}
    except FileNotFoundError:
        pass

    # mcp-publisher not available — record the generated file path
    return {
        "status": "pending_manual",
        "note": (
            f"server.json written to {server_json_path}. "
            "Install mcp-publisher and run: "
            f"mcp-publisher publish --file {server_json_path}"
        ),
        "server_json_path": str(server_json_path),
        "submitted_at": None,
    }


def submit_github_mcp_registry(server: dict, ledger: dict) -> dict:
    """Fork punkpeye/awesome-mcp-servers and open a PR."""
    existing = ledger.get(server["id"], {}).get("github_mcp_registry", {})
    if existing.get("pr_url"):
        return {**existing, "status": "already_submitted"}

    result = github_mcp_registry.submit(server)
    if result.get("error") == "already_submitted":
        return {"status": "already_submitted", "pr_url": None, "submitted_at": now_iso()}
    if result.get("error"):
        return {"status": "error", "error": result["error"], "submitted_at": now_iso()}
    return {"status": "submitted", "pr_url": result["pr_url"], "submitted_at": now_iso()}


def main(server_id: str) -> None:
    server = load_server(server_id)
    ledger = load_ledger()
    server_ledger = ledger.setdefault(server_id, {})

    print(f"\n{'='*60}")
    print(f"  Submitting: {server['name']}")
    print(f"  Server ID : {server_id}")
    print(f"{'='*60}\n")

    # ── 1. Official MCP Registry ──────────────────────────────────
    print(f"[1/4] {REGISTRIES['official_mcp_registry']['label']}")
    print("─" * 60)
    existing = server_ledger.get("official_mcp_registry", {})
    if existing.get("pr_url"):
        print(f"  Already submitted: {existing['pr_url']}")
        result_official = existing
    else:
        print("  Generating server.json …")
        print(official_mcp_registry.render(server))
        print()
        result_official = submit_official_mcp_registry(server, ledger)
        server_ledger["official_mcp_registry"] = result_official
        if result_official.get("pr_url"):
            print(f"  ✓ PR: {result_official['pr_url']}")
        else:
            print(f"  → {result_official.get('note', result_official)}")
    print()

    # ── 2. GitHub Awesome MCP Servers ────────────────────────────
    print(f"[2/4] {REGISTRIES['github_mcp_registry']['label']}")
    print("─" * 60)
    print("  Payload preview:")
    print(github_mcp_registry.render(server))
    print()
    existing = server_ledger.get("github_mcp_registry", {})
    if existing.get("pr_url"):
        print(f"  Already submitted: {existing['pr_url']}")
        result_github = existing
    else:
        print("  Forking repo and opening PR …")
        result_github = submit_github_mcp_registry(server, ledger)
        server_ledger["github_mcp_registry"] = result_github
        if result_github.get("pr_url"):
            print(f"  ✓ PR: {result_github['pr_url']}")
        elif result_github.get("status") == "already_submitted":
            print("  Already submitted (line already present in README)")
        else:
            print(f"  ✗ Error: {result_github.get('error')}")
    print()

    # ── 3. mcp.so ────────────────────────────────────────────────
    print(f"[3/4] {REGISTRIES['mcp_so']['label']}")
    print("─" * 60)
    print(mcp_so.render(server))
    existing = server_ledger.get("mcp_so", {})
    if existing.get("submitted_at"):
        print(f"\n  ↳ Previously submitted at {existing['submitted_at']}")
    else:
        server_ledger["mcp_so"] = {"status": "payload_printed", "submitted_at": now_iso()}
    print()

    # ── 4. PulseMCP ──────────────────────────────────────────────
    print(f"[4/4] {REGISTRIES['pulsemcp']['label']}")
    print("─" * 60)
    print(pulsemcp.render(server))
    existing = server_ledger.get("pulsemcp", {})
    if existing.get("submitted_at"):
        print(f"\n  ↳ Previously submitted at {existing['submitted_at']}")
    else:
        server_ledger["pulsemcp"] = {"status": "payload_printed", "submitted_at": now_iso()}
    print()

    # ── Summary ───────────────────────────────────────────────────
    save_ledger(ledger)
    print(f"{'='*60}")
    print("  SUMMARY")
    print(f"{'='*60}")
    print(f"  Official MCP Registry : {result_official.get('pr_url') or result_official.get('status')}")
    print(f"  Awesome MCP Servers   : {result_github.get('pr_url') or result_github.get('status')}")
    print(f"  mcp.so                : payload printed — paste at github.com/chatmcp/mcpso/issues/1")
    print(f"  PulseMCP              : payload printed — submit at pulsemcp.com/submit")
    print(f"\n  Ledger saved → registry/submissions.json")
    print()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: python -m registry.submit <server_id>")
        sys.exit(1)
    main(sys.argv[1])
