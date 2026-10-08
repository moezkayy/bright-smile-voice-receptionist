"""Mock mode: replay a scripted call against the clinic API (no keys, no ElevenLabs).

Start the server first (uvicorn receptionist.server:app --app-dir src), open
http://localhost:8000, then run this. The tool calls are the real ones the agent
makes, so the dashboard fills exactly as it does on a live call.
"""

import os
import sys
import time

import httpx

BASE = os.getenv("CLINIC_URL", "http://localhost:8000")
PAUSE = float(os.getenv("PAUSE", "1.5"))
headers = {"X-Tool-Secret": os.getenv("TOOL_SECRET", "")}


def say(who, text):
    print(f"{who:>7}: {text}")
    time.sleep(PAUSE)


def tool(name, **args):
    r = httpx.post(f"{BASE}/tools/{name}", json=args, headers=headers, timeout=10)
    r.raise_for_status()
    body = r.json()
    print(f"   tool → {name}: {body.get('summary') or body.get('message')}")
    time.sleep(PAUSE / 2)
    return body


def main():
    try:
        httpx.get(f"{BASE}/health", timeout=3)
    except httpx.HTTPError:
        sys.exit(f"Clinic API not running at {BASE}")

    say("Riley", "Thanks for calling Bright Smile Dental, this is Riley. How can I help you today?")
    say("Caller", "Hi, do you take Delta Dental?")
    ins = tool("verify_insurance", carrier="Delta Dental")
    say("Riley", ins["answer"])
    say("Caller", "It's the PPO. Great. Can I book a cleaning next week, mornings if possible?")
    say("Riley", "Of course. Have you been to see us before?")
    say("Caller", "Yes, about a year ago.")
    slots = tool("check_availability", service="cleaning", preferred_date="", time_of_day="morning")
    options = slots["slots"][:2]
    say("Riley", "I have " + " or ".join(s["spoken"] for s in options) + ". Which works better?")
    pick = options[0]
    say("Caller", "The first one.")
    say("Riley", "Great. Can I get your full name and the best number to reach you?")
    say("Caller", "Jordan Miles, 512-555-0199.")
    say("Riley", f"Thanks, Jordan. That's five one two, five five five, zero one nine nine. A cleaning {pick['spoken']}. Shall I book it?")
    say("Caller", "Yes please.")
    b = tool("book_appointment", service="cleaning", start=pick["start"], patient_name="Jordan Miles",
             phone="5125550199", is_new_patient=False, insurance_carrier="Delta Dental PPO")
    say("Riley", f"You're all set for {b['spoken']} with {b['with']}. Your confirmation code is "
                 f"{b['confirmation_code_spoken']}. Please arrive 5 minutes early. Anything else?")
    say("Caller", "No, that's it. Thanks!")
    say("Riley", "Have a great day, Jordan. Bye!")


if __name__ == "__main__":
    main()
