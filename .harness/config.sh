# .harness/config.sh — voice-concierge settings for the agent harness (~/projects/agent-harness).
# The run's scope is the spec + brief passed to `harness start`; this file is only what differs from defaults.
POLICY=build-only
CHECK_CMD=".harness/check.sh"          # offline: pytest -m "not live" + ruff (if installed) + compileall
INIT_CMD=".harness/init.sh"            # venv + pinned deps (once pyproject.toml exists)
BASE_PORT=7841
HOURS=14
MAX_ATTEMPTS=2
AGENT_SETTINGS=.claude/settings.json
