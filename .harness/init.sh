#!/usr/bin/env bash
# .harness/init.sh — run by the harness before every session: a venv with the pinned dependencies, once pyproject.toml
# exists (C1 creates it). Idempotent; reinstalls only when pyproject.toml changed. No server to start.
set -euo pipefail
cd "$(dirname "$0")/.."
SCRATCH=${HARNESS_SCRATCH:-/tmp/voice-concierge}
mkdir -p "$SCRATCH"
if [[ ! -f pyproject.toml ]]; then echo "no pyproject.toml yet (C1 creates it): nothing to install"; exit 0; fi
[[ -x .venv/bin/python ]] || python3 -m venv .venv
stamp=.venv/.pyproject.sha
want=$(sha256sum pyproject.toml | cut -d' ' -f1)
if [[ "$(cat "$stamp" 2>/dev/null)" != "$want" ]]; then
  .venv/bin/pip install -q --upgrade pip >/dev/null
  .venv/bin/pip install -q -e ".[dev]" && echo "$want" > "$stamp"
fi
.venv/bin/python -c "import livekit.agents as a; print('livekit-agents', a.__version__)" 2>/dev/null || echo "livekit-agents not installed yet"
