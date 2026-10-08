"""Clinic API: the webhook tools the ElevenLabs agent calls, plus the live dashboard.

Run:  uvicorn receptionist.server:app --port 8000
"""

from __future__ import annotations

import hmac
import json
import re
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import clinic, insights, insurance, scheduling
from .calls import CallHistory
from .settings import ROOT, Settings

WEB = ROOT / "web"
# Result fields echoed to the dashboard (never the full phone number).
DETAIL_KEYS = ("status", "carrier", "service", "service_label", "with", "spoken", "confirmation_code", "note",
               "message", "callback_window", "patient_name")


def now() -> datetime:
    return datetime.now(clinic.TIMEZONE)


class AvailabilityIn(BaseModel):
    service: str
    preferred_date: str | None = None
    time_of_day: str = "any"


class BookIn(BaseModel):
    service: str
    start: str
    patient_name: str
    phone: str
    is_new_patient: bool = False
    insurance_carrier: str = ""
    notes: str = ""


class InsuranceIn(BaseModel):
    carrier: str
    plan_type: str = ""


class LiveEventIn(BaseModel):
    type: str = Field(pattern="^(start|message|mode|end)$")
    conversation_id: str = ""
    role: str = ""
    text: str = ""
    mode: str = ""


class CallbackIn(BaseModel):
    patient_name: str
    phone: str
    reason: str
    urgency: str = Field("routine", pattern="^(routine|urgent)$")


