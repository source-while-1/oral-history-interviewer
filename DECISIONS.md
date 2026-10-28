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
