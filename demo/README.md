# Synthetic demo (no real people, no real audio)

`demo/` is a self-contained backup demo for the hackathon: if the venue
Wi-Fi fails or no teammate is available, replay this instead of a live
interview.

- **Everything here is fictional.** All names, places, and events in
  [script.json](script.json) were invented for the demo. The "audio clips"
  are generated silence sized to the segment timestamps — the point being
  replayed is the *linkage* (fact → clip slice), not the sound.
- [replay.py](replay.py) feeds the script through a local `MOCK_LLM=1`
  server exactly like the browser would after speech-to-text, then keeps
  serving so the session replays with audio, timeline, and family map.

Run it:

```bash
python3 demo/replay.py
# open http://127.0.0.1:8000/?session=demo-synthetic
# resume story: http://127.0.0.1:8000/?session=demo-resumed
```

The script is a 4-turn arc (still all-fictional): turn 1 introduces Aunt
Rosa (opens thread `th-aunt-rosa`, next question asks about her), turn 2
introduces Grandpa Emil (opens `th-grandpa-emil`), turn 3 re-mentions Aunt
Rosa (covers `th-aunt-rosa`), and turn 4 is a short wrap-up ("Not much
more to say today.", no names; `pause_suggested` turns true via the
MOCK shortening proxy — 6 words vs a ~17-word baseline — while Grandpa
Emil stays open). The console prints
`threads_opened`/`threads_covered`/`pause_suggested` per turn so the
open→covered arc and the pause nudge are visible without a browser.

Session 2 (`demo-resumed`) is the resume story: its first turn sends
`resume_from=demo-synthetic`, so the still-open Grandpa Emil thread is
copied over and the opening question re-opens it; re-mentioning him
covers it. Same mechanism as the UI's "Resume a session" box, which sends
`resume_from` on the first turn. `GET /api/threads?session_id=...`
returns the saved thread list (confined + corrupt-tolerant like
`/api/facts`); the `?session=` replay page renders it under "Open
threads" too.

Also in this folder:

- `how-it-works.html` — served at `/how-it-works`; auto-playing 7-scene
  web tour of one turn (talk → think → map → saved facts file → replay,
  same fictional script).
- `make_video.py` → `demo.mp4` — the tour as a 56s 720p video. Needs Pillow
  in the project env: `python3 -m venv .venv && .venv/bin/pip install pillow`,
  then `.venv/bin/python demo/make_video.py`. The server and test suites stay
  stdlib-only; Pillow is only for the optional video render.
- v3 themes: `.venv/bin/python demo/make_video_v2.py --theme light|dark`
  renders `demo_v3_light.mp4` / `demo_v3_dark.mp4` (section kickers, footer
  progress, dimmed basemap in dark). `--preview` writes one PNG per scene to
  `/tmp/v3prev_<theme>` for approval before the full render.
- v4: same scenes, designed — vendored IBM Plex Sans (`assets/fonts/`, OFL),
  sticker portraits (white ring + hairline black outline, fixed dark details),
  padded label chips, Samantha voiceover muxed per scene
  (`--out demo/demo_v4_light.mp4`). Build fails fast on narration overrun,
  missing voice, or bad mux (audio stream 90s, sane levels).
- v5: Plex Serif display titles + letterspaced kickers; voice is edge-tts
  `en-US-AvaNeural` (no key needed, network at render time).
  `.venv/bin/pip install edge-tts`, then render `--out demo/demo_v5_light.mp4`.
  Serif cuts live in `assets/fonts/` next to the Sans variable font.
- v6: the adaptive story as `demo_v6_light.mp4` / `demo_v6_dark.mp4`
  (8 scenes, 90s, 720p30, h264 + AAC; v5 files untouched). Scene list:
  title; threads (Open-threads panel: Aunt Rosa opens turn 1, Grandpa
  Emil opens turn 2, Rosa covered on the turn-3 re-mention); keep-going
  (turn counter passes the old 3-round limit to 6 while threads stay
  open); pause (tiredness cue "I'm tired, let's pick this up another
  time" + Keep going / Pause & save); resume (code `demo-synthetic` →
  `resume_from` carries 1 open thread + 7 saved facts into
  `demo-resumed`, opening question re-opens Grandpa Emil); map
  (fiction banner + OSM credit kept); payoff (4 turns / 8 segments /
  7 facts / 2 opened · 1 covered · 1 carried); outro. Counts come from
  `demo_stats()` in the renderer, which replays
  [`script.json`](script.json) with the server stub's Title-Name rule,
  so the video cannot drift from the demo it depicts. Narration is a
  new 183-word Ava script for this story (existing 180–220 overrun
  gate unchanged). `--preview` writes to `/tmp/v6prev_<theme>`.
- v4 (designed + voiced): same script renders `demo_v4_light.mp4` /
  `demo_v4_dark.mp4` (90s, 720p30, h264 + AAC). New in v4: vendored
  IBM Plex Sans (`assets/fonts/IBMPlexSans-Variable.ttf`, Regular body /
  Bold titles via the wght axis; system fonts then PIL default as fallback;
  OFL licensed — see below), sticker portraits (white ring + thin black
  outer ring, fixed dark ink on both themes), chip-backed labels with 12px+
  clearances, and a ~205-word Samantha voiceover (`say -v Samantha`, one
  block per scene padded/trimmed to its scene, muxed AAC). `--preview`
  writes to `/tmp/v4prev_<theme>`; `--no-audio` skips the voiceover.
- Font license: IBM Plex Sans is © IBM and licensed under the SIL Open
  Font License 1.1 (`assets/fonts/OFL.txt` source note; upstream:
  https://github.com/google/fonts/tree/main/ofl/ibmplexsans). Keep the
  vendored file committed so renders stay offline and reproducible.
- `make_video_v2.py` → `demo_v2.mp4` — the full 3-turn story as a 90s
  720p30 video (title, talk, family graph, map, saved facts file, payoff,
  outro). Preview one frame per scene first:
  `.venv/bin/python demo/make_video_v2.py --preview` (writes `/tmp/v2prev/`).
- `assets/basemap_ohio.png` — vendored map tiles around Columbus, Ohio
  (z11, fetched once from OpenStreetMap; the v2 renderer works offline from
  this file and fails fast with a clear error when it is missing). Map
  tiles: © OpenStreetMap contributors. Every map frame is labeled
  "Fictional places — illustrative": the geography is real, the three pins
  (family farm, red barn, county fairgrounds) are invented.

Click any fact's ▶ replay to hear (silence of) the exact clip slice it
cites. The family map fills in with Aunt Rosa and Grandpa Emil via the
documented stub heuristic; the live Fireworks path extracts people with
JSON mode instead (see `mock_llm_turn` docstring in `server.py`).
