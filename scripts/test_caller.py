"""Place a real test call to the live agent with a synthetic caller voice.

The caller's lines are spoken with ElevenLabs text-to-speech and streamed into
the conversation like a microphone, in real time. The caller listens to what
Riley says and picks its next line from a small script (insurance → booking →
details → confirm → goodbye). Everything Riley says, every tool call and the
booking are real.

  python scripts/test_caller.py                 # call, mirror it on the dashboard
  python scripts/test_caller.py --out media/call  # also save a synced WAV + transcript

Outputs (with --out): call.wav (both voices, 16 kHz mono), call.json (turns with
wall-clock times, conversation id). Needs ELEVENLABS_API_KEY and an agent
created with scripts/sync_agent.py.
"""

import argparse
import asyncio
import base64
import json
import os
import re
import ssl
import sys
import time
import wave
from array import array
from pathlib import Path

import certifi
import httpx
import websockets

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from receptionist.settings import AGENT_STATE, RUNTIME  # noqa: E402

API = "https://api.elevenlabs.io"
RATE = 16000  # pcm_16000 in and out
CHUNK = 1600  # 100 ms of 16-bit mono
TAGS = re.compile(r"\[[a-z ]+\]\s*")  # expressive audio tags, e.g. "[happy]"
CALLER_VOICE = "iP95p4xoKVk53GoZ742B"  # "Chris: charming, down-to-earth" (premade)

LINES = {
    "open": "Hi! Do you guys take Delta Dental?",
    "book": "Oh great, it's the PPO. Could I book a cleaning next week? Mornings are best for me.",
    "existing": "Yes, I've been there before.",
    "pick": "The first one works for me.",
    "details": "Sure, it's Jordan Miles. Five one two, five five five, zero one nine nine.",
    "name": "It's Jordan Miles.",
    "phone": "Five one two, five five five, zero one nine nine.",
    "yes": "Yes, please.",
    "right": "Yes, that's right.",
    "bye": "No, that's everything. Thanks so much!",
}


def next_line(agent_text: str, said: set) -> str | None:
    t = agent_text.lower()
    if "open" not in said:
        return "open"
    if "book" not in said:
        return "book"
    if re.search(r"been (to see us|here|in|with us) before|new patient|first visit|visited", t) and "existing" not in said:
        return "existing"
    if re.search(r"confirmation (code|number)|you're all set|you are all set|booked", t) or "anything else" in t:
        return "bye"
    asks_name = re.search(r"(full |your )?name", t)
    asks_phone = re.search(r"phone|number to reach|best number|contact", t)
    if asks_name and asks_phone and "details" not in said:
        return "details"
    if asks_name and "details" not in said and "name" not in said:
        return "name"
    if asks_phone and "details" not in said and "phone" not in said:
        return "phone"
    if re.search(r"\b(am|pm)\b", t) and re.search(r"\bor\b|which|work", t) and "pick" not in said:
        return "pick"
    if re.search(r"is that (right|correct)", t) and not re.search(r"book|schedul|appointment", t):
        return "right"
    if re.search(r"shall i|should i|does that|is that (right|correct)|sound good|book (it|that)|go ahead|confirm", t):
        return "yes"
    return None


def tts(key: str, text: str, cache: Path) -> bytes:
    f = cache / (re.sub(r"\W+", "_", text.lower())[:60] + ".pcm")
    if f.exists():
        return f.read_bytes()
    r = httpx.post(f"{API}/v1/text-to-speech/{CALLER_VOICE}", params={"output_format": "pcm_16000"},
                   headers={"xi-api-key": key}, json={"text": text, "model_id": "eleven_flash_v2_5"}, timeout=60)
    r.raise_for_status()
    cache.mkdir(parents=True, exist_ok=True)
    f.write_bytes(r.content)
    return r.content


class Track:
    """Builds the call's audio on a wall-clock timeline so it lines up with the screen recording."""

    def __init__(self, t0: float):
        self.t0 = t0
        self.buf = array("h")

    def place(self, at: float, pcm: bytes):
        start = max(0, int((at - self.t0) * RATE))
        samples = array("h")
        samples.frombytes(pcm[: len(pcm) - len(pcm) % 2])
        end = start + len(samples)
        if len(self.buf) < end:
            self.buf.extend([0] * (end - len(self.buf)))
        for i, v in enumerate(samples):
            s = self.buf[start + i] + v
            self.buf[start + i] = max(-32768, min(32767, s))

    def save(self, path: Path):
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(self.buf.tobytes())


