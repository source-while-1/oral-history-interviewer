"""Minimal oral-history-interviewer backend (stdlib only).

POST /api/turn  {session_id, audio_b64, history, transcript, segments}
  -> {question, audio_text, facts}
GET  /          serves index.html (single static frontend, no build step)
GET  /api/facts?session_id=...  returns saved facts for a session

Storage: recordings/<session>/<clip>.wav + transcript.jsonl (gitignored).
LLM: Fireworks via OpenAI-compatible chat-completions endpoint. Two
concurrent calls per turn: (1) warm single-question follow-up (short
max_tokens), (2) JSON-mode fact extraction
{kind: person|place|event|relationship, text, when, segment_ids}.
segment_ids are mapped server-side to (clip_id, start, end) so every
persisted fact cites a clip slice. MOCK_LLM=1 (default) forces stub.

STT default: browser Web Speech API (offline demo, no key). The turn
endpoint already accepts transcript segments, so a future server-side
Fireworks Whisper step can fill `segments` without changing the schema;
see README "STT upgrade path".
"""

import base64
import concurrent.futures
import json
import math
import os
import re
import time
import wave
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
RECORDINGS = ROOT / "recordings"
FIREWORKS_BASE_URL = os.environ.get(
    "FIREWORKS_BASE_URL", "https://api.fireworks.ai/inference/v1"
).rstrip("/")
FIREWORKS_URL = FIREWORKS_BASE_URL + "/chat/completions"
FIREWORKS_MODEL = os.environ.get(
    "FIREWORKS_MODEL", "accounts/fireworks/models/llama-v3p1-8b-instruct"
)
# Reserved for the documented server-side STT upgrade path (not called in v1).
FIREWORKS_STT_MODEL = os.environ.get("FIREWORKS_STT_MODEL", "whisper-v3-turbo")

FACT_KINDS = ("person", "place", "event", "relationship")
# Generous budgets: reasoning-style models (e.g. muse-spark-open) spend tokens
# on reasoning traces before the answer; small budgets truncate to "".
FOLLOWUP_MAX_TOKENS = int(os.environ.get("FIREWORKS_FOLLOWUP_MAX_TOKENS", "1024"))
FACTS_MAX_TOKENS = int(os.environ.get("FIREWORKS_FACTS_MAX_TOKENS", "2048"))


def utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


def normalize_segments(raw):
    """Normalize caller-supplied transcript segments to [{id,text,start,end}]."""
    segs = []
    if not isinstance(raw, list):
        return segs
    for i, s in enumerate(raw):
        if not isinstance(s, dict):
            continue
        sid = str(s.get("id") or f"seg-{i}")
        try:
            start = float(s.get("start", 0))
            end = float(s.get("end", 0))
        except (TypeError, ValueError):
            start, end = 0.0, 0.0
        if not math.isfinite(start):
            start = 0.0
        if not math.isfinite(end):
            end = 0.0
        segs.append(
            {"id": sid, "text": str(s.get("text", "")), "start": start, "end": end}
        )
    return segs


def resolve_fact_links(raw_facts, clip_id, seg_by_id):
    """Map segment_ids -> (clip_id, start, end). Every fact cites a clip slice.

    Models sometimes return shortened ids ("0" for "seg-0"), so each known
    segment also registers aliases: its bare index and any numeric suffix.
    Exact ids always win over aliases.
    """
    aliases = {}
    # Numeric-suffix aliases first (exact ids still win at resolve time),
    # then positional-index aliases only where nothing is registered yet.
    for sid in seg_by_id:
        suffix = sid.rsplit("-", 1)[-1].rsplit("_", 1)[-1]
        if suffix != sid and suffix not in seg_by_id:
            aliases.setdefault(suffix, sid)
    for i, sid in enumerate(seg_by_id):
        aliases.setdefault(str(i), sid)
    facts = []
    for f in raw_facts or []:
        if not isinstance(f, dict):
            continue
        kind = str(f.get("kind", ""))
        if kind not in FACT_KINDS:
            continue
        text = str(f.get("text", "")).strip()
        if not text:
            continue
        seg_ids = f.get("segment_ids") or []
        if isinstance(seg_ids, str):
            seg_ids = [seg_ids]
        resolved = []
        for s in seg_ids:
            s = str(s)
            if s in seg_by_id:
                resolved.append(s)
            elif s in aliases:
                resolved.append(aliases[s])
        seg_ids = resolved
        if seg_ids:
            seg = seg_by_id[seg_ids[0]]
            start, end = seg["start"], seg["end"]
            seg_id = seg_ids[0]
        else:
            start, end, seg_id = 0.0, 0.0, ""
        fact = {
            "kind": kind,
            "text": text,
            "when": str(f.get("when", "")),
            "clip_id": clip_id,
            "start": start,
            "end": end,
            "segment_id": seg_id,
        }
        people = f.get("people")
        if isinstance(people, list) and people:
            fact["people"] = [str(p) for p in people if str(p).strip()]
        facts.append(fact)
    return facts


