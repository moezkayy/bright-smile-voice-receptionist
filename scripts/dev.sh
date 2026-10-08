#!/usr/bin/env bash
# Real mode: clinic API + public HTTPS tunnel + point the agent's tools at it.
#   scripts/dev.sh          # re-point existing tools at the new tunnel URL
#   scripts/dev.sh --full   # full sync: secret, knowledge base, tools and agent
# Needs: .venv, ELEVENLABS_API_KEY in .env, and cloudflared (bin/cloudflared or on PATH).
set -euo pipefail
cd "$(dirname "$0")/.."

CF=bin/cloudflared
for c in "$(command -v cloudflared || true)" "$HOME/.local/bin/cloudflared" /opt/homebrew/bin/cloudflared; do
  [ -n "$c" ] && [ -x "$c" ] && CF=$c && break
done
[ -x "$CF" ] || { echo "cloudflared not found (expected bin/cloudflared)"; exit 1; }

# The API must know the tool secret before it starts, so create it first if needed.
grep -q '^TOOL_SECRET=.' .env 2>/dev/null || .venv/bin/python -c "import sys; sys.path.insert(0, 'scripts'); from sync_agent import ensure_tool_secret; ensure_tool_secret()"

.venv/bin/uvicorn receptionist.server:app --app-dir src --port 8000 --log-level warning --reload --reload-dir src &
API_PID=$!
LOG=$(mktemp)
"$CF" tunnel --no-autoupdate --url http://localhost:8000 >"$LOG" 2>&1 &
CF_PID=$!
trap 'kill $API_PID $CF_PID 2>/dev/null' EXIT

echo -n "Opening tunnel"
for _ in $(seq 1 30); do
  URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -1 || true)
  [ -n "$URL" ] && break
  echo -n "."; sleep 1
done
echo
[ -n "${URL:-}" ] || { echo "Tunnel did not start:"; cat "$LOG"; exit 1; }

# Wait until the tunnel actually serves the API, then re-point the tools.
for _ in $(seq 1 20); do curl -sf "$URL/health" >/dev/null && break; sleep 1; done
if [ "${1:-}" = "--full" ]; then SYNC_ARGS=(); else SYNC_ARGS=(--tools-only); fi
PUBLIC_BASE_URL="$URL" .venv/bin/python scripts/sync_agent.py "${SYNC_ARGS[@]+"${SYNC_ARGS[@]}"}"

echo
echo "Dashboard: http://localhost:8000"
echo "Tools:     $URL/tools/*"
wait $API_PID
