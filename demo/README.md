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

Click any fact's ▶ replay to hear (silence of) the exact clip slice it
cites. The family map fills in with Aunt Rosa and Grandpa Emil via the
documented stub heuristic; the live Fireworks path extracts people with
JSON mode instead (see `mock_llm_turn` docstring in `server.py`).
