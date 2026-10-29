# Decisions

Recorded during setup. Each entry: decision + why.

## 1. Muse + Fireworks only (no other model providers)
- Why: keeps secrets surface to two keys, one chat/question path (Fireworks
  LLM) plus the coded agent. Avoids multi-provider abstraction in v1.

## 2. Browser speech over Baseten
- Why: Web Speech STT + `speechSynthesis` TTS need no keys, no GPU, no
  per-minute cost, and work offline-ish. Baseten would add infra + cost for
  no v1 benefit.

## 3. Local server over Modal
- Why: v1 compute is trivial (serve static UI, append files, proxy Fireworks).
  A local process is free, debuggable, and keeps intimate family audio on the
  family's own disk. Modal's remote GPUs solve nothing here.

## 4. Push-to-talk over streaming
- Why: simpler, robust to silence/noise, each turn maps 1:1 to a citable clip.
  Streaming ASR adds partial-transcript complexity with no product payoff yet.

## 6. Fireworks model + two-call wiring (OpenAI-compatible, concurrent)
- Choice: default `FIREWORKS_MODEL=accounts/fireworks/models/llama-v3p1-8b-instruct`
  via `POST {FIREWORKS_BASE_URL}/chat/completions` with stdlib `urllib` (no SDK).
  Small instruct model: cheap/fast enough for short questions + JSON extraction.
- Two concurrent calls per turn (`ThreadPoolExecutor`): (1) follow-up question
  (short max_tokens=96, plain text), (2) fact extraction
  (`response_format json_object`, schema `{kind person|place|event|relationship,
  text, when, segment_ids}`). `segment_ids` resolve server-side to
  `(clip_id, start, end)`; unknown kinds/ids dropped so every saved fact cites
  a clip slice.
- Fallback: any LLM failure (no key, timeout, bad JSON) falls back to the
  deterministic stub and notes `(llm fallback: …)`; the interview loop never
  breaks. `MOCK_LLM=1` default keeps the offline demo working with no key.

## 7. Browser STT default; Fireworks-Whisper as upgrade path
- Why: Web Speech STT needs no key/cost and works for the offline demo; the
  turn schema already carries `{transcript, segments}`, so a future server-side
  Whisper step (`FIREWORKS_STT_MODEL`, audio/transcriptions endpoint) can fill
  finer segments with no contract change. Not implemented in v1.

## 5. Backend: FastAPI preferred, stdlib fallback
- Why: FastAPI gives typed routes + static serving in few lines; if the
  environment lacks it, `http.server` stdlib covers v1 needs. Either way the
  contract is: serve `/`, accept turn uploads, append JSONL, call Fireworks.
  Final choice: stdlib `http.server` (zero deps, instant cold start).

## 8. Synthetic demo over a recorded real interview
- Why: a real recording would put a teammate's voice/name in a public repo
  forever. `demo/` is all-fictional (invented people/places, generated
  silence sized to the timestamps) and exercises the same path the browser
  uses: POST /api/turn with transcript+segments, saved clips, replay via
  `/?session=`. Doubles as the venue-Wi-Fi backup demo.

## 9. Clip serving + read-only session replay
- Choice: `GET /api/clip?session_id=&clip_id=` serves stored wavs with
  alnum-only id filters and a parents-containment check (no traversal);
  `/?session=<id>` loads `/api/facts` and maps clips to `/api/clip` URLs so
  any saved session replays with audio, timeline, and map.
- Stub-only person heuristic (`Title Name` regex in `mock_llm_turn`) so the
  offline/MOCK path also fills the family map; the real Fireworks path never
  runs it (JSON-mode extraction instead). Documented as stub behavior.

