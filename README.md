# Oral History Interviewer

A browser-based voice interviewer that turns family stories into a citable
timeline and family map.

- Voice loop: TTS question → push-to-talk answer → browser STT → Fireworks
  LLM next question + JSON fact extraction.
- Every fact cites `clip_id` + `start`/`end`.
- Local disk storage only (`recordings/`). No Baseten, no Modal.

See [SPEC.md](./SPEC.md) and [DECISIONS.md](./DECISIONS.md).

## Layout

- `server.py` — stdlib-only backend; `POST /api/turn`, `GET /api/facts`
- `index.html` — single static frontend (no build step): push-to-talk via
  MediaRecorder, question playback via speechSynthesis, timeline list +
  SVG family map, click-to-replay clip slices
- `recordings/` — local audio clips + transcripts (gitignored, never committed)
- `SPEC.md`, `DECISIONS.md` — product + decisions

## Run

Requires Python 3.9 (pinned: developed on 3.9.6; any 3.9+ works, stdlib only).

```sh
cp .env.example .env   # then fill in keys locally; never commit .env
pip install -r requirements.txt   # no-op: stdlib only, verifies pip works
MOCK_LLM=1 python3 server.py      # stubbed LLM, works offline
# open http://127.0.0.1:8000 in Chrome (mic + Web Speech STT need Chrome)
```

Env vars: `FIREWORKS_API_KEY` (real LLM path only), `FIREWORKS_MODEL`,
`MOCK_LLM=1` (default stub) / `MOCK_LLM=0` (call Fireworks), `PORT` (default 8000).

## Smoke test

```sh
MOCK_LLM=1 PORT=8001 python3 server.py &
SRV=$!
sleep 1
curl -s -X POST localhost:8001/api/turn \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"smoke","audio_b64":"","history":[]}'
# expect: {"question": "...", "audio_text": "", "facts": []}
curl -s 'localhost:8001/api/facts?session_id=smoke'
kill $SRV
```

Use Chrome for the full loop: Start → hold the talk button → release →
question plays via speechSynthesis, timeline/map update, replay replays the clip.
Never commit `.env`, `recordings/`, or real audio.
