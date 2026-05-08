# Norric MCP Registry

Multi-registry submission system for all Norric MCP servers.
Adding a new server is a 10-minute exercise.

---

## Directory structure

```
registry/
  servers.yaml                    ← source of truth — all servers
  submissions.json                ← ledger of submission status per server per registry
  anthropic-partnership.md        ← partnership track (not automated)
  submit.py                       ← CLI entrypoint
  generators/
    official_mcp_registry.py      → registry.modelcontextprotocol.io
    github_mcp_registry.py        → punkpeye/awesome-mcp-servers (PR)
    mcp_so.py                     → mcp.so (form payload)
    pulsemcp.py                   → PulseMCP (form payload)
```

---

## Adding a new server

1. **Add an entry to `servers.yaml`**

   Copy an existing entry (e.g. `norric-mcp`) and change:
   - `id` — unique slug, e.g. `sigvik-mcp`
   - `name`, `title`, `description_short`, `description_long`
   - `server_url` — live HTTPS endpoint
   - `github_url`
   - `free_tier_tools`, `paid_tier_tools`, `tool_count`
   - Set `status: live` when ready

2. **Run the CLI**

   ```bash
   cd /path/to/norric-mcp
   pip install pyyaml  # once, if not installed
   python -m registry.submit <server_id>
   ```

3. **Handle outputs**
   - **Official MCP Registry**: `server.json` written to `registry/<id>_server.json`.
     If `mcp-publisher` is installed, it auto-submits. Otherwise follow the printed
     instruction to run `mcp-publisher publish`.
   - **Awesome MCP Servers**: PR opened automatically via `gh` CLI.
     Copy the PR URL from output.
   - **mcp.so**: Copy the printed block and paste as a comment on
     [github.com/chatmcp/mcpso/issues/1](https://github.com/chatmcp/mcpso/issues/1).
   - **PulseMCP**: Copy the printed fields and paste at
     [pulsemcp.com/submit](https://pulsemcp.com/submit).

4. **Check the ledger**

   `registry/submissions.json` records timestamps and PR URLs. Re-running the CLI
   is idempotent — already-submitted registries are skipped.

---

## Registries covered

| Registry | Type | Automation |
|----------|------|------------|
| [registry.modelcontextprotocol.io](https://registry.modelcontextprotocol.io) | Official | Auto via `mcp-publisher` |
| [punkpeye/awesome-mcp-servers](https://github.com/punkpeye/awesome-mcp-servers) | GitHub PR | Auto via `gh` CLI |
| [mcp.so](https://mcp.so) | Form (GitHub issue) | Payload printed |
| [PulseMCP](https://pulsemcp.com) | Form | Payload printed |
| Anthropic connector directory | Partnership | See `anthropic-partnership.md` |

---

## Planned servers

| ID | Product | Status |
|----|---------|--------|
| `norric-mcp` | Norric (all products) | ✅ live |
| `sigvik-mcp` | Sigvik standalone | ⏸ upcoming |
| `kreditvakt-mcp` | Kreditvakt standalone | ⏸ upcoming |
| `signal-mcp` | SIGNAL standalone | ⏸ upcoming |

---

## Prerequisites

```bash
pip install pyyaml          # YAML parsing
gh auth login               # GitHub CLI (for PR-based submissions)
npm install -g mcp-publisher # Optional: auto-submit to official registry
```
