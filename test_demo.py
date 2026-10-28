"""Demo tests: synthetic session integrity + clip/replay serving.

Spawns server.py (MOCK_LLM=1), feeds demo/script.json turns like the
browser would, then checks:
  1. every fact links to a real clip slice (file exists, 0<=start<end<=wav
     duration), kinds are valid, and the stub surfaces the demo's people so
     the family map fills in;
  2. GET /api/clip serves byte-identical audio, rejects unknown/traversal
     clip ids with 404, and index.html carries the ?session= replay hook.

Usage: python3 test_demo.py
"""

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "demo"))
from replay import post, silent_wav_b64  # noqa: E402  (stdlib-only helpers)

PORT = "18082"
BASE = f"http://127.0.0.1:{PORT}"
SCRIPT = json.loads((ROOT / "demo" / "script.json").read_text())


def wav_duration(path):
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate() or 1)


def main():
    env = dict(os.environ, MOCK_LLM="1", PORT=PORT)
    srv = subprocess.Popen(
        [sys.executable, "server.py"], env=env, cwd=str(ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    sid = f"demo-test-{int(time.time())}"
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(BASE + "/", timeout=2).read()
                break
            except Exception:
                time.sleep(0.2)

        history, all_facts = [], []
        for turn in SCRIPT["turns"]:
            dur = max(s["end"] for s in turn["segments"])
            audio = silent_wav_b64(dur)
            status, data = post(BASE, "/api/turn", {
                "session_id": sid,
                "audio_b64": audio,
                "history": history,
                "transcript": turn["transcript"],
                "segments": turn["segments"],
            })
            assert status == 200, data
            assert data["facts"], f"expected facts for turn: {turn['transcript'][:40]}"
            all_facts.extend(data["facts"])
            history.append({"role": "user", "text": turn["transcript"]})

        # Test 1: every fact cites a real clip slice within the wav bounds.
        session_dir = ROOT / "recordings" / sid
        seg_ids = {s["id"] for t in SCRIPT["turns"] for s in t["segments"]}
        people = set()
        for f in all_facts:
            assert f["kind"] in ("person", "place", "event", "relationship"), f
            clip = session_dir / f"{f['clip_id']}.wav"
            assert clip.is_file(), f"missing clip file for {f}"
            length = wav_duration(clip)
            assert 0.0 <= f["start"] < f["end"] <= length, (f, length)
            assert f["segment_id"] in seg_ids, f
            people.update(f.get("people", []))
        assert {"Aunt Rosa", "Grandpa Emil"} <= people, (
            f"map people missing: {sorted(people)}"
        )
        print(f"TEST 1 OK: {len(all_facts)} facts link to real clip slices; "
              f"map people={sorted(people)}")

        # Test 2: clip serving + replay contract.
        first = all_facts[0]
        with urllib.request.urlopen(
            f"{BASE}/api/clip?session_id={sid}&clip_id={first['clip_id']}",
            timeout=15,
        ) as resp:
            assert resp.status == 200, resp.status
            assert resp.headers.get("Content-Type") == "audio/wav"
            served = resp.read()
        raw = (session_dir / f"{first['clip_id']}.wav").read_bytes()
        assert served == raw, "clip bytes must match stored wav"

        for bad in ("nosuchclip",
                    "session_id=%s&clip_id=..%%2F..%%2Fserver" % sid,
                    "session_id=&clip_id="):
            try:
                urllib.request.urlopen(f"{BASE}/api/clip?{bad}", timeout=15)
                raise AssertionError(f"expected 404 for ?{bad}")
            except urllib.error.HTTPError as e:
                assert e.code == 404, (bad, e.code)

        html = (ROOT / "index.html").read_text()
        assert "URLSearchParams" in html and "/api/clip" in html, \
            "frontend must carry the ?session= replay hook"
        print("TEST 2 OK: /api/clip serves exact bytes, 404s clean, replay hook present")
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()
        shutil.rmtree(ROOT / "recordings" / sid, ignore_errors=True)


if __name__ == "__main__":
    main()
