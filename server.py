"""Minimal oral-history-interviewer backend (stdlib only).

POST /api/turn  {session_id, audio_b64, history, transcript, segments,
               resume_from?}
  -> {question, audio_text, facts, threads, threads_opened, threads_covered,
      pause_suggested, fallback}
GET  /          serves index.html (single static frontend, no build step)
GET  /api/facts?session_id=...  returns saved facts for a session
GET  /api/threads?session_id=...  returns saved threads for a session

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

# Gentle-pause cues (case-insensitive substrings of the turn transcript).
# A suggestion only — the server never force-stops the interview.
TIRED_CUES = ("tired", "enough for today", "let's stop", "let\u2019s stop",
              "another time")
PAUSE_TURN_THRESHOLD = 6
MAX_THREADS_RETURNED = 20


def thread_id_for(text):
    """Deterministic thread id from the thread text (stable across turns)."""
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return "th-" + (slug[:48] or "untitled")


def load_threads(session_dir):
    """Load persisted threads list; corrupt/missing recovers to []."""
    path = Path(session_dir) / "threads.json"
    try:
        data = json.loads(path.read_text()) if path.exists() else []
    except (ValueError, OSError):
        return []
    if not isinstance(data, list):
        return []
    threads = []
    for t in data:
        if not isinstance(t, dict) or not str(t.get("text", "")).strip():
            continue
        tid = str(t.get("id") or thread_id_for(str(t.get("text", ""))))
        threads.append({
            "id": tid,
            "text": str(t.get("text", "")),
            "segment_id": str(t.get("segment_id", "")),
            "status": "covered" if t.get("status") == "covered" else "open",
        })
    return threads


def save_threads(session_dir, threads):
    Path(session_dir).mkdir(parents=True, exist_ok=True)
    Path(session_dir, "threads.json").write_text(json.dumps(threads or [], indent=2))


def pause_suggested(turn_count, transcript_text):
    """True when turn_count>=threshold or the transcript carries a tired cue."""
    t = (transcript_text or "").lower()
    if turn_count >= PAUSE_TURN_THRESHOLD:
        return True
    return any(cue in t for cue in TIRED_CUES)


def sanitize_id(raw, default="default"):
    cleaned = "".join(
        c for c in str(raw or default).strip() or default
        if c.isalnum() or c in "-_"
    )
    return cleaned or default
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


def mock_llm_turn(history, transcript_text, segments, open_threads=None):
    """Deterministic stub: next question + linked demo facts for non-empty turns.

    STUB-ONLY heuristic: besides the whole-turn event fact, emit one person
    fact per "Title Name" mention (e.g. "Aunt Rosa") so the offline demo and
    synthetic replay show the family map filling in. The real Fireworks path
    extracts people via JSON mode instead; this regex never runs there.
    Adaptivity: when open threads remain, ask about the oldest open thread
    first; otherwise fall back to the deterministic question cycle.
    """
    open_threads = [t for t in (open_threads or []) if t.get("status") == "open"]
    if open_threads:
        oldest = open_threads[0].get("text", "")
        question = f"Can you tell me more about {oldest}?"
    else:
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


def gen_followup(history, transcript_text, open_threads=None):
    """Call 1: one warm open-ended follow-up question (short max_tokens).

    Adaptive: when open loose-end threads remain, the prompt asks the model
    to prefer the most salient OPEN thread; with no open threads it asks a
    fresh question.
    """
    history_tail = json.dumps(history)[-4000:]
    open_threads = [t for t in (open_threads or []) if t.get("status") == "open"]
    thread_hint = ""
    if open_threads:
        names = ", ".join(t.get("text", "") for t in open_threads[:8])
        thread_hint = (
            f" Open loose ends worth revisiting: {names}. Prefer the most "
            "salient OPEN thread and ask a gentle follow-up about it; only "
            "ask a fresh question when none fits."
        )
    messages = [
        {
            "role": "system",
            "content": (
                "You are a gentle oral-history interviewer. Ask ONE short "
                "warm open-ended follow-up question (under 25 words). "
                "Reply with the question text only, no JSON, no quotes."
                + thread_hint
            ),
        },
        {
            "role": "user",
            "content": f"History: {history_tail}\nLatest turn: {transcript_text[-1500:]}",
        },
    ]
    return _post_chat(messages, max_tokens=FOLLOWUP_MAX_TOKENS, temperature=0.6).strip()


def extract_facts_raw(transcript_text, valid_ids, open_threads=None):
    """Call 2: JSON-mode fact+thread extraction with segment_ids citing segments.

    Returns (facts, threads_opened, threads_covered_ids). threads_opened items
    are {text, segment_id}; threads_covered_ids are thread-id or text strings.
    """
    open_hint = ""
    if open_threads:
        open_hint = (
            " Already-open threads: "
            + json.dumps([{"id": t.get("id"), "text": t.get("text")}
                          for t in open_threads if t.get("status") == "open"])
            + ". Mark a thread covered (by id) when this turn answers or "
              "re-mentions it; open a new thread {text, segment_id} only for a "
              "person/place that is genuinely new, never for an empty turn."
        )
    messages = [
        {
            "role": "system",
            "content": (
                "Extract facts and loose-end threads from one interview turn. "
                'Reply ONLY as JSON: {"facts": [{"kind": '
                '"person|place|event|relationship", "text": str, "when": str, '
                '"segment_ids": [str]}], '
                '"threads_opened": [{"text": str, "segment_id": str}], '
                '"threads_covered": [str]}. '
                f"kind must be one of person/place/event/relationship. "
                f"segment_ids must cite these ids (or [] if none apply): {valid_ids}."
                + open_hint
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
        return [], [], []
    if isinstance(parsed, list):
        return (parsed, [], [])
    facts = parsed.get("facts", [])
    if not isinstance(facts, list):
        facts = []
    opened = parsed.get("threads_opened", [])
    if not isinstance(opened, list):
        opened = []
    covered = parsed.get("threads_covered", [])
    if not isinstance(covered, list):
        covered = []
    return facts, opened, covered


def run_llm_turn(history, transcript_text, segments, open_threads=None):
    """Run follow-up + fact/thread extraction; return (question, raw, opened, covered)."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        q_future = pool.submit(gen_followup, history, transcript_text, open_threads)
        f_future = pool.submit(
            extract_facts_raw, transcript_text,
            [s["id"] for s in segments], open_threads,
        )
        question = q_future.result()
        raw_facts, opened, covered = f_future.result()
        return question, raw_facts, opened, covered


