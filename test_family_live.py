"""Phase 3 family-archive tests, LIVE path (MOCK_LLM=0, needs FIREWORKS_API_KEY).

Same cross-person contract as test_family.py, served by a live-mode
server: entity linking, corroboration display, disagreement display, and
no-merge are deterministic; ask-the-family and talk-with-a-relative run
once each against the real Fireworks model (grounded + cited or the
not-found sentence — never invented).

MANDATORY ENV RULE: source .env first (FIREWORKS_API_KEY, DEMO_PASSWORD
empty). Missing key fails loudly (exit 1) — a skip would hide an
untested live path.

Usage:
  source .env
  DEMO_PASSWORD= python3 test_family_live.py
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

PORT = os.environ.get("FAMILY_LIVE_PORT", "18222")
BASE = f"http://127.0.0.1:{PORT}"
TAG = f"fam-live-{int(time.time()) % 1000000}"


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
        print("FAIL: no FIREWORKS_API_KEY in environment — live family "
              "eval needs a key (source .env first).")
        return 1
    if os.environ.get("MOCK_LLM", "1") != "0":
        print("FAIL: MOCK_LLM must be 0 for the live family eval.")
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
                   {"display_name": f"Lydia {TAG}", "relation": "aunt"})
        lydia = body(t)
        lid, ltok = lydia.get("person_id", ""), lydia.get("person_token",
                                                          "")
        s, t = raw("POST", "/api/people",
                   {"display_name": f"Noah {TAG}", "relation": "nephew"})
        noah = body(t)
        nid, ntok = noah.get("person_id", ""), noah.get("person_token",
                                                       "")
        check("live-create-persons",
              lid.startswith("p-") and nid.startswith("p-"), lid[:8])

        sid_l, sid_n = f"{TAG}-l", f"{TAG}-n"
        seg_l = (f"Uncle Bram {TAG} built the {TAG} boathouse "
                 f"with his own hands.")
        seg_n = (f"uncle  bram {TAG} painted the {TAG} boathouse "
                 f"every spring.")
        for sid, segtext, clip, when in [
                (sid_l, seg_l, f"clip-{TAG}-l", "the spring of 1971"),
                (sid_n, seg_n, f"clip-{TAG}-n", "the spring of 1972")]:
            sdir = ROOT / "recordings" / sid
            sdir.mkdir(parents=True, exist_ok=True)
            srvmod.write_silent_wav(sdir / f"{clip}.wav", seconds=10.0)
            seg = {"id": f"seg-{sid}", "text": segtext,
                   "start": 0.5, "end": 9.0}
            with open(sdir / "transcript.jsonl", "w") as fh:
                fh.write(json.dumps({
                    "ts": "2026-01-01T00:00:00+00:00", "clip_id": clip,
                    "history_len": 0, "question": "q",
                    "transcript": segtext, "segments": [seg],
                    "threads_opened": [], "threads_covered": [],
                    "pause_suggested": False, "distress": False,
                }) + "\n")
            (sdir / "facts.json").write_text(json.dumps([{
                "kind": "person", "text": segtext.split(" built ")[0]
                if " built " in segtext else segtext.split(" painted ")[0],
                "when": when, "clip_id": clip,
                "start": 0.5, "end": 9.0,
                "segment_id": f"seg-{sid}"}], indent=2))
        for sid, pid in ((sid_l, lid), (sid_n, nid)):
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

        # -- deterministic index checks, served live --
        s, t = raw("GET",
                   f"/api/family-entities?person_ids={lid},{nid}")
        fam = body(t)
        ents = {e["normalized"]: e for e in fam.get("entities", [])}
        ent = ents.get(f"uncle bram {TAG}".lower())
        check("live-entities-200", s == 200 and ent is not None,
              f"status={s}")
        check("live-link-corroborated",
              bool(ent) and ent.get("corroborated") is True
              and len(ent.get("mentions", [])) == 2
              and len(ent.get("corroborated_by", [])) == 2,
              f"{(ent or {}).get('corroborated_by')}")
        dz = (ent or {}).get("disagreements", [])
        check("live-disagreement-no-merge",
              sorted(d.get("when") for d in dz)
              == ["the spring of 1971", "the spring of 1972"]
              and all(len(d.get("mentions", [])) == 1 for d in dz),
              f"{[d.get('when') for d in dz]}")

        # -- live ask-the-family: grounded + cited, spanning relatives --
        q = f"Who worked on the {TAG} boathouse?"
        s, t = raw("POST", "/api/ask",
                   {"person_ids": [lid, nid], "question": q})
        d = body(t)
        cites = d.get("citations", [])
        ok, why = (check_citations(None, [sid_l, sid_n], cites)
                   if cites else (False, "no citations"))
        answered_ok = (d.get("unanswered") is False and ok)
        refused_ok = (d.get("answer_text") == NOT_FOUND
                      and d.get("unanswered") is True and cites == [])
        check("live-ask-family", s == 200 and (answered_ok or refused_ok),
              f"status={s} {why[:80]}")
        if cites:
            check("live-ask-spans",
                  {c.get("person_id") for c in cites} <= {lid, nid}
                  and cites[0].get("person_id") in (lid, nid),
                  f"{[c.get('person_id') for c in cites]}")

        # -- live talk-with-a-relative under per-person consent --
        s, t = raw("POST", "/api/consent",
                   {"person_id": lid, "person_token": ltok,
                    "ai_reconstruction": True, "access": "family",
                    "access_list": ["Guest"], "voice_clone": False})
        code = body(t).get("invite_codes", {}).get("Guest", "")
        s, t = raw("POST", "/api/character",
                   {"person_id": lid,
                    "question": f"What did Uncle Bram {TAG} build?",
                    "requester": "Guest", "invite_code": code})
        ch = body(t)
        ch_cites = ch.get("citations", [])
        okc, whyc = (check_citations(None, [sid_l, sid_n], ch_cites)
                     if ch_cites else (False, "no citations"))
        ch_ok = (s == 200 and ch.get("reconstruction") is True
                 and ch.get("ai_label")
                 and ((ch.get("unanswered") is False and okc)
                      or (ch.get("answer_text", "").startswith(NOT_FOUND)
                          and ch_cites == [])))
        check("live-character-person",
              ch_ok, f"status={s} {whyc[:80]}")

        # -- revoke isolates, live too --
        s, _ = raw("POST", "/api/consent",
                   {"person_id": nid, "person_token": ntok,
                    "revoke": True})
        s, t = raw("GET",
                   f"/api/family-entities?person_ids={lid},{nid}")
        fam2 = body(t)
        ent2 = {e["normalized"]: e for e in fam2.get("entities", [])}.get(
            f"uncle bram {TAG}".lower())
        check("live-revoke-isolated",
              s == 200 and ent2 is not None
              and {m["person_id"] for m in ent2["mentions"]} == {lid},
              f"status={s}")
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
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())