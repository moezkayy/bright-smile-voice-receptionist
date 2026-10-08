import pytest
from fastapi.testclient import TestClient

from receptionist.server import create_app
from receptionist.settings import Settings

from .conftest import NOW


@pytest.fixture
def client(tmp_path, cal):
    s = Settings(
        calendar_backend="mock", tool_secret="s3cret", elevenlabs_api_key="", agent_id="",
        google_service_account_file="", google_calendar_id="", public_base_url="", runtime_dir=tmp_path,
    )
    return TestClient(create_app(s, calendar=cal, clock=lambda: NOW))


H = {"X-Tool-Secret": "s3cret"}


def test_tools_require_secret(client):
    assert client.post("/tools/verify_insurance", json={"carrier": "Delta"}).status_code == 401
    assert client.post("/tools/verify_insurance", json={"carrier": "Delta"}, headers={"X-Tool-Secret": "x"}).status_code == 401


def test_full_call_flow(client):
    ins = client.post("/tools/verify_insurance", json={"carrier": "Delta Dental"}, headers=H).json()
    assert ins["status"] == "in_network"

    slots = client.post("/tools/check_availability", json={"service": "cleaning", "preferred_date": "2026-10-13",
                                                           "time_of_day": "morning"}, headers=H).json()
    first = slots["slots"][0]["start"]

    booked = client.post("/tools/book_appointment", headers=H, json={
        "service": "cleaning", "start": first, "patient_name": "Jordan Miles", "phone": "5125550199",
        "is_new_patient": False, "insurance_carrier": "Delta Dental PPO"}).json()
    assert booked["ok"] and booked["booked"]

    state = client.get("/api/state").json()
    assert any(e["source"] == "voice-agent" for e in state["events"])
    assert [t["tool"] for t in state["tool_log"]] == ["book_appointment", "check_availability", "verify_insurance"]
    assert "5125550199" not in str(state["tool_log"]), "full phone numbers stay out of the log"


def test_rule_violation_is_a_readable_tool_result(client):
    r = client.post("/tools/book_appointment", headers=H, json={
        "service": "cleaning", "start": "2026-10-13T12:00", "patient_name": "Jo Li", "phone": "5125550199"})
    assert r.status_code == 200 and r.json()["ok"] is False and "hours" in r.json()["message"]


def test_callback_queue(client):
    r = client.post("/tools/request_callback", headers=H, json={
        "patient_name": "sam lee", "phone": "512 555 0111", "reason": "billing question", "urgency": "routine"}).json()
    assert r["created"]
    cb = client.get("/api/state").json()["callbacks"][0]
    assert cb["patient_name"] == "Sam Lee" and cb["phone"] == "(512) 555-0111"


def test_signed_url_needs_agent(client):
    assert client.get("/api/signed-url").status_code == 400
