"""Clinic scheduling rules, independent of where the calendar lives.

Everything the LLM must never get wrong (opening hours, lunch, appointment
length, which chair, double-booking, lead time) is enforced here in code. The
agent only chooses among slots this module offers.
"""

from __future__ import annotations

import random
import re
from datetime import date, datetime, timedelta

from . import clinic
from .calendars.base import Calendar, Event

TZ = clinic.TIMEZONE


class BookingError(ValueError):
    """A booking request the clinic rules reject. The message is safe to read to the caller."""


# ---------- formatting helpers (spoken-friendly) ----------

def spoken_time(dt: datetime) -> str:
    dt = dt.astimezone(TZ)
    h = dt.hour % 12 or 12
    m = f":{dt.minute:02d}" if dt.minute else ""
    return f"{h}{m} {'AM' if dt.hour < 12 else 'PM'}"


def spoken_datetime(dt: datetime, now: datetime | None = None) -> str:
    dt = dt.astimezone(TZ)
    day = f"{dt:%A}, {dt:%B} {dt.day}"
    if now is not None:
        delta = (dt.date() - now.astimezone(TZ).date()).days
        if delta == 0:
            day = f"today, {day}"
        elif delta == 1:
            day = f"tomorrow, {day}"
    return f"{day} at {spoken_time(dt)}"


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        raise BookingError("That phone number doesn't look complete. Could you say all ten digits again?")
    return digits


def format_phone(digits: str) -> str:
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"


def parse_local(value: str) -> datetime:
    """Accept '2026-10-13T09:15', with or without offset; interpret naive times as clinic time."""
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        raise BookingError("I couldn't read that appointment time.") from None
    return dt.replace(tzinfo=TZ) if dt.tzinfo is None else dt.astimezone(TZ)


def parse_day(value: str | None, today: date) -> date | None:
    if not value:
        return None
    v = value.strip().lower()
    if v == "today":
        return today
    if v == "tomorrow":
        return today + timedelta(days=1)
    try:
        return date.fromisoformat(v[:10])
    except ValueError:
        return None


# ---------- availability ----------

def is_open_day(d: date) -> bool:
    return d.weekday() in clinic.HOURS and d.isoformat() not in clinic.CLOSED_DATES


def _candidate_starts(d: date, minutes: int):
    step = timedelta(minutes=clinic.SLOT_GRID_MINUTES)
    length = timedelta(minutes=minutes)
    for open_t, close_t in clinic.HOURS.get(d.weekday(), []):
        t = datetime.combine(d, open_t, TZ)
        end = datetime.combine(d, close_t, TZ)
        while t + length <= end:
            yield t
            t += step


def _conflicts(start: datetime, end: datetime, provider: str, events: list[Event]) -> bool:
    return any(
        e.provider in (provider, "all") and e.start < end and e.end > start
        for e in events
    )


def _time_of_day_ok(t: datetime, time_of_day: str) -> bool:
    if time_of_day == "morning":
        return t.hour < 12
    if time_of_day == "afternoon":
        return t.hour >= 12
    return True


def _spread(slots: list[datetime], k: int, min_gap_minutes: int = 60) -> list[datetime]:
    """Pick k slots spread across the day, never closer than an hour apart.

    Offering "8:00, 8:15 or 8:30" sounds robotic on a call; "8, 10:30 or 3" is a real choice.
    """
    thinned: list[datetime] = []
    for t in slots:
        if not thinned or t - thinned[-1] >= timedelta(minutes=min_gap_minutes):
            thinned.append(t)
    slots = thinned
    if len(slots) <= k:
        return slots
    idx = sorted({round(i * (len(slots) - 1) / (k - 1)) for i in range(k)}) if k > 1 else [0]
    return [slots[i] for i in idx]


