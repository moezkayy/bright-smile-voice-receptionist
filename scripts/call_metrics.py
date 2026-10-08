"""Pull one call's real latency and outcome numbers from ElevenLabs.

  python scripts/call_metrics.py                    # the call in media/call/call.json
  python scripts/call_metrics.py conv_xxx           # any conversation id

Saves the (scrubbed) conversation to media/call/conversation.json and prints medians.
"""

import json
import os
import statistics
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from receptionist.scrub import scrub  # noqa: E402

load_dotenv(ROOT / ".env")
cid = sys.argv[1] if len(sys.argv) > 1 else json.loads((ROOT / "media/call/call.json").read_text())["conversation_id"]
d = httpx.get(f"https://api.elevenlabs.io/v1/convai/conversations/{cid}",
              headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]}, timeout=20).json()
(ROOT / "media/call/conversation.json").write_text(json.dumps(scrub(d), indent=1))

metrics: dict[str, list[float]] = {}
for turn in d["transcript"]:
    for k, v in ((turn.get("conversation_turn_metrics") or {}).get("metrics") or {}).items():
        if v.get("elapsed_time") is not None:
            metrics.setdefault(k, []).append(v["elapsed_time"])
print(f"conversation {cid}: {d['metadata'].get('call_duration_secs')} s, status {d['status']}")
print("evaluation:", {k: v["result"] for k, v in (d["analysis"].get("evaluation_criteria_results") or {}).items()})
for k, v in sorted(metrics.items()):
    print(f"  {k:48s} n={len(v):2d}  median {statistics.median(v):.2f} s  max {max(v):.2f} s")
tools = [r["tool_latency_secs"] for t in d["transcript"] for r in (t.get("tool_results") or []) if r.get("tool_name") != "end_call"]
print("  tool round trips (s):", [round(x, 2) for x in tools])
usage = ((d["metadata"].get("charging") or {}).get("llm_usage") or {}).get("irreversible_generation", {}).get("model_usage", {})
cost = sum(p.get("price", 0) for m in usage.values() for p in m.values() if isinstance(p, dict))
print(f"  LLM cost: ${cost:.4f}")
