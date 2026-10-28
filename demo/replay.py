"""Replay the synthetic demo: feed demo/script.json through a MOCK_LLM server.

Generates a silent .wav per turn (stdlib `wave`; duration covers the last
segment end), POSTs each turn to /api/turn exactly like the browser would
after STT, then keeps the server up so the session replays in the UI.

All persons/places/events are fictional (see script.json). No mic, no keys,
no network needed. Clips land in recordings/demo-synthetic/ (gitignored).

Usage:
    python3 demo/replay.py [--port 8000]

Then open:  http://127.0.0.1:8000/?session=demo-synthetic
Ctrl-C stops the server.
"""

import argparse
import base64
import io
import json
import os
import subprocess
import sys
import time
import urllib.request
import wave
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent
ROOT = DEMO_DIR.parent
SAMPLE_RATE = 16000


def silent_wav_b64(duration_s):
    """Silent mono 16-bit WAV, base64-encoded, of at least duration_s."""
    n = max(1, int(SAMPLE_RATE * (duration_s + 1.0)))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(b"\x00\x00" * n)
    return base64.b64encode(buf.getvalue()).decode()


def post(base, path, obj):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(obj).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.status, json.loads(resp.read().decode())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="8000")
    args = ap.parse_args()
    base = f"http://127.0.0.1:{args.port}"

    script = json.loads((DEMO_DIR / "script.json").read_text())
    session_id = script["session_id"]

    env = dict(os.environ, MOCK_LLM="1", PORT=str(args.port))
    srv = subprocess.Popen(
        [sys.executable, str(ROOT / "server.py")],
        env=env, cwd=str(ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(base + "/", timeout=2).read()
                break
            except Exception:
                time.sleep(0.2)

        history = []
        for i, turn in enumerate(script["turns"]):
            segs = turn["segments"]
            dur = max(s["end"] for s in segs)
            status, data = post(base, "/api/turn", {
                "session_id": session_id,
                "audio_b64": silent_wav_b64(dur),
                "history": history,
                "transcript": turn["transcript"],
                "segments": segs,
            })
            assert status == 200, data
            print(f"--- turn {i + 1} ---")
            print("YOU:", turn["transcript"])
            print("Q:  ", data["question"])
            for f in data["facts"]:
                print(f"  [{f['kind']}] {f['text']} "
                      f"({f['clip_id']} {f['start']}-{f['end']}s)")
            history.append({"role": "user", "text": turn["transcript"]})
            history.append({"role": "assistant", "text": data["question"]})

        print()
        print(f"Demo session ready: {base}/?session={session_id}")
        print("Press Ctrl-C to stop the server.")
        srv.wait()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()


if __name__ == "__main__":
    main()
