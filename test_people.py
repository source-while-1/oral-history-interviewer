"""Phase 2 generational setup tests (MOCK_LLM=1, works offline).

Covers the effortless-setup contract:
- Helper creates one record per interviewee (name + relation); self-setup
  ("Add me too") is the same call — no hard-coded roles.
- One unguessable personal link per interviewee; opening it (GET /i/<token>
  + lookup) resolves to that person; unknown links 404.
- Sessions bind to exactly one person; a new session auto-resumes the
  person's open threads/facts/consent (no codes typed).
- Helper-left next-time topics: surface as the opener when no open thread
  fits, marked asked once used; held while tired; never mid-conversation.
- Per-person consent save/get/revoke isolation.
- DEMO_MODE blocks people/topics writes; personal links never resolve.
- index.html carries the setup UI hooks without banned taste patterns.

Usage: python3 test_people.py
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
PORT = "18211"
BASE = f"http://127.0.0.1:{PORT}"
TAG = f"p2-{int(time.time()) % 1000000}"


def raw(method, path, obj=None, headers=None):
    heads = dict(headers or {})
    data = None
    if obj is not None:
        data = json.dumps(obj).encode()
        heads.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(BASE + path, data=data,
                                 headers=heads, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def body(text):
    try:
        return json.loads(text or "{}")
    except ValueError:
        return {}


def start(port, extra_env):
    env = dict(os.environ, MOCK_LLM="1", PORT=port, DEMO_PASSWORD="",
               **extra_env)
    srv = subprocess.Popen(
        [sys.executable, "server.py"], env=env, cwd=str(ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            urllib.request.urlopen(base + "/", timeout=2).read()
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


def turn(session_id, person_id, token, transcript, seg_text=""):
    segs = ([{"id": "seg-0", "text": seg_text or transcript,
              "start": 0, "end": 1}] if transcript else [])
    return raw("POST", "/api/turn",
               {"session_id": session_id, "audio_b64": "",
                "history": [], "transcript": transcript,
                "segments": segs, "person_id": person_id,
                "person_token": token})


def main():
    results = []

    def check(name, cond, detail=""):
        results.append((name, bool(cond), detail))
        print(f"{'PASS' if cond else 'FAIL'} {name}"
              + (f" — {detail}" if detail else ""))

    srv = start(PORT, {})
    try:
        # -- helper creates a person (name + relation) --
        s, t = raw("POST", "/api/people",
                   {"display_name": "Grandma Rosa", "relation": "grandmother"})
        rosa = body(t)
        check("create-person", s == 200 and rosa.get("person_id", "").startswith("p-")
              and rosa.get("person_token") and rosa.get("personal_link", "").startswith("/i/"),
              f"status={s} keys={sorted(rosa)}")
        rosa_id = rosa.get("person_id", "")
        rosa_tok = rosa.get("person_token", "")
        rh = {"X-Person-Token": rosa_tok}

        # -- raw token never touches disk (hash only) --
        stored = (ROOT / "recordings" / "people" / rosa_id / "person.json").read_text()
        check("token-hashed", rosa_tok not in stored and "token_hash" in stored,
              "raw token absent from person.json")

        # -- validation + auth errors --
        s, _ = raw("POST", "/api/people", {})
        check("create-needs-name", s == 400, f"status={s}")
        s, _ = raw("GET", "/api/person?person_id=nope-xyz")
        check("person-unknown-404", s == 404, f"status={s}")
        s, _ = raw("GET", f"/api/person?person_id={rosa_id}")
        check("person-needs-link", s == 403, f"status={s}")
        s, t = turn(f"{TAG}-x", rosa_id, "wrong-token", "")
        check("turn-bad-token-403", s == 403, f"status={s}")
        s, t = turn(f"{TAG}-x", "p-nope", "whatever", "")
        check("turn-unknown-person-404", s == 404, f"status={s}")

        # -- self-setup ("Add me too") is equally easy --
        s, t = raw("POST", "/api/people",
                   {"display_name": "Sam", "relation": "self (helper)"})
        sam = body(t)
        check("self-setup", s == 200 and sam.get("person_id") != rosa_id
              and sam.get("personal_link") != rosa.get("personal_link"),
              f"status={s}")
        sam_id, sam_tok = sam.get("person_id", ""), sam.get("person_token", "")

        # -- lookup + personal link open --
        s, t = raw("POST", "/api/people/lookup", {"token": rosa_tok})
        check("lookup", s == 200 and body(t).get("person_id") == rosa_id,
              f"status={s}")
        s, _ = raw("POST", "/api/people/lookup", {"token": "nope"})
        check("lookup-bad-404", s == 404, f"status={s}")
        s, t = raw("GET", rosa.get("personal_link", "/i/nope"))
        check("link-opens", s == 200 and "Oral History" in t, f"status={s}")
        s, _ = raw("GET", "/i/definitely-not-a-token")
        check("link-bad-404", s == 404, f"status={s}")

        # -- helper view with the link --
        s, t = raw("GET", f"/api/person?person_id={rosa_id}", None, rh)
        view = body(t)
        check("person-view", s == 200 and view.get("person", {}).get("display_name")
              == "Grandma Rosa" and view.get("sessions") == [],
              f"status={s}")

        # -- turn binds the session to the person --
        s1 = f"{TAG}-rosa-1"
        s, t = turn(s1, rosa_id, rosa_tok, "I grew up with Aunt Rosa")
        d1 = body(t)
        opened = d1.get("threads_opened", [])
        check("turn-binds", s == 200 and opened
              and (ROOT / "recordings" / s1 / "person.json").is_file()
              and s1 in body(raw(
                  "GET", f"/api/person?person_id={rosa_id}", None, rh)[1]
              ).get("sessions", []),
              f"status={s} opened={opened}")

        # -- auto start/resume: new session reopens her threads --
        s2 = f"{TAG}-rosa-2"
        s, t = turn(s2, rosa_id, rosa_tok, "")
        d2 = body(t)
        texts = [x.get("text", "") for x in d2.get("threads", [])]
        check("auto-resume", s == 200 and d2.get("question")
              and any("Aunt Rosa" in x for x in texts),
              f"status={s} threads={texts}")

        # -- next-time topics: opener when nothing fits, then consumed --
        s, t = raw("POST", "/api/people",
                   {"display_name": "Theo", "relation": "uncle"})
        theo = body(t)
        th, tid = {"X-Person-Token": theo.get("person_token", "")}, theo.get("person_id", "")
        s, t = raw("POST", "/api/next-topics",
                   {"person_id": tid,
                    "topics": ["What was the bakery on Main Street like?",
                               "Tell me about the harvest festival."]})
        check("leave-topics", s == 200 and len(body(t).get("added", [])) == 2,
              f"status={s}")
        s, t = raw("POST", "/api/next-topics", {"person_id": tid, "topics": []})
        check("topics-need-text", s == 400, f"status={s}")
        s, t = raw("POST", "/api/next-topics",
                   {"person_id": "p-nope", "topics": ["x"]})
        check("topics-unknown-404", s == 404, f"status={s}")
        s, t = turn(f"{TAG}-theo-1", tid, theo.get("person_token", ""), "")
        d = body(t)
        check("topic-opener", s == 200
              and d.get("question") == "What was the bakery on Main Street like?"
              and len(d.get("topics_asked", [])) == 1
              and d.get("topics_pending") == 1,
              f"status={s} q={d.get('question')!r}")
        s, t = turn(f"{TAG}-theo-1", tid, theo.get("person_token", ""), "")
        d = body(t)
        check("topic-second", s == 200
              and d.get("question") == "Tell me about the harvest festival."
              and len(d.get("topics_asked", [])) == 1
              and d.get("topics_pending") == 0,
              f"status={s} q={d.get('question')!r}")

        # -- topics held while tired (turn-count fallback), never forced --
        s, t = raw("POST", "/api/people", {"display_name": "Hal"})
        hal = body(t)
        hid, htok = hal.get("person_id", ""), hal.get("person_token", "")
        hs = f"{TAG}-hal-1"
        for _ in range(6):
            turn(hs, hid, htok, "")
        s, t = raw("POST", "/api/next-topics",
                   {"person_id": hid, "topics": ["Ask about the boat."]})
        check("leave-late-topic", s == 200, f"status={s}")
        s, t = turn(hs, hid, htok, "")
        d = body(t)
        check("topic-held-when-tired", s == 200
              and d.get("pause_suggested") is True
              and len(d.get("topics_held", [])) == 1
              and d.get("topics_asked", []) == []
              and d.get("question") != "Ask about the boat.",
              f"held={d.get('topics_held')} q={d.get('question')!r}")

        # -- topics never interrupt while a thread is open --
        s, t = raw("POST", "/api/people", {"display_name": "Meg"})
        meg = body(t)
        mid, mtok = meg.get("person_id", ""), meg.get("person_token", "")
        raw("POST", "/api/next-topics",
            {"person_id": mid, "topics": ["Ask about the boat."]})
        s, t = turn(f"{TAG}-meg-1", mid, mtok, "I grew up with Aunt Rosa")
        d = body(t)
        check("no-mid-interrupt", s == 200
              and "Aunt Rosa" in (d.get("question") or "")
              and d.get("topics_asked", []) == []
              and d.get("topics_pending") == 1,
              f"q={d.get('question')!r}")

        # -- per-person consent: save, read back, revoke is isolated --
        s, t = raw("POST", "/api/consent",
                   {"person_id": rosa_id, "person_token": rosa_tok,
                    "ai_reconstruction": "yes", "access": "family",
                    "voice_clone": "no"})
        check("person-consent-save", s == 200
              and body(t).get("consent", {}).get("ai_reconstruction") is True,
              f"status={s}")
        s, t = raw("GET", f"/api/consent?person_id={rosa_id}")
        check("person-consent-get", s == 200
              and body(t).get("consent", {}).get("access") == "family",
              f"status={s}")
        s, t = turn(f"{TAG}-rosa-3", rosa_id, rosa_tok, "")
        check("consent-rides-along", s == 200
              and body(t).get("consent", {}).get("ai_reconstruction") is True,
              f"status={s}")
        raw("POST", "/api/consent",
            {"person_id": rosa_id, "person_token": rosa_tok, "revoke": True})
        s, t = raw("GET", f"/api/consent?person_id={rosa_id}")
        s2c, t2c = raw("GET", f"/api/consent?person_id={sam_id}")
        check("revoke-isolated", body(t).get("consent", {}).get("revoked") is True
              and not body(t2c).get("consent", {}).get("revoked"),
              "rosa revoked, sam untouched")

        # -- setup UI hooks, no banned taste patterns added --
        html = (ROOT / "index.html").read_text()
        check("ui-setup-wiring", all(x in html for x in
              ('id="setup"', 'id="p-create"', 'id="p-addme"', 'id="t-leave"',
               'id="t-person"', 'id="forperson"', "/api/people",
               "people/lookup", "next-topics", "personal_link")),
              "setup + links + topics hooks")
        banned = [b for b in ("bg-clip-text", "linear-gradient", "aurora",
                              "glassmorphism", "hover:scale-105")
                  if b in html]
        check("ui-no-slop", not banned, f"banned={banned}")
    finally:
        stop(srv)

    # -- DEMO_MODE: people/topics writes blocked, links never resolve --
    srv = start("18212", {"DEMO_MODE": "1"})
    try:
        import urllib.request as _u
        base = "http://127.0.0.1:18212"

        def draw(method, path, obj=None):
            data = json.dumps(obj).encode() if obj is not None else None
            req = _u.Request(base + path, data=data,
                             headers={"Content-Type": "application/json"},
                             method=method)
            try:
                with _u.urlopen(req, timeout=15) as resp:
                    return resp.status, resp.read().decode()
            except urllib.error.HTTPError as e:
                return e.code, e.read().decode()

        s, _ = draw("POST", "/api/people", {"display_name": "X"})
        check("demo-people-403", s == 403, f"status={s}")
        s, _ = draw("POST", "/api/next-topics",
                    {"person_id": "p-x", "topics": ["y"]})
        check("demo-topics-403", s == 403, f"status={s}")
    finally:
        stop(srv)

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("FAILURES:", failed)
        sys.exit(1)


if __name__ == "__main__":
    main()
