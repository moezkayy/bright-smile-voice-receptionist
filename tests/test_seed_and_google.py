from datetime import date, datetime, timedelta

from receptionist import seed
from receptionist.calendars.base import Event
from receptionist.calendars.google import from_google, to_google
from receptionist.scheduling import TZ, _conflicts, find_slots

from .conftest import NOW


def test_seed_is_realistic_and_conflict_free():
    events = seed.build(date(2026, 10, 12), days=14)
    assert len(events) > 60
    for i, e in enumerate(events):
        others = events[:i] + events[i + 1:]
        assert not _conflicts(e.start, e.end, e.provider, others)
    assert seed.build(date(2026, 10, 12)) == seed.build(date(2026, 10, 12)), "deterministic"


def test_seeded_calendar_still_has_openings(cal):
    cal.replace_all(seed.build(NOW.date(), days=14))
    r = find_slots(cal, "cleaning", NOW, preferred_date="2026-10-13")
    assert len(r["slots"]) == 3


def test_google_round_trip():
    e = Event(start=datetime(2026, 10, 13, 9, tzinfo=TZ), end=datetime(2026, 10, 13, 10, tzinfo=TZ),
              provider="hygiene", summary="Cleaning: Jordan M.", service="cleaning",
              patient_name="Jordan Miles", phone="5125550199", confirmation="4821", source="voice-agent")
    g = to_google(e)
    g["id"] = "abc"
    back = from_google(g)
    assert (back.provider, back.service, back.phone, back.confirmation, back.start) == \
           ("hygiene", "cleaning", "5125550199", "4821", e.start)


def test_google_manual_and_all_day_events_block_everything():
    manual = from_google({"id": "m", "summary": "Staff meeting",
                          "start": {"dateTime": "2026-10-13T08:00:00-05:00"},
                          "end": {"dateTime": "2026-10-13T09:00:00-05:00"}})
    allday = from_google({"id": "d", "summary": "Closed", "start": {"date": "2026-10-14"}, "end": {"date": "2026-10-15"}})
    assert manual.provider == "all" and allday.provider == "all"
    assert allday.end - allday.start == timedelta(days=1)
