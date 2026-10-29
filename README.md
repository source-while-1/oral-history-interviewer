# Oral History Interviewer

A browser-based voice interviewer that turns family stories into a citable
timeline and family map.

- Voice loop: TTS question → push-to-talk answer → browser STT → Fireworks
  LLM next question + JSON fact extraction.
- Every fact cites `clip_id` + `start`/`end`.
- Local disk storage only (`recordings/`). No Baseten, no Modal.

See [SPEC.md](./SPEC.md) and [DECISIONS.md](./DECISIONS.md).

## Layout

- `server.py` — stdlib-only backend; `POST /api/turn`, `GET /api/facts`,
  `GET /api/threads`, `GET /api/clip`; `demo/` synthetic backup demo;
  `test_smoke.py` / `test_demo.py` / `test_review.py` / `test_adaptive.py` suites
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

Env vars: `FIREWORKS_API_KEY` (real LLM path only, read from env —
never committed), `FIREWORKS_MODEL`, `FIREWORKS_BASE_URL` (default
`https://api.fireworks.ai/inference/v1`), `MOCK_LLM=1` (default stub) /
`MOCK_LLM=0` (call Fireworks), `PORT` (default 8000).

## Fireworks wiring

- OpenAI-compatible chat client (`POST {base}/chat/completions`, Bearer key
  from `FIREWORKS_API_KEY` only, stdlib `urllib` — no SDK).
- Two concurrent calls per turn (`ThreadPoolExecutor`, max 2):
  1. follow-up question — short `max_tokens` (96), plain text, one warm question;
  2. fact extraction — `response_format: {"type": "json_object"}`, schema
     `{kind: person|place|event|relationship, text, when, segment_ids}`.
- `segment_ids` are resolved server-side to `(clip_id, start, end)`; every
  saved fact cites a clip slice. Unknown kinds/ids are dropped.
- Fallback: any LLM error (missing key, timeout, bad JSON) falls back to the
  deterministic stub so the interview loop keeps running; the turn notes
  `(llm fallback: …)` in `audio_text`.

## STT default + upgrade path

- Default v1: browser Web Speech API STT (offline demo, no key). The frontend
  sends `{transcript, segments: [{id, text, start, end}]}`; the server also
  accepts `audio_text` and derives a `seg-0` segment when none is given.
- Upgrade path (not implemented): POST the saved clip to
  `{FIREWORKS_BASE_URL}/audio/transcriptions` with `FIREWORKS_STT_MODEL`
  (e.g. Whisper) to get word/segment timestamps, then fill `segments` before
  the LLM calls. No schema change needed.

## Synthetic demo (backup for the live interview)

All-fictional 3-turn interview with generated silent clips — no mic, no
keys, no network. Feeds `demo/script.json` through the server, then serves
a replay with timeline, map, and clip audio:

```sh
python3 demo/replay.py
# open http://127.0.0.1:8000/?session=demo-synthetic
```

`GET /api/clip?session_id=…&clip_id=…` serves stored wavs (404 on unknown
or traversal-y ids); `/?session=<id>` loads any saved session read-only.
Details in [demo/README.md](demo/README.md).

## Explainer: animated tour + video

