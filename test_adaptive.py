"""Adaptive-interview tests: threads open/cover, gentle pause, resume_from.

Spawns server.py (MOCK_LLM=1, stdlib only), drives /api/turn like the
browser would, and asserts exact response shapes (not just 200s):
  A. turn 1 mentioning a person opens a thread; the follow-up asks about it.
  B. re-mentioning that person covers the thread; the question falls back
     to the deterministic cycle.
  C. pause_suggested is false early, true after 6 turns, and true on a
     tiredness cue ("I'm tired, let's stop").
  D. resume_from copies open threads + facts into a fresh session and the
     opening question references the carried thread.
  E. resume_from an unknown id starts clean (no error, no threads).
Usage: python3 test_adaptive.py
"""

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = "18083"
BASE = f"http://127.0.0.1:{PORT}"

CYCLE = [
    "Where did you grow up, and what do you remember most about it?",
    "Can you tell me about a person who shaped your childhood?",
    "What is a moment you are proud of that we should record?",
]


def post(path, obj):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(obj).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.status, json.loads(resp.read().decode())


def get_threads(sid):
    with urllib.request.urlopen(
        BASE + f"/api/threads?session_id={sid}", timeout=15
    ) as resp:
        return json.loads(resp.read().decode())


def check_shape(data):
    assert isinstance(data.get("question"), str) and data["question"], data
    assert isinstance(data.get("facts"), list), data
    assert isinstance(data.get("threads"), list), data
    for t in data["threads"]:
        assert set(("id", "text", "segment_id", "status")) <= set(t), t
        assert t["status"] in ("open", "covered"), t
    assert isinstance(data.get("threads_opened"), list), data
    assert isinstance(data.get("threads_covered"), list), data
    assert data.get("pause_suggested") is False or data.get(
        "pause_suggested") is True, data
    assert data.get("fallback") is False, data


def turn(sid, text, history, extra=None):
    body = {
        "session_id": sid,
        "audio_b64": "",
        "history": history,
        "transcript": text,
        "segments": [{"id": "seg-0", "text": text, "start": 0.0, "end": 1.0}],
    }
    if extra:
        body.update(extra)
    st, data = post("/api/turn", body)
    assert st == 200, data
    check_shape(data)
    return data


