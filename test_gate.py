"""Password gate for the shared demo (MOCK_LLM=1, works offline).

When DEMO_PASSWORD is set, EVERY route needs a valid session cookie from
POST /login (pages -> password page, /api/* -> 401 JSON). When unset, local
dev is unchanged (no gate). Uses only a throwaway test password via env.

Usage: python3 test_gate.py
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

GATE_PW_ENV = "test-gate-password"  # throwaway value, test-only
PORT_GATED = "18311"
PORT_OPEN = "18312"
PORT_LOGIN = "18313"
BASE_GATED = f"http://127.0.0.1:{PORT_GATED}"
BASE_OPEN = f"http://127.0.0.1:{PORT_OPEN}"
BASE_LOGIN = f"http://127.0.0.1:{PORT_LOGIN}"


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
            return (resp.status, resp.read().decode("utf-8", "replace"),
                    resp.headers.get("Set-Cookie", ""))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), e.headers.get("Set-Cookie", "")


def start(port, extra_env):
    env = dict(os.environ, MOCK_LLM="1", PORT=port, **extra_env)
    env.pop("DEMO_PASSWORD", None)
    env.update(extra_env)
    srv = subprocess.Popen(
        [sys.executable, "server.py"], env=env, cwd=str(ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            urllib.request.urlopen(base + "/api/demo-info", timeout=2).read()
            break
        except urllib.error.HTTPError:
            break  # server is up (gated answers are still answers)
        except Exception:
            time.sleep(0.2)
    return srv


def stop(srv):
    srv.terminate()
    try:
        srv.wait(timeout=5)
    except Exception:
        srv.kill()


def cookie_header(value):
    return {"Cookie": f"demo_auth={value}"}


def main():
    results = []

    def check(name, cond, detail=""):
        results.append((name, bool(cond), detail))
        print(f"{'PASS' if cond else 'FAIL'} {name}"
              + (f" — {detail}" if detail else ""))

    # -- gate off (local dev unchanged): everything open, no login route --
    srv = start(PORT_OPEN, {"DEMO_MODE": "0"})
    try:
        s, t, _ = raw(BASE_OPEN, "GET", "/", None)
        check("open-page-200", s == 200, f"status={s}")
        s, t, _ = raw(BASE_OPEN, "GET", "/api/facts?session_id=x", None)
        check("open-api-200", s == 200, f"status={s}")
        s, t, _ = raw(BASE_OPEN, "POST", "/login",
                      {"password": "anything"})
        check("open-no-login-route", s == 404, f"status={s}")
    finally:
        stop(srv)

    # -- gate on: pages -> password page, api (incl. clip) -> 401 --
    srv = start(PORT_GATED, {"DEMO_MODE": "1",
                             "DEMO_PASSWORD": GATE_PW_ENV})
    try:
        s, t, _ = raw(BASE_GATED, "GET", "/", None)
        check("gate-page-401-html", s == 401 and "password" in t.lower(),
              f"status={s}")
        s, t, _ = raw(BASE_GATED, "GET", "/how-it-works", None)
        check("gate-howto-401-html", s == 401 and "password" in t.lower(),
              f"status={s}")
        for path, name in (
                ("/api/facts?session_id=demo-synthetic", "facts"),
                ("/api/threads?session_id=demo-synthetic", "threads"),
                ("/api/demo-info", "demo-info"),
                ("/api/clip?session_id=demo-synthetic&clip_id=nope",
                 "clip-blocked")):
            s, t, _ = raw(BASE_GATED, "GET", path, None)
            check(f"gate-401-{name}", s == 401, f"status={s}")
        s, t, _ = raw(BASE_GATED, "POST", "/api/ask",
                      {"session_ids": ["demo-synthetic"],
                       "question": "What about the farm?"})
        check("gate-401-ask", s == 401, f"status={s}")

        # -- wrong password rejected, no cookie, nothing leaked --
        s, t, setc = raw(BASE_GATED, "POST", "/login",
                         {"password": "wrong-password"})
        check("gate-wrong-401", s == 401 and not setc, f"status={s}")
        check("gate-wrong-no-leak", "wrong-password" not in t,
              f"body={t[:60]}")

        # -- right password sets cookie (HttpOnly, SameSite, Path, no
        #    Secure on plain-HTTP localhost) and grants access --
        s, t, setc = raw(BASE_GATED, "POST", "/login",
                         {"password": GATE_PW_ENV})
        cookie = setc.split(";", 1)[0].split("=", 1)[1] if "=" in setc else ""
        check("gate-login-200", s == 200 and bool(cookie), f"status={s}")
        check("gate-cookie-flags",
              all(k in setc for k in
                  ("HttpOnly", "SameSite=Lax", "Path=/", "Max-Age="))
              and "Secure" not in setc,
              f"flags={setc[:120]}")
        heads = cookie_header(cookie)
        s, t, _ = raw(BASE_GATED, "GET", "/", None, heads)
        check("gate-cookie-page-200", s == 200, f"status={s}")
        s, t, _ = raw(BASE_GATED, "GET",
                      "/api/facts?session_id=demo-synthetic", None, heads)
        try:
            facts = json.loads(t).get("facts") or []
        except ValueError:
            facts = []
        check("gate-cookie-facts-200", s == 200 and len(facts) > 0,
              f"status={s} facts={len(facts)}")
        clip_id = (facts[0].get("clip_id") or "") if facts else ""
        if clip_id:
            s, _, _ = raw(
                BASE_GATED, "GET",
                f"/api/clip?session_id=demo-synthetic&clip_id={clip_id}",
                None, heads)
            check("gate-cookie-clip-200", s == 200, f"status={s}")

        # -- forged / tampered / expired / garbage cookies rejected --
        forged = [(cookie[:-1] + ("0" if cookie[-1:] != "0" else "1"),
                   "tampered"),
                  ("9999999999." + "0" * 64, "forged"),
                  ("1." + "0" * 64, "expired"),
                  ("not-a-cookie", "garbage")]
        for bad, name in forged:
            s, _, _ = raw(BASE_GATED, "GET", "/api/facts?session_id=x",
                          None, cookie_header(bad))
            check(f"gate-reject-{name}", s == 401, f"status={s}")

        # -- logout clears the cookie --
        s, _, setc = raw(BASE_GATED, "POST", "/logout", {}, heads)
        check("gate-logout", s == 200 and "Max-Age=0" in setc,
              f"status={s}")
    finally:
        stop(srv)

    # -- login rate limit (fresh server): wrong attempts -> 429, and the
    #    CF-Connecting-IP identity is honored as a separate client --
    srv = start(PORT_LOGIN, {"DEMO_MODE": "1",
                             "DEMO_PASSWORD": GATE_PW_ENV})
    try:
        codes = [raw(BASE_LOGIN, "POST", "/login",
                     {"password": "wrong-password"})[0] for _ in range(11)]
        check("gate-login-rate-429",
              codes[:10] == [401] * 10 and codes[10] == 429,
              f"codes={codes}")
        s, _, _ = raw(BASE_LOGIN, "POST", "/login",
                      {"password": "wrong-password"},
                      {"CF-Connecting-IP": "9.9.9.9"})
        check("gate-login-rate-cf-identity", s == 401, f"status={s}")
    finally:
        stop(srv)

    # -- share.sh refuses without a password, before doing anything else --
    # NEVER let this test open a real tunnel: point SHARE_ENV_FILE at an
    # empty file (so the checkout's real .env password can't leak in) and
    # put a fake cloudflared first on PATH that only records it was called.
    sh = ROOT / "scripts" / "share.sh"
    import tempfile
    tmpd = tempfile.mkdtemp(prefix="gate-share-")
    empty_env = os.path.join(tmpd, "empty.env")
    open(empty_env, "w").close()
    marker = os.path.join(tmpd, "cloudflared-called")
    stubdir = os.path.join(tmpd, "bin")
    os.makedirs(stubdir, exist_ok=True)
    with open(os.path.join(stubdir, "cloudflared"), "w") as f:
        f.write("#!/bin/bash\necho CALLED >> '%s'\nexit 0\n" % marker)
    os.chmod(os.path.join(stubdir, "cloudflared"), 0o755)
    env = {k: v for k, v in os.environ.items() if k != "DEMO_PASSWORD"}
    env["SHARE_ENV_FILE"] = empty_env
    env["PATH"] = stubdir + os.pathsep + env.get("PATH", "/usr/bin:/bin")
    try:
        r = subprocess.run(["bash", str(sh), "18911"], env=env, cwd=str(ROOT),
                           capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        r = None
    check("share-refuses-no-password",
          r is not None and r.returncode != 0
          and "DEMO_PASSWORD" in (r.stderr or "")
          and not os.path.exists(marker),
          f"rc={None if r is None else r.returncode}"
          f" marker={os.path.exists(marker)}")

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("FAILURES:", failed)
        sys.exit(1)


if __name__ == "__main__":
    main()
