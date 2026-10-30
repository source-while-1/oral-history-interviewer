"""Phase 2 live test (MOCK_LLM=0 — needs a real Fireworks key).

Fails loudly when FIREWORKS_API_KEY is missing: live suites need the key.
Exercises one full generational arc against the real model: create a
person, record a bound turn, leave a next-time topic, and resume in a new
session (threads/topics/consent ride along).

Local server only (127.0.0.1). NEVER scripts/share.sh or cloudflared.

Usage: MOCK_LLM=0 python3 test_people_live.py  (key from .env)
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

# Fail loudly when the live key is missing (never silently mock).
for _line in (ROOT / ".env").read_text().splitlines():
    if _line.strip().startswith("FIREWORKS_API_KEY=") and "=" in _line:
        _v = _line.split("=", 1)[1].strip().strip("'\"")
        if _v and "FIREWORKS_API_KEY" not in os.environ:
            os.environ["FIREWORKS_API_KEY"] = _v
if not os.environ.get("FIREWORKS_API_KEY"):
    print("FAIL live-needs-key — set FIREWORKS_API_KEY in .env "
          "(live suites need the key; MOCK_LLM=0)")
    sys.exit(1)

PORT = "18213"
BASE = f"http://127.0.0.1:{PORT}"
TAG = f"live-p2-{int(time.time()) % 1000000}"


def raw(method, path, obj=None, headers=None):
    heads = dict(headers or {})
    data = None
    if obj is not None:
        data = json.dumps(obj).encode()
        heads.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(BASE + path, data=data,
                                 headers=heads, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def body(text):
    try:
        return json.loads(text or "{}")
    except ValueError:
        return {}


def main():
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
                   {"display_name": "Live Grandma", "relation": "grandmother"})
        me = body(t)
        check("live-create", s == 200 and me.get("personal_link", "").startswith("/i/"),
              f"status={s}")
        pid, tok = me.get("person_id", ""), me.get("person_token", "")
        s, t = raw("GET", me.get("personal_link", "/i/nope"))
        check("live-link-opens", s == 200 and "Oral History" in t, f"status={s}")

        s1 = f"{TAG}-s1"
        s, t = raw("POST", "/api/turn",
                   {"session_id": s1, "audio_b64": "", "history": [],
                    "transcript": "I grew up on a small farm near the river. "
                    "My mother taught me to bake bread there.",
                    "segments": [{"id": "seg-0",
                                  "text": "I grew up on a small farm near the river.",
                                  "start": 0, "end": 1}],
                    "person_id": pid, "person_token": tok})
        d1 = body(t)
        check("live-bound-turn", s == 200 and d1.get("question")
              and d1.get("fallback") is False,
              f"status={s} fallback={d1.get('fallback')} "
              f"q={(d1.get('question') or '')[:60]!r}")

        s, t = raw("POST", "/api/next-topics",
                   {"person_id": pid,
                    "topics": ["What did the farmhouse kitchen look like?"]})
        check("live-leave-topic", s == 200, f"status={s}")

        s2 = f"{TAG}-s2"
        s, t = raw("POST", "/api/turn",
                   {"session_id": s2, "audio_b64": "", "history": [],
                    "transcript": "", "segments": [],
                    "person_id": pid, "person_token": tok})
        d2 = body(t)
        check("live-resume", s == 200 and d2.get("question")
              and isinstance(d2.get("threads"), list),
              f"status={s} threads={len(d2.get('threads', []))} "
              f"asked={d2.get('topics_asked')} held={d2.get('topics_held')}")
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("FAILURES:", failed)
        sys.exit(1)


if __name__ == "__main__":
    main()
