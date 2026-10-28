"""Review-hardening tests from the skeptical pass (2026-10-28).

Each test pins a finding: /api/facts traversal confinement, corrupt
facts.json recovery, segment-id alias priority, non-finite segment bounds,
empty-audio playable clips, and the fallback flag contract.
Usage: python3 test_review.py
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
from server import normalize_segments, resolve_fact_links  # noqa: E402

PORT = "18088"
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
        return resp.status, resp.read(), resp.headers.get("Content-Type")


def main():
    env = dict(os.environ, MOCK_LLM="1", PORT=PORT)
    srv = subprocess.Popen(
        [sys.executable, "server.py"], env=env, cwd=str(ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    sids = []
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(BASE + "/", timeout=2).read()
                break
            except Exception:
                time.sleep(0.2)

        # T1: /api/facts must confine session_id like /api/turn and /api/clip.
        victim = f"rv-victim-{int(time.time())}"
        sids.append(victim)
        post("/api/turn", {
            "session_id": victim, "audio_b64": "",
            "transcript": "I grew up on a farm in Ohio with Aunt Rosa.",
            "segments": [{"id": "seg-0", "text": "x", "start": 0.0, "end": 1.0}],
        })
        st, body, _ = get(f"/api/facts?session_id=../recordings/{victim}")
        assert st == 200, (st, body)
        assert json.loads(body) == {"facts": []}, (
            f"traversal read escaped confinement: {body[:200]}")

        # T2: corrupt facts.json recovers to [] on GET and on the next POST.
        sid = f"rv-corrupt-{int(time.time())}"
        sids.append(sid)
        post("/api/turn", {"session_id": sid, "audio_b64": "",
                           "transcript": "hello",
                           "segments": [{"id": "seg-0", "text": "hello",
                                         "start": 0.0, "end": 1.0}]})
        (ROOT / "recordings" / sid / "facts.json").write_text("{not json")
        st, body, _ = get(f"/api/facts?session_id={sid}")
        assert st == 200 and json.loads(body) == {"facts": []}, (st, body)
        st, data = post("/api/turn", {"session_id": sid, "audio_b64": "",
                                      "transcript": "second",
                                      "segments": [{"id": "seg-0", "text": "second",
                                                    "start": 0.0, "end": 1.0}]})
        assert st == 200, data
        saved = json.loads((ROOT / "recordings" / sid / "facts.json").read_text())
        assert isinstance(saved, list) and saved, "POST must recover persistence"
        print("T1+T2 OK: facts confinement + corrupt recovery")

        # T3: alias priority — numeric suffix beats positional index.
        seg_by_id = {"seg-1": {"id": "seg-1", "text": "a", "start": 9.0, "end": 10.0},
                     "seg-0": {"id": "seg-0", "text": "b", "start": 0.0, "end": 1.0}}
        out = resolve_fact_links(
            [{"kind": "event", "text": "t", "when": "", "segment_ids": ["0"]}],
            "clip-x", seg_by_id)
        assert out[0]["segment_id"] == "seg-0", out
        assert (out[0]["start"], out[0]["end"]) == (0.0, 1.0), out
        print("T3 OK: '0' resolves to seg-0 regardless of dict order")

        # T4: non-finite bounds are clamped to 0.0.
        segs = normalize_segments(
            [{"id": "s", "text": "t", "start": float("nan"), "end": float("inf")}])
        assert segs == [{"id": "s", "text": "t", "start": 0.0, "end": 0.0}], segs
        print("T4 OK: NaN/inf bounds clamped")

        # T5: empty audio still yields a playable clip and a valid slice.
        sid = f"rv-empty-{int(time.time())}"
        sids.append(sid)
        st, data = post("/api/turn", {"session_id": sid, "audio_b64": "",
                                      "transcript": "Aunt Rosa told stories.",
                                      "segments": [{"id": "seg-0",
                                                    "text": "Aunt Rosa told stories.",
                                                    "start": 0.0, "end": 0.0}]})
        assert st == 200, data
        for f in data["facts"]:
            clip = ROOT / "recordings" / sid / f"{f['clip_id']}.wav"
            assert clip.is_file() and clip.stat().st_size > 44, f
            assert 0.0 <= f["start"] < f["end"], f
        st, blob, ctype = get(
            f"/api/clip?session_id={sid}&clip_id={data['facts'][0]['clip_id']}")
        assert st == 200 and len(blob) > 44 and ctype == "audio/wav", (st, len(blob))
        print(f"T5 OK: {len(data['facts'])} facts cite playable clip slices")

        # T6: every turn response carries the fallback contract flag.
        assert data.get("fallback") is False, data
        print("T6 OK: fallback flag present and false on clean MOCK turn")

        # T7: frontend surfaces errors instead of hanging on "Thinking...".
        html = (ROOT / "index.html").read_text()
        assert "res.ok" in html and "try" in html, "sendTurn needs an error path"
        assert "clipTooShort" in html or "too short" in html or "end <= f.start" in html \
            or "f.end > f.start" in html or "end<=start" in html.replace(" ", ""), \
            "replay needs a zero-length guard"
        print("T7 OK: frontend error path + replay guard present")
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
