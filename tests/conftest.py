from datetime import datetime

import pytest

from receptionist import clinic
from receptionist.calendars.mock import MockCalendar

# Monday 12 October 2026, 9:00 AM in Austin.
NOW = datetime(2026, 10, 12, 9, 0, tzinfo=clinic.TIMEZONE)


@pytest.fixture
def cal(tmp_path):
    return MockCalendar(tmp_path / "calendar.json")


@pytest.fixture
def now():
    return NOW
