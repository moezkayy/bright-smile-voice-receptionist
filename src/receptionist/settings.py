from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "data" / "runtime"
AGENT_STATE = ROOT / "agent" / "state.json"

load_dotenv(ROOT / ".env")


@dataclass
class Settings:
    calendar_backend: str
    tool_secret: str
    elevenlabs_api_key: str
    agent_id: str
    google_service_account_file: str
    google_calendar_id: str
    public_base_url: str
    runtime_dir: Path

    @classmethod
    def load(cls) -> "Settings":
        agent_id = os.getenv("ELEVENLABS_AGENT_ID", "")
        if not agent_id and AGENT_STATE.exists():
            agent_id = json.loads(AGENT_STATE.read_text()).get("agent_id", "")
        return cls(
            calendar_backend=os.getenv("CALENDAR_BACKEND", "mock"),
            tool_secret=os.getenv("TOOL_SECRET", ""),
            elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY", ""),
            agent_id=agent_id,
            google_service_account_file=os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", ""),
            google_calendar_id=os.getenv("GOOGLE_CALENDAR_ID", ""),
            public_base_url=os.getenv("PUBLIC_BASE_URL", "").rstrip("/"),
            runtime_dir=Path(os.getenv("RUNTIME_DIR", RUNTIME)),
        )

    def calendar(self):
        if self.calendar_backend == "google":
            from .calendars.google import GoogleCalendar

            sa = Path(self.google_service_account_file)
            if not sa.is_absolute():
                sa = ROOT / sa
            return GoogleCalendar(str(sa), self.google_calendar_id)
        from .calendars.mock import MockCalendar

        return MockCalendar(self.runtime_dir / "calendar.json")
