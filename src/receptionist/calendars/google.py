"""Google Calendar backend (REST API v3, service-account auth).

Setup: share the clinic calendar with the service account's email
("Make changes to events"), then set GOOGLE_SERVICE_ACCOUNT_FILE and
GOOGLE_CALENDAR_ID in .env. Clinic metadata (provider, service, phone,
confirmation code) is stored in the event's private extendedProperties, so
the scheduler can tell the hygiene chair from the doctor's chair.
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

import httpx

from .base import Event

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
API = "https://www.googleapis.com/calendar/v3"
COLOR_BY_PROVIDER = {"hygiene": "7", "doctor": "3"}  # peacock blue, grape


class GoogleCalendar:
    name = "google"

    def __init__(self, service_account_file: str, calendar_id: str, client: httpx.Client | None = None):
        from google.oauth2 import service_account

        self.calendar_id = calendar_id
        self._creds = service_account.Credentials.from_service_account_file(service_account_file, scopes=SCOPES)
        self._http = client or httpx.Client(timeout=10)

    def _headers(self) -> dict:
        if not self._creds.valid:
            from google.auth.transport.requests import Request

            self._creds.refresh(Request())
        return {"Authorization": f"Bearer {self._creds.token}"}

    def _url(self, suffix: str = "") -> str:
        return f"{API}/calendars/{quote(self.calendar_id, safe='')}/events{suffix}"

    def list_events(self, start: datetime, end: datetime) -> list[Event]:
        events, page = [], None
        while True:
            params = {
                "timeMin": start.isoformat(),
                "timeMax": end.isoformat(),
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": 250,
            }
            if page:
                params["pageToken"] = page
            r = self._http.get(self._url(), params=params, headers=self._headers())
            r.raise_for_status()
            body = r.json()
            events += [from_google(item) for item in body.get("items", []) if item.get("status") != "cancelled"]
            page = body.get("nextPageToken")
            if not page:
                return [e for e in events if e is not None]

    def create_event(self, event: Event) -> Event:
        r = self._http.post(self._url(), json=to_google(event), headers=self._headers())
        r.raise_for_status()
        event.id = r.json()["id"]
        return event


def to_google(e: Event) -> dict:
    private = {
        "provider": e.provider,
        "service": e.service,
        "patient_name": e.patient_name,
        "phone": e.phone,
        "confirmation": e.confirmation,
        "source": e.source,
    }
    private.update({f"d_{k}": v for k, v in e.details.items()})
    lines = [f"{k.removeprefix('d_').replace('_', ' ').title()}: {v}" for k, v in private.items() if v and k != "source"]
    return {
        "summary": e.summary,
        "description": "\n".join(lines),
        "start": {"dateTime": e.start.isoformat()},
        "end": {"dateTime": e.end.isoformat()},
        "colorId": COLOR_BY_PROVIDER.get(e.provider),
        "extendedProperties": {"private": {k: str(v) for k, v in private.items()}},
    }


def from_google(item: dict) -> Event | None:
    start, end = item.get("start", {}), item.get("end", {})
    if "dateTime" not in start:
        # All-day event (e.g. "Office closed"): block both chairs for the day.
        if "date" not in start:
            return None
        s = datetime.fromisoformat(start["date"] + "T00:00:00+00:00")
        en = datetime.fromisoformat(end["date"] + "T00:00:00+00:00")
        return Event(start=s, end=en, provider="all", summary=item.get("summary", ""), id=item["id"])
    p = item.get("extendedProperties", {}).get("private", {})
    return Event(
        start=datetime.fromisoformat(start["dateTime"]),
        end=datetime.fromisoformat(end["dateTime"]),
        provider=p.get("provider", "all"),  # events added by hand block both chairs
        summary=item.get("summary", ""),
        id=item["id"],
        service=p.get("service", ""),
        patient_name=p.get("patient_name", ""),
        phone=p.get("phone", ""),
        confirmation=p.get("confirmation", ""),
        source=p.get("source", "front-desk"),
        details={k[2:]: v for k, v in p.items() if k.startswith("d_")},
    )