def mock_llm_turn(history, transcript_text, segments):
    """Deterministic stub: next question + linked demo facts for non-empty turns.

    STUB-ONLY heuristic: besides the whole-turn event fact, emit one person
    fact per "Title Name" mention (e.g. "Aunt Rosa") so the offline demo and
    synthetic replay show the family map filling in. The real Fireworks path
    extracts people via JSON mode instead; this regex never runs there.
    """
    n = len(history) if isinstance(history, list) else 0
    questions = [
        "Where did you grow up, and what do you remember most about it?",
        "Can you tell me about a person who shaped your childhood?",
        "What is a moment you are proud of that we should record?",
    ]
    question = questions[n % len(questions)]
    seg_by_id = {s["id"]: s for s in segments}
    raw = []
    t = (transcript_text or "").strip()
    if t and t != "(begin interview)":
        if segments:
            raw = [
                {
                    "kind": "event",
                    "text": t[:160],
                    "when": "",
                    "segment_ids": [segments[0]["id"]],
                }
            ]
        seen = set()
        for s in segments:
            for m in re.finditer(
                r"\b(Aunt|Uncle|Grandma|Grandpa|Mother|Father|Granny|Cousin)"
                r"\s+([A-Z][a-z]+)",
                s.get("text", ""),
            ):
                name = f"{m.group(1)} {m.group(2)}"
                if name not in seen:
                    seen.add(name)
                    raw.append(
                        {
                            "kind": "person",
                            "text": name,
                            "when": "",
                            "people": [name],
                            "segment_ids": [s["id"]],
                        }
                    )
    return question, resolve_fact_links(raw, "mock-clip", seg_by_id)


def _post_chat(messages, response_format=None, max_tokens=128, temperature=0.5):
    """POST to the Fireworks OpenAI-compatible chat endpoint. Key from env only."""
    api_key = os.environ.get("FIREWORKS_API_KEY", "")
    if not api_key:
        raise RuntimeError("FIREWORKS_API_KEY not set")
    payload = {"model": FIREWORKS_MODEL, "messages": messages}
    if response_format is not None:
        payload["response_format"] = response_format
    payload["max_tokens"] = max_tokens
    payload["temperature"] = temperature
    req = urllib.request.Request(
        FIREWORKS_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode())
    return body["choices"][0]["message"]["content"]


def gen_followup(history, transcript_text):
    """Call 1: one warm open-ended follow-up question (short max_tokens)."""
    history_tail = json.dumps(history)[-4000:]
    messages = [
        {
            "role": "system",
            "content": (
                "You are a gentle oral-history interviewer. Ask ONE short "
                "warm open-ended follow-up question (under 25 words). "
                "Reply with the question text only, no JSON, no quotes."
            ),
        },
        {
            "role": "user",
            "content": f"History: {history_tail}\nLatest turn: {transcript_text[-1500:]}",
        },
    ]
    return _post_chat(messages, max_tokens=FOLLOWUP_MAX_TOKENS, temperature=0.6).strip()


def extract_facts_raw(transcript_text, valid_ids):
    """Call 2: JSON-mode fact extraction with segment_ids citing transcript segments."""
    messages = [
        {
            "role": "system",
            "content": (
                "Extract facts from one interview turn. Reply ONLY as JSON: "
                '{"facts": [{"kind": "person|place|event|relationship", '
                '"text": str, "when": str, "segment_ids": [str]}]}. '
                f"kind must be one of person/place/event/relationship. "
                f"segment_ids must cite these ids (or [] if none apply): {valid_ids}."
            ),
        },
        {"role": "user", "content": transcript_text[-4000:] or "(no transcript)"},
    ]
    content = _post_chat(
        messages,
        response_format={"type": "json_object"},
        max_tokens=FACTS_MAX_TOKENS,
        temperature=0.0,
    )
    try:
        parsed = json.loads(content)
    except ValueError:
        return []
    facts = parsed.get("facts", parsed if isinstance(parsed, list) else [])
    return facts if isinstance(facts, list) else []


