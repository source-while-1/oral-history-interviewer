#!/bin/bash
# Share the fictional demo publicly (read-only) via a cloudflared tunnel.
#
# Starts the server with DEMO_MODE=1 (replay-only: no new interviews, no
# consent writes, no recording) and MOCK_LLM=0 (real Fireworks answers over
# the fictional demo session), bound to 127.0.0.1, then opens a
# `cloudflared tunnel --url` to it and prints the public URL.
# Both processes stop on Ctrl-C.
#
# Usage: ./scripts/share.sh [port]
#   Needs FIREWORKS_API_KEY in the environment (or .env); the server reads
#   it for the live ask/character calls. Never commit a key.
set -euo pipefail

PORT="${1:-${PORT:-8000}}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Password gate: refuse to share publicly without DEMO_PASSWORD (env or .env).
# The server requires the same value to mint session cookies for every route.
if [ -z "${DEMO_PASSWORD:-}" ] && [ -f "$ROOT/.env" ]; then
  _pw="$( { grep -E '^(export[[:space:]]+)?DEMO_PASSWORD=' "$ROOT/.env" || true; } | tail -n 1 | cut -d= -f2-)"
  _pw="${_pw%$'\r'}"
  case "$_pw" in
    \"*\") _pw="${_pw#\"}"; _pw="${_pw%\"}" ;;
    \'*\') _pw="${_pw#\'}"; _pw="${_pw%\'}" ;;
  esac
  DEMO_PASSWORD="$_pw"
fi
if [ -z "${DEMO_PASSWORD:-}" ]; then
  echo "error: DEMO_PASSWORD is not set." >&2
  echo "Set it in the environment or in $ROOT/.env, then re-run." >&2
  echo "(See .env.example for the placeholder; never commit the real value.)" >&2
  exit 1
fi
export DEMO_PASSWORD

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "error: cloudflared is not installed." >&2
  echo "Install it with: brew install cloudflared" >&2
  exit 1
fi
if [ ! -f "$ROOT/server.py" ]; then
  echo "error: run from the repo checkout (expected $ROOT/server.py)." >&2
  exit 1
fi

export DEMO_MODE=1 MOCK_LLM=0 PORT
echo "Starting replay-only demo server on http://127.0.0.1:$PORT ..."
echo "(DEMO_MODE=1 MOCK_LLM=0 — fictional demo session only, writes blocked)"
# No subshell: $! must be the python PID itself, or cleanup orphans it.
cd "$ROOT"
python3 server.py &
SRV=$!
cleanup() {
  kill "$SRV" 2>/dev/null || true
  wait "$SRV" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Wait for the local server before opening the tunnel.
for _ in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$PORT/" >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done

echo "Opening public tunnel (Ctrl-C stops the server and the tunnel) ..."
# Not exec: the EXIT trap must survive to stop the server, which (as a
# background job) ignores the Ctrl-C SIGINT.
cloudflared tunnel --url "http://localhost:$PORT"
