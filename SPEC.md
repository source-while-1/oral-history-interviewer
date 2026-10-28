# Oral History Interviewer — Product Spec

## Vision
A browser-based voice interviewer that helps families capture oral histories.
An AI asks gentle follow-up questions, records answers, and turns them into a
citable timeline and family map.

## Voice interview loop
1. Browser plays the next interview question via TTS (`speechSynthesis`).
2. Narrator holds push-to-talk, speaks the answer, releases.
3. Browser transcribes the turn via Web Speech API (`SpeechRecognition`).
4. Transcript + conversation history go to the Fireworks LLM, which returns:
   (a) the next question to ask, (b) structured facts extracted from the turn.
5. Server saves the audio clip + transcript + facts to local disk.
6. Repeat. The session ends when the narrator clicks "Finish".

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
- Question generation: prompt with interview goal, asked-so-far list, and the
  last transcript; returns one short, open-ended next question.
- Fact extraction: same turn transcript -> strict JSON: array of
  `{ type, label, detail, date, people, clip_id, start, end }`.
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
