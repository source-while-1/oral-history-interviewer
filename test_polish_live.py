"""Phase 7 polish tests, LIVE path (MOCK_LLM=0, needs FIREWORKS_API_KEY).

Same stretch contract as test_polish.py, served by a live-mode server:
the family tree + timeline is deterministic (no LLM call), and the
accessibility hooks are static page content. The live run proves the
new endpoint and fixtures behave identically with the real model
configured.

MANDATORY ENV RULE: source .env first (FIREWORKS_API_KEY, DEMO_PASSWORD
empty). Missing key fails loudly (exit 1) — a skip would hide an
untested live path.

Usage:
  source .env
  DEMO_PASSWORD= python3 test_polish_live.py
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

PORT = os.environ.get("POLISH_LIVE_PORT", "18242")
BASE = f"http://127.0.0.1:{PORT}"
TAG = f"pol-live-{int(time.time()) % 1000000}"


def raw(method, path, obj=None, timeout=90):
    data = None
    heads = {}
    if obj is not None:
        data = json.dumps(obj).encode()
        heads = {"Content-Type": "application/json"}
    req = urllib.request.Request(BASE + path, data=data,
                                 headers=heads, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def body(text):
    try:
        return json.loads(text or "{}")
    except ValueError:
        return {}


def main():
    if not os.environ.get("FIREWORKS_API_KEY"):
        print("FAIL live requires FIREWORKS_API_KEY (source .env first)")
        return 1
    results = []

    def check(name, cond, detail=""):
        results.append((name, bool(cond), detail))
        print(f"{'PASS' if cond else 'FAIL'} {name}"
              + (f" — {detail}" if detail else ""))

    env = dict(os.environ, MOCK_LLM="0", PORT=PORT, DEMO_PASSWORD="")
    srv = subprocess.Popen(
        [sys.executable, "server.py"], env=env, cwd=str(ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(BASE + "/", timeout=2).read()
                break
            except Exception:
                time.sleep(0.2)

        s, t = raw("POST", "/api/people",
                   {"display_name": f"Rosa {TAG}",
                    "relation": "grandmother"})
        rosa = body(t)
        rosa_id = rosa.get("person_id", "")
        check("live-create-rosa", s == 200 and rosa_id.startswith("p-"),
              f"status={s}")

        sid = f"{TAG}-r"
        sdir = ROOT / "recordings" / sid
        sdir.mkdir(parents=True, exist_ok=True)
        srvmod.write_silent_wav(sdir / f"clip-{TAG}-r.wav", seconds=10.0)
        (sdir / "transcript.jsonl").write_text(json.dumps({
            "ts": "2026-01-01T00:00:00+00:00",
            "clip_id": f"clip-{TAG}-r", "history_len": 0,
            "question": "q", "transcript": f"mill story {TAG}",
            "segments": [{"id": f"seg-{sid}",
                          "text": f"I married in 1958 near the {TAG} mill.",
                          "start": 0.5, "end": 9.0}],
            "threads_opened": [], "threads_covered": [],
            "pause_suggested": False, "distress": False,
        }) + "\n")
        (sdir / "facts.json").write_text(json.dumps([{
            "kind": "place", "text": f"The {TAG} Mill", "when": "1958",
            "clip_id": f"clip-{TAG}-r", "start": 0.5, "end": 6.0,
            "segment_id": f"seg-{sid}"}]))
        (sdir / "person.json").write_text(json.dumps(
            {"person_id": rosa_id}))
        ppath = ROOT / "recordings" / "people" / rosa_id / "sessions.json"
        ppath.write_text(json.dumps([sid]))

        s, t = raw("GET", f"/api/family-tree?person_ids={rosa_id}")
        tree = body(t)
        nodes = tree.get("nodes", [])
        tl = tree.get("timeline", [])
        check("live-tree-200", s == 200 and len(nodes) == 1,
              f"status={s} n={len(nodes)}")
        check("live-tree-sample",
              bool(nodes) and bool(nodes[0].get("sample", {}).get(
                  "clip_id")),
              "node plays its own voice")
        check("live-tree-timeline",
              [e["when"] for e in tl] == ["1958"],
              f"{[e.get('when') for e in tl]}")

        html = (ROOT / "index.html").read_text()
        check("live-ui-tree-hooks",
              all(h in html for h in ("step-tree", "tree-timeline",
                                      "a11ybar", "ohi-a11y-")),
              "tree + accessibility hooks shipped")
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
