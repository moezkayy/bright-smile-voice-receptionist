"""Fill a calendar with a realistic, mostly-booked clinic schedule.

A real dental schedule is mostly full, so the agent has to search for
openings instead of booking the first hour of the day. Deterministic for a
given seed. Patients are invented initials only.
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta

from . import clinic
from .calendars.base import Event
from .scheduling import TZ, _candidate_starts, _conflicts, is_open_day

FIRST = "Ava Ben Cara Dev Eli Fay Gus Hana Ivan Jade Kai Lena Milo Nia Owen Pia Quin Rosa Sam Tess".split()
LAST = "ABCDFGHJKLMNPRSTVW"

HYGIENE_MIX = ["cleaning"] * 6 + ["new_patient_exam"] * 2 + ["kids_cleaning"] * 2
CARRIERS = ["Delta Dental PPO"] * 4 + ["Cigna Dental PPO"] * 2 + ["MetLife PDP", "Aetna Dental PPO",
            "Guardian Dental", "Blue Cross Blue Shield of Texas Dental", "Self-pay", "Membership plan"]
DOCTOR_MIX = ["filling"] * 5 + ["crown_consult", "whitening_consult", "emergency"]


def build(start: date, days: int = 14, fill: float = 0.65, seed: int = 7) -> list[Event]:
    rng = random.Random(seed)
    events: list[Event] = []
    for i in range(days):
        d = start + timedelta(days=i)
        if not is_open_day(d):
            continue
        for provider, mix in (("hygiene", HYGIENE_MIX), ("doctor", DOCTOR_MIX)):
            # Keep a little air in the schedule so openings appear on most days.
            target = fill - (0.15 if i < 2 else 0)
            open_minutes = sum(
                (datetime.combine(d, b, TZ) - datetime.combine(d, a, TZ)).seconds // 60
                for a, b in clinic.HOURS[d.weekday()]
            )
            booked = 0
            attempts = 0
            while booked < open_minutes * target and attempts < 200:
                attempts += 1
                service = clinic.SERVICES[rng.choice(mix)]
                starts = list(_candidate_starts(d, service.minutes))
                t = rng.choice(starts)
                if t.minute not in (0, 30):
                    continue
                end = t + timedelta(minutes=service.minutes)
                if _conflicts(t, end, provider, events):
                    continue
                who = f"{rng.choice(FIRST)} {rng.choice(LAST)}."
                new = service.id == "new_patient_exam" or rng.random() < 0.08
                events.append(Event(
                    start=t, end=end, provider=provider, service=service.id,
                    summary=f"{service.label}: {who}", patient_name=who,
                    id=f"seed{len(events):04d}",
                    details={"new_patient": "yes" if new else "no", "insurance": rng.choice(CARRIERS)},
                ))
                booked += service.minutes
    return sorted(events, key=lambda e: e.start)


def today() -> date:
    return datetime.now(TZ).date()
