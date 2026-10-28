"""Smoke test: stubbed LLM (MOCK_LLM=1) proves fact->clip linkage shape.

Starts server.py as a subprocess on a free port, POSTs one turn with
transcript segments, asserts every fact cites clip_id+start+end and a
valid kind enum, and prints the observed payloads.
Usage: python3 test_smoke.py
"""

import json
import os
import subprocess
import sys
import time
import urllib.request

PORT = "18081"
BASE = f"http://127.0.0.1:{PORT}"


def post(path, obj):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(obj).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.status, json.loads(resp.read().decode())


def main():
    env = dict(os.environ, MOCK_LLM="1", PORT=PORT)
    srv = subprocess.Popen(
        [sys.executable, "server.py"], env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(BASE + "/", timeout=2).read()
                break
            except Exception:
                time.sleep(0.2)
        sid = f"smoke-{int(time.time())}"
        status, turn = post("/api/turn", {
            "session_id": sid,
            "audio_b64": "",
            "history": [{"role": "user", "text": "I grew up in Lisbon with Ana."}],
            "transcript": "I grew up in Lisbon with Ana.",
            "segments": [
                {"id": "seg-0", "text": "I grew up in Lisbon", "start": 0.0, "end": 2.5},
                {"id": "seg-1", "text": "with Ana.", "start": 2.5, "end": 4.0},
            ],
        })
        print("POST /api/turn status:", status)
        print("POST /api/turn body:", json.dumps(turn, indent=2))
        assert status == 200, turn
        assert isinstance(turn.get("question"), str) and turn["question"], "missing question"
        facts = turn.get("facts")
        assert isinstance(facts, list) and facts, "expected >=1 stubbed fact"
        for f in facts:
            assert f.get("kind") in ("person", "place", "event", "relationship"), f
            assert isinstance(f.get("text"), str) and f["text"], f
            assert isinstance(f.get("clip_id"), str) and f["clip_id"].startswith("clip-"), f
            assert isinstance(f.get("start"), (int, float)), f
            assert isinstance(f.get("end"), (int, float)), f
            assert f.get("segment_id") in ("seg-0", "seg-1"), f
        req = urllib.request.Request(
            BASE + f"/api/facts?session_id={sid}", method="GET"
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            saved = json.loads(resp.read().decode())
        print("GET /api/facts body:", json.dumps(saved, indent=2))
        assert saved.get("facts") == facts, "persisted facts must match turn facts"
        print("SMOKE OK: fact->clip linkage shape verified "
              f"({len(facts)} fact(s), clip {facts[0]['clip_id']})")
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()


if __name__ == "__main__":
    main()
