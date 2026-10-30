"""Phase 3 family-archive tests (MOCK_LLM=1, works offline).

Covers the cross-person generational contract:
- Person-level identity: sessions bind to exactly one person (no roles).
- Entity linking: the same person/place mentioned by several relatives
  (case/spacing variants) becomes ONE entity with each relative's cited clip.
- Corroboration display: >=2 consenting relatives -> corroborated badge.
- Disagreement display: conflicting whens stay side-by-side with
  per-relative citations, NEVER merged into one canonical fact.
- Ask-the-family: POST /api/ask gains optional person_ids; omitted scope =
  all consenting persons; non-consenting persons silently excluded.
- Talk-with-a-relative: POST /api/character takes {person_id, ...} (single
  person only); revoke/retire isolate per person.
- index.html carries the family archive UI hooks, no banned taste patterns.

Usage: python3 test_family.py
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

PORT = "18221"
BASE = f"http://127.0.0.1:{PORT}"
TAG = f"fam-{int(time.time()) % 1000000}"


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
    """Disk fixture like ask_eval_common: silent wav + transcript + facts."""
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
        # -- two relatives, fluid roles (helper records too) --
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

        # -- sessions bound 1:1 to a person; same entities, variant spellings,
        #    conflicting whens (side-by-side, never merged) --
        sid_a1, sid_a2, sid_b = f"{TAG}-a1", f"{TAG}-a2", f"{TAG}-b"
        seg_a1 = (f"I grew up near the {TAG} bakehouse. "
                  f"Grandma Zinnia {TAG} taught us everything.")
        seg_a2 = (f"Grandma Zinnia {TAG} kept the garden behind the house.")
        seg_b = (f"grandma   zinnia {TAG} ran the {TAG} bakehouse counter, "
                 f"that is what I remember.")
        write_session(sid_a1, [(f"clip-{TAG}-a1", 10.0,
                                [seg(sid_a1, seg_a1)], False)], [
            {"kind": "person", "text": f"Grandma Zinnia {TAG}",
             "when": "1962", "clip_id": f"clip-{TAG}-a1",
             "start": 0.5, "end": 6.0, "segment_id": f"seg-{sid_a1}"},
            {"kind": "place", "text": f"The {TAG} Bakehouse",
             "when": "", "clip_id": f"clip-{TAG}-a1",
             "start": 0.5, "end": 6.0, "segment_id": f"seg-{sid_a1}"},
        ])
        write_session(sid_a2, [(f"clip-{TAG}-a2", 10.0,
                                [seg(sid_a2, seg_a2)], False)], [
            {"kind": "person", "text": f"Grandma Zinnia {TAG}",
             "when": "1962", "clip_id": f"clip-{TAG}-a2",
             "start": 0.5, "end": 6.0, "segment_id": f"seg-{sid_a2}"},
        ])
        write_session(sid_b, [(f"clip-{TAG}-b", 10.0,
                               [seg(sid_b, seg_b)], False)], [
            {"kind": "person", "text": f"grandma   zinnia {TAG}",
             "when": "1963", "clip_id": f"clip-{TAG}-b",
             "start": 0.5, "end": 6.0, "segment_id": f"seg-{sid_b}"},
            {"kind": "place", "text": f"the {TAG} bakehouse",
             "when": "", "clip_id": f"clip-{TAG}-b",
             "start": 0.5, "end": 6.0, "segment_id": f"seg-{sid_b}"},
        ])
        bind(sid_a1, rosa_id)
        bind(sid_a2, rosa_id)
        bind(sid_b, sam_id)

        # -- entity linking across relatives --
        s, t = raw("GET", f"/api/family-entities?person_ids={rosa_id},{sam_id}")
        fam = body(t)
        ents = {e["normalized"]: e for e in fam.get("entities", [])}
        zin = ents.get(f"grandma zinnia {TAG}".lower())
        bak = ents.get(f"the {TAG} bakehouse")
        check("entities-200", s == 200 and len(fam.get("entities", [])) == 2,
              f"status={s} n={len(fam.get('entities', []))}")
        check("link-one-entity", zin is not None and len(zin["mentions"]) == 3,
              f"mentions={len(zin['mentions']) if zin else 0}")
        persons = {m["person_id"] for m in (zin or {}).get("mentions", [])}
        check("link-both-relatives", persons == {rosa_id, sam_id},
              f"{sorted(persons)}")

        # -- every mention cites a real playable clip slice --
        clips_ok = True
        for m in (zin or {}).get("mentions", []) + (
                (bak or {}).get("mentions", [])):
            clip = (ROOT / "recordings" / m["session_id"] /
                    (m["clip_id"] + ".wav"))
            if not (clip.is_file() and 0.0 <= m["start"] < m["end"]
                    and m["quote"].strip()
                    and m["session_id"] in (sid_a1, sid_a2, sid_b)):
                clips_ok = False
        check("mentions-cited-clips", clips_ok and bool(zin) and bool(bak),
              "all mentions resolve to real slices")

        # -- corroboration shown, disagreements side-by-side, never merged --
        check("corroborated-badge",
              bool(zin) and zin.get("corroborated") is True
              and len(zin.get("corroborated_by", [])) == 2,
              f"{(zin or {}).get('corroborated_by')}")
        check("bakery-corroborated",
              bool(bak) and bak.get("corroborated") is True,
              f"{(bak or {}).get('corroborated_by')}")
        dz = (zin or {}).get("disagreements", [])
        dwhens = sorted(d.get("when") for d in dz)
        check("disagreement-side-by-side",
              dwhens == ["1962", "1963"]
              and all(len(d.get("mentions", [])) >= 1 for d in dz),
              f"whens={dwhens}")
        check("no-merge",
              (zin or {}).get("whens", []) == ["1962", "1963"]
              and not bak.get("disagreements"),
              f"zin={zin.get('whens') if zin else None}")

        # -- ask-the-family across relatives (retrieval is top-k=2, so one
        #    answer may cite one relative; spanning is proven by the union
        #    of targeted questions, each staying strictly in scope) --
        q = f"What did Grandma Zinnia {TAG} teach?"
        s, t = raw("POST", "/api/ask",
                   {"person_ids": [rosa_id, sam_id], "question": q})
        d = body(t)
        cites = d.get("citations", [])
        check("ask-family-answered",
              s == 200 and d.get("unanswered") is False and len(cites) >= 1,
              f"status={s} n={len(cites)}")
        qb = f"Who ran the {TAG} bakehouse counter {TAG}?"
        s, t = raw("POST", "/api/ask",
                   {"person_ids": [rosa_id, sam_id], "question": qb})
        db = body(t)
        cites_b = db.get("citations", [])
        check("ask-family-answered-b",
              s == 200 and db.get("unanswered") is False and cites_b,
              f"status={s}")
        spanned = ({c.get("person_id") for c in cites}
                   | {c.get("person_id") for c in cites_b})
        check("ask-family-spans-relatives", spanned == {rosa_id, sam_id},
              f"{sorted(spanned)}")
        leaked = [c for c in cites + cites_b
                  if c.get("session_id") not in (sid_a1, sid_a2, sid_b)]
        check("ask-family-no-leak", not leaked and all(
            c.get("quote", "").strip() for c in cites + cites_b),
              f"leaked={len(leaked)}")

        # -- omitted scope = all consenting persons --
        s, t = raw("POST", "/api/ask", {"question": qb})
        dflt = body(t)
        dcites = dflt.get("citations", [])
        # Default scope spans every consenting person (earlier runs'
        # fixtures linger on disk, so citations may include them): the
        # contract is answered + current relatives found + nobody revoked.
        revoked_hit = False
        for c in dcites:
            _, tc = raw("GET", f"/api/consent?person_id={c.get('person_id')}")
            if body(tc).get("consent", {}).get("revoked"):
                revoked_hit = True
        check("ask-default-scope",
              s == 200 and dflt.get("unanswered") is False and dcites
              and {rosa_id, sam_id} & {c.get("person_id") for c in dcites}
              and not revoked_hit,
              f"status={s} unans={dflt.get('unanswered')} "
              f"cites={[(c.get('person_id'), c.get('session_id')) for c in dcites]}")
        # -- unknown persons resolve to nothing (unanswered, not error) --
        s, t = raw("POST", "/api/ask",
                   {"person_ids": ["p-nope"], "question": q})
        dd = body(t)
        check("ask-unknown-person-unanswered",
              s == 200 and dd.get("unanswered") is True
              and dd.get("citations") == [],
              f"status={s}")

        # -- revoked relative silently excluded (never leaks) --
        s, _ = raw("POST", "/api/consent",
                   {"person_id": sam_id, "person_token": sam_tok,
                    "revoke": True})
        check("revoke-sam", s == 200, f"status={s}")
        s, t = raw("GET", f"/api/family-entities?person_ids={rosa_id},{sam_id}")
        fam2 = body(t)
        ents2 = {e["normalized"]: e for e in fam2.get("entities", [])}
        zin2 = ents2.get(f"grandma zinnia {TAG}".lower())
        check("revoked-excluded-from-entities",
              s == 200 and zin2 is not None
              and {m["person_id"] for m in zin2["mentions"]} == {rosa_id}
              and zin2.get("corroborated") is False,
              f"status={s}")
        s, t = raw("POST", "/api/ask",
                   {"person_ids": [rosa_id, sam_id], "question": q})
        d2 = body(t)
        check("revoked-excluded-from-ask",
              s == 200 and d2.get("unanswered") is False
              and {c.get("person_id") for c in d2.get("citations", [])}
              == {rosa_id},
              f"status={s}")
        s, t = raw("POST", "/api/ask", {"question": qb})
        d2b = body(t)
        check("revoked-excluded-from-default",
              s == 200 and all(c.get("session_id") != sid_b
                               for c in d2b.get("citations", [])),
              f"status={s}")
        # -- restore sam (any save clears revoked) --
        s, _ = raw("POST", "/api/consent",
                   {"person_id": sam_id, "person_token": sam_tok,
                    "access": "family"})
        check("unrevoke-sam", s == 200, f"status={s}")

        # -- talk-with-a-relative: per-person consent gate --
        s, t = raw("POST", "/api/consent",
                   {"person_id": rosa_id, "person_token": rosa_tok,
                    "ai_reconstruction": True, "access": "family",
                    "access_list": ["Visitor"], "voice_clone": False})
        codes = body(t).get("invite_codes", {})
        check("consent-codes", s == 200 and codes.get("Visitor"), f"s={s}")
        code = codes.get("Visitor", "")
        chq = f"What did Grandma Zinnia {TAG} teach?"
        s, t = raw("POST", "/api/character",
                   {"person_id": rosa_id, "question": chq,
                    "requester": "Visitor", "invite_code": code})
        ch = body(t)
        check("character-person-ok",
              s == 200 and ch.get("reconstruction") is True
              and ch.get("ai_label")
              and ch.get("unanswered") is False
              and {c.get("session_id") for c in ch.get("citations", [])}
              <= {sid_a1, sid_a2},
              f"status={s}")
        s, _ = raw("POST", "/api/character",
                   {"person_id": rosa_id, "question": chq,
                    "requester": "Visitor", "invite_code": "wrong"})
        check("character-wrong-code-403", s == 403, f"status={s}")
        s, _ = raw("POST", "/api/character",
                   {"person_id": sam_id, "question": chq,
                    "requester": "Visitor", "invite_code": code})
        check("character-no-consent-403", s == 403, f"status={s}")
        s, _ = raw("POST", "/api/character",
                   {"person_id": "p-nope", "question": chq,
                    "requester": "Visitor", "invite_code": code})
        check("character-unknown-person-403", s == 403, f"status={s}")

        # -- retire isolates per person: character dark, archive intact --
        s, _ = raw("POST", "/api/consent",
                   {"person_id": rosa_id, "person_token": rosa_tok,
                    "retire": True})
        check("retire-rosa", s == 200, f"status={s}")
        s, _ = raw("POST", "/api/character",
                   {"person_id": rosa_id, "question": chq,
                    "requester": "Visitor", "invite_code": code})
        check("retired-character-dark", s == 403, f"status={s}")
        s, t = raw("POST", "/api/ask",
                   {"person_ids": [rosa_id], "question": q})
        check("retired-ask-intact",
              s == 200 and body(t).get("unanswered") is False,
              f"status={s}")
        s, _ = raw("POST", "/api/consent",
                   {"person_id": rosa_id, "person_token": rosa_tok,
                    "retire": False})
        s, t = raw("POST", "/api/character",
                   {"person_id": rosa_id, "question": chq,
                    "requester": "Visitor", "invite_code": code})
        check("unretire-restores",
              s == 200 and body(t).get("unanswered") is False,
              f"status={s}")

        # -- revoke isolates per person: rosa dark, sam untouched --
        s, _ = raw("POST", "/api/consent",
                   {"person_id": rosa_id, "person_token": rosa_tok,
                    "revoke": True})
        check("revoke-rosa", s == 200, f"status={s}")
        s, _ = raw("POST", "/api/character",
                   {"person_id": rosa_id, "question": chq,
                    "requester": "Visitor", "invite_code": code})
        check("revoked-character-dark", s == 403, f"status={s}")
        s, t = raw("POST", "/api/ask",
                   {"session_ids": [sid_a1], "question": q})
        check("revoked-ask-dark", s == 403, f"status={s}")
        s, t = raw("POST", "/api/ask",
                   {"session_ids": [sid_b], "question": qb})
        d3 = body(t)
        check("revoke-isolated",
              s == 200 and d3.get("unanswered") is False
              and {c.get("person_id") for c in d3.get("citations", [])}
              == {sam_id},
              f"status={s}")

        # -- family archive UI hooks, no banned taste patterns --
        html = (ROOT / "index.html").read_text()
        check("ui-family-wiring", all(x in html for x in
              ('id="step-family"', 'id="fampersons"', 'id="famload"',
               'id="family-entities"', "/api/family-entities",
               'id="askpersons"', 'id="charperson"', "Both mention this",
               "side-by-side")),
              "family archive + ask-across + per-relative hooks")
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