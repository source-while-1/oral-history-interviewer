"""Shareable-demo hardening tests (MOCK_LLM=1, works offline).

Covers Tasks 1+2 (+ share.sh contract):
- DEMO_MODE=1: POST /api/turn + /api/consent (save/revoke/retire) -> 403
  with no writes to recordings/; arbitrary session ids -> 404 on every
  session-scoped route; the fictional demo session still serves facts,
  clips, ask, and character with the published demo invite code.
- Rate limits (LLM routes only): per-IP cap -> 429, CF-Connecting-IP is
  honored as the client identity, global daily cap -> 429 across IPs,
  static pages and clip replay stay unlimited.
- share.sh exists, is executable, binds 127.0.0.1 in DEMO_MODE with
  MOCK_LLM=0, and prints the brew install line when cloudflared is gone.

Usage: python3 test_share.py
"""

import json
import os
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent

PORT_DEMO = "18121"
PORT_IP = "18122"
PORT_DAY = "18123"
BASE_DEMO = f"http://127.0.0.1:{PORT_DEMO}"
BASE_IP = f"http://127.0.0.1:{PORT_IP}"
BASE_DAY = f"http://127.0.0.1:{PORT_DAY}"


def raw(base, method, path, obj=None, headers=None):
    heads = dict(headers or {})
    data = None
    if obj is not None:
        data = json.dumps(obj).encode()
        heads.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(base + path, data=data,
                                 headers=heads, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def body(text):
    try:
        return json.loads(text or "{}")
    except ValueError:
        return {}


def start(port, extra_env):
    env = dict(os.environ, MOCK_LLM="1", PORT=port, **extra_env)
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


def main():
    results = []

    def check(name, cond, detail=""):
        results.append((name, bool(cond), detail))
        print(f"{'PASS' if cond else 'FAIL'} {name}"
              + (f" — {detail}" if detail else ""))

    srv = start(PORT_DEMO, {"DEMO_MODE": "1"})
    try:
        # -- demo-info advertises the fictional session + invite code --
        s, t = raw(BASE_DEMO, "GET", "/api/demo-info")
        info = body(t)
        ch = info.get("character", {})
        check("demo-info", s == 200 and info.get("demo_mode") is True
              and ch.get("session_id") == "demo-synthetic"
              and ch.get("requester") and ch.get("invite_code"),
              f"status={s} char={ch}")
        demo_sid = ch.get("session_id") or "demo-synthetic"
        requester, code = ch.get("requester"), ch.get("invite_code")

        # -- write blocking: turn + consent save/revoke/retire -> 403 --
        sdir = ROOT / "recordings" / demo_sid
        before = {p.name: (p.read_bytes() if p.is_file() else None)
                  for p in (sdir / "transcript.jsonl", sdir / "facts.json",
                            sdir / "threads.json", sdir / "consent.json")}
        s, t = raw(BASE_DEMO, "POST", "/api/turn",
                   {"session_id": "demo-synthetic", "audio_b64": "",
                    "history": [], "transcript": "hello", "segments": []})
        check("demo-turn-403", s == 403 and "replay-only" in t, f"status={s}")
        for payload, name in (
                ({"session_id": demo_sid, "access": "x"}, "save"),
                ({"session_id": demo_sid, "revoke": True}, "revoke"),
                ({"session_id": demo_sid, "retire": True}, "retire")):
            s, t = raw(BASE_DEMO, "POST", "/api/consent", payload)
            check(f"demo-consent-{name}-403",
                  s == 403 and "replay-only" in t, f"status={s}")
        s, t = raw(BASE_DEMO, "POST", "/api/turn",
                   {"session_id": "brand-new-session", "audio_b64": "",
                    "history": [], "transcript": "hi", "segments": []})
        check("demo-new-session-blocked",
              s == 403 and not (ROOT / "recordings"
                                / "brand-new-session").exists(),
              f"status={s}")
        after = {p.name: (p.read_bytes() if p.is_file() else None)
                 for p in (sdir / "transcript.jsonl", sdir / "facts.json",
                           sdir / "threads.json", sdir / "consent.json")}
        check("demo-no-recordings-write", before == after,
              "transcript/facts/threads/consent byte-identical")

        # -- arbitrary session ids -> 404 on every session-scoped route --
        for method, path, obj, name in (
                ("GET", "/api/facts?session_id=arbitrary-xyz", None, "facts"),
                ("GET", "/api/threads?session_id=arbitrary-xyz", None, "threads"),
                ("GET", "/api/consent?session_id=arbitrary-xyz", None, "consent"),
                ("GET", "/api/clip?session_id=arbitrary-xyz&clip_id=clip-1",
                 None, "clip"),
                ("POST", "/api/ask",
                 {"session_ids": ["arbitrary-xyz"], "question": "What?"},
                 "ask"),
                ("POST", "/api/character",
                 {"session_ids": ["arbitrary-xyz"], "question": "What?",
                  "requester": "x", "invite_code": "y"}, "character")):
            s, _ = raw(BASE_DEMO, method, path, obj)
            check(f"demo-404-{name}", s == 404, f"status={s}")

        # -- fictional demo session still serves (facts/ask/character) --
        s, t = raw(BASE_DEMO, "GET",
                   f"/api/facts?session_id={demo_sid}")
        facts = body(t).get("facts") or []
        check("demo-facts-serve", s == 200 and len(facts) > 0,
              f"status={s} facts={len(facts)}")
        s, t = raw(BASE_DEMO, "POST", "/api/ask",
                   {"session_ids": [demo_sid],
                    "question": "What did she say about the farm?"})
        d = body(t)
        check("demo-ask-serve", s == 200 and d.get("answer_text"),
              f"status={s}")
        s, t = raw(BASE_DEMO, "POST", "/api/character",
                   {"session_ids": [demo_sid],
                    "question": "What did you love about the farm?",
                    "requester": requester, "invite_code": code})
        d = body(t)
        check("demo-character-invite", s == 200
              and d.get("reconstruction") is True
              and d.get("answer_text"), f"status={s}")
        s, t = raw(BASE_DEMO, "POST", "/api/character",
                   {"session_ids": [demo_sid],
                    "question": "What did you love about the farm?",
                    "requester": requester, "invite_code": "wrong-code"})
        check("demo-character-bad-code-403", s == 403, f"status={s}")

        # -- clip replay unlimited: hammer one demo clip, all 200 --
        clip_id = (facts[0].get("clip_id") if facts else "")
        clip_path = (f"/api/clip?session_id={demo_sid}&clip_id={clip_id}"
                     if clip_id else "")
        ok = True
        if clip_path:
            for _ in range(30):
                s, _ = raw(BASE_DEMO, "GET", clip_path)
                ok = ok and s == 200
        check("demo-clip-unlimited", bool(clip_path) and ok,
              f"clip={clip_id}")

        # -- index.html carries the demo banner + invite display + 429 text --
        html = (ROOT / "index.html").read_text()
        check("ui-demo-wiring", all(x in html for x in
              ('id="demo"', "demo-info", "demoname", "democode",
               "Shared demo")),
              "banner + invitecode hooks")
    finally:
        stop(srv)

    # -- per-IP limit + CF-Connecting-IP (non-demo server, tiny caps) --
    srv = start(PORT_IP, {"RATE_LIMIT_PER_IP_MAX": "3",
                          "RATE_LIMIT_PER_IP_WINDOW_S": "3600",
                          "RATE_LIMIT_GLOBAL_DAY_MAX": "1000"})
    try:
        ask = {"session_ids": ["rate-a"], "question": "What about the farm?"}
        codes = [raw(BASE_IP, "POST", "/api/ask", ask)[0] for _ in range(4)]
        check("rate-per-ip-429", codes == [200, 200, 200, 429],
              f"codes={codes}")
        s, t = raw(BASE_IP, "POST", "/api/ask", ask)
        check("rate-429-message", s == 429 and "try" in body(t).get("error", "").lower(),
              f"status={s} err={t[:80]}")
        # A different client behind the same tunnel (CF header) is unaffected.
        s, _ = raw(BASE_IP, "POST", "/api/ask", ask,
                   {"CF-Connecting-IP": "9.9.9.9"})
        check("rate-cf-header-identity", s == 200, f"status={s}")
        s, _ = raw(BASE_IP, "POST", "/api/ask", ask,
                   {"CF-Connecting-IP": "9.9.9.9"})
        check("rate-cf-header-counted", s == 200, f"status={s}")
        # Static pages ignore the limiter even for the exhausted IP.
        s, _ = raw(BASE_IP, "GET", "/")
        check("rate-static-unlimited", s == 200, f"status={s}")
        s, _ = raw(BASE_IP, "GET", "/how-it-works")
        check("rate-howto-unlimited", s == 200, f"status={s}")
    finally:
        stop(srv)

    # -- global daily cap spans client identities --
    srv = start(PORT_DAY, {"RATE_LIMIT_PER_IP_MAX": "1000",
                           "RATE_LIMIT_PER_IP_WINDOW_S": "3600",
                           "RATE_LIMIT_GLOBAL_DAY_MAX": "4"})
    try:
        ask = {"session_ids": ["rate-b"], "question": "What about the farm?"}
        codes = [raw(BASE_DAY, "POST", "/api/ask", ask,
                     {"CF-Connecting-IP": f"10.0.0.{i}"})[0]
                 for i in range(5)]
        check("rate-daily-cap-429", codes == [200, 200, 200, 200, 429],
              f"codes={codes}")
    finally:
        stop(srv)

    # -- share.sh contract (never executed here: no public tunnel) --
    sh = ROOT / "scripts" / "share.sh"
    text = sh.read_text() if sh.is_file() else ""
    check("share-script", sh.is_file()
          and bool(sh.stat().st_mode & stat.S_IXUSR)
          and "DEMO_MODE=1" in text and "MOCK_LLM=0" in text
          and "127.0.0.1" in text and "cloudflared tunnel --url" in text
          and "brew install cloudflared" in text,
          "executable, demo env, 127.0.0.1, tunnel, brew hint")

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("FAILURES:", failed)
        sys.exit(1)


if __name__ == "__main__":
    main()
