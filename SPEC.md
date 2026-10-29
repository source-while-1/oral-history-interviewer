# Oral History Interviewer — Product Spec

## Vision
A browser-based voice interviewer that helps families capture oral histories.
An AI asks gentle follow-up questions, records answers, and turns them into a
citable timeline and family map.

## Voice interview loop (adaptive)
1. Browser plays the next interview question via TTS (`speechSynthesis`).
2. Narrator holds push-to-talk, speaks the answer, releases.
3. Browser transcribes the turn via Web Speech API (`SpeechRecognition`).
4. Transcript + conversation history + open loose-end threads go to the
   Fireworks LLM, which returns: (a) the next question to ask, (b) structured
   facts extracted from the turn, (c) threads opened / threads covered.
5. Server saves the audio clip + transcript + facts + threads to local disk.
6. Repeat. There is no fixed 3-question script: each follow-up prefers the
   most salient OPEN thread and only asks a fresh question when none fits.
   The session ends when the narrator clicks "Finish" (or accepts the gentle
   pause suggestion, which never force-stops).

## Loose-end threads
- Each turn may yield threads `[{id, text, segment_id, status}]` with
  `status` open|covered, persisted per session in
  `recordings/<session_id>/threads.json`.
- A thread opens per person/place fact whose text is not already threaded;
  an OPEN thread is covered when a later non-empty transcript re-mentions
  its text (case-insensitive substring). Empty transcripts never open or
  cover anything.
- `POST /api/turn` returns the full current list (open + recently covered,
  capped at ~20) as `threads`, plus `threads_opened` / `threads_covered`
  id lists for the turn.
- `POST /api/turn` accepts optional `resume_from` (a prior session id,
  sanitized like `session_id`). On the first turn it copies that session's
  OPEN threads (+facts for the map) into the new session, so the opening
  question re-opens the oldest open thread. Unknown `resume_from` starts a
  normal fresh session (no error).
- The UI renders an "Open threads" panel from `threads[].text` (+status)
  on every turn, and the `?session=` replay page renders the saved list
  via `GET /api/threads?session_id=...` (same confinement and
  corrupt-tolerant `[]` recovery as `/api/facts`).

## Gentle pause
- `POST /api/turn` returns `pause_suggested: bool`, true when the turn
  count reaches 6 OR the interviewee is judged tired — never by keyword
  matching. Real path (`MOCK_LLM=0`): the fact-extraction LLM call also
  returns `fatigue: {tired, reason}`, judging first-person and implicit
  cues ("I'm tired", "let's stop", "not much more to say", "let's wrap
  this up", markedly terse/disengaged replies) while ignoring
  third-person or historical mentions ("my father was tired after the
  war", "the work was exhausting back then"). MOCK path (offline demo /
  tests): a length-only behavioral proxy — a non-empty turn under 40%
  of the session's own baseline mean (needs >= 3 prior turns, baseline
  mean >= 8 words), documented as a stub approximation. The UI phrases
  it gently; the interview never stops on its own.
- When true, the UI shows a banner ("We've covered a lot — want to pause
  and pick this up another time?") with [Keep going] (dismisses) and
  [Pause & save] (ends the session and shows a resume code = the
  `session_id`, with a Copy button). Typing that code into "Resume a
  session" on the start screen sends it as `resume_from` on the first
  turn.

## Push-to-talk turns
- One turn = one press-and-hold utterance. No continuous listening, no
  server-side streaming ASR.
- Each turn stores: `clip_id`, audio file, transcript, `start`/`end` offsets
  (seconds within the session or clip), created timestamp.
- If STT fails or the turn is empty, the turn is kept with an empty transcript
  and the interviewer asks the narrator to repeat.

## Timeline + family map
- Timeline: chronological list of life events extracted from facts, each with
  date (or date range / circa), title, summary.
- Family map: people mentioned and relationships (parent/child/spouse/sibling).
- **Citation rule: every fact MUST cite `clip_id` + `start`/`end`.** A fact
  without a clip citation is invalid and must not render on the timeline/map.

## Fireworks LLM usage
- Question generation: prompt with interview goal, asked-so-far list, the
  last transcript, and the open threads; the prompt prefers the most salient
  OPEN thread and only asks a fresh question when none fits. Returns one
  short, open-ended next question. (MOCK stub: deterministic cycle, but
  consumes the oldest open thread first.)
- Fact extraction: same turn transcript -> strict JSON:
  `{facts: [{kind, text, when, segment_ids}], threads_opened: [{text,
  segment_id}], threads_covered: [id-or-text], fatigue: {tired, reason}}`
  with `threads_opened` only for genuinely new people/places, never for
  empty turns. `fatigue` rides this same call (no extra latency) and
  drives `pause_suggested` on the real path.
- No other LLM provider in v1. No fine-tuning; prompt + JSON parsing only.

## Browser speech (STT/TTS)
- STT: Web Speech API `SpeechRecognition` (Chrome). No API key needed.
- TTS: `speechSynthesis` with a picked warm voice. No server audio synthesis.
- Explicit non-goal: no Baseten, no server-side ASR/TTS in v1.

## Local disk storage
- `recordings/<session_id>/` holds `*.webm` clips + `transcript.jsonl`.
- `data/facts.json` (or per-session JSON) holds extracted facts with citations.
- No cloud storage, no database server in v1. No Modal, no remote GPU.

## Explicit non-goals
- No Baseten (ASR/TTS) — browser speech only.
- No Modal (remote compute) — local server only.
- No real-time streaming transcription — push-to-talk turns only.
- No user accounts / multi-tenancy in v1.
