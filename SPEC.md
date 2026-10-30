# Oral History Interviewer — Product Spec

## Vision (generational)
The APP is the interviewer. A setup helper (e.g. a grandson) sets the family
up once; each interviewee (e.g. a grandparent) gets one personal link and
just talks — no codes, no accounts, no typing for elders. The app asks gentle
follow-up questions, records answers, and turns them into a citable timeline
and family map that descendants explore generations later. Roles are
fluid, not hard-coded: anyone in the family can be an interviewee —
including the helper ("Add me too") — and one person can help set up,
record, and ask across generations; the archive includes whoever
recorded.

## Roles (fluid — NOT hard-coded castes)
- A **person** is any family member with a record (`person_id`). ONE person
  can hold several roles at once: helper, interviewee, and
  descendant-asker are things a person DOES, not kinds of people.
- **Helper** (setup role, e.g. a grandson — but anyone): creates the
  family, registers one record per interviewee, shares each personal
  link, and leaves next-time topics. Never required to sit in on the
  interview. Setting up YOURSELF is exactly as easy as setting up a
  grandparent ("Add me too" creates your own `person_id` + personal
  link alongside theirs).
- **Interviewee** (recording role, e.g. a grandparent — but anyone,
  INCLUDING the helper): opens their personal link and talks. Auto
  start/resume, push-to-talk only. No codes, no accounts, no resume
  codes to type. The archive includes whoever recorded, across
  generations — a helper who records is archived like any interviewee.
- **Descendant / asker** (exploring role, generations later — but also
  today): explores timelines, the family map, Ask-the-family answers,
  and per-relative reconstructions. Exploring is read-only and never
  adds to the archive; but an asker who ALSO records does so through
  their own interviewee personal link, so the archive keeps growing
  generation after generation.

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

## Generational model (Phase 1 spec; implementation follows)
- **Per-interviewee personal link + auto start/resume.** One `person_id`
  per interviewee, one unguessable personal link
  (`GET /i/<person_token>` resolving to `?person=<person_id>`). Opening the
  link auto-starts a session for that person and auto-resumes their open
  threads/facts/consent on the next visit — the elder never types a resume
  code, invite code, or password. Tokens are random unguessable secrets,
  stored hashed server-side like invite codes); whoever holds a link
  (usually the helper distributing them, or the person themselves via
  "Add me too") is the only party who needs to handle it. A person who
  both helps and records simply holds their own link plus any links
  they distribute.
  New: `POST /api/people {display_name}` → `{person_id, person_token,
  personal_link}`; `GET /api/person?person_id=` (helper/descendant view);
  `POST /api/turn` accepts `person_id` (+ token-cookie/header) and binds
  the session to that person (`recordings/<session>/person.json`
  `{person_id}`; per-person index `recordings/people/<person_id>/sessions.json`).
  Same turn/facts/threads/clip shapes otherwise.
- **Helper leaves next-time topics (never interrupts).** The helper may
  leave short topics/questions for a specific interviewee:
  `POST /api/next-topics {person_id, topics: [str]}` (stored per person in
  `recordings/people/<person_id>/next_topics.json`
  `[{id, text, status: queued|asked, created_at}]`). They surface ONLY as
  candidate openers/follow-ups at the START of a future session (or when no
  open thread fits), marked `asked` once used. They are HELD (not asked)
  when the interviewee is judged tired/distressed (`pause_suggested` or
  turn `distress: true`), and they NEVER interrupt mid-conversation.
- **Person-level identity + cross-person entities.** Every session belongs
  to exactly one `person_id`; facts/clips stay per-session (citation
  invariant unchanged), and a DERIVED cross-person entity index groups
  normalized names (people/places) across relatives WITHOUT merging:
  `GET /api/family-entities?person_ids=[...]` →
  `{entities: [{name, mentions: [{person_id, session_id, clip_id, start,
  end, quote}]}]}`. Each mention keeps its own per-relative cited clip;
  clips play via the unchanged `GET /api/clip`.
- **Corroboration + disagreement (never merged).** When ≥2 consenting
  relatives cite the same entity/event, the UI shows "both mention this"
  (a corroboration badge listing each relative's cited clip). When cited
  accounts conflict (different dates/details), the UI shows them
  side-by-side with per-relative citations — NEVER merged into one
  "canonical" fact, never auto-corrected.
- **Ask-the-family across ALL consenting relatives.** `POST /api/ask`
  gains an optional `person_ids` scope; omitted = all persons whose
  per-person consent currently allows archive answers (unrevoked; retire
  does not block Day-2 archive answers unless the family closes archive
  access). Per-claim playable citations required as today, now spanning
  relatives: each citation carries `{person_id, session_id, clip_id,
  start, end, quote}`. Persons without consent are silently excluded
  (never leak across scope). No new knowledge source; same grounding
  contract.
- **Talk-with-a-relative per-person consent + retirement.** The character
  mode is per-relative: `POST /api/character` takes `{person_id,
  question, requester, invite_code}` (single person; multi-person
  characters are NOT offered). The gate is per-person: allowed only when
  THAT person's consent is `ai_reconstruction: true`, unrevoked, and
  unretired, plus the per-person (`requester`, `invite_code`) check.
  Revoke/retire are per person: revoking person A silences A's archive +
  character without touching person B; retiring A disables only A's
  character (A's wishes/recordings stay intact; un-retire restores).
  Consent storage moves from per-session `consent.json` to per-person
  `recordings/people/<person_id>/consent.json` (same shape incl.
  `access_list`/`invite_codes`/`retired`/`revoked`); existing per-session
  files read as fallback during migration. No cloned voice by default
  (unchanged: stretch only, `voice_clone: true` per person required,
  real-clip fallback always available).

## Safety (all carried forward, per person)
- Grounding + citations: every claim cites a playable clip slice; "I
  couldn't find that in the recordings." + no-merge + no-invention rules
  unchanged, now across relatives.
- Consent PER PERSON: per-interviewee record; archive/character scope
  checks run per person on every call (default-deny).
- Revoke/retire PER PERSON (separate actions, separate fields, separate
  effects — see above).
- Grief + fatigue handling: model-judged (never keywords); gentle repair
  question; pause suggestion never force-stops; distress tone keyed ONLY
  on turn `distress: true`, never on `pause_suggested`; next-time topics
  held when tired/distressed; character never initiates difficult topics
  or role-plays distress.
- No cloned voice by default: hidden unless per-person
  `voice_clone: true`.

## Explicit non-goals
- No Baseten (ASR/TTS) — browser speech only.
- No Modal (remote compute) — local server only.
- No real-time streaming transcription — push-to-talk turns only.
- No user accounts for interviewees in v1 (personal links, not logins).
  Helper/descendant auth stays out of scope until the deployment accounts
  work in docs/SPEC-archive-character.md §10.2 lands.