def run_llm_turn(history, transcript_text, segments):
    """Run follow-up + fact extraction concurrently; return (question, raw_facts)."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        q_future = pool.submit(gen_followup, history, transcript_text)
        f_future = pool.submit(
            extract_facts_raw, transcript_text, [s["id"] for s in segments]
        )
        return q_future.result(), f_future.result()


def write_silent_wav(path, seconds=1.0, framerate=8000):
    """Write a valid silent wav so empty-audio turns stay playable."""
    nframes = max(1, int(seconds * framerate))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(framerate)
        w.writeframes(b"\x00" * nframes * 2)


def clip_duration(path):
    """Return wav duration in seconds, or None when unknown."""
    try:
        with wave.open(str(path), "rb") as w:
            rate = w.getframerate() or 0
            if rate <= 0:
                return None
            return w.getnframes() / float(rate)
    except Exception:
        return None


def clamp_fact_range(start, end, duration):
    """Clamp a fact slice into 0<=start<end<=duration; ordered fallback."""
    try:
        s = float(start)
    except (TypeError, ValueError):
        s = 0.0
    try:
        e = float(end)
    except (TypeError, ValueError):
        e = 0.0
    if not math.isfinite(s):
        s = 0.0
    if not math.isfinite(e):
        e = 0.0
    if duration is None or not math.isfinite(duration) or duration <= 0:
        if not e > s:
            e = s + 1.0
        return s, e
    dur = float(duration)
    s = min(max(s, 0.0), dur)
    e = min(max(e, 0.0), dur)
    if not e > s:
        if s < dur:
            e = min(dur, s + 1.0)
            if not e > s:
                e = dur
                s = max(0.0, dur - 1.0)
        else:
            e = dur
            s = max(0.0, dur - 1.0)
    return s, e


def sniff_audio_ctype(data):
    """Sniff Content-Type from magic bytes; default audio/wav."""
    if data[:4] == b"RIFF":
        return "audio/wav"
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "audio/webm"
    if data[:4] == b"OggS":
        return "audio/ogg"
    return "audio/wav"


class Handler(BaseHTTPRequestHandler):
    server_version = "OHI/0.2"

    def log_message(self, *args):
        pass

    def _send_json(self, obj, status=200):
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_file(self, path, ctype):
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._serve_file(ROOT / "index.html", "text/html; charset=utf-8")
        elif parsed.path == "/how-it-works":
            self._serve_file(ROOT / "demo" / "how-it-works.html",
                             "text/html; charset=utf-8")
        elif parsed.path == "/api/facts":
            qs = parse_qs(parsed.query)
            session_id = "".join(
                c for c in (qs.get("session_id") or [""])[0]
                if c.isalnum() or c in "-_"
            )
            facts_path = (RECORDINGS / session_id / "facts.json") if session_id else None
            if (
                not facts_path
                or RECORDINGS not in facts_path.resolve().parents
                or not facts_path.is_file()
            ):
                self._send_json({"facts": []})
            else:
                try:
                    self._send_json({"facts": json.loads(facts_path.read_text())})
                except (ValueError, OSError):
                    self._send_json({"facts": []})
        elif parsed.path == "/api/clip":
            qs = parse_qs(parsed.query)
            session_id = "".join(
                c for c in (qs.get("session_id") or [""])[0]
                if c.isalnum() or c in "-_"
            )
            clip_id = "".join(
                c for c in (qs.get("clip_id") or [""])[0]
                if c.isalnum() or c in "-_"
            )
            clip_path = (RECORDINGS / session_id / (clip_id + ".wav")) if (
                session_id and clip_id
            ) else None
            # Confine to the session dir: no traversal, must be a real file.
            if (
                not clip_path
                or RECORDINGS not in clip_path.resolve().parents
                or not clip_path.is_file()
            ):
                self.send_response(404)
                self.end_headers()
            else:
                try:
                    data = clip_path.read_bytes()
                except OSError:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", sniff_audio_ctype(data))
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/turn":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length or 0).decode() or "{}")
        except (ValueError, UnicodeDecodeError):
            self._send_json({"error": "invalid JSON body"}, 400)
            return

        session_id = str(payload.get("session_id") or "default").strip() or "default"
        # Keep session dir safe: alnum + dash/underscore only.
        session_id = "".join(c for c in session_id if c.isalnum() or c in "-_") or "default"
        history = payload.get("history") or []
        audio_b64 = payload.get("audio_b64") or ""
        # STT input: browser transcript by default; server-side Whisper can
        # later fill `segments` without changing this schema.
        transcript_text = str(
            payload.get("transcript") or payload.get("audio_text") or ""
        )
        if not transcript_text and history and isinstance(history[-1], dict):
            last = history[-1]
            if last.get("role") == "user":
                transcript_text = str(last.get("text", ""))
        segments = normalize_segments(payload.get("segments"))
        if transcript_text and not segments:
            segments = [
                {"id": "seg-0", "text": transcript_text, "start": 0.0, "end": 0.0}
            ]
        seg_by_id = {s["id"]: s for s in segments}

        session_dir = RECORDINGS / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        clip_id = f"clip-{int(time.time() * 1000)}"
        clip_path = session_dir / f"{clip_id}.wav"
        if audio_b64:
            try:
                clip_path.write_bytes(base64.b64decode(audio_b64))
            except (ValueError, base64.binascii.Error):
                self._send_json({"error": "audio_b64 is not valid base64"}, 400)
                return
        else:
            write_silent_wav(clip_path)

        use_mock = os.environ.get("MOCK_LLM", "1") != "0"
        fallback_note = ""
        fallback = False
        try:
            if use_mock:
                question, facts = mock_llm_turn(history, transcript_text, segments)
                facts = resolve_fact_links(
                    [
                        {
                            "kind": f["kind"],
                            "text": f["text"],
                            "when": f["when"],
                            "people": f.get("people", []),
                            "segment_ids": [f.get("segment_id")] if f.get("segment_id") else [],
                        }
                        for f in facts
                    ],
                    clip_id,
                    seg_by_id,
                )
            else:
                question, raw_facts = run_llm_turn(history, transcript_text, segments)
                facts = resolve_fact_links(raw_facts, clip_id, seg_by_id)
        except Exception as e:  # fall back to stub so the loop stays runnable
            question, facts = mock_llm_turn(history, transcript_text, segments)
            facts = resolve_fact_links(
                [
                    {
                        "kind": f["kind"],
                        "text": f["text"],
                        "when": f["when"],
                        "people": f.get("people", []),
                        "segment_ids": [f.get("segment_id")] if f.get("segment_id") else [],
                    }
                    for f in facts
                ],
                clip_id,
                seg_by_id,
            )
            fallback_note = f"(llm fallback: {e})"
            fallback = True

        duration = clip_duration(clip_path)
        clamped = []
        for f in facts:
            s, e = clamp_fact_range(f.get("start", 0.0), f.get("end", 0.0), duration)
            f["start"], f["end"] = s, e
            clamped.append(f)
        facts = clamped

        result = {
            "question": question or mock_llm_turn(history, transcript_text, segments)[0],
            "audio_text": (fallback_note + " " + transcript_text).strip(),
            "facts": facts,
            "fallback": fallback,
        }

        # Append turn + persist facts.
        with open(session_dir / "transcript.jsonl", "a") as fh:
            fh.write(json.dumps({
                "ts": utcnow_iso(), "clip_id": clip_id,
                "history_len": len(history), "question": result["question"],
                "transcript": transcript_text, "segments": segments,
            }) + "\n")
        facts_path = session_dir / "facts.json"
        try:
            existing = json.loads(facts_path.read_text()) if facts_path.exists() else []
            if not isinstance(existing, list):
                existing = []
        except (ValueError, OSError):
            existing = []
        facts_path.write_text(json.dumps(existing + facts, indent=2))

        self._send_json(result)


def main():
    port = int(os.environ.get("PORT", "8000"))
    srv = HTTPServer(("127.0.0.1", port), Handler)
    print(f"oral-history-interviewer on http://127.0.0.1:{port} (MOCK_LLM={os.environ.get('MOCK_LLM', '1')})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
