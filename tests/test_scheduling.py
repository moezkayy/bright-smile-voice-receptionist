import random
from datetime import datetime, timedelta

import pytest

from receptionist import clinic, scheduling
from receptionist.calendars.base import Event
from receptionist.scheduling import BookingError, book, find_slots

TZ = clinic.TIMEZONE


def at(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ)


def booking(cal, now, start="2026-10-13T09:00", service="cleaning", phone="512-555-0199", **kw):
    return book(cal, service_id=service, start=start, patient_name="jordan miles", phone=phone,
                now=now, rng=random.Random(1), **kw)


def test_slots_respect_lead_time_and_hours(cal, now):
    r = find_slots(cal, "cleaning", now, preferred_date="2026-10-12")
    starts = [datetime.fromisoformat(s["start"]) for s in r["slots"]]
    assert starts and all(s >= now + timedelta(minutes=clinic.MIN_LEAD_MINUTES) for s in starts)
    for s in starts:
        assert not (12 <= s.hour < 13), "lunch must stay free"
        assert s + timedelta(minutes=60) <= s.replace(hour=17, minute=0)


def test_slots_are_spread_across_the_day(cal, now):
    r = find_slots(cal, "cleaning", now, preferred_date="2026-10-13")
    hours = [datetime.fromisoformat(s["start"]).hour for s in r["slots"]]
    assert hours[0] == 8 and hours[-1] >= 15


def test_offered_slots_are_at_least_an_hour_apart(cal, now):
    # Only 8:00-9:00 free in the morning on Tuesday: should offer one Tuesday time, then roll on.
    cal.create_event(Event(start=at(13, 9), end=at(13, 17), provider="hygiene", summary="busy"))
    r = find_slots(cal, "cleaning", now, preferred_date="2026-10-13", time_of_day="morning")
    starts = [datetime.fromisoformat(s["start"]) for s in r["slots"]]
    assert sum(s.day == 13 for s in starts) == 1
    for a, b in zip(starts, starts[1:]):
        assert b - a >= timedelta(minutes=60)


def test_morning_filter(cal, now):
    r = find_slots(cal, "cleaning", now, preferred_date="2026-10-13", time_of_day="morning")
    assert all(datetime.fromisoformat(s["start"]).hour < 12 for s in r["slots"])


def test_weekend_request_rolls_to_monday_with_note(cal, now):
    r = find_slots(cal, "cleaning", now, preferred_date="2026-10-17")  # Saturday
    assert "closed" in r["note"].lower()
    assert datetime.fromisoformat(r["slots"][0]["start"]).date().isoformat() == "2026-10-19"


def test_friday_closes_at_two(cal, now):
    r = find_slots(cal, "new_patient_exam", now, preferred_date="2026-10-16")
    for s in r["slots"]:
        t = datetime.fromisoformat(s["start"])
        if t.date().isoformat() == "2026-10-16":
            assert t + timedelta(minutes=90) <= t.replace(hour=14, minute=0)


def test_busy_hygiene_chair_does_not_block_doctor(cal, now):
    cal.create_event(Event(start=at(13, 8), end=at(13, 17), provider="hygiene", summary="full"))
    hyg = find_slots(cal, "cleaning", now, preferred_date="2026-10-13")
    doc = find_slots(cal, "filling", now, preferred_date="2026-10-13")
    assert not hyg["slots"][0]["start"].startswith("2026-10-13")
    assert hyg["note"].startswith("No openings")
    assert doc["slots"][0]["start"].startswith("2026-10-13")


def test_manual_event_blocks_both_chairs(cal, now):
    cal.create_event(Event(start=at(13, 0), end=at(14, 0), provider="all", summary="Office closed"))
    r = find_slots(cal, "filling", now, preferred_date="2026-10-13")
    assert not r["slots"][0]["start"].startswith("2026-10-13")


def test_holiday_is_closed(cal, now):
    later = datetime(2026, 11, 20, 9, tzinfo=TZ)
    r = find_slots(cal, "cleaning", later, preferred_date="2026-11-26")
    assert "closed" in r["note"].lower()
    assert all(not s["start"].startswith("2026-11-26") for s in r["slots"])


def test_past_date_is_ignored(cal, now):
    r = find_slots(cal, "cleaning", now, preferred_date="2026-10-01")
    assert "passed" in r["note"] and r["slots"]


def test_unknown_service(cal, now):
    with pytest.raises(BookingError):
        find_slots(cal, "root_canal_party", now)


def test_spoken_labels(now):
    assert scheduling.spoken_datetime(at(13, 9, 15), now) == "tomorrow, Tuesday, October 13 at 9:15 AM"
    assert scheduling.spoken_time(at(13, 13)) == "1 PM"


def test_book_happy_path(cal, now):
    r = booking(cal, now, is_new_patient=True, insurance_carrier="Delta Dental PPO")
    assert r["booked"] and len(r["confirmation_code"]) == 4
    assert r["phone"] == "(512) 555-0199" and r["patient_name"] == "Jordan Miles"
    assert r["arrive_early_minutes"] == 15
    ev = cal.list_events(at(13, 0), at(14, 0))
    assert len(ev) == 1 and ev[0].source == "voice-agent" and ev[0].summary == "Cleaning and checkup: Jordan M."


def test_book_is_idempotent(cal, now):
    a = booking(cal, now)
    b = booking(cal, now, phone="+1 (512) 555 0199")
    assert b["already_booked"] and a["confirmation_code"] == b["confirmation_code"]
    assert len(cal.list_events(at(13, 0), at(14, 0))) == 1


def test_double_booking_rejected(cal, now):
    booking(cal, now)
    with pytest.raises(BookingError, match="just taken"):
        booking(cal, now, start="2026-10-13T09:30", phone="5125550100")


@pytest.mark.parametrize("start,msg", [
    ("2026-10-12T10:00", "too soon"),
    ("2026-10-13T12:00", "outside"),     # lunch
    ("2026-10-13T16:30", "outside"),     # runs past close
    ("2026-10-13T09:10", "outside"),     # off the 15-minute grid
    ("2026-10-17T10:00", "outside"),     # Saturday
    ("2027-01-30T10:00", "days ahead"),
    ("next tuesday", "couldn't read"),
])
def test_book_rejects_bad_times(cal, now, start, msg):
    with pytest.raises(BookingError, match=msg):
        booking(cal, now, start=start)


@pytest.mark.parametrize("phone", ["555-0199", "", "12345678901234"])
def test_book_rejects_bad_phone(cal, now, phone):
    with pytest.raises(BookingError, match="ten digits"):
        booking(cal, now, phone=phone)


def test_book_accepts_offset_times(cal, now):
    r = booking(cal, now, start="2026-10-13T14:00:00Z")  # 9 AM Central
    assert r["start"].startswith("2026-10-13T09:00")
