"""Consent capture: store, view, revoke, resume-carry, gentle placement.

Stubbed LLM (MOCK_LLM=1). Starts server.py on a free port, exercises
POST/GET /api/consent and /api/turn, and asserts:
- consent stores all three answers incl. a separate voice-clone yes/no
- consent is viewable (GET) and revocable (POST revoke:true)
- consent carries across resumed sessions (resume_from)
- placement: never due on the opening turn; due near a pause/late turn;
  not due once complete.
Usage: python3 test_consent.py
"""

import json
import os
import subprocess
import sys
import time
import urllib.request

PORT = "18091"
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


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=15) as resp:
        return resp.status, json.loads(resp.read().decode())


def turn(sid, text, extra=None):
    body = {
        "session_id": sid,
        "audio_b64": "",
        "history": [],
        "transcript": text,
        "segments": [{"id": "seg-0", "text": text, "start": 0.0, "end": 1.0}],
    }
    if extra:
        body.update(extra)
    return post("/api/turn", body)


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
        ts = str(int(time.time() * 1000))
        sid = f"consent-{ts}"

        # 1. Placement: opening turn never asks for consent.
        _, t1 = turn(sid, "I grew up in Lisbon with Aunt Rosa.")
        assert t1.get("consent_due") is False, t1
        assert t1.get("consent_prompt") == "", t1
        assert t1.get("question"), "opening question must still be asked"

        # 2. Store: all three answers, voice clone a separate yes/no.
        _, saved = post("/api/consent", {
            "session_id": sid,
            "ai_reconstruction": True,
            "access": "immediate family only",
            "voice_clone": "no",
        })
        c = saved["consent"]
        assert c["ai_reconstruction"] is True, c
        assert c["access"] == "immediate family only", c
        assert c["voice_clone"] is False, c

        # 3. Viewable: GET returns the stored wishes.
        _, seen = get(f"/api/consent?session_id={sid}")
        assert seen["consent"] == c, seen

        # 4. Not due once complete.
        _, t2 = turn(sid, "My father worked the docks for thirty years.")
        assert t2.get("consent_due") is False, t2
        assert t2.get("consent") == c, t2

        # 5. Revocable: withdraw clears the record.
        _, revoked = post("/api/consent", {"session_id": sid, "revoke": True})
        assert revoked["consent"]["revoked"] is True, revoked
        assert revoked["consent"]["ai_reconstruction"] is None, revoked
        assert revoked["consent"]["voice_clone"] is None, revoked
        _, seen2 = get(f"/api/consent?session_id={sid}")
        assert seen2["consent"]["revoked"] is True, seen2

        # 6. Placement after revoke: due again near pause/late turns
        # (turn 4+), with a prompt covering all three asks.
        turn(sid, "We spent summers at my grandmother's house.")
        _, t3 = turn(sid, "Sunday dinners brought everyone together.")
        assert t3.get("consent_due") is True, t3
        prompt = t3.get("consent_prompt", "")
        assert "reconstruction" in prompt.lower(), prompt
        assert "voice" in prompt.lower(), prompt
        assert "access" in prompt.lower(), prompt

        # 7. Resume-carry: fresh session resumed from a consented session.
        sid_src = f"consent-src-{ts}"
        turn(sid_src, "I grew up in Lisbon.")
        post("/api/consent", {
            "session_id": sid_src,
            "ai_reconstruction": "yes",
            "access": "family only",
            "voice_clone": "yes",
        })
        sid_new = f"consent-new-{ts}"
        _, rt1 = turn(sid_new, "Tell me about home.",
                      extra={"resume_from": sid_src})
        _, carried = get(f"/api/consent?session_id={sid_new}")
        assert carried["consent"]["ai_reconstruction"] is True, carried
        assert carried["consent"]["access"] == "family only", carried
        assert carried["consent"]["voice_clone"] is True, carried
        assert rt1.get("consent_due") is False, rt1
        print("CONSENT OK: store, view, revoke, placement, resume-carry")
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()


if __name__ == "__main__":
    main()
