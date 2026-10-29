"""Model-judged fatigue tests (MOCK behavioral proxy + real-path prompt).

MOCK_LLM=1 judges fatigue behaviorally: a non-empty turn under 40% of the
session's own baseline mean (>=3 prior turns, mean >= 8 words) suggests a
pause. No keyword/regex lists anywhere. The real LLM path judges via a
fatigue:{tired,reason} field on the existing fact-extraction call (prompt
+ parse_fatigue unit-tested here; live judgment needs MOCK_LLM=0 + key).

Covers: implicit wrap-up cues trigger, steep shortening triggers, prior
false positives do NOT trigger (third-person/historical "tired",
"exhausting", long vivid story containing "tired"), the turn-count>=6
fallback still fires, empty never fires. Every HTTP case also asserts
pause_suggested type + that facts/threads still flow.
Usage: python3 test_fatigue.py
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
sys.path.insert(0, str(ROOT))
import server

PORT = "18085"
BASE = f"http://127.0.0.1:{PORT}"

# ~17-word baselines (no Title Names, so no threads open).
BASELINES = [
    "The harvest that year was long and hot and we worked every single day until sundown together.",
    "The barn roof leaked all spring so we patched it board by board each weekend without fail.",
    "The county fair drew the whole valley and we stayed late every night through Sunday closing.",
]
# ~14-word baselines for the false-positive sessions.
FP_BASELINES = [
    "We worked the fields together that summer, dawn to dusk, six days every week.",
    "The river ran high that spring and flooded the low pasture twice in May.",
    "The winter stored apples lasted until March and tasted sweeter every month.",
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


def check_shape(data):
    assert isinstance(data.get("question"), str) and data["question"], data
    assert isinstance(data.get("facts"), list), data
    assert isinstance(data.get("threads"), list), data
    for t in data["threads"]:
        assert set(("id", "text", "segment_id", "status")) <= set(t), t
    assert isinstance(data.get("threads_opened"), list), data
    assert isinstance(data.get("threads_covered"), list), data
    assert data.get("pause_suggested") is False or data.get(
        "pause_suggested") is True, data
    assert data.get("fallback") is False, data


def turn(sid, text, history):
    body = {
        "session_id": sid,
        "audio_b64": "",
        "history": history,
        "transcript": text,
        "segments": [{"id": "seg-0", "text": text, "start": 0.0, "end": 1.0}],
    }
    st, data = post("/api/turn", body)
    assert st == 200, data
    check_shape(data)
    return data


def baseline(sid, lines, hist):
    for text in lines:
        d = turn(sid, text, hist)
        assert d["pause_suggested"] is False, (text, d)
        assert d["facts"], (text, d)  # facts still flow on baseline turns
        hist.append({"role": "user", "text": text})
    return hist


def unit_checks():
    # parse_fatigue: explicit true survives, everything else is not-tired.
    assert server.parse_fatigue(
        {"fatigue": {"tired": True, "reason": "says stop"}}
    ) == {"tired": True, "reason": "says stop"}
    assert server.parse_fatigue({}) == {"tired": False, "reason": ""}
    assert server.parse_fatigue({"fatigue": {"tired": "yes"}}) == {
        "tired": False, "reason": ""}
    assert server.parse_fatigue({"fatigue": "tired"}) == {
        "tired": False, "reason": ""}
    assert server.parse_fatigue([]) == {"tired": False, "reason": ""}
    # Real-path prompt: first-person vs third-person/historical distinction.
    p = server.FATIGUE_INSTRUCTIONS
    assert '"fatigue"' in p and '"tired"' in p, p
    assert "I'm tired" in p and "let's wrap this up" in p, p
    assert "my father was tired after the war" in p, p
    assert "the work was exhausting back then" in p, p
    assert "When unsure, false" in p, p
    # pause_suggested: threshold edge + proxy wiring, never keywords.
    assert server.pause_suggested(5, "x" * 500) is False
    assert server.pause_suggested(6, "x" * 500) is True
    assert server.pause_suggested(1, "my father was tired") is False
    assert server.pause_suggested(1, "I'm tired, let's stop") is False
    assert server.pause_suggested(
        1, "I'm tired, let's stop", [17, 17, 17], llm_tired=True) is True
    assert server.pause_suggested(1, "", [17, 17, 17]) is False
    print("UNIT OK: parse_fatigue, prompt wording, threshold/proxy wiring")


def main():
    unit_checks()
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

        # Implicit wrap-up phrasing triggers (via shortening, not keywords).
        for label, closer in [
            ("wrap-up", "Let's wrap this up for today."),
            ("nothing-more", "Not much more to say."),
            ("steep-short", "Done for now."),
        ]:
            sid = f"fat-{label}-{stamp}"
            sids.append(sid)
            hist = baseline(sid, BASELINES, [])
            d = turn(sid, closer, hist)
            assert d["pause_suggested"] is True, (label, d)
            assert d["facts"], (label, d)
            print(f"TRIGGER OK ({label}): {closer!r} -> pause true, facts flow")

        # False positives do NOT trigger.
        for label, fp in [
            ("third-person",
             "My father was tired after the war, he worked the fields every day until dark."),
            ("historical",
             "The harvest work was exhausting back then, dawn to dusk for six solid weeks running."),
            ("vivid-story",
             "The winter march was brutal and I was so tired I could barely lift my pack, "
             "but the unit kept singing all night and we reached the river crossing by dawn together."),
        ]:
            sid = f"fat-fp-{label}-{stamp}"
            sids.append(sid)
            hist = baseline(sid, FP_BASELINES, [])
            d = turn(sid, fp, hist)
            assert d["pause_suggested"] is False, (label, d)
            assert d["facts"], (label, d)
            print(f"NO-FIRE OK ({label}): facts flow, pause false")

        # Turn-count>=6 fallback still fires on a fresh sustained session.
        sid6 = f"fat-long6-{stamp}"
        sids.append(sid6)
        hist6 = []
        last = None
        for i in range(6):
            txt = ("We talked about the harvest all week long, every single "
                   f"day from dawn until dark, week {i}.")
            last = turn(sid6, txt, hist6)
            hist6.append({"role": "user", "text": txt})
            if i < 5:
                assert last["pause_suggested"] is False, (i, last)
                assert last["facts"], (i, last)
        assert last["pause_suggested"] is True, last
        assert last["facts"], last
        print("FALLBACK OK: 6 sustained long turns, pause true on turn 6")

        # Empty transcript never pauses.
        side = f"fat-empty-{stamp}"
        sids.append(side)
        de = turn(side, "", [])
        assert de["pause_suggested"] is False, de
        print("EMPTY OK: empty transcript -> pause false")

        print("FATIGUE OK: triggers, false positives, fallback, empty")
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