## 10. Live model: muse-spark-open (verified 2026-10-28)
- The placeholder `llama-v3p1-8b-instruct` 404s on this account (stale
  catalog id). `/models` lists 29 serverless ids, no Llama; picked
  `muse-spark-open` (matches the team's Meta Muse access).
- Two model quirks fixed server-side: (1) it is a reasoning model, so the
  96/512 token budgets truncated answers to `""` — budgets raised to
  1024/2048, env-overridable via `FIREWORKS_FOLLOWUP_MAX_TOKENS` /
  `FIREWORKS_FACTS_MAX_TOKENS`; (2) it cites `"0"` for `"seg-0"`, so
  `resolve_fact_links` now accepts index/numeric-suffix aliases (exact ids
  win). Verified live: warm follow-up + 5 clip-linked facts, no fallback.

## 11. (a) Confine /api/facts like /api/clip
- Cause: `GET /api/facts` used the raw `session_id` in a path join, so
  `?session_id=../recordings/<victim>` read another session's facts (T1).
- Fix: same alnum `+ -_` filter and `RECORDINGS in resolved.parents` guard
  as `/api/clip`; anything else returns `{"facts": []}`.

## 12. (b) Corrupt facts.json recovers to []
- Cause: `json.loads` on a corrupt `facts.json` raised unhandled (GET 500)
  and POST appended onto unreadable state (T2).
- Fix: `try/except (ValueError, OSError)` on both paths; GET serves
  `{"facts": []}`, POST resets to `[]` and keeps serving.

## 13. (c) Alias priority: exact > numeric suffix > positional index
- Cause: positional-index aliases were registered first, so with dict order
  `{seg-1, seg-0}` the alias `"0"` bound to `seg-1` (T3).
- Fix: register numeric-suffix aliases first, positional indexes second with
  `setdefault` (never overwrite); exact ids still win at resolve time.

## 14. (d) Clamp non-finite segment bounds
- Cause: `NaN`/`inf` survived `float()` and flowed into fact slices (T4).
- Fix: `math.isfinite` check in `normalize_segments` resets either to `0.0`.

## 15. (e) Empty audio yields a playable 1s silent wav + clamped slices
- Cause: empty `audio_b64` wrote 0 bytes, so the clip was unplayable and
  facts cited a zero-length `0-0` range (T5).
- Fix: stdlib `wave` writes 1s of silence; every fact is clamped into
  `0<=start<end<=duration` (guarded; ordered-only fallback when unknown).

## 16. (f) Turn response carries `fallback: bool`
- Cause: the LLM-fallback path was invisible to the UI (T6).
- Fix: `result["fallback"]` is `True` only when the except path ran.

## 17. (g) Sniff /api/clip Content-Type from magic bytes
- Cause: clips were always served as `audio/wav` even for browser `webm`/ogg
  uploads. Fix: RIFF->wav, EBML->webm, OggS->ogg, default wav.

## 18. (h) Stub `seen` set is per-turn, not per-segment
- Cause: `seen` was re-created inside the segment loop, so a name repeated
  across segments emitted duplicate person facts.
- Fix: hoist `seen = set()` above the loop so cross-segment duplicates emit
  once.

## 19. (i) sendTurn shows errors + offline-answer note
- Cause: `sendTurn` had no `try/catch` or `res.ok` check, so failures left
  `#status` stuck on "Thinking…"; fallback answers looked identical (T7).
- Fix: `try/catch` + `res.ok` check writes the error to `#status`; when
  `response.fallback` is true the question gains an "(offline answer)" note.

## 20. (j) replay() guards zero-length slices
- Cause: `replay()` set `currentTime` past `end` with no guard and choked on
  `end<=start` (T7). Fix: early return with a "clip too short" status.

## 21. Explainer: animated tour + rendered video (no new deps for the app)
- Why: judges may not watch a full live interview; a 50-second tour and a
  56s 720p video (`demo/demo.mp4`, 326KB) explain the loop with no setup.
- `demo/how-it-works.html` served at `/how-it-works` (new server route);
  auto-plays 6 scenes with play/back/next/replay and `prefers-reduced-motion`
  support.
- `demo/make_video.py` renders the same script with Pillow frames piped to
  ffmpeg/libx264. Pillow lives only in the project `.venv` (optional tool);
  server.py and all test suites stay stdlib-only.

## 22. Explainer v2: vendored basemap, fictional banner, "saved facts file"
- Vendored basemap: `demo/assets/basemap_ohio.png` (six z11 OSM tiles
  around lat 40.06 lon -82.88, fetched once with a proper User-Agent,
  composited to 768x512) is committed so `demo/make_video_v2.py` renders
  fully offline and reproducibly — no network at render time, no tile-URL
  dependency in the artifact. Missing file fails fast with a re-fetch
  pointer. Credit "© OpenStreetMap contributors" in demo/README.md, here,
  the outro frame, and every map frame, per the OSM licence.
- Fictional banner: real Columbus-area geography under invented pins
  (family farm, red barn, county fairgrounds) could mislead, so every map
  frame carries a persistent "Fictional places — illustrative" banner, and
  the same three points appear in the graph, map, and records scenes.
  Haversine arcs between them are labeled with real computed km values.
- "Saved facts file" wording: the store is called only that (facts.jsonl
  rows: kind/text/clip/start-end) in the video, the tour, and the READMEs —
  never "database", which would overpromise a query layer v1 does not have.
- Stats bound to script: turn/segment/fact counts on the records and payoff
  scenes are read from `demo/script.json` at render time (3 turns,
  6 segments, 6 rows), so the video cannot drift from the demo it depicts.

## 24. v4 video: vendored Plex, sticker portraits, layout chips, voiceover
- Type: vendored IBM Plex Sans (`demo/assets/fonts/IBMPlexSans-Variable.ttf`,
  OFL; note in `demo/assets/fonts/OFL.txt` + `demo/README.md`) is the first
  font source; system fonts then PIL default are fallbacks. Regular renders
  body, the variable wght=700 axis renders titles/labels. Renderer and docs
  never touch network at render time.
- Portraits: each portrait draws to a transparent RGBA layer, then an
  alpha-dilation composite outlines it (black mask largest, white ring
  middle, art on top). Interiors stay fixed dark ink on both themes, so one
  sticker reads on light and dark. Names moved to chips outside the sticker.
- Layout: every label that sat on art got a chip (padded rounded rect);
  clip markers moved above a capped waveform, graph nodes grew so kind
  labels clear the edge, footer version label floats on a chip 14px above
  the progress bar, map kicker uses light ink on the dark fiction banner,
  km chips float clear of pins. Preview-first held (`/tmp/v4prev_*`,
  viewed each still, two fix rounds: kicker contrast, km-chip clearance).
- Voice: ~205 words, one block per scene, `say -v Samantha` per-scene AIFF,
  `apad,atrim` to exact scene length, concat, mux AAC (`-c:v copy`). The
  renderer prints per-scene speech-vs-scene durations and aborts on overrun —
  it caught one live (title 8.42s > 8s; trimmed to 19 words). Graph is the
  tightest fit (13.73s in 14s).
- Outputs: `demo_v4_light.mp4` (2.43MB) + `demo_v4_dark.mp4` (2.32MB),
  90s 720p30 h264 + AAC, ffprobe-verified. Sticker layers and fonts are
  cached per render so 2700-frame themes stay fast.

## 23. v3 video restyle: light + dark themes with section chrome
- Why: v2 was legible but bland (black on white, no sections). v3 adds a
  `THEMES` palette dict, per-scene kickers ("03 · MAP"), and a footer
  progress bar — same story, designed. Both themes render from one script
  (`--theme light|dark` → `demo_v3_light.mp4` / `demo_v3_dark.mp4`); the
  photographic basemap is dimmed in dark mode, portraits stay identical.
- Preview-first process held: stills approved in /tmp/v3prev_* before the
  full 2700-frame renders; one real bug caught that way (chrome always said
  "00 · INTRO" because the preview loop never passed the scene index).

## 25. v4 video: Plex type, sticker portraits, layout chips, Samantha voiceover
- Typography: vendored IBM Plex Sans variable font (demo/assets/fonts/,
  OFL), Regular body + Bold (wght=700) titles; system-font fallback chain.
- Stickers: portraits render to transparent layers, outlined via alpha
  dilation (black outer ring, white ring, art on top); interior details stay
  fixed dark ink so one sticker reads on both themes.
- Post-ship catch: the sticker cache was keyed by label only, so talk-scene
  portraits reused title-scene positions (chip floated alone). Fixed by
  keying on (label, x, y, r); verified in fresh previews + shipped frames.
- Voiceover: macOS `say -v Samantha`, 205 words fitted per scene (build
  fails on overrun), muxed AAC; renderer self-gates (voice present in
  `say -v '?'`, audio stream 90s, mean level sane).
- Retouches deferred to next version: payoff numerals sit ~3px high;
  graph edge passes behind the red-barn node (text unobscured).

## 26. v5: real display typography + neural voiceover
- Why: v4's Plex Sans loaded correctly but read as a default grotesque.
  Titles/kickers now use vendored IBM Plex Serif Bold (static cuts in
  `assets/fonts/`, OFL) with manual letterspacing on kickers; body stays
  Plex Sans. The pairing is visibly designed, not default.
- Voice: `say`/Samantha replaced by edge-tts `en-US-AvaNeural` (free,
  keyless, network at render only). Fireworks hosts no TTS-capable model
  on this account (29 models listed, none speech); ElevenLabs would need
  a user-supplied key, so edge-tts is the no-blocker path.
- Ava speaks slower than Samantha: the build's overrun gate caught graph
  (+1.2s) and records (+0.1s) overruns, fixed by trimming 6 words total.
  This is the gate working as designed, not a defect.
