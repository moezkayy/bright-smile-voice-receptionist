"""JSON-file calendar used in mock mode and in tests."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path

from .base import Event


class MockCalendar:
    name = "mock"

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("[]")

    def _load(self) -> list[Event]:
        return [Event.from_json(e) for e in json.loads(self.path.read_text())]

    def _save(self, events: list[Event]) -> None:
        events.sort(key=lambda e: e.start)
        self.path.write_text(json.dumps([e.to_json() for e in events], indent=1))

    def list_events(self, start: datetime, end: datetime) -> list[Event]:
        with self._lock:
            return [e for e in self._load() if e.start < end and e.end > start]

    def create_event(self, event: Event) -> Event:
        with self._lock:
            events = self._load()
            event.id = event.id or uuid.uuid4().hex[:12]
            events.append(event)
            self._save(events)
            return event

    def replace_all(self, events: list[Event]) -> None:
        with self._lock:
            self._save(list(events))
