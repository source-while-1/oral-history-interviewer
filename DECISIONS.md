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

## 5. Backend: FastAPI preferred, stdlib fallback
- Why: FastAPI gives typed routes + static serving in few lines; if the
  environment lacks it, `http.server` stdlib covers v1 needs. Either way the
  contract is: serve `/`, accept turn uploads, append JSONL, call Fireworks.
  Final choice recorded at backend implementation time.
