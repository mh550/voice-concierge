#!/usr/bin/env bash
# Start the concierge worker (Michael runs this, or the systemd unit in deploy/ does; plan C7 "run-worker.sh").
#   scripts/run-worker.sh [start|dev|console|connect|download-files|--help]   # default: start
# Loads ~/.config/voice-concierge/env if it exists (plain NAME=value lines), checks the keys the configured providers
# need, then execs the worker. It prints names, never values.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
f="$HOME/.config/voice-concierge/env"
if [[ -f $f ]]; then set -a; . "$f"; set +a; fi
need=(LIVEKIT_URL LIVEKIT_API_KEY LIVEKIT_API_SECRET)
if [[ ${CONCIERGE_LLM_PROVIDER:-anthropic} == openrouter ]]; then need+=(OPENROUTER_API_KEY); else need+=(ANTHROPIC_API_KEY); fi
if [[ ${CONCIERGE_SPEECH:-inference} == deepgram ]]; then need+=(DEEPGRAM_API_KEY); fi
for name in "${need[@]}"; do
  if [[ -z ${!name:-} ]]; then echo "run-worker: $name is not set (expected in $f)" >&2; exit 1; fi
done
[[ -x .venv/bin/python ]] || { echo "run-worker: no .venv here; run .harness/init.sh first" >&2; exit 1; }
exec .venv/bin/python -m concierge.worker "${@:-start}"
