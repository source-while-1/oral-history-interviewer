# UI Review — First-time-user before/after for the `index.html` simplification (`bad47d6`)

Commit: `bad47d6` — "UI simplification: one clear path in three steps".
Scope of the change (from `git show bad47d6 --stat` / diff): `index.html` only, +112/−27.
No API, payload, grounding, consent/revoke/retire, gate, demo, or rate-limit changes.
Review method: read `index.html` at HEAD, read the parent (`bad47d6^`) version,
read the `git diff bad47d6^ bad47d6`, and viewed screenshots
`/tmp/ui_before_*.png` vs `/tmp/ui_after_*.png`.

First-viewport result: before = wall of panels (session jargon, resume field,
Start/Hold/Finish, empty threads, empty timeline, empty map, full Ask archive,
full reconstruction gate). After = ordered path
("1. Record a story → 2. Ask the recordings → 3. Talk with the AI
reconstruction"), one visible step, one primary CTA per step
(`ui_after_desktop_light.png`, `ui_after_mobile_light.png`).

## Ranked issues, before → after

### 1. No onboarding / wall of panels / session-id jargon in the first viewport
- Before: first viewport opened with `Session: s-<id>` jargon plus every panel
  stacked on one page (`ui_before_desktop_light.png`). No statement of order or
  where to start. (`bad47d6^:index.html`: `Session: <code id="sid">` line,
  all sections unhidden.)
- After: plain-language path at the top — "Three steps, in order: 1. Record a
  story → 2. Ask the recordings → 3. Talk with the AI reconstruction. Start at
  step 1." (`index.html:42`). Only Step 1 is visible; Steps 2/3 are `hidden`
  (`index.html:103,121`). Session id moved into the resume `<details>`.
- Verified: `ui_after_desktop_light.png` (path sentence + Step 1 only);
  `git diff bad47d6^ bad47d6` (added line 42, `hidden` on Step 2/3 sections);
  code probe `grep aria-current index.html` (Step 1 marked current, lines 45–47).

### 2. Six-plus competing CTAs
- Before: `Start`, `Hold to talk`, `Finish`, `Ask`, `Ask`, `Stop` all visible
  at once, all styled equally (`ui_before_desktop_light.png`).
- After: one primary CTA per visible step — `Start the interview` (Step 1,
  `index.html:79`, `button.primary`), `Ask` (Step 2), `Ask the reconstruction`
  (Step 3). Step nav (`nav.modes`, `index.html:44-48`) switches visibility via
  `show()` (`index.html:410-430`); only one step is unhidden at a time.
- Verified: `ui_after_desktop_light.png` (only `Start the interview` primary in
  view); `ui_after_step2.png` and `ui_after_step3.png` (DOM-probe renders, one
  primary each); code probe of `modes()` show/hide logic.

### 3. Reconstruction consent-gate wall
- Before: the full Step 3 gate (Which recording, Your name, Invite code,
  question, Ask/Stop, banner, label, read-only note) rendered in the open on
  first load (`ui_before_desktop_light.png`).
- After: gate fields collapsed into `<details><summary>Who may enter (name and
  invite code)</summary>` (`index.html:135-141`), closed by default. The
  safety banner, label, proof `<details open>`, and read-only/Stop note stay
  always visible (`index.html:124,129-134`).
- Verified: `ui_after_step3.png` (gate collapsed, banner + question + proof
  visible); code probe `index.html:135-141`.

### 4. Session-ID prefill jargon
- Before: "Resume a session (optional): [past session id]" inline at top, plus
  "Session: s-…" and "Sessions to ask (comma-separated)" / "Session:" labels in
  Steps 2/3 (`ui_before_desktop_light.png`; `bad47d6^` ask/charscope inputs).
- After: resume becomes `<details><summary>Have a resume code? Continue a
  saved story</summary>` with plain hint "Enter the code above, then press
  'Start the interview'. Leave it empty to begin a new story."
  (`index.html:85-90`); "This interview's code" shown inside, not in the
  header. Step 2 scope becomes "Which recordings? (usually filled in for you)"
  (`index.html:114-117`); Step 3 scope lives under "Who may enter"
  (`index.html:137`).
- Verified: `ui_after_desktop_light.png` (no session id in first viewport);
  code probe `index.html:85-90,114-117,137`.

### 5. Undiscoverable Hold-to-talk
- Before: bare `Hold to talk` button (disabled until Start), no explanation of
  press-and-hold or the microphone permission (`ui_before_desktop_light.png`).
- After: same button plus persistent hint `id="talkhint"`: "'Hold to talk':
  press and hold the button while you speak, then let go. You will need to
  allow the microphone." (`index.html:83`).
- Verified: `ui_after_desktop_light.png` (hint rendered under the buttons);
  code probe `index.html:83`.

### 6. Empty threads / timeline / map look broken
- Before: "Open threads — No open threads yet.", bare "Timeline" heading with
  no rows, and a large empty bordered Family-map box rendered in the open
  (`ui_before_desktop_light.png`).
- After: all three collapsed into one closed `<details id="learned">`
  `<summary>What we've learned so far (follow-ups, timeline, family map)</summary>`
  (`index.html:91-100`), so the empty states are one line until there is
  content. Rendering code (`renderFacts`/`renderThreads`) unchanged.
- Verified: `ui_after_desktop_light.png` (single collapsed "What we've learned
  so far" row); code probe `index.html:91-100`.

### 7. Mobile input overflow
- Before: fixed `min-width:16rem/24rem/12rem` inline styles on ask/char inputs;
  at 390px width the Question inputs visibly overflow the card
  (`ui_before_mobile_light.png`: "What did she say about the bakery?" and
  "What did you love about the farm?" bleed past the box edge).
- After: global `input, select { max-width: 100%; box-sizing: border-box; }`
  (`index.html:13`) plus `input[type="text"], input:not([type]) { width: 100%;
  max-width: 26rem; }` and `#askq, #charq { width: 100%; max-width: 26rem; }`
  (`index.html:24-25`). Buttons wrap via `nav.modes { flex-wrap: wrap }`.
- Verified: `ui_after_mobile_light.png` (question inputs fit; Step 3 button
  wraps to its own row); code probe `index.html:13,24-25`.
  Residual wrinkle: on the 390px render the Step-1 `Finish` button wraps below
  the disabled `Hold to talk` button rather than staying on one row — cosmetic
  only, no overflow.

### 8. Consent / pause hidden + Withdraw wording
- Before and after: `#consentbox` (`AI reconstruction OK? / Who may access it?
  / Cloned voice OK? / Save wishes / Withdraw`, `index.html:65-73`) and
  `#pause` (`Pause & save`, `index.html:60-64`) remain `hidden` until triggered
  by interview flow — intentionally not in the first-viewport path. No change
  in `bad47d6` (boxes untouched in the diff except being inside the Step 1
  section). `Withdraw` wording (`c-revoke`, `index.html:71,401,561`) kept as-is.
- Verified: code probe only (`index.html:60-73`, `hidden` attributes,
  `postConsent({revoke: true})` wiring at line 401) — post-Start/pause/consent
  states were NOT screenshot-verified (see gaps).

### 9. Buried 50-second tour link
- Before: tour link trailed the session-id line — "Session: s-… · How it works
  (50-second tour)" — easy to skip as metadata (`ui_before_desktop_light.png`).
- After: standalone line under the three-step path with its own spacing class:
  `<p><a class="tour" href="/how-it-works">How it works (50-second tour)</a></p>`
  (`index.html:43`, `.tour` style at line 23).
- Verified: `ui_after_desktop_light.png` and `ui_after_mobile_light.png` (tour
  on its own line under the path sentence); code probe `index.html:23,43`.

### 10. No dark mode
- Before: no dark styles; forced-dark rendering shows dark text on light `#q`
  / `#askbox` greys and washed-out nav (see `ui_before_desktop_dark.png`,
  which renders the old light-only CSS — page stays light).
- After: `color-scheme: light dark` (`index.html:8`) plus a
  `@media (prefers-color-scheme: dark)` block restyling body, `#q`, step nav
  (active `#2b3355`), details, hints, svg, `#askbox`, `#charbox`, links
  (`index.html:26-37`).
- Verified: `ui_after_desktop_dark.png` (dark body, readable prompt box, active
  Step 1 pill, collapsed details) vs `ui_before_desktop_dark.png`; code probe
  `index.html:8,26-37`.
  Residual wrinkle: in the dark screenshot the primary `Start the interview`
  button renders light-grey-on-dark; contrast is acceptable but weaker than the
  light-theme indigo active pill.

## Verification matrix
| Check | Evidence |
|---|---|
| Step 1 desktop light after | `/tmp/ui_after_desktop_light.png` |
| Step 1 desktop dark after | `/tmp/ui_after_desktop_dark.png` |
| Step 1 mobile light after | `/tmp/ui_after_mobile_light.png` |
| Before desktop/mobile light | `/tmp/ui_before_desktop_light.png`, `/tmp/ui_before_mobile_light.png` |
| Before dark (old CSS, light render) | `/tmp/ui_before_desktop_dark.png` |
| Step 2 after | `/tmp/ui_after_step2.png` (DOM-probe render) |
| Step 3 after | `/tmp/ui_after_step3.png` (DOM-probe render) |
| Before source | `git show bad47d6^:index.html` (top 120 lines read) |
| Change scope | `git diff bad47d6^ bad47d6 -- index.html` (full diff read) |
| Lines cited above | `index.html` at HEAD (`grep -n` probes + full read of lines 1–144) |

## Gaps (honest)
1. Post-Start / pause / consent states are code-read only at review time:
   `#pause`, `#consentbox`, `#resumecode` are `hidden` until interview events
   fire; no screenshot exercises them. Wiring (`pausequit`, `c-save`,
   `c-revoke` → `postConsent`) was read in `index.html` but not clicked.
2. Steps 2/3 afters are DOM-probe renders (`ui_after_step2.png`,
   `ui_after_step3.png`), not full click-throughs of the `modes()` switcher
   in a live browser; the `show()` hide/show logic was read, not driven.
3. No live microphone / TTS / server round-trip was run; Ask and
   reconstruction answers, citations, replay, and demo fill were not executed.
4. `ui_before_desktop_dark.png` renders the pre-change page (light CSS) rather
   than a true dark rendering — useful only as a no-dark-support baseline.
5. Mobile-dark pair (`ui_before_mobile_dark.png` / `ui_after_mobile_dark.png`)
   exists on disk but was not opened for this review; dark sign-off rests on
   the desktop-dark pair plus the shared `@media` block.
