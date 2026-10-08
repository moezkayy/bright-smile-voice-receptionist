from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass
class Event:
    start: datetime  # timezone-aware
    end: datetime
    provider: str  # "hygiene" | "doctor"
    summary: str
    id: str = ""
    service: str = ""
    patient_name: str = ""
    phone: str = ""
    confirmation: str = ""
    source: str = "front-desk"  # "voice-agent" for bookings made by the AI
    details: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        d = asdict(self)
        d["start"] = self.start.isoformat()
        d["end"] = self.end.isoformat()
        return d

    @classmethod
    def from_json(cls, d: dict) -> "Event":
        d = dict(d)
        d["start"] = datetime.fromisoformat(d["start"])
        d["end"] = datetime.fromisoformat(d["end"])
        return cls(**d)


class Calendar(Protocol):
    name: str

    def list_events(self, start: datetime, end: datetime) -> list[Event]: ...

    def create_event(self, event: Event) -> Event: ...
