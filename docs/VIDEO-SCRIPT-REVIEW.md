# Video Script Review — demo_v12 (fresh-eyes critique)

Read-only scope: `NARRATION` dict + on-screen strings in `frame_*`
(`text()` / `chip()` / `say()`) in `demo/make_video_v12.py`.
Judged as (a) a hackathon judge and (b) a family member who might use this.

## Verdict in one paragraph

Technically the video is honest and consistent — every claim is checkable,
every quote is really spoken, nothing is faked. But it **sounds like a spec
read aloud, not a story about a family**. The narration is a feature list
walked in UI order ("First you talk… It keeps going… Pause and save… On the
record… Later family asks… Talk with the reconstruction… Try it yourself").
There is no person with a name and a want in the first 15 seconds, no stakes
("why should I record my aunt before it's too late?"), and an ending that
tells a grandparent to "run the replay script". A judge will score it
competent but forgettable; a family member will feel this is built for
developers, not for them.

## Scene-by-scene

### 0 · Intro (title)

- Narration: "Meet the Oral History Interviewer. Every fact links back to the
  voice that said it. Everyone here is fictional."
- On-screen: "Oral History Interviewer" / "Every fact links back to the voice
  that said it." / "a hackathon demo · all people and places fictional"
- Judge: competent tagline, but no hook. No question, no tension, no promise.
  "Every fact links back to the voice" is an architecture property, not a
  reason to care.
- Family: "Interviewer" sounds like a job interview or a journalist. "Fact"
  sounds like homework. Nobody says "I want my facts linked back".
  They say "I wish I'd recorded Mom telling that story."
- Weakest line: "Everyone here is fictional" as the third sentence.
  Legally necessary, emotionally fatal as an opener — the first faces we meet
  are instantly declared not-real. Move the fiction disclaimer to a small
  caption, not the voiceover.

### 1 · Talk & threads (threads)

- Narration: "First, you talk. Mention Aunt Rosa, and a thread opens. Mention
  her again, and it is covered. The next question prefers the oldest open
  thread."
- On-screen: "Step 1 · Talk — threads open as you speak" / "thread
  th-aunt-rosa · opened/covered" / "re-mention covers the thread" /
  "What we've learned so far (collapsed)"
- Feature-list narration: three sentences = three mechanics (open, cover,
  scheduling policy). The last sentence is pure scheduler documentation.
  Nobody outside the team knows or cares what "prefers the oldest open
  thread" means.
- Jargon: "thread", "opened/covered", "th-aunt-rosa" (a product id shown to a
  grandmother), "re-mention".
- Describes what's on screen: the voiceover literally narrates the chip
  changing from "opened" to "covered". Redundant by design.
- Family rewrite direction: "Just start talking — say 'Aunt Rosa grew up on
  a farm…' and the app remembers to ask about her later."

### 2 · Keep going (continue)

- Narration: "The interview follows loose ends as threads. It keeps going
  while there is history to cover, asking next about Grandpa Emil."
- On-screen: "Step 1 · Keeps going while stories remain" / six "turn N"
  boxes / "keeps going while threads stay open" / "Can you tell me more about
  Grandpa Emil? The follow-up prefers the oldest open thread."
- Flat/robotic: "It keeps going while there is history to cover" is what a
  loop condition sounds like, not encouragement.
- Spec-not-story: "The follow-up prefers the oldest open thread" is a
  priority-queue description pasted into a speech bubble — a fictional
  grandchild would never say this sentence. It breaks character and reminds
  the viewer these are puppets for the scheduler.
- Family question: *can I stop it?* Six numbered boxes filling in order reads
  as "you must do all six". Nothing says "you can stop anytime" until the
  next scene.

### 3 · Gentle pause (pause)

- Narration: "When you are tired, just say so. The interview suggests a gentle
  pause, never a stop, and meets heavy moments gently, with time to rest."
- On-screen: "Step 1 · Tired? — a gentle pause, never a stop" /
  "I'm tired, let's pick this up another time." /
  "Take all the time you need. We can rest here as long as you like." /
  "pausing is always your choice" / "> Your resume code"
- Best scene in the video. The exchange is human, the "never a stop" framing
  is genuinely comforting, and "pausing is always your choice" is the first
  line that grants the user power instead of describing the system.
- Remaining nit: narration says "gently" twice in one sentence
  ("meets heavy moments gently, with time to rest"). One "gently" is enough.
- "Grief handling" (the file docstring's term) is never named on screen or in
  narration — good instinct (don't label grief), but then the narration's
  "heavy moments" is vague. One concrete half-sentence ("even when a memory
  hurts") would land harder than "heavy moments".

### 4 · Resume (resume)

- Narration: "Pause and save, and your code is your session. A new session
  carries the open threads, the saved facts, and the map facts."
- On-screen: "Step 1 · Resume — your code is your session" / "Your resume
  code: demo-synthetic" / "New session · demo-resumed" / "resume_from carries
  over" / "N open thread + M saved facts" / "map facts included"
- Jargon pile-up: "your code is your session", "resume_from carries over"
  (a function name on screen in a family product), "map facts",
  "demo-synthetic / demo-resumed" (synthetic test fixtures as the hero prop).
- Feature-list narration: the second sentence is an inventory of carried
  state (threads + facts + map facts). A family member hears "carries the
  open threads" as noise.
- Missing "why this matters": never says the actual human payoff — "come
  back next Sunday and pick up exactly where Grandma left off".
- "shown at Pause & save" with an ampersand reads like a button label
  quoted in court. Say "we showed it when you paused".

### 5 · Consent (consent)

- Narration: "On the record, you decide what happens next. May family talk
  with a reconstruction? Who may access it? May it use your voice?"
- On-screen: "Step 1 · Your words, your rules" / "on-the-record consent" /
  "Yes — and only family." / "AI reconstruction: yes / Who may listen:
  family / Cloned voice: no" / "revoke any time"
- Strongest heading in the video ("Your words, your rules" — keep it, and
  consider making it the video's thesis).
- Jargon: "On the record" / "on-the-record consent" means nothing to a
  non-journalist family; "reconstruction", "Cloned voice: no" as a chip.
  "AI reconstruction: yes" as a consent row is asking a tired elder to
  consent to a term the video never defines in plain words.
- Narration is three questions in a row with no answer and no feeling.
  It lists the consent schema instead of the reassurance: "nothing is shared,
  nothing speaks in your voice, unless you say so — and you can take it back."
- "revoke any time" is the right promise in the wrong register. Families say
  "you can change your mind / take it back anytime".

### 6 · Ask the archive (ask)

- Narration: "Later, family asks the archive. Answers quote the recordings and
  play the real clip. When nothing covers it, it says so: I couldn't find that
  in the recordings."
- On-screen: "Step 2 · Ask the archive" / "Family asks: where did Aunt Rosa
  grow up?" / "ARCHIVE ANSWER" / "clip seg-0 · 0.0–3.5s · plays the real
  clip" / "Family asks: did anyone here visit the moon?" / "I couldn't find
  that in the recordings." / "closest topic: the county fair"
- "Ask the archive" is insider language (the API endpoint is called ask);
  families "ask Grandma's stories", not "the archive".
- "clip seg-0 · 0.0–3.5s" is a segment id + timestamp on screen — pure
  developer exhaust. Show "plays Rosa's own voice ▶" instead.
- "When nothing covers it, it says so" smuggles the thread-coverage model
  ("covers") into a sentence about honesty. Say "when the answer isn't in
  the recordings".
- The moon question ("did anyone here visit the moon?") is meant to demo
  honest refusal, but played straight it makes the family look foolish.
  Frame it as the narrator's probe, not "family asks": e.g. "Ask something
  nobody said…".
- Quoting the refusal line verbatim in narration ("it says so: I couldn't
  find…") is the video describing its own caption. Let the clip speak; the
  narrator should name the virtue ("it never makes things up").

### 7 · Talk with the reconstruction (character)

- Narration: "Talk with the reconstruction. Answers in your own phrasing,
  always labeled, every claim cited, only for people named in consent.
  No cloned voice here."
- On-screen: "Step 3 · Talk with the reconstruction" /
  "AI reconstruction — not the real person" / "Aunt Rosa · seg-0 · 0.0–3.5s
  · cited" / "only for people named in consent" /
  "can be retired any time · no cloned voice here"
- This is the emotional and ethical climax of the product and the narration
  treats it as a compliance checklist: labeled + cited + consented +
  no-clone. Four guarantees, zero feeling.
- "Answers in your own phrasing" is ambiguous (whose "your"? the deceased's?
  the user's?). Probably means "in her own recorded words" — say that.
- "only for people named in consent" is consent-schema leakage; say "only
  when she said yes".
- "can be retired any time" — "retired" is HR language for a simulacrum of
  a dead relative. Say "you can turn it off / put it away".
- Missing "why this matters" entirely: never one sentence on what a family
  *gets* here ("hear her stories in her words, after she's gone") nor the
  plain-spoken boundary ("it's not her — it only repeats what she recorded").

### 8 · Outro (outro)

- Narration: "Try it yourself. Run the replay script. All people and places
  are fictional."
- On-screen: "Try it yourself" / "python3 demo/replay.py" /
  "github.com/source-while-1/oral-history-interviewer" /
  "MOCK_LLM=1 runs without a key · MOCK_LLM=0 uses Fireworks"
- Weakest ending in the video. Three problems:
  1. It addresses only developers ("Run the replay script", "MOCK_LLM=1…").
     A family member's next step is nowhere ("record your first story").
  2. It ends on the fiction disclaimer — the last word is a denial.
     End on the promise ("Every story keeps its voice."), disclaimer as
     caption.
  3. "MOCK_LLM=1 … MOCK_LLM=0 uses Fireworks" is environment-variable
     documentation as a closing title card. Cut from the video; belongs in
     the README.

## Cross-cutting notes (judge's list)

1. **Feature-list narration.** Nearly every scene maps 1:1 to a feature in
   build order (talk → continue → pause → resume → consent → ask →
   character → outro). There is no arc — no setup, no complication, no
   payoff. Consider a spine: one family (Rosa + Emil), one sitting, one
   pause, one return months later, one question asked of the archive.
   Let features appear as beats in that story.
2. **Jargon / internal terms on screen or in VO** (glossary of what to
   rename or demote to README): thread(s), opened/covered, re-mention,
   oldest open thread, resume code / resume_from, open thread + saved facts,
   map facts, facts.jsonl ("saved facts file" is better but still a
   filename), seg-0 / 0.0–3.5s, on-the-record (consent), archive,
   reconstruction (never glossed), closest topic, retired, MOCK_LLM,
   demo-synthetic / demo-resumed, "Step N ·" nav labels as narration
   ("Step 1 · Talk" is fine on screen; never say "step one" aloud).
3. **Flat / robotic phrasing.** "It keeps going while there is history to
   cover." / "A new session carries the open threads." / "Answers quote the
   recordings." Subject-verb-object with a system subject in almost every
   line. Give the subject back to people: "you", "Rosa", "your family".
4. **Lines that merely describe what's on screen.** Threads ("Mention her
   again, and it is covered"), Ask (quoting the refusal caption verbatim),
   Resume (reading the carried-state card aloud). Rule of thumb: if the
   viewer can read it, the voice should add meaning, not echo it.
5. **Missing emotional hook / why-this-matters.** The video never says the
   one sentence the whole project depends on: *record them while you can;
   their voice stays answerable after they're gone.* The pause scene almost
   gets there ("never a stop"); make that tenderness the through-line, not
   one scene's chip.
6. **Opening / ending.** Open on a person and a want ("Rosa is 82. Her
   grandson wants her Ohio childhood in her own voice."), not on the product
   name. End on an invitation for families plus a separate dev card —
   never end on env vars and a fiction denial.
7. **Spec rather than story.** The scheduler ("prefers the oldest open
   thread"), the state transfer ("carries the open threads, the saved
   facts, and the map facts"), the consent schema (three enumerated
   questions), the no-hallucination guarantee ("every claim cited") are all
   true and all phrased as requirements. Each needs one human translation:
   oldest-open-thread → "it remembers who you haven't asked about";
   resume carry-over → "pick up next Sunday where you left off";
   cited claims → "every answer plays her actual voice".
