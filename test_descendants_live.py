"""Phase 4 descendant suites, LIVE path (MOCK_LLM=0, needs FIREWORKS_API_KEY).

Same descendant contract as test_descendants.py, served by a live-mode
server: ask-the-family default scope, per-claim person_id citations, and
the single-relative reconstruction run once each against the real
Fireworks model (grounded + cited or the not-found sentence — never
invented). Revoke/retire isolation is deterministic.

MANDATORY ENV RULE: source .env first (FIREWORKS_API_KEY, DEMO_PASSWORD
empty). Missing key fails loudly (exit 1) — a skip would hide an
untested live path.

Usage:
  source .env
  DEMO_PASSWORD= python3 test_descendants_live.py
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

PORT = os.environ.get("DESC_LIVE_PORT", "18224")
BASE = f"http://127.0.0.1:{PORT}"
TAG = f"desc-live-{int(time.time()) % 1000000}"


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
    key = os.environ.get("FIREWORKS_API_KEY", "")
    if key:
        print(f"key check: present len={len(key)} prefix={key[:4]}****")
    else:
        print("FAIL: no FIREWORKS_API_KEY in environment — live descendant "
              "eval needs a key (source .env first).")
        return 1
    if os.environ.get("MOCK_LLM", "1") != "0":
        print("FAIL: MOCK_LLM must be 0 for the live descendant eval.")
        return 1
    from ask_eval_common import NOT_FOUND, check_citations

    results = []

    def check(name, cond, detail=""):
        results.append((name, bool(cond), detail))
        print(f"{'PASS' if cond else 'FAIL'} {name}"
              + (f" — {detail}" if detail else ""))

    env = dict(os.environ, MOCK_LLM="0", PORT=PORT)
    srv = subprocess.Popen(
        [sys.executable, "server.py"], env=env, cwd=str(ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(BASE + "/", timeout=2).read()
                break
            except Exception:
                time.sleep(0.5)

        s, t = raw("POST", "/api/people",
                   {"display_name": f"Tess {TAG}", "relation": "aunt"})
        tess = body(t)
        tid, ttok = tess.get("person_id", ""), tess.get("person_token", "")
        s, t = raw("POST", "/api/people",
                   {"display_name": f"Abe {TAG}", "relation": "nephew"})
        abe = body(t)
        aid, atok = abe.get("person_id", ""), abe.get("person_token", "")
        check("live-create-persons",
              tid.startswith("p-") and aid.startswith("p-"), tid[:8])

        sid_t, sid_a = f"{TAG}-t", f"{TAG}-a"
        seg_t = (f"Aunt Wren {TAG} baked the {TAG} mill bread "
                 f"every Sunday.")
        seg_a = (f"uncle  wren {TAG} ground the {TAG} mill flour "
                 f"with stone wheels.")
        for sid, segtext, clip in [
                (sid_t, seg_t, f"clip-{TAG}-t"),
                (sid_a, seg_a, f"clip-{TAG}-a")]:
            sdir = ROOT / "recordings" / sid
            sdir.mkdir(parents=True, exist_ok=True)
            srvmod.write_silent_wav(sdir / f"{clip}.wav", seconds=10.0)
            segm = {"id": f"seg-{sid}", "text": segtext,
                    "start": 0.5, "end": 9.0}
            with open(sdir / "transcript.jsonl", "w") as fh:
                fh.write(json.dumps({
                    "ts": "2026-01-01T00:00:00+00:00", "clip_id": clip,
                    "history_len": 0, "question": "q",
                    "transcript": segtext, "segments": [segm],
                    "threads_opened": [], "threads_covered": [],
                    "pause_suggested": False, "distress": False,
                }) + "\n")
            fact = {"kind": "person", "text": segtext.split(" baked ")[0]
                    if sid == sid_t else segtext.split(" ground ")[0],
                    "when": "", "clip_id": clip,
                    "start": 0.5, "end": 6.0,
                    "segment_id": f"seg-{sid}"}
            (sdir / "facts.json").write_text(json.dumps([fact], indent=2))
            (sdir / "person.json").write_text(json.dumps(
                {"person_id": tid if sid == sid_t else aid}))
            pdir = ROOT / "recordings" / "people" / (
                tid if sid == sid_t else aid)
            ppath = pdir / "sessions.json"
            try:
                sessions = json.loads(ppath.read_text())
            except (ValueError, OSError):
                sessions = []
            if sid not in sessions:
                sessions.append(sid)
            ppath.write_text(json.dumps(sessions, indent=2))

        # -- live ask-the-family across relatives (grounded or not-found) --
        q = f"Who baked the {TAG} mill bread?"
        s, t = raw("POST", "/api/ask",
                   {"person_ids": [tid, aid], "question": q})
        d = body(t)
        cites = d.get("citations", [])
        if d.get("unanswered"):
            check("live-ask-family",
                  s == 200 and NOT_FOUND in str(d.get("answer_text", "")),
                  f"status={s} honest-not-found")
        else:
            ok, detail = check_citations(None, [sid_t, sid_a], cites)
            check("live-ask-family",
                  s == 200 and ok
                  and all(c.get("person_id") in (tid, aid) for c in cites),
                  f"status={s} {detail}")

        # -- live default scope finds the current relatives --
        s, t = raw("POST", "/api/ask", {"question": q})
        dd = body(t)
        dcites = dd.get("citations", [])
        check("live-ask-default-scope",
              s == 200 and (
                  dd.get("unanswered") is True
                  or ({tid, aid} & {c.get("person_id") for c in dcites})),
              f"status={s}")

        # -- live talk-with-a-relative: labeled, only their words --
        s, t = raw("POST", "/api/consent",
                   {"person_id": tid, "person_token": ttok,
                    "ai_reconstruction": True, "access": "family",
                    "access_list": ["Visitor"], "voice_clone": False})
        code = body(t).get("invite_codes", {}).get("Visitor", "")
        check("live-consent-codes", bool(code), f"s={s}")
        s, t = raw("POST", "/api/character",
                   {"person_id": tid, "question": q,
                    "requester": "Visitor", "invite_code": code})
        ch = body(t)
        chc = ch.get("citations", [])
        if ch.get("unanswered"):
            check("live-character-relative",
                  s == 200 and ch.get("reconstruction") is True
                  and ch.get("ai_label")
                  and ch.get("person_id") == tid,
                  f"status={s} honest-not-found")
        else:
            ok, detail = check_citations(None, [sid_t], chc)
            check("live-character-relative",
                  s == 200 and ok and ch.get("reconstruction") is True
                  and ch.get("ai_label")
                  and ch.get("person_id") == tid
                  and all(c.get("person_id") == tid for c in chc),
                  f"status={s} {detail}")

        # -- live consent matrix: retire darkens character, ask intact --
        s, _ = raw("POST", "/api/consent",
                   {"person_id": tid, "person_token": ttok,
                    "retire": True})
        check("live-retire", s == 200, f"status={s}")
        s, _ = raw("POST", "/api/character",
                   {"person_id": tid, "question": q,
                    "requester": "Visitor", "invite_code": code})
        check("live-retired-character-dark", s == 403, f"status={s}")
        s, t = raw("POST", "/api/ask",
                   {"person_ids": [tid], "question": q})
        check("live-retired-ask-intact", s == 200, f"status={s}")
        s, _ = raw("POST", "/api/consent",
                   {"person_id": tid, "person_token": ttok,
                    "retire": False})
        s, _ = raw("POST", "/api/consent",
                   {"person_id": tid, "person_token": ttok,
                    "revoke": True})
        check("live-revoke", s == 200, f"status={s}")
        s, t = raw("POST", "/api/ask", {"question": q})
        check("live-revoked-excluded-default",
              all(c.get("session_id") != sid_t
                  for c in body(t).get("citations", [])),
              f"status={s}")
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
