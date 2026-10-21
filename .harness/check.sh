#!/usr/bin/env bash
# .harness/check.sh — the offline suite: no network, no keys. pytest (not live, not llm) + ruff (if in the venv) + compileall.
set -uo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f pyproject.toml ]]; then echo "no pyproject.toml yet: nothing to check"; exit 0; fi
PY=.venv/bin/python; [[ -x $PY ]] || PY=python3
rc=0
$PY -m compileall -q concierge scripts tests >/dev/null 2>&1 || { echo "compileall failed"; rc=1; }
if [[ -x .venv/bin/ruff ]]; then .venv/bin/ruff check . || rc=1; fi
$PY -m pytest -m "not live and not llm" -q "$@" || rc=1
exit $rc