def find_slots(
    calendar: Calendar,
    service_id: str,
    now: datetime,
    preferred_date: str | None = None,
    time_of_day: str = "any",
    limit: int = 3,
) -> dict:
    service = clinic.SERVICES.get(service_id)
    if service is None:
        raise BookingError(f"Unknown service '{service_id}'.")
    now = now.astimezone(TZ)
    earliest = now + timedelta(minutes=clinic.MIN_LEAD_MINUTES)
    today = now.date()
    wanted = parse_day(preferred_date, today)
    note = ""
    if wanted and wanted < today:
        wanted, note = None, "That date has already passed."
    if wanted and (wanted - today).days > clinic.MAX_DAYS_AHEAD:
        wanted, note = None, f"We only book up to {clinic.MAX_DAYS_AHEAD} days ahead."
    if wanted and not is_open_day(wanted):
        note = f"We're closed on {wanted:%A}, {wanted:%B} {wanted.day}."
    start_day = wanted or today
    horizon_end = datetime.combine(today + timedelta(days=clinic.MAX_DAYS_AHEAD + 1), datetime.min.time(), TZ)
    events = calendar.list_events(datetime.combine(start_day, datetime.min.time(), TZ), horizon_end)
    length = timedelta(minutes=service.minutes)

    picked: list[datetime] = []
    on_requested_day = False
    d = start_day
    while len(picked) < limit and (d - today).days <= clinic.MAX_DAYS_AHEAD:
        if is_open_day(d):
            free = [
                t for t in _candidate_starts(d, service.minutes)
                if t >= earliest
                and _time_of_day_ok(t, time_of_day)
                and not _conflicts(t, t + length, service.provider, events)
            ]
            if free:
                if d == wanted:
                    on_requested_day = True
                picked += _spread(free, limit - len(picked))
        d += timedelta(days=1)

    if wanted and is_open_day(wanted) and not on_requested_day:
        part = "" if time_of_day == "any" else f" {time_of_day}"
        note = f"No{part} openings on {wanted:%A}, {wanted:%B} {wanted.day}."

    return {
        "service": service.id,
        "service_label": service.label,
        "duration_minutes": service.minutes,
        "with": clinic.PROVIDERS[service.provider].name,
        "note": note,
        "slots": [{"start": t.isoformat(timespec="minutes"), "spoken": spoken_datetime(t, now)} for t in picked],
    }


# ---------- booking ----------

def book(
    calendar: Calendar,
    *,
    service_id: str,
    start: str,
    patient_name: str,
    phone: str,
    now: datetime,
    is_new_patient: bool = False,
    insurance_carrier: str = "",
    notes: str = "",
    rng: random.Random | None = None,
) -> dict:
    service = clinic.SERVICES.get(service_id)
    if service is None:
        raise BookingError(f"Unknown service '{service_id}'.")
    name = " ".join((patient_name or "").split()).title()
    if len(name) < 2:
        raise BookingError("I need the patient's full name to book.")
    digits = normalize_phone(phone)
    t = parse_local(start)
    end = t + timedelta(minutes=service.minutes)
    now = now.astimezone(TZ)

    if t < now + timedelta(minutes=clinic.MIN_LEAD_MINUTES):
        raise BookingError("That time is too soon to book. Let me find the next opening.")
    if (t.date() - now.date()).days > clinic.MAX_DAYS_AHEAD:
        raise BookingError(f"We only book up to {clinic.MAX_DAYS_AHEAD} days ahead.")
    if not is_open_day(t.date()) or t not in set(_candidate_starts(t.date(), service.minutes)):
        raise BookingError("That time is outside our opening hours for this appointment.")

    day_start = datetime.combine(t.date(), datetime.min.time(), TZ)
    events = calendar.list_events(day_start, day_start + timedelta(days=1))

    # Idempotent: the same caller asking for the same slot twice gets the same booking back.
    for e in events:
        if e.phone == digits and e.start == t and e.service == service.id:
            return _confirmation(e, now, duplicate=True)

    if _conflicts(t, end, service.provider, events):
        raise BookingError("That slot was just taken. Let me check what else is open.")

    code = f"{(rng or random).randint(1000, 9999)}"
    first, last = (name.split(" ", 1) + [""])[:2]
    event = Event(
        start=t,
        end=end,
        provider=service.provider,
        summary=f"{service.label}: {first} {last[:1] + '.' if last else ''}".strip(),
        service=service.id,
        patient_name=name,
        phone=digits,
        confirmation=code,
        source="voice-agent",
        details={
            "new_patient": "yes" if is_new_patient else "no",
            "insurance": insurance_carrier or "not given",
            "notes": notes,
            "booked_at": now.isoformat(timespec="seconds"),
        },
    )
    return _confirmation(calendar.create_event(event), now)


def _confirmation(e: Event, now: datetime, duplicate: bool = False) -> dict:
    service = clinic.SERVICES[e.service]
    return {
        "booked": True,
        "already_booked": duplicate,
        "confirmation_code": e.confirmation,
        "confirmation_code_spoken": " ".join(e.confirmation),
        "service": service.label,
        "start": e.start.isoformat(timespec="minutes"),
        "spoken": spoken_datetime(e.start, now),
        "with": clinic.PROVIDERS[service.provider].name,
        "patient_name": e.patient_name,
        "phone": format_phone(e.phone),
        "arrive_early_minutes": 15 if e.details.get("new_patient") == "yes" else 5,
        "event_id": e.id,
    }
