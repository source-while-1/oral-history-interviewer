"""Phase 7 polish tests (MOCK_LLM=1, works offline).

Covers the two stretch picks:
(a) living family tree + timeline — GET /api/family-tree returns one
    node per consenting relative (each with a playable voice sample),
    a date-sorted timeline of dated stories with per-relative citations,
    and silently excludes revoked relatives; every sample clip streams.
(b) elder accessibility pass — index.html carries Larger text, High
    contrast, Written captions, and Slower speech toggles persisted in
    localStorage, a captions region, and reduced-motion handling; the
    page keeps its existing palette (no banned taste patterns).

Usage: python3 test_polish.py
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import server as srvmod  # noqa: E402  (write_silent_wav for fixtures)

PORT = "18241"
BASE = f"http://127.0.0.1:{PORT}"
TAG = f"pol-{int(time.time()) % 1000000}"

BANNED = ["bg-clip-text", "aurora", "glassmorphism", "hover:scale-105",
          "rounded-2xl", "backdrop-blur", "linear-gradient(135deg"]


def raw(method, path, obj=None):
    data = None
    heads = {}
    if obj is not None:
        data = json.dumps(obj).encode()
        heads = {"Content-Type": "application/json"}
    req = urllib.request.Request(BASE + path, data=data,
                                 headers=heads, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def raw_bytes(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=20) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def body(text):
    try:
        return json.loads(text or "{}")
    except ValueError:
        return {}


def start(port):
    env = dict(os.environ, MOCK_LLM="1", PORT=port, DEMO_PASSWORD="")
    srv = subprocess.Popen(
        [sys.executable, "server.py"], env=env, cwd=str(ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    for _ in range(50):
        try:
            urllib.request.urlopen(BASE + "/", timeout=2).read()
            break
        except Exception:
            time.sleep(0.2)
    return srv


def stop(srv):
    srv.terminate()
    try:
        srv.wait(timeout=5)
    except Exception:
        srv.kill()


def write_session(sid, clip_id, duration, segments, facts):
    sdir = ROOT / "recordings" / sid
    sdir.mkdir(parents=True, exist_ok=True)
    srvmod.write_silent_wav(sdir / f"{clip_id}.wav", seconds=duration)
    with open(sdir / "transcript.jsonl", "w") as fh:
        fh.write(json.dumps({
            "ts": "2026-01-01T00:00:00+00:00",
            "clip_id": clip_id, "history_len": 0, "question": "q",
            "transcript": " ".join(s["text"] for s in segments),
            "segments": segments, "threads_opened": [],
            "threads_covered": [], "pause_suggested": False,
            "distress": False,
        }) + "\n")
    (sdir / "facts.json").write_text(json.dumps(facts, indent=2))


def bind(sid, pid):
    (ROOT / "recordings" / sid / "person.json").write_text(
        json.dumps({"person_id": pid}))
    ppath = ROOT / "recordings" / "people" / pid / "sessions.json"
    try:
        sessions = json.loads(ppath.read_text())
    except (ValueError, OSError):
        sessions = []
    if sid not in sessions:
        sessions.append(sid)
    ppath.write_text(json.dumps(sessions, indent=2))


def main():
    results = []

    def check(name, cond, detail=""):
        results.append((name, bool(cond), detail))
        print(f"{'PASS' if cond else 'FAIL'} {name}"
              + (f" — {detail}" if detail else ""))

    srv = start(PORT)
    try:
        s, t = raw("POST", "/api/people",
                   {"display_name": f"Rosa {TAG}", "relation": "grandmother"})
        rosa = body(t)
        rosa_id, rosa_tok = rosa.get("person_id", ""), rosa.get(
            "person_token", "")
        check("create-rosa", s == 200 and rosa_id.startswith("p-"),
              f"status={s}")
        s, t = raw("POST", "/api/people",
                   {"display_name": f"Sam {TAG}", "relation": "grandson"})
        sam = body(t)
        sam_id, sam_tok = sam.get("person_id", ""), sam.get(
            "person_token", "")
        check("create-sam", s == 200 and sam_id.startswith("p-"),
              f"status={s}")

        sid_r = f"{TAG}-r"
        sid_s = f"{TAG}-s"
        write_session(sid_r, f"clip-{TAG}-r", 10.0,
                      [{"id": f"seg-{sid_r}",
                        "text": f"I married in 1958 near the {TAG} mill.",
                        "start": 0.5, "end": 9.0}],
                      [{"kind": "place", "text": f"The {TAG} Mill",
                        "when": "1958", "clip_id": f"clip-{TAG}-r",
                        "start": 0.5, "end": 6.0,
                        "segment_id": f"seg-{sid_r}"}])
        write_session(sid_s, f"clip-{TAG}-s", 10.0,
                      [{"id": f"seg-{sid_s}",
                        "text": f"Grandma crossed the {TAG} mill in 1962.",
                        "start": 0.5, "end": 9.0}],
                      [{"kind": "place", "text": f"The {TAG} Mill",
                        "when": "1962", "clip_id": f"clip-{TAG}-s",
                        "start": 0.5, "end": 6.0,
                        "segment_id": f"seg-{sid_s}"},
                       {"kind": "person", "text": "Undated Tale",
                        "when": "", "clip_id": f"clip-{TAG}-s",
                        "start": 0.5, "end": 6.0,
                        "segment_id": f"seg-{sid_s}"}])
        bind(sid_r, rosa_id)
        bind(sid_s, sam_id)

        # -- family tree: nodes + sorted timeline + voice samples --
        s, t = raw("GET",
                   f"/api/family-tree?person_ids={rosa_id},{sam_id}")
        tree = body(t)
        nodes = {n["person_id"]: n for n in tree.get("nodes", [])}
        tl = tree.get("timeline", [])
        check("tree-200", s == 200 and len(nodes) == 2, f"status={s}")
        check("tree-node-fields",
              all({"display_name", "relation", "clip_count", "sample"}
                  <= set(n) for n in nodes.values()),
              f"{sorted(nodes)}")
        check("tree-relation",
              nodes.get(rosa_id, {}).get("relation") == "grandmother",
              f"{nodes.get(rosa_id, {}).get('relation')}")
        check("tree-samples",
              all(n.get("sample", {}).get("clip_id") for n in nodes.values()),
              "every node plays its own voice")
        whens = [e["when"] for e in tl]
        check("tree-timeline-sorted",
              whens == sorted(whens) and whens == ["1958", "1962"],
              f"{whens}")
        check("tree-undated-excluded",
              all(e["when"] for e in tl)
              and not any(e["text"] == "Undated Tale" for e in tl),
              f"n={len(tl)}")
        check("tree-cites",
              all({"session_id", "clip_id", "person_id"} <= set(e)
                  for e in tl),
              "per-relative citations on every entry")

        # -- every node sample streams real audio --
        ok = True
        for n in nodes.values():
            smp = n.get("sample", {})
            st, data = raw_bytes(
                f"/api/clip?session_id={smp.get('session_id')}"
                f"&clip_id={smp.get('clip_id')}")
            ok = ok and st == 200 and len(data) > 100
        check("tree-samples-stream", ok, "wav bytes for each voice")

        # -- revoked relative silently excluded --
        s, _ = raw("POST", "/api/consent",
                   {"person_id": sam_id, "person_token": sam_tok,
                    "revoke": True})
        check("revoke-sam", s == 200, f"status={s}")
        s, t = raw("GET",
                   f"/api/family-tree?person_ids={rosa_id},{sam_id}")
        tree2 = body(t)
        ids2 = [n["person_id"] for n in tree2.get("nodes", [])]
        check("revoked-excluded-from-tree",
              s == 200 and ids2 == [rosa_id], f"{ids2}")
        check("revoked-excluded-from-timeline",
              all(e["person_id"] == rosa_id
                  for e in tree2.get("timeline", [])),
              f"n={len(tree2.get('timeline', []))}")

        # -- missing scope is a 400, not a silent empty --
        s, t = raw("GET", "/api/family-tree")
        check("tree-requires-scope",
              s == 400 and "person_ids" in body(t).get("error", ""),
              f"status={s}")

        # -- elder accessibility hooks in the page --
        html = (ROOT / "index.html").read_text()
        for hook in ("a11ybar", "a11y-large", "a11y-contrast",
                     "a11y-captions", "a11y-slow", 'id="caption"',
                     "ohi-a11y-", "step-tree", "tree-nodes",
                     "tree-timeline", "prefers-reduced-motion",
                     "u.rate = 0.8"):
            check(f"ui-{hook}", hook in html, hook)
        check("ui-no-banned-patterns",
              not any(b in html for b in BANNED),
              "no gradient/glass/emoji-card tells")
    finally:
        stop(srv)

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
