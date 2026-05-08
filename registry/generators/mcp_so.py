"""
Generates submission payload for mcp.so.
mcp.so accepts submissions via a comment on GitHub Issue #1:
  github.com/chatmcp/mcpso/issues/1
"""

import textwrap


def render(server: dict) -> str:
    tools_preview = "\n".join(
        f"  - `{t}`" for t in server["paid_tier_tools"][:6]
    )
    return textwrap.dedent(f"""
        ┌─────────────────────────────────────────────────┐
        │  mcp.so SUBMISSION — paste as GitHub comment    │
        │  github.com/chatmcp/mcpso/issues/1              │
        └─────────────────────────────────────────────────┘

        **{server['name']}**
        {server['server_url']}

        {server['description_short'].strip()}

        **Category:** {', '.join(server['categories'][:2])}
        **Auth:** {server['auth_type']} token
        **Transport:** {server['transport']}
        **Tools:** {server['tool_count']} tools (free tier: `{server['free_tier_tools'][0]}`)

        Top tools:
{tools_preview}

        **GitHub:** {server['github_url']}
        **Homepage:** {server['homepage']}
        **Contact:** {server['contact_email']}
    """).strip()