async def run(args):
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    key = os.environ["ELEVENLABS_API_KEY"]
    secret = os.getenv("TOOL_SECRET", "")
    agent_id = json.loads(AGENT_STATE.read_text())["agent_id"]
    dash = httpx.AsyncClient(base_url=args.dashboard, headers={"X-Tool-Secret": secret}, timeout=5)

    async def mirror(**ev):
        try:
            await dash.post("/api/live", json=ev)
        except httpx.HTTPError:
            pass

    cache = RUNTIME / "caller-voice"
    audio = {k: tts(key, v, cache) for k, v in LINES.items()}
    url = httpx.get(f"{API}/v1/convai/conversation/get-signed-url", params={"agent_id": agent_id},
                    headers={"xi-api-key": key}, timeout=10).json()["signed_url"]

    t0 = time.time()
    track = Track(t0)
    turns: list[dict] = []
    said: set = set()
    outbox: list[bytes] = []  # caller audio waiting to be streamed
    state = {"heard_audio": True, "last_rx": time.time(), "agent_until": 0.0, "last_agent_text": "", "agent_turn_text": "", "done": False, "cid": "",
             "await_reply": True, "speaking": False}

    async with websockets.connect(url, max_size=None, ssl=ssl.create_default_context(cafile=certifi.where())) as ws:
        await ws.send(json.dumps({"type": "conversation_initiation_client_data"}))

        async def mic():
            """Stream 100 ms frames in real time: caller speech when queued, else silence."""
            nxt = time.time()
            while not state["done"]:
                if outbox:
                    frame = outbox[0][:CHUNK * 2]
                    outbox[0] = outbox[0][CHUNK * 2:]
                    if not outbox[0]:
                        outbox.pop(0)
                    frame = frame.ljust(CHUNK * 2, b"\0")
                else:
                    frame = bytes(CHUNK * 2)
                await ws.send(json.dumps({"user_audio_chunk": base64.b64encode(frame).decode()}))
                nxt += CHUNK / RATE
                await asyncio.sleep(max(0, nxt - time.time()))

        def say(line: str):
            pcm = audio[line]
            start = time.time() + 0.05
            track.place(start, pcm)
            outbox.append(pcm + bytes(int(RATE * 0.4) * 2))  # trailing pause so the turn ends cleanly
            said.add(line)
            state["await_reply"] = True
            turns.append({"role": "user", "line": line, "text": LINES[line], "t": round(start - t0, 2),
                          "dur": round(len(pcm) / 2 / RATE, 2)})
            print(f"{start - t0:6.1f}s  Caller: {LINES[line]}")

        async def turn_taker():
            """When Riley has finished speaking (in real playback time), answer."""
            while not state["done"]:
                await asyncio.sleep(0.1)
                now = time.time()
                quiet = now > state["agent_until"] + 0.9 and now > state["last_rx"] + 1.2
                if state["speaking"] and now > state["agent_until"]:
                    state["speaking"] = False
                    await mirror(type="mode", mode="listening")
                # The text of a reply arrives before its audio: only answer once that audio has played.
                if not (quiet and (state["heard_audio"] or now > state["last_rx"] + 4) and state["await_reply"] and state["agent_turn_text"] and not outbox):
                    continue
                line = next_line(state["agent_turn_text"], said)
                state["agent_turn_text"] = ""
                if line:
                    state["await_reply"] = False
                    say(line)

        async def receive():
            async for raw in ws:
                ev = json.loads(raw)
                kind = ev.get("type")
                if kind == "conversation_initiation_metadata":
                    state["cid"] = ev["conversation_initiation_metadata_event"]["conversation_id"]
                    await mirror(type="start", conversation_id=state["cid"])
                    print(f"conversation {state['cid']}")
                elif kind == "ping":
                    e = ev["ping_event"]
                    await asyncio.sleep((e.get("ping_ms") or 0) / 1000)
                    await ws.send(json.dumps({"type": "pong", "event_id": e["event_id"]}))
                elif kind == "audio":
                    pcm = base64.b64decode(ev["audio_event"]["audio_base_64"])
                    state["last_rx"] = time.time()
                    state["heard_audio"] = True
                    at = max(time.time(), state["agent_until"])
                    track.place(at, pcm)
                    state["agent_until"] = at + len(pcm) / 2 / RATE
                    if not state["speaking"]:
                        state["speaking"] = True
                        await mirror(type="mode", mode="speaking")
                elif kind == "agent_response":
                    text = TAGS.sub("", ev["agent_response_event"]["agent_response"]).strip()
                    state["last_rx"] = time.time()
                    state["heard_audio"] = False
                    state["agent_turn_text"] = (state["agent_turn_text"] + " " + text).strip()
                    turns.append({"role": "agent", "text": text, "t": round(max(time.time(), state["agent_until"]) - t0, 2)})
                    await mirror(type="message", role="agent", text=text)
                    print(f"{time.time() - t0:6.1f}s  Riley:  {text}")
                elif kind == "user_transcript":
                    text = ev["user_transcription_event"]["user_transcript"]
                    if text.strip():
                        await mirror(type="message", role="user", text=text)
                elif kind == "interruption":
                    print("  (interruption)")
                elif kind == "agent_tool_response":
                    print(f"         tool → {ev['agent_tool_response'].get('tool_name')}")

        tasks = [asyncio.create_task(c()) for c in (mic, turn_taker)]
        try:
            await asyncio.wait_for(receive(), timeout=args.max_secs)
        except (websockets.ConnectionClosed, asyncio.TimeoutError):
            pass
        # Let Riley's last words finish playing on the timeline.
        await asyncio.sleep(max(0, state["agent_until"] - time.time()) + 0.5)
        state["done"] = True
        for t in tasks:
            t.cancel()

    await mirror(type="end", conversation_id=state["cid"])
    print(f"call ended after {time.time() - t0:.1f}s")
    if args.out:
        out = ROOT / args.out
        out.mkdir(parents=True, exist_ok=True)
        track.save(out / "call.wav")
        (out / "call.json").write_text(json.dumps(
            {"conversation_id": state["cid"], "t0_epoch": t0, "turns": turns}, indent=1))
        print(f"saved {args.out}/call.wav and call.json")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="")
    ap.add_argument("--dashboard", default="http://localhost:8000")
    ap.add_argument("--max-secs", type=float, default=180)
    asyncio.run(run(ap.parse_args()))
