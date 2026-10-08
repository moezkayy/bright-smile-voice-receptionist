"""Seed the clinic calendar with a realistic week of existing appointments.

  python scripts/seed_calendar.py            # mock calendar (data/runtime/calendar.json)
  python scripts/seed_calendar.py --google   # writes events to the Google Calendar in .env
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from receptionist import seed  # noqa: E402
from receptionist.settings import Settings  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--google", action="store_true", help="write to Google Calendar instead of the mock file")
ap.add_argument("--days", type=int, default=14)
args = ap.parse_args()

s = Settings.load()
events = seed.build(seed.today(), days=args.days)
if args.google:
    s.calendar_backend = "google"
    cal = s.calendar()
    for i, e in enumerate(events, 1):
        e.id = ""
        cal.create_event(e)
        print(f"\r{i}/{len(events)} events written", end="", flush=True)
    print()
else:
    from receptionist.calendars.mock import MockCalendar

    cal = MockCalendar(s.runtime_dir / "calendar.json")
    cal.replace_all(events)
    print(f"{len(events)} appointments seeded into {cal.path}")