def apply_thread_updates(threads, transcript_text, facts, llm_opened=None,
                         llm_covered=None):
    """Merge coverage + newly opened threads; return (threads, opened_ids, covered_ids).

    Deterministic server-side rules (both paths): an OPEN thread is covered
    when a non-empty later transcript re-mentions its text (case-insensitive
    substring); a thread opens per person/place fact whose text is not already
    threaded. Empty transcripts never open or cover anything. Real-path LLM
    proposals are merged in (deduped by id/text); MOCK passes none.
    """
    threads = [dict(t) for t in (threads or [])]
    opened_ids, covered_ids = [], []
    t = (transcript_text or "").strip()
    if t:
        low = t.lower()
        for th in threads:
            if th.get("status") == "open" and th.get("text", "").lower() in low:
                th["status"] = "covered"
                covered_ids.append(th["id"])
    # LLM-proposed covers (real path): match by id, else by text.
    for c in (llm_covered or []):
        key = str(c.get("id") if isinstance(c, dict) else c or "")
        if not key:
            continue
        for th in threads:
            if th.get("status") == "open" and key in (th.get("id"), th.get("text")):
                th["status"] = "covered"
                if th["id"] not in covered_ids:
                    covered_ids.append(th["id"])
    if t and t != "(begin interview)":
        known = {th.get("text", "").strip().lower() for th in threads}
        candidates = []
        for f in (facts or []):
            if not isinstance(f, dict) or f.get("kind") not in ("person", "place"):
                continue
            text = str(f.get("text", "")).strip()
            if text and text.lower() not in known:
                candidates.append((text, str(f.get("segment_id", ""))))
                known.add(text.lower())
        for item in (llm_opened or []):
            text = str(item.get("text", "") if isinstance(item, dict) else item or "").strip()
            seg = str(item.get("segment_id", "") if isinstance(item, dict) else "")
            if text and text.lower() not in known:
                candidates.append((text, seg))
                known.add(text.lower())
        for text, seg in candidates:
            tid = thread_id_for(text)
            # Avoid id collision with different text: suffix until unique.
            base, n = tid, 2
            ids = {th["id"] for th in threads}
            while tid in ids:
                tid = f"{base}-{n}"
                n += 1
            threads.append({"id": tid, "text": text, "segment_id": seg,
                            "status": "open"})
            opened_ids.append(tid)
    return threads, opened_ids, covered_ids


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
        elif parsed.path == "/api/threads":
            qs = parse_qs(parsed.query)
            session_id = "".join(
                c for c in (qs.get("session_id") or [""])[0]
                if c.isalnum() or c in "-_"
            )
            session_dir = (RECORDINGS / session_id) if session_id else None
            if (
                not session_dir
                or RECORDINGS not in session_dir.resolve().parents
                or not session_dir.is_dir()
            ):
                self._send_json({"threads": []})
            else:
                # load_threads normalizes + recovers corrupt/missing to [].
                self._send_json({"threads": load_threads(session_dir)})
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

        session_id = sanitize_id(payload.get("session_id") or "default")
        resume_from = sanitize_id(payload.get("resume_from") or "", default="")
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
        # Resume: on the first turn of a new session, copy the source
        # session's OPEN threads (+facts for the map). Unknown source ->
        # normal fresh session, no error.
        transcript_path = session_dir / "transcript.jsonl"
        is_first_turn = (not transcript_path.exists()
                         or transcript_path.stat().st_size == 0)
        if is_first_turn and resume_from and resume_from != session_id:
            src_dir = RECORDINGS / resume_from
            try:
                if (RECORDINGS in src_dir.resolve().parents and src_dir.is_dir()
                        and not (session_dir / "threads.json").exists()):
                    src_threads = load_threads(src_dir)
                    reopened = [dict(t) for t in src_threads
                                if t.get("status") == "open"]
                    if reopened:
                        save_threads(session_dir, reopened)
                    src_facts_path = src_dir / "facts.json"
                    if src_facts_path.is_file() and not (session_dir / "facts.json").exists():
                        try:
                            src_facts = json.loads(src_facts_path.read_text())
                            if isinstance(src_facts, list) and src_facts:
                                (session_dir / "facts.json").write_text(
                                    json.dumps(src_facts, indent=2))
                        except (ValueError, OSError):
                            pass
            except OSError:
                pass
        threads = load_threads(session_dir)
        open_for_prompt = [t for t in threads if t.get("status") == "open"]
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
        llm_opened, llm_covered = [], []
        try:
            if use_mock:
                question, facts = mock_llm_turn(history, transcript_text, segments,
                                                open_for_prompt)
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
                question, raw_facts, llm_opened, llm_covered = run_llm_turn(
                    history, transcript_text, segments, open_for_prompt)
                facts = resolve_fact_links(raw_facts, clip_id, seg_by_id)
        except Exception as e:  # fall back to stub so the loop stays runnable
            question, facts = mock_llm_turn(history, transcript_text, segments,
                                            open_for_prompt)
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

        threads, threads_opened, threads_covered = apply_thread_updates(
            threads, transcript_text, facts, llm_opened, llm_covered)
        save_threads(session_dir, threads)
        # Re-ask adaptively now that this turn's threads are known: the
        # outgoing question prefers the oldest still-open thread, else the
        # deterministic cycle (so a just-covered thread is never re-asked).
        still_open = [t for t in threads if t.get("status") == "open"]
        if use_mock and not fallback:
            if still_open:
                question = f"Can you tell me more about {still_open[0]['text']}?"
            else:
                n = len(history) if isinstance(history, list) else 0
                question = [
                    "Where did you grow up, and what do you remember most about it?",
                    "Can you tell me about a person who shaped your childhood?",
                    "What is a moment you are proud of that we should record?",
                ][n % 3]
        # turn_count includes the turn being saved.
        try:
            prior_turns = sum(1 for _ in open(transcript_path)) if transcript_path.exists() else 0
        except OSError:
            prior_turns = 0
        turn_count = prior_turns + 1
        suggested = pause_suggested(turn_count, transcript_text)

        result = {
            "question": question or mock_llm_turn(
                history, transcript_text, segments, open_for_prompt)[0],
            "audio_text": (fallback_note + " " + transcript_text).strip(),
            "facts": facts,
            "fallback": fallback,
            "threads": [
                {"id": t["id"], "text": t["text"], "segment_id": t.get("segment_id", ""),
                 "status": t["status"]}
                for t in threads[-MAX_THREADS_RETURNED:]
            ],
            "threads_opened": threads_opened,
            "threads_covered": threads_covered,
            "pause_suggested": suggested,
        }

        # Append turn + persist facts.
        with open(session_dir / "transcript.jsonl", "a") as fh:
            fh.write(json.dumps({
                "ts": utcnow_iso(), "clip_id": clip_id,
                "history_len": len(history), "question": result["question"],
                "transcript": transcript_text, "segments": segments,
                "threads_opened": threads_opened,
                "threads_covered": threads_covered,
                "pause_suggested": suggested,
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
