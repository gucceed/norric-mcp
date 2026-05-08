"""
Generates submission payload for PulseMCP.
Submit at: https://www.pulsemcp.com/submit
"""

import textwrap


def render(server: dict) -> str:
    return textwrap.dedent(f"""
        ┌─────────────────────────────────────────────────┐
        │  PulseMCP SUBMISSION — pulsemcp.com/submit      │
        └─────────────────────────────────────────────────┘

        Server Name         : {server['name']}
        Short Description   : {server['description_short'].strip().replace(chr(10), ' ')}
        Endpoint URL        : {server['server_url']}
        GitHub URL          : {server['github_url']}
        Homepage            : {server['homepage']}
        Contact Email       : {server['contact_email']}

        Category            : {server['categories'][0]}
        Tags                : {', '.join(server['tags'][:8])}

        Auth Type           : Bearer token
        Transport           : {server['transport']}
        Protocol Version    : {server['protocol_version']}

        Free Tier Tools     : {', '.join(server['free_tier_tools'])}
        Paid Tier Tools     : {', '.join(server['paid_tier_tools'][:5])} (+ {len(server['paid_tier_tools']) - 5} more)

        Long Description    :
        {server['description_long'].strip()}
    """).strip()