def create_app(settings: Settings | None = None, calendar=None, clock=now) -> FastAPI:
    settings = settings or Settings.load()
    calendar = calendar or settings.calendar()
    runtime: Path = settings.runtime_dir
    runtime.mkdir(parents=True, exist_ok=True)
    tasks_file = runtime / "callbacks.json"
    log_file = runtime / "tool_log.jsonl"
    tool_log: deque = deque(maxlen=50)
    if log_file.exists():  # survive restarts: reload the most recent entries
        for line in log_file.read_text().splitlines()[-50:]:
            try:
                tool_log.appendleft(json.loads(line))
            except ValueError:
                pass
    lock = threading.Lock()

    calls = CallHistory(settings.elevenlabs_api_key, settings.agent_id)
    app = FastAPI(title="Bright Smile Dental: clinic API")

    def check_secret(x_tool_secret: str = Header(default="")):
        if settings.tool_secret and not hmac.compare_digest(x_tool_secret, settings.tool_secret):
            raise HTTPException(401, "bad tool secret")

    def record(tool: str, args: dict, result: dict, started: float) -> dict:
        entry = {
            "id": uuid.uuid4().hex[:8],
            "at": clock().isoformat(timespec="seconds"),
            "tool": tool,
            "args": args,
            "ok": result.get("ok", True),
            "summary": result.get("summary", ""),
            "detail": {k: result[k] for k in DETAIL_KEYS if k in result},
            "ms": round((time.perf_counter() - started) * 1000, 1),
        }
        if "slots" in result:
            entry["detail"]["slots"] = [x["spoken"] for x in result["slots"]]
        with lock:
            tool_log.appendleft(entry)
            with log_file.open("a") as f:
                f.write(json.dumps(entry) + "\n")
        return result

    def run(tool: str, args: dict, fn) -> dict:
        started = time.perf_counter()
        try:
            result = {"ok": True, **fn()}
        except scheduling.BookingError as e:
            result = {"ok": False, "message": str(e), "summary": str(e)}
        return record(tool, args, result, started)

    # ---------- tools ----------

    @app.post("/tools/check_availability", dependencies=[Depends(check_secret)])
    def check_availability(body: AvailabilityIn):
        def fn():
            r = scheduling.find_slots(calendar, body.service, clock(), body.preferred_date, body.time_of_day)
            r["summary"] = f"{len(r['slots'])} slots for {r['service_label']}"
            return r
        return run("check_availability", body.model_dump(), fn)

    @app.post("/tools/book_appointment", dependencies=[Depends(check_secret)])
    def book_appointment(body: BookIn):
        def fn():
            r = scheduling.book(
                calendar,
                service_id=body.service,
                start=body.start,
                patient_name=body.patient_name,
                phone=body.phone,
                now=clock(),
                is_new_patient=body.is_new_patient,
                insurance_carrier=body.insurance_carrier,
                notes=body.notes,
            )
            r["summary"] = f"Booked {r['service']} {r['spoken']} (#{r['confirmation_code']})"
            return r
        args = body.model_dump()
        args["phone"] = "***" + re.sub(r"\D", "", body.phone)[-4:]  # keep the log free of full numbers
        return run("book_appointment", args, fn)

    @app.post("/tools/verify_insurance", dependencies=[Depends(check_secret)])
    def verify_insurance(body: InsuranceIn):
        def fn():
            r = insurance.lookup(body.carrier, body.plan_type)
            r["summary"] = f"{r.get('carrier', body.carrier)}: {r['status'].replace('_', ' ')}"
            return r
        return run("verify_insurance", body.model_dump(), fn)

    @app.post("/tools/request_callback", dependencies=[Depends(check_secret)])
    def request_callback(body: CallbackIn):
        def fn():
            digits = scheduling.normalize_phone(body.phone)
            task = {
                "id": uuid.uuid4().hex[:8],
                "created": clock().isoformat(timespec="seconds"),
                "patient_name": " ".join(body.patient_name.split()).title(),
                "phone": scheduling.format_phone(digits),
                "reason": body.reason,
                "urgency": body.urgency,
            }
            with lock:
                tasks = json.loads(tasks_file.read_text()) if tasks_file.exists() else []
                tasks.insert(0, task)
                tasks_file.write_text(json.dumps(tasks, indent=1))
            when = "within 30 minutes" if body.urgency == "urgent" else "by the end of the next business day"
            return {"created": True, "callback_window": when, "summary": f"{body.urgency} callback: {body.reason}"}
        args = body.model_dump()
        args["phone"] = "***" + re.sub(r"\D", "", body.phone)[-4:]
        return run("request_callback", args, fn)

    # ---------- live calls that don't come from the browser (phone line, test caller) ----------

    live: dict = {"active": False, "conversation_id": "", "started": "", "ended": "", "mode": "", "messages": []}

    @app.post("/api/live", dependencies=[Depends(check_secret)])
    def live_event(ev: LiveEventIn):
        with lock:
            if ev.type == "start":
                live.update(active=True, conversation_id=ev.conversation_id, started=clock().isoformat(),
                            ended="", mode="listening", messages=[])
            elif ev.type == "message":
                live["messages"].append({"role": ev.role, "text": ev.text, "at": clock().isoformat()})
            elif ev.type == "mode":
                live["mode"] = ev.mode
            elif ev.type == "end":
                live.update(active=False, ended=clock().isoformat())
        return {"ok": True}

    # ---------- dashboard ----------

    @app.get("/api/state")
    def state():
        t = clock()
        start = datetime.combine(t.date(), datetime.min.time(), clinic.TIMEZONE)
        events = calendar.list_events(start, start + timedelta(days=clinic.MAX_DAYS_AHEAD + 1))
        with lock:
            log = list(tool_log)
            tasks = json.loads(tasks_file.read_text()) if tasks_file.exists() else []
        days = insights.open_days(t.date(), 10)
        last_day = datetime.combine(days[-1] + timedelta(days=1), datetime.min.time(), clinic.TIMEZONE)
        return {
            "now": t.isoformat(timespec="seconds"),
            "calendar": calendar.name,
            "agent_ready": calls.enabled,
            "providers": {k: {"name": p.name, "role": p.role} for k, p in clinic.PROVIDERS.items()},
            "hours": {str(k): [[a.isoformat("minutes"), b.isoformat("minutes")] for a, b in v] for k, v in clinic.HOURS.items()},
            "events": [insights.event_view(e) for e in events if e.start < last_day],
            "kpis": insights.kpis(events, t, log, calls.today(start)),
            "tool_log": log,
            "callbacks": tasks[:10],
            "live": live,
        }

    @app.get("/api/calls/{conversation_id}")
    def call_review(conversation_id: str):
        if not calls.enabled:
            raise HTTPException(400, "Agent not configured.")
        try:
            return calls.review(conversation_id)
        except httpx.HTTPError as e:
            raise HTTPException(502, str(e)) from None

    @app.get("/api/signed-url")
    def signed_url():
        if not (settings.agent_id and settings.elevenlabs_api_key):
            raise HTTPException(400, "Agent not configured. Run scripts/sync_agent.py first.")
        r = httpx.get(
            "https://api.elevenlabs.io/v1/convai/conversation/get-signed-url",
            params={"agent_id": settings.agent_id},
            headers={"xi-api-key": settings.elevenlabs_api_key},
            timeout=10,
        )
        if r.status_code != 200:
            raise HTTPException(502, f"ElevenLabs: {r.text[:200]}")
        return {"signed_url": r.json()["signed_url"]}

    @app.get("/health")
    def health():
        return {"ok": True, "calendar": calendar.name}

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException):
        return JSONResponse({"ok": False, "message": exc.detail}, status_code=exc.status_code)

    @app.middleware("http")
    async def no_cache_dashboard(request: Request, call_next):
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static"):
            response.headers["Cache-Control"] = "no-store"
        return response

    if WEB.exists():
        app.mount("/static", StaticFiles(directory=WEB), name="static")

        @app.get("/")
        def index():
            return FileResponse(WEB / "index.html")

    return app


def __getattr__(name):  # `uvicorn receptionist.server:app`, built lazily so tests can import freely
    if name == "app":
        globals()["app"] = create_app()
        return globals()["app"]
    raise AttributeError(name)
