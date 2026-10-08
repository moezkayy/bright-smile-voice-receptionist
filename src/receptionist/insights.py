"""Front-office numbers for the dashboard, computed from the calendar itself."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from statistics import median

from . import clinic
from .calendars.base import Event
from .scheduling import TZ, is_open_day


def open_minutes(d: date) -> int:
    return sum(
        (datetime.combine(d, b) - datetime.combine(d, a)).seconds // 60 for a, b in clinic.HOURS.get(d.weekday(), [])
    )


def event_view(e: Event) -> dict:
    s = clinic.SERVICES.get(e.service)
    return {
        "id": e.id,
        "start": e.start.isoformat(),
        "end": e.end.isoformat(),
        "provider": e.provider,
        "patient": e.patient_name or e.summary,
        "service": s.label if s else e.summary,
        "category": s.category if s else "block",
        "cdt": list(s.cdt) if s else [],
        "fee": s.fee if s else 0,
        "new_patient": e.details.get("new_patient") == "yes",
        "insurance": e.details.get("insurance", ""),
        "source": e.source,
        "confirmation": e.confirmation,
        "booked_at": e.details.get("booked_at", ""),
    }


def open_days(start: date, count: int) -> list[date]:
    days, d = [], start
    while len(days) < count:
        if is_open_day(d):
            days.append(d)
        d += timedelta(days=1)
    return days


def day_stats(events: list[Event], d: date) -> dict:
    mins = open_minutes(d) * len(clinic.PROVIDERS)
    booked = sum(
        (min(e.end, datetime.combine(d, datetime.max.time(), TZ)) - max(e.start, datetime.combine(d, datetime.min.time(), TZ))).seconds // 60
        for e in events if e.start.astimezone(TZ).date() == d and e.provider in clinic.PROVIDERS
    )
    production = sum(
        clinic.SERVICES[e.service].fee for e in events
        if e.start.astimezone(TZ).date() == d and e.service in clinic.SERVICES
    )
    return {"date": d.isoformat(), "fill": round(min(booked / mins, 1) * 100) if mins else 0, "production": production}


def kpis(events: list[Event], now: datetime, tool_log: list[dict], calls: dict) -> dict:
    today = now.astimezone(TZ).date()
    by_riley_today = [
        e for e in events
        if e.source == "voice-agent" and e.details.get("booked_at", "")[:10] == today.isoformat()
    ]
    days = open_days(today, 5)
    window = [day_stats(events, d) for d in days]
    tabs = window + [day_stats(events, d) for d in open_days(days[-1] + timedelta(days=1), 5)]
    open_total = sum(open_minutes(d) for d in days) * len(clinic.PROVIDERS)
    booked_total = sum(w["fill"] * open_minutes(date.fromisoformat(w["date"])) * len(clinic.PROVIDERS) / 100 for w in window)
    latencies = [t["ms"] for t in tool_log if t.get("at", "")[:10] == today.isoformat()]
    return {
        "calls_today": calls.get("calls", 0),
        "avg_call_secs": calls.get("avg_secs", 0),
        "booked_today": len(by_riley_today),
        "production_today": sum(clinic.SERVICES[e.service].fee for e in by_riley_today if e.service in clinic.SERVICES),
        "new_patients_today": sum(e.details.get("new_patient") == "yes" for e in by_riley_today),
        "utilization": round(booked_total / open_total * 100) if open_total else 0,
        "open_chair_hours": round((open_total - booked_total) / 60, 1),
        "tool_median_ms": round(median(latencies), 1) if latencies else None,
        "days": tabs,  # 10 open days for the schedule tabs; utilization uses the first 5
    }
