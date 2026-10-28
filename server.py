"""Minimal oral-history-interviewer backend (stdlib only).

POST /api/turn  {session_id, audio_b64, history} -> {question, audio_text, facts}
GET  /          serves index.html (single static frontend, no build step)
GET  /api/facts?session_id=...  returns saved facts for a session

Storage: recordings/<session>/<clip>.wav + transcript.jsonl (gitignored).
LLM is stubbed; real Fireworks wiring comes next. MOCK_LLM=1 (default) forces stub.
"""

import base64
import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
RECORDINGS = ROOT / "recordings"
FIREWORKS_URL = "https://api.fireworks.ai/inference/v1/chat/completions"
FIREWORKS_MODEL = os.environ.get("FIREWORKS_MODEL", "accounts/fireworks/models/llama-v3p1-8b-instruct")


def utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


def mock_turn(history):
    """Deterministic stub: next question + zero or one demo fact."""
    n = len(history) if isinstance(history, list) else 0
    questions = [
        "Where did you grow up, and what do you remember most about it?",
        "Can you tell me about a person who shaped your childhood?",
        "What is a moment you are proud of that we should record?",
    ]
    return {
        "question": questions[n % len(questions)],
        "audio_text": "",
        "facts": [],
    }


def call_fireworks(history):
    """Real LLM path (wiring placeholder). Raises on any failure -> caller falls back."""
    api_key = os.environ.get("FIREWORKS_API_KEY", "")
    if not api_key:
        raise RuntimeError("FIREWORKS_API_KEY not set")
    messages = [
        {"role": "system", "content": (
            "You are a gentle oral-history interviewer. Given the conversation "
            "history, ask ONE short open-ended follow-up question and extract "
            "facts as JSON. Reply ONLY as JSON: "
            '{"question": str, "audio_text": str, '
            '"facts": [{"kind": str, "text": str, "when": str}]}.'
        )},
        {"role": "user", "content": json.dumps(history)[-6000:]},
    ]
    req = urllib.request.Request(
        FIREWORKS_URL,
        data=json.dumps({"model": FIREWORKS_MODEL, "messages": messages}).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode())
    content = body["choices"][0]["message"]["content"]
    return json.loads(content)


class Handler(BaseHTTPRequestHandler):
    server_version = "OHI/0.1"

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
        elif parsed.path == "/api/facts":
            qs = parse_qs(parsed.query)
            session_id = (qs.get("session_id") or [""])[0]
            facts_path = RECORDINGS / session_id / "facts.json" if session_id else None
            if not facts_path or not facts_path.exists():
                self._send_json({"facts": []})
            else:
                self._send_json({"facts": json.loads(facts_path.read_text())})
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
            clip_path.write_bytes(b"")

        use_mock = os.environ.get("MOCK_LLM", "1") != "0"
        try:
            result = mock_turn(history) if use_mock else call_fireworks(history)
        except Exception as e:  # fall back to stub so the loop stays runnable
            result = mock_turn(history)
            result["audio_text"] = f"(llm fallback: {e})"

        # Attach citation (clip slice; whole-clip offsets for the stub).
        facts = result.get("facts") or []
        for f in facts:
            f.setdefault("clip_id", clip_id)
            f.setdefault("start", 0)
            f.setdefault("end", 0)
        result["facts"] = facts
        result.setdefault("question", mock_turn(history)["question"])
        result.setdefault("audio_text", "")

        # Append turn + persist facts.
        with open(session_dir / "transcript.jsonl", "a") as fh:
            fh.write(json.dumps({
                "ts": utcnow_iso(), "clip_id": clip_id,
                "history_len": len(history), "question": result["question"],
            }) + "\n")
        facts_path = session_dir / "facts.json"
        existing = json.loads(facts_path.read_text()) if facts_path.exists() else []
        facts_path.write_text(json.dumps(existing + facts, indent=2))

        self._send_json(result)


def main():
    port = int(os.environ.get("PORT", "8000"))
    srv = HTTPServer(("127.0.0.1", port), Handler)
    print(f"oral-history-interviewer on http://127.0.0.1:{port} (MOCK_LLM={os.environ.get('MOCK_LLM', '1')})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
