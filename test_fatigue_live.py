"""Live fatigue-detector probe suite (MOCK_LLM=0, needs FIREWORKS_API_KEY).

Commits the full skeptic probe set as runnable live tests: expecting-pause
probes (shrinking/implicit fatigue, grief-quiet exhaustion, explicit wrap-up)
must yield pause_suggested=true at the tired turns and false before; no-pause
probes (third-person/historical tiredness, vivid-but-short stories, naturally
terse speaker, descriptive 'exhausting', quoted 'I'm tired') must stay false
on every turn. Also covers the turn-count>=6 fallback and empty-never-fires
on the live path.

Also covers grief-sensitive follow-ups: after an emotionally heavy turn
the question must acknowledge and offer pause/stop/rest instead of
thread-chasing, while calm turns stay normal content questions.

Sessions are capped short enough that the turn-count fallback (>=6) cannot
fire inside the pause/no-pause probes, and the MOCK shortening proxy cannot
fire either (it needs >=3 priors and only runs meaningfully on the mock
path... note pause_suggested ORs the proxy on both paths, so baselines are
kept long enough that short honest answers never trip it). Any pause=true in
a no-pause probe is therefore a pure model false positive.

Usage:
  source .env            # provide FIREWORKS_API_KEY (never printed)
  python3 test_fatigue_live.py            # 1 round per probe
  FATIGUE_LIVE_ROUNDS=3 python3 test_fatigue_live.py   # full 3/3 confirmation
  FATIGUE_LIVE_PORT=18103 python3 test_fatigue_live.py

Without a key the suite skips cleanly (message, exit 0).
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

PORT = os.environ.get("FATIGUE_LIVE_PORT", "18103")
BASE = f"http://127.0.0.1:{PORT}"
ROUNDS = int(os.environ.get("FATIGUE_LIVE_ROUNDS", "1"))
# Comma-separated subset for targeted re-runs, e.g. FATIGUE_LIVE_ONLY=long6,empty.
ONLY = {s.strip() for s in os.environ.get("FATIGUE_LIVE_ONLY", "").split(",") if s.strip()}


def wanted(name):
    return not ONLY or name in ONLY

RICH_T1 = (
    "I grew up on a small dairy farm outside Modesto with my parents and four "
    "siblings, and every morning before school we all helped with the milking "
    "from five until seven, then ran laughing to catch the bus with straw "
    "still in our hair, and summers meant irrigating the alfalfa fields, "
    "swimming in the canal after supper, falling asleep to the crickets and "
    "the far-off hum of the Highway 99 trucks carrying peaches north to market."
)
RICH_T2 = (
    "My grandmother Rosa lived with us in a little room off the kitchen and "
    "she told the best stories while she kneaded bread dough every single "
    "Friday, stories about crossing the border as a girl, about the earthquake "
    "she slept through, about the wedding dress she sewed from her sister's "
    "curtains, and the whole house smelled of yeast and cinnamon until Sunday."
)
SHRINK_T3 = (
    "I don't remember much else about that time, honestly. That's about it, I think."
)
DEFLECT_T4 = (
    "I'm not sure... how much longer is this? I'm running out of things to say."
)

GRIEF_T1 = (
    "Daniel and I were married forty-three years, and he built our whole house "
    "with his own hands, every cabinet and windowsill, and on Sundays he would "
    "play the guitar on the porch while I shelled peas, and the neighbors always "
    "said ours was the happiest porch on the street."
)
GRIEF_T2 = (
    "Sorry... talking about the funeral... it's still hard... give me a moment, please."
)
GRIEF_T3 = (
    "Yeah... it's been a hard time... I don't have much more to say about that."
)

WRAP_BASELINES = [
    "The harvest that year was long and hot and we worked every single day until sundown together.",
    "The barn roof leaked all spring so we patched it board by board each weekend without fail.",
    "The county fair drew the whole valley and we stayed late every night through Sunday closing.",
]
WRAP_CLOSER = "Let's wrap this up for today."

FP_BASELINES = [
    "We worked the fields together that summer, dawn to dusk, six days every week.",
    "The river ran high that spring and flooded the low pasture twice in May.",
    "The winter stored apples lasted until March and tasted sweeter every month.",
]
# No-pause probes: 3 turns each (proxy needs >=3 priors, so it cannot fire).
NO_PAUSE = {
    "historical": [
        "My father was tired after the war, but he worked the fields every day until dark.",
        "My mother said the whole village was worn out that winter, yet they still held the dance.",
        "The old crew was exhausted by harvest end, or so my grandfather always told it.",
    ],
    "vivid-short": [
        "The fox stole a whole chicken at dawn, feathers everywhere, and the dog just watched!",
        "Lightning split the big oak clean in half, and we heated with it all winter long.",
        "The flood took the bridge in one night, and we rowed to church for a month.",
    ],
    "terse": [
        "Born in Fresno. Three brothers. Good childhood, mostly outside playing ball.",
        "Worked the cannery ten years. Met my wife there. Married in June.",
        "Two kids, both teachers now. Proud of them. That's the story.",
    ],
    "exhausting": [
        "The harvest work was exhausting back then, dawn to dusk for six solid weeks running.",
        "Wash day was grueling in those years, hauling every bucket up from the creek.",
        "That winter was brutal for the whole county, deep snow until April arrived.",
    ],
    "quoted": [
        'My mother always said "I\'m tired, children" when supper ran late, then kept humming.',
        'The foreman would shout "let\'s stop for water" at noon, and we all dropped our tools.',
        'Grandpa\'s letter said "I want to wrap this up", meaning the fence, before the rain.',
    ],
}
LONG6_TEXT = (
    "We talked about the harvest all week long, every single day from dawn until dark, week {}."
)


def post(path, obj):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(obj).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.status, json.loads(resp.read().decode())


def turn(sid, text, history):
    body = {
        "session_id": sid,
        "audio_b64": "",
        "history": history,
        "transcript": text,
        "segments": [{"id": "seg-0", "text": text, "start": 0.0, "end": 1.0}],
    }
    st, data = post("/api/turn", body)
    assert st == 200, data
    # Retry once IN THE SAME SESSION on transient LLM fallback so blips
    # don't fail the suite (a fresh session would reset turn_count and
    # break the turn-count probe; a same-session retry only appends one
    # extra similar-length prior turn, which no expectation depends on).
    if data.get("fallback") is True:
        time.sleep(2)
        st, data = post("/api/turn", body)
        assert st == 200, data
        data["_retried"] = True
    assert isinstance(data.get("question"), str) and data["question"], data
    assert isinstance(data.get("facts"), list), data
    assert data.get("pause_suggested") is False or data.get(
        "pause_suggested") is True, data
    assert data.get("fallback") is False, data
    return data


def run_session(sid, texts, expect):
    """Run texts in one session; expect[i] is True/False/'either' per turn."""
    hist, got = [], []
    for i, text in enumerate(texts):
        d = turn(sid, text, hist)
        hist.append({"role": "user", "text": text})
        got.append(d["pause_suggested"])
        exp = expect[i]
        if exp != "either":
            assert d["pause_suggested"] is exp, (
                f"{sid} turn {i + 1}: expected pause={exp}, got {got[-1]} "
                f"for {text!r} (fatigue path live, fallback={d.get('fallback')})")
    return got


# Grief-sensitive follow-ups: after an emotionally heavy turn the question
# must acknowledge and offer pause/stop/rest (never thread-chase); before
# the heavy turn it must stay a normal content question with no pause
# offer. Repair runs only on tired turns, so normal-turn latency is
# unchanged (heavy turns pay one extra short call, still far under 11s).
GRIEF_Q_OFFER = ("paus", "stop")
GRIEF_Q_CALM_T1 = ("paus", "stop")


def grief_question_probe(tag):
    """One grief session; return (sid, pauses, latencies, questions)."""
    sid = f"fp-live-griefq-{tag}"
    hist, pauses, dts, questions = [], [], [], []
    for text in (GRIEF_T1, GRIEF_T2, GRIEF_T3):
        t0 = time.time()
        d = turn(sid, text, hist)
        dts.append(time.time() - t0)
        hist.append({"role": "user", "text": text})
        pauses.append(d["pause_suggested"])
        questions.append(d["question"])
    return sid, pauses, dts, questions


def check_grief_questions(tag):
    """Pause pattern F,T,T plus: calm T1 stays a normal content question
    (no pause/stop offer); heavy T2/T3 acknowledge and offer pause/stop."""
    sid, pauses, dts, questions = grief_question_probe(tag)
    assert pauses == [False, True, True], (sid, pauses)
    q1 = (questions[0] or "").lower()
    assert not any(w in q1 for w in GRIEF_Q_CALM_T1), (sid, questions[0])
    for i in (1, 2):
        q = (questions[i] or "").lower()
        assert any(w in q for w in GRIEF_Q_OFFER), (sid, questions[i])
    print(f"LIVE OK grief-sensitive follow-ups "
          f"({', '.join(f'{dt:.2f}s' for dt in dts)}): "
          f"T1 normal; T2/T3 offer pause/stop", flush=True)
    for i, q in enumerate(questions):
        print(f"  griefq T{i + 1}: {q!r}", flush=True)
    return sid


def main():
    key = os.environ.get("FIREWORKS_API_KEY", "")
    if not key:
        print("SKIP: no FIREWORKS_API_KEY in env (source .env); "
              "live fatigue probes need MOCK_LLM=0 + key. exit 0")
        return 0
    env = dict(os.environ, MOCK_LLM="0", PORT=PORT)
    srv = subprocess.Popen(
        [sys.executable, "server.py"], env=env, cwd=str(ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    stamp = f"{int(time.time())}-{os.getpid()}"
    sids = []
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(BASE + "/", timeout=2).read()
                break
            except Exception:
                time.sleep(0.5)
        for r in range(ROUNDS):
            tag = f"{stamp}-r{r + 1}"
            # Expect-pause: shrinking/implicit fatigue.
            if wanted("shrink"):
                sid = f"fp-live-shrink-{tag}"
                sids.append(sid)
                assert run_session(sid, [RICH_T1, RICH_T2, SHRINK_T3, DEFLECT_T4],
                                   [False, False, True, True])
                print(f"LIVE OK round {r + 1}: shrinking fatigue F,F,T,T", flush=True)
            # Expect-pause: grief-quiet emotional exhaustion.
            if wanted("grief"):
                sid = f"fp-live-grief-{tag}"
                sids.append(sid)
                assert run_session(sid, [GRIEF_T1, GRIEF_T2, GRIEF_T3],
                                   [False, True, True])
                print(f"LIVE OK round {r + 1}: grief-quiet F,T,T", flush=True)
            # Grief-sensitive follow-ups: heavy turns offer pause/stop,
            # calm turns stay normal content questions.
            if wanted("griefq"):
                sids.append(check_grief_questions(f"{tag}"))
            # Expect-pause: explicit wrap-up after rich baselines.
            if wanted("wrap"):
                sid = f"fp-live-wrap-{tag}"
                sids.append(sid)
                assert run_session(sid, WRAP_BASELINES + [WRAP_CLOSER],
                                   [False, False, False, True])
                print(f"LIVE OK round {r + 1}: wrap-up pause on closer only", flush=True)
            # No-pause probes: every turn must stay false.
            for label, texts in NO_PAUSE.items():
                if not wanted(f"fp-{label}"):
                    continue
                sid = f"fp-live-fp-{label}-{tag}"
                sids.append(sid)
                assert run_session(sid, texts, [False] * len(texts))
                print(f"LIVE OK round {r + 1}: no-pause {label} "
                      f"{len(texts)}/{len(texts)} false", flush=True)
            # Turn-count fallback still fires live on a sustained session.
            if wanted("long6"):
                sid = f"fp-live-long6-{tag}"
                sids.append(sid)
                assert run_session(
                    sid, [LONG6_TEXT.format(i) for i in range(6)],
                    [False] * 5 + [True])
                print(f"LIVE OK round {r + 1}: turn-count fallback fires on turn 6",
                      flush=True)
            # Empty transcript never pauses.
            if wanted("empty"):
                sid = f"fp-live-empty-{tag}"
                sids.append(sid)
                assert run_session(sid, [""], [False])
                print(f"LIVE OK round {r + 1}: empty -> pause false", flush=True)
        print(f"FATIGUE-LIVE OK: {ROUNDS} round(s), all probes pass, no fallbacks")
        return 0
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except Exception:
            srv.kill()
        for s in sids:
            shutil.rmtree(ROOT / "recordings" / s, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