- [`/how-it-works`](http://127.0.0.1:8000/how-it-works) — auto-playing
  7-scene web tour of one turn (talk → think → map → saved facts file →
  replay), with play/back/next/replay controls and `prefers-reduced-motion`
  support.
- [`demo/demo.mp4`](demo/demo.mp4) — the same tour as a 56s 720p video,
  rendered by [`demo/make_video.py`](demo/make_video.py) (Pillow frames →
  ffmpeg/libx264; needs Pillow: `python3 -m venv .venv && .venv/bin/pip install pillow`).
- v4 voiced: [`demo/demo_v4_light.mp4`](demo/demo_v4_light.mp4) and
  [`demo/demo_v4_dark.mp4`](demo/demo_v4_dark.mp4) — the 90s story with
  section chrome, vendored IBM Plex Sans, sticker portraits, and a
  Samantha voiceover (AAC). Rendered by
  [`demo/make_video_v2.py`](demo/make_video_v2.py)
  (`.venv/bin/python demo/make_video_v2.py --theme light|dark`).
- v5: [`demo/demo_v5_light.mp4`](demo/demo_v5_light.mp4) and
  [`demo/demo_v5_dark.mp4`](demo/demo_v5_dark.mp4) — Plex Serif display
  type with letterspaced kickers, edge-tts Ava neural voiceover.
  Needs `edge-tts` in the project env.
- v3 restyle: [`demo/demo_v3_light.mp4`](demo/demo_v3_light.mp4) and
  [`demo/demo_v3_dark.mp4`](demo/demo_v3_dark.mp4) — the 90s v2 story with
  section chrome (kickers, footer progress), light + dark themes (silent).
- [`demo/demo_v2.mp4`](demo/demo_v2.mp4) — the full 3-turn story as a 90s
  720p30 video, rendered by [`demo/make_video_v2.py`](demo/make_video_v2.py)
  off the vendored [`demo/assets/basemap_ohio.png`](demo/assets/basemap_ohio.png)
  (map: © OpenStreetMap contributors; all pins fictional).

## Adaptive loop (threads, gentle pause, resume)

Each turn returns loose-end `threads` (`[{id, text, segment_id,
status}]`, open|covered) plus `threads_opened` / `threads_covered` id
lists and a `pause_suggested` bool. Mentioning a person opens a thread
(`th-aunt-rosa`); re-mentioning her later covers it. The next question
prefers the oldest open thread and only asks a fresh question when none
fits. After 6 turns — or on a tiredness cue ("I'm tired", "enough for
today", "let's stop", "another time") — the UI shows a gentle pause
banner with Keep going / Pause & save. Pausing shows a resume code (=
the `session_id`); typing it into "Resume a session" sends it as
`resume_from` on the first turn, which copies the old session's open
threads (+ facts) so the opening question picks the story back up.
Unknown codes start a clean session.

```sh
MOCK_LLM=1 PORT=8001 python3 server.py &
SRV=$!
sleep 1
# turn 1: opens th-aunt-rosa, asks about her
curl -s -X POST localhost:8001/api/turn -H 'Content-Type: application/json' \
  -d '{"session_id":"s1","audio_b64":"","history":[], "transcript":"I grew up with Aunt Rosa.", "segments":[{"id":"seg-0","text":"I grew up with Aunt Rosa.","start":0,"end":1}]}'
# turn 2: covers it, falls back to the cycle question
curl -s -X POST localhost:8001/api/turn -H 'Content-Type: application/json' \
  -d '{"session_id":"s1","audio_b64":"","history":[{"role":"user","text":"I grew up with Aunt Rosa."}], "transcript":"Aunt Rosa taught me to bake.", "segments":[{"id":"seg-0","text":"Aunt Rosa taught me to bake.","start":0,"end":1}]}'
# resume in a fresh session: opening question asks about the carried thread
curl -s -X POST localhost:8001/api/turn -H 'Content-Type: application/json' \
  -d '{"session_id":"s2","resume_from":"s1","audio_b64":"","history":[], "transcript":"(begin interview)","segments":[]}'
curl -s 'localhost:8001/api/threads?session_id=s2'
kill $SRV
```

```sh
python3 test_adaptive.py
```

Covers open-on-turn-1, cover-on-re-mention, pause after 6 turns + on
tired cue, resume carrying threads/facts with the opening question
referencing the thread, and clean start on unknown `resume_from`.
Asserts exact response shapes (`threads`, `threads_opened`,
`threads_covered`, `pause_suggested`, `fallback`).

## Demo tests

```sh
python3 test_demo.py
```

1. Feeds the synthetic script through a MOCK server and asserts every fact
   cites a real clip slice (`0 <= start < end <= wav duration`), kinds are
   valid, and the map people (Aunt Rosa, Grandpa Emil) surface.
2. Asserts `/api/clip` returns byte-identical audio, 404s cleanly, and
   `index.html` carries the `?session=` replay hook.

## Smoke test (stubbed LLM, proves fact→clip linkage)

```sh
python3 test_smoke.py
```

Observed (MOCK_LLM=1, 2026-10-28):

```json
{
  "question": "Can you tell me about a person who shaped your childhood?",
  "audio_text": "I grew up in Lisbon with Ana.",
  "facts": [
    {
      "kind": "event",
      "text": "I grew up in Lisbon with Ana.",
      "when": "",
      "clip_id": "clip-1793187716647",
      "start": 0.0,
      "end": 2.5,
      "segment_id": "seg-0"
    }
  ]
}
SMOKE OK: fact->clip linkage shape verified (1 fact(s))
```

Every fact carries `clip_id` + `start`/`end` (+ source `segment_id`) and
`GET /api/facts` returns the same list that `POST /api/turn` produced.

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
