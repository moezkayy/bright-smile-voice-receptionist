"""Read-only views of the agent's calls from the ElevenLabs Conversations API."""

from __future__ import annotations

import time
from datetime import datetime

import httpx

API = "https://api.elevenlabs.io/v1/convai/conversations"


class CallHistory:
    def __init__(self, api_key: str, agent_id: str, ttl: float = 15):
        self.api_key, self.agent_id, self.ttl = api_key, agent_id, ttl
        self._cache: tuple[float, dict] | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.agent_id)

    def _get(self, url: str, **params) -> dict:
        r = httpx.get(url, params=params, headers={"xi-api-key": self.api_key}, timeout=10)
        r.raise_for_status()
        return r.json()

    def today(self, day_start: datetime) -> dict:
        """Calls handled since local midnight: count, average length, success rate."""
        if not self.enabled:
            return {"calls": 0, "avg_secs": 0, "successful": 0}
        if self._cache and time.monotonic() - self._cache[0] < self.ttl:
            return self._cache[1]
        try:
            body = self._get(API, agent_id=self.agent_id, page_size=100,
                             call_start_after_unix=int(day_start.timestamp()))
        except httpx.HTTPError:
            return self._cache[1] if self._cache else {"calls": 0, "avg_secs": 0, "successful": 0}
        convs = [c for c in body.get("conversations", []) if c.get("call_duration_secs", 0) > 0]
        result = {
            "calls": len(convs),
            "avg_secs": round(sum(c["call_duration_secs"] for c in convs) / len(convs)) if convs else 0,
            "successful": sum(c.get("call_successful") == "success" for c in convs),
        }
        self._cache = (time.monotonic(), result)
        return result

    def review(self, conversation_id: str) -> dict:
        """Post-call analysis for one call: summary, evaluation results, extracted fields."""
        d = self._get(f"{API}/{conversation_id}")
        a = d.get("analysis") or {}
        meta = d.get("metadata") or {}
        return {
            "status": d.get("status"),
            "ready": bool(a.get("transcript_summary")),
            "title": a.get("call_summary_title") or "",
            "summary": a.get("transcript_summary") or "",
            "duration_secs": meta.get("call_duration_secs", 0),
            "criteria": [
                {"id": k, "result": v.get("result"), "rationale": v.get("rationale", "")}
                for k, v in (a.get("evaluation_criteria_results") or {}).items()
            ],
            "data": {k: v.get("value") for k, v in (a.get("data_collection_results") or {}).items()},
        }
