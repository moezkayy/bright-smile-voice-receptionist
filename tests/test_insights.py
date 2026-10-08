import random
from datetime import datetime

from receptionist import clinic, insights, seed
from receptionist.scheduling import book, find_slots

from .conftest import NOW


def test_kpis_count_only_rileys_bookings_today(cal):
    cal.replace_all(seed.build(NOW.date(), days=14))
    slot = find_slots(cal, "new_patient_exam", NOW)["slots"][0]["start"]
    book(cal, service_id="new_patient_exam", start=slot, patient_name="Priya Shah",
         phone="7375550142", now=NOW, is_new_patient=True, rng=random.Random(2))
    events = cal.list_events(NOW.replace(hour=0), NOW.replace(day=30))
    k = insights.kpis(events, NOW, [{"at": NOW.isoformat(), "ms": 3.0}], {"calls": 2, "avg_secs": 95})
    assert k["booked_today"] == 1 and k["new_patients_today"] == 1
    assert k["production_today"] == clinic.SERVICES["new_patient_exam"].fee
    assert 0 < k["utilization"] < 100 and len(k["days"]) == 10
    assert k["calls_today"] == 2 and k["tool_median_ms"] == 3.0


def test_event_view_has_codes_and_flags(cal):
    r = book(cal, service_id="cleaning", start="2026-10-13T09:00", patient_name="Jordan Miles",
             phone="5125550199", now=NOW, insurance_carrier="Delta Dental PPO", rng=random.Random(1))
    e = cal.list_events(datetime.fromisoformat(r["start"]), datetime.fromisoformat(r["start"]).replace(hour=23))[0]
    v = insights.event_view(e)
    assert v["cdt"] == ["D0120", "D1110", "D0274"] and v["category"] == "preventive"
    assert v["source"] == "voice-agent" and v["insurance"] == "Delta Dental PPO" and v["booked_at"]
