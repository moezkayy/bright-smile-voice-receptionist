"""Run the agent's eval suite on ElevenLabs Agent Testing (real tools, no mocks).

  python scripts/run_evals.py              # sync tests from agent/evals.json, run each once
  python scripts/run_evals.py --repeat 3   # run each test 3 times for a pass rate
  python scripts/run_evals.py --only "Weekend request"

Writes media/evals/<timestamp>.json with every run, transcript and judge rationale.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from receptionist.scrub import scrub  # noqa: E402
from receptionist.settings import AGENT_STATE  # noqa: E402

API = "https://api.elevenlabs.io"


def main():
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--only", action="append", default=[])
    args = ap.parse_args()

    key = os.getenv("ELEVENLABS_API_KEY") or sys.exit("ELEVENLABS_API_KEY missing")
    state = json.loads(AGENT_STATE.read_text())
    agent_id = state["agent_id"]
    http = httpx.Client(base_url=API, headers={"xi-api-key": key}, timeout=60)

    def call(method, path, **kw):
        r = http.request(method, path, **kw)
        if r.status_code >= 400:
            sys.exit(f"{method} {path} -> {r.status_code}\n{r.text[:1500]}")
        return r.json() if r.content else {}

    suite = json.loads((ROOT / "agent" / "evals.json").read_text())
    tests = [t for t in suite["tests"] if not args.only or t["name"] in args.only]
    state.setdefault("tests", {})
    for t in tests:
        body = {
            "type": "simulation",
            "name": f"Bright Smile · {t['name']}",
            "simulation_scenario": t["scenario"],
            "success_conditions": t["success"],
            "simulation_max_turns": suite["max_turns"],
        }
        tid = state["tests"].get(t["name"])
        if tid:
            call("PUT", f"/v1/convai/agent-testing/{tid}", json=body)
        else:
            state["tests"][t["name"]] = call("POST", "/v1/convai/agent-testing/create", json=body)["id"]
    AGENT_STATE.write_text(json.dumps(state, indent=2))

    ids = [state["tests"][t["name"]] for t in tests]
    name_by_id = {state["tests"][t["name"]]: t["name"] for t in tests}
    started = time.time()
    inv = call("POST", f"/v1/convai/agents/{agent_id}/run-tests",
               json={"tests": [{"test_id": i} for i in ids], "repeat_count": args.repeat})
    print(f"Running {len(ids)} tests x{args.repeat} (invocation {inv['id']})")
    while True:
        inv = call("GET", f"/v1/convai/test-invocations/{inv['id']}")
        runs = inv["test_runs"]
        done = [r for r in runs if r["status"] != "pending"]
        print(f"\r{len(done)}/{len(runs)} finished", end="", flush=True)
        if len(done) == len(runs):
            break
        time.sleep(5)
    elapsed = time.time() - started
    print()

    by_test: dict[str, list] = {}
    for r in runs:
        by_test.setdefault(name_by_id.get(r["test_id"], r["test_name"]), []).append(r)
    passed_total = sum(r["status"] == "passed" for r in runs)
    credits = sum(r.get("credits_used") or 0 for r in runs)
    for name, rs in by_test.items():
        ok = sum(r["status"] == "passed" for r in rs)
        mark = "PASS" if ok == len(rs) else "FAIL"
        print(f"  [{mark}] {ok}/{len(rs)}  {name}")
        if ok < len(rs):
            for r in rs:
                if r["status"] != "passed":
                    why = (r.get("condition_result") or {}).get("rationale") or {}
                    print(f"         ↳ {json.dumps(why)[:400]}")
    print(f"\n{passed_total}/{len(runs)} runs passed · {elapsed:.0f}s wall time · {credits} credits")

    out = ROOT / "media" / "evals"
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (out / f"{stamp}.json").write_text(json.dumps(scrub({
        "ran_at_utc": stamp, "agent_id": agent_id, "repeat": args.repeat, "elapsed_secs": round(elapsed),
        "passed": passed_total, "total": len(runs), "credits_used": credits, "runs": runs,
    }), indent=1))
    print(f"Saved media/evals/{stamp}.json")


if __name__ == "__main__":
    main()
