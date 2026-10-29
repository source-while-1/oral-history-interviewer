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
```

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
