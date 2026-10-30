"""Phase 4 descendant suites (MOCK_LLM=1, works offline).

Descendant contract: the exploring generation reads, never adds.
- Ask-the-family over ALL consenting relatives: omitted scope searches
  every consenting relative; each claim cites the right person's voice
  (per-claim person_id); honest not-found when nothing matches.
- Talk-with-a-relative: choose any consented relative (single person_id);
  labeled AI reconstruction; answers use ONLY that relative's words.
- Access per person per consent; revoke/retire isolate per person;
  retirement blocks character only (archive answers stay intact).
- index.html carries the descendant UI hooks, no banned taste patterns.

Usage: python3 test_descendants.py
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

PORT = "18223"
BASE = f"http://127.0.0.1:{PORT}"
TAG = f"desc-{int(time.time()) % 1000000}"


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


def write_session(sid, rows, facts):
    sdir = ROOT / "recordings" / sid
    sdir.mkdir(parents=True, exist_ok=True)
    with open(sdir / "transcript.jsonl", "w") as fh:
        for clip_id, duration, segments, distress in rows:
            srvmod.write_silent_wav(sdir / f"{clip_id}.wav",
                                    seconds=duration)
            fh.write(json.dumps({
                "ts": "2026-01-01T00:00:00+00:00",
                "clip_id": clip_id,
                "history_len": 0,
                "question": "q",
                "transcript": " ".join(s["text"] for s in segments),
                "segments": segments,
                "threads_opened": [],
                "threads_covered": [],
                "pause_suggested": False,
                "distress": distress,
            }) + "\n")
    (sdir / "facts.json").write_text(json.dumps(facts, indent=2))


def bind(sid, pid):
    (ROOT / "recordings" / sid / "person.json").write_text(
        json.dumps({"person_id": pid}))
    pdir = ROOT / "recordings" / "people" / pid
    ppath = pdir / "sessions.json"
    try:
        sessions = json.loads(ppath.read_text())
    except (ValueError, OSError):
        sessions = []
    if sid not in sessions:
        sessions.append(sid)
    ppath.write_text(json.dumps(sessions, indent=2))


def seg(sid, text, dur=10.0):
    return {"id": f"seg-{sid}", "text": text,
            "start": 0.5, "end": dur - 1.0}


def main():
    results = []

    def check(name, cond, detail=""):
        results.append((name, bool(cond), detail))
        print(f"{'PASS' if cond else 'FAIL'} {name}"
              + (f" — {detail}" if detail else ""))

    srv = start(PORT, {})
    try:
        s, t = raw("POST", "/api/people",
                   {"display_name": f"Mae {TAG}", "relation": "grandmother"})
        mae = body(t)
        mae_id, mae_tok = mae.get("person_id", ""), mae.get(
            "person_token", "")
        check("create-mae", s == 200 and mae_id.startswith("p-"),
              f"status={s}")
        s, t = raw("POST", "/api/people",
                   {"display_name": f"Jon {TAG}", "relation": "grandson"})
        jon = body(t)
        jon_id, jon_tok = jon.get("person_id", ""), jon.get(
            "person_token", "")
        check("create-jon", s == 200 and jon_id.startswith("p-"),
              f"status={s}")

        sid_m, sid_j = f"{TAG}-m", f"{TAG}-j"
        seg_m = (f"The {TAG} orchard apples made the best pie "
                 f"every harvest.")
        seg_j = (f"I mended the {TAG} orchard fence with new wire "
                 f"last spring.")
        write_session(sid_m, [(f"clip-{TAG}-m", 10.0,
                               [seg(sid_m, seg_m)], False)], [
            {"kind": "place", "text": f"The {TAG} orchard",
             "when": "", "clip_id": f"clip-{TAG}-m",
             "start": 0.5, "end": 6.0, "segment_id": f"seg-{sid_m}"},
        ])
        write_session(sid_j, [(f"clip-{TAG}-j", 10.0,
                               [seg(sid_j, seg_j)], False)], [
            {"kind": "place", "text": f"the {TAG} orchard",
             "when": "", "clip_id": f"clip-{TAG}-j",
             "start": 0.5, "end": 6.0, "segment_id": f"seg-{sid_j}"},
        ])
        bind(sid_m, mae_id)
        bind(sid_j, jon_id)

        # -- ask-the-family: omitted scope = ALL consenting relatives --
        q = f"What happened at the {TAG} orchard?"
        s, t = raw("POST", "/api/ask", {"question": q})
        d = body(t)
        cites = d.get("citations", [])
        check("ask-family-default-answered",
              s == 200 and d.get("unanswered") is False and cites,
              f"status={s}")
        # Default scope spans every consenting person on disk (earlier
        # runs' fixtures legitimately share it): the contract is current
        # relatives found + every citation carrying a real person_id.
        check("ask-cited-right-voices",
              bool(cites)
              and {mae_id, jon_id} & {c.get("person_id") for c in cites}
              and all((c.get("person_id") or "").startswith("p-")
                      for c in cites),
              f"{[(c.get('person_id'), c.get('session_id')) for c in cites]}")

        # -- honest not-found (no invention) --
        s, t = raw("POST", "/api/ask",
                   {"question": "Xylophone quantum zebra waltz "
                                "quux flibberti"})
        dn = body(t)
        check("ask-honest-not-found",
              s == 200 and dn.get("unanswered") is True,
              f"status={s} unans={dn.get('unanswered')}")

        # -- talk-with-a-relative: any consented relative, only THEIR words --
        s, t = raw("POST", "/api/consent",
                   {"person_id": mae_id, "person_token": mae_tok,
                    "ai_reconstruction": True, "access": "family",
                    "access_list": ["Visitor"], "voice_clone": False})
        codes = body(t).get("invite_codes", {})
        check("consent-codes", s == 200 and codes.get("Visitor"), f"s={s}")
        code = codes.get("Visitor", "")
        s, t = raw("POST", "/api/character",
                   {"person_id": mae_id, "question": q,
                    "requester": "Visitor", "invite_code": code})
        ch = body(t)
        chc = ch.get("citations", [])
        check("character-labeled",
              s == 200 and ch.get("reconstruction") is True
              and ch.get("ai_label")
              and "not the person" in str(ch.get("ai_label", "")),
              f"status={s}")
        check("character-only-their-words",
              s == 200 and chc
              and all(c.get("person_id") == mae_id for c in chc)
              and all(c.get("session_id") == sid_m for c in chc),
              f"status={s} cites={[(c.get('person_id'), c.get('session_id')) for c in chc]}")
        check("character-person-id",
              ch.get("person_id") == mae_id, f"{ch.get('person_id')}")
        s, _ = raw("POST", "/api/character",
                   {"person_id": mae_id, "question": q,
                    "requester": "Visitor", "invite_code": "wrong"})
        check("character-wrong-code-403", s == 403, f"status={s}")
        s, _ = raw("POST", "/api/character",
                   {"person_id": jon_id, "question": q,
                    "requester": "Visitor", "invite_code": code})
        check("character-other-no-consent-403", s == 403, f"status={s}")

        # -- consent matrix per person: retire blocks character only --
        s, _ = raw("POST", "/api/consent",
                   {"person_id": mae_id, "person_token": mae_tok,
                    "retire": True})
        check("retire-mae", s == 200, f"status={s}")
        s, _ = raw("POST", "/api/character",
                   {"person_id": mae_id, "question": q,
                    "requester": "Visitor", "invite_code": code})
        check("retired-character-dark", s == 403, f"status={s}")
        s, t = raw("POST", "/api/ask",
                   {"person_ids": [mae_id], "question": q})
        check("retired-ask-intact",
              s == 200 and body(t).get("unanswered") is False,
              f"status={s}")
        s, _ = raw("POST", "/api/consent",
                   {"person_id": mae_id, "person_token": mae_tok,
                    "retire": False})
        s, t = raw("POST", "/api/character",
                   {"person_id": mae_id, "question": q,
                    "requester": "Visitor", "invite_code": code})
        check("unretire-restores",
              s == 200 and body(t).get("unanswered") is False,
              f"status={s}")

        # -- revoke isolates per person: mae dark, jon untouched --
        s, _ = raw("POST", "/api/consent",
                   {"person_id": mae_id, "person_token": mae_tok,
                    "revoke": True})
        check("revoke-mae", s == 200, f"status={s}")
        s, _ = raw("POST", "/api/character",
                   {"person_id": mae_id, "question": q,
                    "requester": "Visitor", "invite_code": code})
        check("revoked-character-dark", s == 403, f"status={s}")
        s, t = raw("POST", "/api/ask", {"question": q})
        dflt = body(t)
        check("revoked-excluded-default",
              s == 200
              and all(c.get("session_id") != sid_m
                      for c in dflt.get("citations", [])),
              f"status={s}")
        qj = f"Who mended the {TAG} orchard fence?"
        s, t = raw("POST", "/api/ask",
                   {"person_ids": [jon_id], "question": qj})
        dj = body(t)
        check("revoke-isolated-jon",
              s == 200 and dj.get("unanswered") is False
              and {c.get("person_id") for c in dj.get("citations", [])}
              == {jon_id},
              f"status={s}")

        # -- descendant UI hooks, no banned taste patterns --
        html = (ROOT / "index.html").read_text()
        check("ui-descendant-wiring", all(x in html for x in
              ('id="askpersons"', 'id="charperson"', 'id="charlabel"',
               'id="charbanner"', "whole family",
               "only that relative", "relative ${c.person_id}",
               "Retired relatives stay unavailable")),
              "ask-everyone + per-relative talk hooks")
        banned = [b for b in ("bg-clip-text", "linear-gradient", "aurora",
                              "glassmorphism", "hover:scale-105")
                  if b in html]
        check("ui-no-slop", not banned, f"banned={banned}")
    finally:
        stop(srv)

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("FAILURES:", failed)
        sys.exit(1)


if __name__ == "__main__":
    main()
