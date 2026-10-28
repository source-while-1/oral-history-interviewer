# Oral History Interviewer

A browser-based voice interviewer that turns family stories into a citable
timeline and family map.

- Voice loop: TTS question → push-to-talk answer → browser STT → Fireworks
  LLM next question + JSON fact extraction.
- Every fact cites `clip_id` + `start`/`end`.
- Local disk storage only (`recordings/`). No Baseten, no Modal.

See [SPEC.md](./SPEC.md) and [DECISIONS.md](./DECISIONS.md).

## Quickstart (placeholder — backend lands next)

```sh
cp .env.example .env   # then fill in keys locally; never commit .env
```

## Layout (planned)

- `SPEC.md`, `DECISIONS.md` — product + decisions
- `recordings/` — local audio clips (gitignored)