def main():
    env = dict(os.environ, MOCK_LLM="1", PORT=PORT)
    srv = subprocess.Popen(
        [sys.executable, "server.py"], env=env, cwd=str(ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    stamp = f"{int(time.time())}-{os.getpid()}"
    sids = []
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(BASE + "/", timeout=2).read()
                break
            except Exception:
                time.sleep(0.2)

        # A+B: open on turn 1, covered on turn 2.
        sid = f"adapt-ab-{stamp}"
        sids.append(sid)
        hist = []
        t1 = "I grew up with Aunt Rosa on the farm."
        d1 = turn(sid, t1, hist)
        assert d1["threads_opened"] == ["th-aunt-rosa"], d1
        assert d1["threads_covered"] == [], d1
        assert len(d1["threads"]) == 1, d1
        assert d1["threads"][0] == {
            "id": "th-aunt-rosa", "text": "Aunt Rosa",
            "segment_id": "seg-0", "status": "open"}, d1["threads"]
        assert "Aunt Rosa" in d1["question"], d1
        assert d1["pause_suggested"] is False, d1
        kinds = {f["kind"] for f in d1["facts"]}
        assert "person" in kinds, d1["facts"]
        assert any(f["text"] == "Aunt Rosa" for f in d1["facts"]
                   if f["kind"] == "person"), d1["facts"]
        hist.append({"role": "user", "text": t1})

        t2 = "Aunt Rosa taught me to bake bread every Sunday."
        d2 = turn(sid, t2, hist)
        assert d2["threads_opened"] == [], d2
        assert d2["threads_covered"] == ["th-aunt-rosa"], d2
        by_id = {t["id"]: t for t in d2["threads"]}
        assert by_id["th-aunt-rosa"]["status"] == "covered", d2
        assert d2["question"] == CYCLE[1 % len(CYCLE)], d2
        assert d2["pause_suggested"] is False, d2
        print("A+B OK: turn1 opened th-aunt-rosa + asked about her; "
              "turn2 covered it + fell back to cycle")

        # C1: pause false early, true after 6 turns.
        sid6 = f"adapt-pause6-{stamp}"
        sids.append(sid6)
        hist6 = []
        last = None
        for i in range(6):
            txt = f"We talked about the harvest in week {i}."
            last = turn(sid6, txt, hist6)
            hist6.append({"role": "user", "text": txt})
            if i < 5:
                assert last["pause_suggested"] is False, (i, last)
        assert last["pause_suggested"] is True, last
        print("C1 OK: pause_suggested false turns 1-5, true on turn 6")

        # C2: first-person tiredness after a full baseline pauses early.
        # (No keyword matching: pause comes from the MOCK shortening proxy —
        #  the short tired turn against three long baseline turns.)
        sidt = f"adapt-tired-{stamp}"
        sids.append(sidt)
        histt = []
        for i in range(3):
            bt = ("The harvest that year was long and hot and we worked "
                  f"every day until sundown, week {i}.")
            dtb = turn(sidt, bt, histt)
            assert dtb["pause_suggested"] is False, (i, dtb)
            histt.append({"role": "user", "text": bt})
        dt = turn(sidt, "I'm tired, let's stop", histt)
        assert dt["pause_suggested"] is True, dt
        assert dt["threads_opened"] == [] and dt["threads_covered"] == [], dt
        print("C2 OK: tired turn after baseline -> pause_suggested true, "
              "no thread change")

        # D: resume_from carries open threads + facts; opening Q re-opens.
        src = f"adapt-src-{stamp}"
        sids.append(src)
        ds = turn(src, "Grandpa Emil fished the river with me.", [])
        assert ds["threads_opened"] == ["th-grandpa-emil"], ds
        dst = f"adapt-dst-{stamp}"
        sids.append(dst)
        st, rd = post("/api/turn", {
            "session_id": dst, "resume_from": src, "audio_b64": "",
            "history": [], "transcript": "(begin interview)",
            "segments": [],
        })
        assert st == 200, rd
        check_shape(rd)
        assert any(t["id"] == "th-grandpa-emil" and t["status"] == "open"
                   for t in rd["threads"]), rd
        assert "Grandpa Emil" in rd["question"], rd
        assert rd["pause_suggested"] is False, rd
        saved_src = json.loads(
            (ROOT / "recordings" / src / "facts.json").read_text())
        saved_dst = json.loads(
            (ROOT / "recordings" / dst / "facts.json").read_text())
        assert saved_dst == saved_src and saved_dst, (saved_src, saved_dst)
        saved_threads = get_threads(dst)["threads"]
        assert any(t["id"] == "th-grandpa-emil" for t in saved_threads), \
            saved_threads
        print("D OK: resume copied open thread + facts; opening Q asks "
              "about Grandpa Emil")

        # E: unknown resume_from starts clean.
        fresh = f"adapt-fresh-{stamp}"
        sids.append(fresh)
        st, re_ = post("/api/turn", {
            "session_id": fresh, "resume_from": f"no-such-{stamp}",
            "audio_b64": "", "history": [],
            "transcript": "Hello, let us begin.",
            "segments": [{"id": "seg-0", "text": "Hello, let us begin.",
                          "start": 0.0, "end": 1.0}],
        })
        assert st == 200, re_
        check_shape(re_)
        assert re_["threads"] == [], re_
        assert re_["threads_opened"] == [] and re_["threads_covered"] == [], re_
        assert re_["pause_suggested"] is False, re_
        assert re_["question"] == CYCLE[0], re_
        print("E OK: unknown resume_from starts clean with cycle question")
        print("ADAPTIVE OK: open/cover, pause, resume all verified")
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()
        for s in sids:
            shutil.rmtree(ROOT / "recordings" / s, ignore_errors=True)


if __name__ == "__main__":
    main()
