"""
Generates a PR to punkpeye/awesome-mcp-servers — the most-starred GitHub
MCP server index (github.com/punkpeye/awesome-mcp-servers).

Submission: add a line to the relevant section of README.md and open a PR.
The CLI submits via `gh` if available.
"""

import subprocess
import tempfile
import textwrap
from pathlib import Path


TARGET_REPO = "punkpeye/awesome-mcp-servers"
SECTION_ANCHOR = "Finance"  # section to insert under


def generate_line(server: dict) -> str:
    """One-line entry in awesome-mcp-servers format."""
    name = server["name"]
    url = server["github_url"]
    desc = server["description_short"].replace("\n", " ").strip()
    return f"- [{name}]({url}) - {desc}"


def render(server: dict) -> str:
    line = generate_line(server)
    return textwrap.dedent(f"""
        TARGET REPO : {TARGET_REPO}
        SECTION     : {SECTION_ANCHOR} (or closest match)
        LINE TO ADD : {line}

        PR title    : Add Norric Swedish Business Intelligence MCP server
        PR body     : |
            Norric provides real-time data from five Swedish government registries
            (Bolagsverket, Skatteverket, Kronofogden, Boverket, Lantmäteriet) via
            a Streamable HTTP MCP server. 19 tools covering insolvency risk, BRF
            property intelligence, and municipal procurement signals.

            Endpoint: {server['server_url']}
            Auth: Bearer token (trial available at norric.io/api)
            Protocol: MCP 2024-11-05 · Streamable HTTP
    """).strip()


def submit(server: dict) -> dict:
    """
    Fork TARGET_REPO, add the server line, open a PR via gh CLI.
    Returns {"pr_url": str, "error": str | None}.
    """
    line = generate_line(server)
    # gh forks to gucceed/<target-repo-name>
    fork_name = TARGET_REPO.split("/")[1]
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        repo_dir = tmp_path / fork_name

        # Fork (idempotent — gh skips if fork already exists)
        subprocess.run(
            ["gh", "repo", "fork", TARGET_REPO, "--clone"],
            cwd=tmp_path, capture_output=True, timeout=120,
        )

        if not repo_dir.exists():
            # Fork may already exist but not cloned
            r = subprocess.run(
                ["gh", "repo", "clone", f"gucceed/{fork_name}", str(repo_dir)],
                capture_output=True, timeout=60,
            )
            if r.returncode != 0:
                return {"pr_url": None, "error": f"Clone failed: {r.stderr.decode()}"}

        readme = repo_dir / "README.md"
        if not readme.exists():
            return {"pr_url": None, "error": "README.md not found in forked repo"}

        content = readme.read_text()
        if line in content:
            return {"pr_url": None, "error": "already_submitted"}

        # Insert line under first Finance-related section heading
        lines = content.splitlines()
        insert_at = None
        for i, l in enumerate(lines):
            if SECTION_ANCHOR.lower() in l.lower() and l.startswith("#"):
                # Find next blank line after the heading and insert
                for j in range(i + 1, min(i + 20, len(lines))):
                    if lines[j].strip() == "":
                        insert_at = j
                        break
                if insert_at:
                    break

        if insert_at is None:
            # Append at end as fallback
            lines.append("")
            lines.append(f"## Finance")
            lines.append(line)
        else:
            lines.insert(insert_at + 1, line)

        readme.write_text("\n".join(lines))

        branch = f"add-norric-{server['id']}"
        subprocess.run(["git", "checkout", "-b", branch], cwd=repo_dir,
                       capture_output=True, check=True)
        subprocess.run(["git", "add", "README.md"], cwd=repo_dir,
                       capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", f"Add {server['name']}"],
            cwd=repo_dir, capture_output=True, check=True,
        )
        subprocess.run(["git", "push", "origin", branch], cwd=repo_dir,
                       capture_output=True, check=True, timeout=60)

        pr = subprocess.run(
            ["gh", "pr", "create",
             "--repo", TARGET_REPO,
             "--title", f"Add {server['name']} MCP server",
             "--body", (
                 f"{server['description_long']}\n\n"
                 f"Endpoint: {server['server_url']}\n"
                 f"Auth: Bearer token\n"
                 f"Protocol: MCP {server['protocol_version']} · {server['transport']}\n"
                 f"Homepage: {server['homepage']}"
             ),
             "--head", f"gucceed:{branch}"],
            cwd=repo_dir, capture_output=True, check=True, timeout=30,
        )
        pr_url = pr.stdout.decode().strip()
        return {"pr_url": pr_url, "error": None}
