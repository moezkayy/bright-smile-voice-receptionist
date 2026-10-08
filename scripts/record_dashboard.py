"""Record the dashboard at 1920x1080 with headless Chrome (DevTools screencast).

  python scripts/record_dashboard.py --secs 190 --frames /tmp/frames --out media/call/dashboard.mp4

Every frame is saved with its wall-clock time, then stitched into a constant
30 fps video, so it lines up with test_caller.py's audio (same clock).
"""

import argparse
import asyncio
import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
import websockets

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9333


async def record(url: str, secs: float, frames: Path) -> list[tuple[float, str]]:
    profile = tempfile.mkdtemp(prefix="chrome-rec-")
    proc = subprocess.Popen([
        CHROME, "--headless=new", f"--remote-debugging-port={PORT}", f"--user-data-dir={profile}",
        "--window-size=1920,1080", "--hide-scrollbars", "--force-device-scale-factor=1",
        "--autoplay-policy=no-user-gesture-required", "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                targets = httpx.get(f"http://127.0.0.1:{PORT}/json").json()
                page = next(t for t in targets if t["type"] == "page")
                break
            except (httpx.HTTPError, StopIteration):
                await asyncio.sleep(0.2)
        shots: list[tuple[float, str]] = []
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=None) as ws:
            n = 0

            async def send(method, **params):
                nonlocal n
                n += 1
                await ws.send(json.dumps({"id": n, "method": method, "params": params}))

            await send("Emulation.setDeviceMetricsOverride", width=1920, height=1080, deviceScaleFactor=1, mobile=False)
            await send("Page.enable")
            await send("Page.navigate", url=url)
            await asyncio.sleep(2.5)
            await send("Page.startScreencast", format="jpeg", quality=92, maxWidth=1920, maxHeight=1080, everyNthFrame=1)
            print(f"recording {url} for {secs:.0f}s (started {time.time():.2f})", flush=True)
            end = time.time() + secs
            while time.time() < end:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                msg = json.loads(raw)
                if msg.get("method") == "Page.screencastFrame":
                    p = msg["params"]
                    f = frames / f"{len(shots):06d}.jpg"
                    f.write_bytes(base64.b64decode(p["data"]))
                    shots.append((p["metadata"]["timestamp"], f.name))
                    await send("Page.screencastFrameAck", sessionId=p["sessionId"])
            await send("Page.stopScreencast")
        return shots
    finally:
        proc.terminate()
        shutil.rmtree(profile, ignore_errors=True)


def stitch(shots, frames: Path, out: Path, ffmpeg: str) -> float:
    """Constant 30 fps video: each output frame shows the latest screencast frame at that moment."""
    t0 = shots[0][0]
    lines = []
    for (t, name), (t_next, _) in zip(shots, shots[1:] + [(shots[-1][0] + 1 / 30, "")]):
        lines.append(f"file '{frames / name}'\nduration {max(t_next - t, 0.001):.4f}")
    lines.append(f"file '{frames / shots[-1][1]}'")
    lst = frames / "list.txt"
    lst.write_text("\n".join(lines))
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-fps_mode", "cfr", "-r", "30", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-crf", "16", "-preset", "medium", str(out)], check=True,
                   env={**os.environ, "DYLD_LIBRARY_PATH": str(Path(ffmpeg).resolve().parent)})  # Remotion's bundled ffmpeg
    return t0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--secs", type=float, default=180)
    ap.add_argument("--frames", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ffmpeg", default="ffmpeg")
    a = ap.parse_args()
    frames = Path(a.frames)
    frames.mkdir(parents=True, exist_ok=True)
    shots = asyncio.run(record(a.url, a.secs, frames))
    t0 = stitch(shots, frames, Path(a.out), a.ffmpeg)
    meta = Path(a.out).with_suffix(".json")
    meta.write_text(json.dumps({"video_t0_epoch": t0, "frames": len(shots)}, indent=1))
    print(f"{len(shots)} frames → {a.out} (t0 {t0:.2f})")
