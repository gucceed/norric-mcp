from pathlib import Path
import yaml

REGISTRY_DIR = Path(__file__).parent
REPO_ROOT = REGISTRY_DIR.parent
SERVERS_YAML = REGISTRY_DIR / "servers.yaml"
SUBMISSIONS_JSON = REGISTRY_DIR / "submissions.json"


def load_server(server_id: str) -> dict:
    with open(SERVERS_YAML) as f:
        data = yaml.safe_load(f)
    for s in data["servers"]:
        if s["id"] == server_id:
            return s
    raise ValueError(f"Server '{server_id}' not found in servers.yaml")


def load_all_servers() -> list[dict]:
    with open(SERVERS_YAML) as f:
        return yaml.safe_load(f)["servers"]
