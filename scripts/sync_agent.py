"""Create or update the ElevenLabs agent from code (idempotent).

  python scripts/sync_agent.py --dry-run     # print the full agent JSON, no network
  python scripts/sync_agent.py               # push secret, knowledge base, 4 tools and the agent
  python scripts/sync_agent.py --tools-only  # just re-point the tools at a new PUBLIC_BASE_URL

Resource IDs (not secrets) are kept in agent/state.json so re-runs update in place.
"""

import argparse
import hashlib
import json
import os
import secrets
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from receptionist import agent_config, knowledge  # noqa: E402
from receptionist.settings import AGENT_STATE, ROOT  # noqa: E402

API = "https://api.elevenlabs.io"


def ensure_tool_secret() -> str:
    value = os.getenv("TOOL_SECRET", "")
    if value:
        return value
    value = secrets.token_urlsafe(32)
    with (ROOT / ".env").open("a") as f:
        f.write(f"\n# Shared secret the agent's webhook tools send to the clinic API (generated)\nTOOL_SECRET={value}\n")
    os.environ["TOOL_SECRET"] = value
    print("Generated TOOL_SECRET and saved it to .env")
    return value


class Client:
    def __init__(self, key: str):
        self.http = httpx.Client(base_url=API, headers={"xi-api-key": key}, timeout=30)

    def call(self, method: str, path: str, **kw) -> dict:
        r = self.http.request(method, path, **kw)
        if r.status_code >= 400:
            sys.exit(f"{method} {path} -> {r.status_code}\n{r.text[:2000]}")
        return r.json() if r.content else {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--tools-only", action="store_true")
    args = ap.parse_args()

    base_url = os.getenv("PUBLIC_BASE_URL", "https://YOUR-TUNNEL.trycloudflare.com").rstrip("/")
    if args.dry_run:
        tools = agent_config.tool_configs(base_url, "SECRET_ID")
        payload = agent_config.agent_payload([f"<{t['name']}>" for t in tools], {"id": "<kb>", "name": "clinic-facts"})
        print(json.dumps({"tools": tools, "agent": payload}, indent=2))
        return

    key = os.getenv("ELEVENLABS_API_KEY") or sys.exit("ELEVENLABS_API_KEY missing in .env")
    if "YOUR-TUNNEL" in base_url:
        sys.exit("PUBLIC_BASE_URL missing. Start scripts/dev.sh (it sets it) or add it to .env.")
    el = Client(key)
    state = json.loads(AGENT_STATE.read_text()) if AGENT_STATE.exists() else {}

    def save():
        AGENT_STATE.write_text(json.dumps(state, indent=2))

    # 1. Webhook auth secret, stored in the ElevenLabs workspace (never in the agent config).
    tool_secret = ensure_tool_secret()
    if not state.get("secret_id"):
        r = el.call("POST", "/v1/convai/secrets", json={"type": "new", "name": "bright_smile_tool_secret", "value": tool_secret})
        state["secret_id"] = r["secret_id"]
        save()
        print("secret      created")

    # 2. Tools: create once, then patch (URL changes every time the tunnel restarts).
    state.setdefault("tools", {})
    for cfg in agent_config.tool_configs(base_url, state["secret_id"]):
        tid = state["tools"].get(cfg["name"])
        if tid:
            el.call("PATCH", f"/v1/convai/tools/{tid}", json={"tool_config": cfg})
            print(f"tool        updated  {cfg['name']}")
        else:
            state["tools"][cfg["name"]] = el.call("POST", "/v1/convai/tools", json={"tool_config": cfg})["id"]
            print(f"tool        created  {cfg['name']}")
        save()
    if args.tools_only:
        print(f"Tools now point at {base_url}")
        return

    # 3. Knowledge base: a new document only when the clinic facts changed.
    text = knowledge.render()
    digest = hashlib.sha256(text.encode()).hexdigest()[:12]
    old_kb = state.get("kb")
    if not old_kb or old_kb.get("hash") != digest:
        r = el.call("POST", "/v1/convai/knowledge-base/text", json={"text": text, "name": f"bright-smile-facts-{digest}"})
        state["kb"] = {"id": r["id"], "name": f"bright-smile-facts-{digest}", "hash": digest}
        save()
        print("knowledge   uploaded")

    # 4. Agent.
    payload = agent_config.agent_payload(list(state["tools"].values()), state["kb"])
    if state.get("agent_id"):
        el.call("PATCH", f"/v1/convai/agents/{state['agent_id']}", json=payload)
        print(f"agent       updated  {state['agent_id']}")
    else:
        state["agent_id"] = el.call("POST", "/v1/convai/agents/create", json=payload)["agent_id"]
        save()
        print(f"agent       created  {state['agent_id']}")

    if old_kb and old_kb["id"] != state["kb"]["id"]:
        el.http.delete(f"/v1/convai/knowledge-base/{old_kb['id']}")

    print(f"\nDone. Dashboard: https://elevenlabs.io/app/agents/agents/{state['agent_id']}")


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    main()
