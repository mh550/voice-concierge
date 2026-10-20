# voice-concierge

A voice agent for Michael Herron's portfolio site that talks about his work and remembers returning visitors, built on
LiveKit Agents 1.8 (Python). The worker runs on Michael's home box and connects out to LiveKit Cloud. Nothing here is
live until Michael starts the worker. **Spec: `docs/spec.md`** (read it first; §6 is a contract shared word for word
with the portfolio site's page).

## Code rules
- Python 3.12, a venv in `.venv`, dependencies pinned in `pyproject.toml` (`livekit-agents~=1.8` and the plugins it
  needs). No other services: memory is SQLite (`concierge/store.py`).
- **Never guess a LiveKit API.** Read the installed package's source in `.venv` (or docs.livekit.io) and match it.
  Fakes (the fake LLM, fake rooms) mirror the real classes and event shapes, read from that source.
- Memory work never runs on the turn path: nothing in a user-turn handler awaits extraction or a store write
  (spec §4.4; a test enforces it).
- Anything said about Michael comes from `knowledge/michael.md`, which is built only from `knowledge/sources/`
  (spec §4.1). Never read the live `~/projects/portfolio_site`: another run is changing it.
- Small modules, type hints throughout, pydantic for anything serialized.

## How to verify
- Suite: `.harness/check.sh`, which runs `pytest -m "not live" -q`, ruff if present, and `compileall`. It is offline:
  no network, no keys.
- Live evals (`pytest -m live`) need LiveKit keys. **Only Michael runs them**, in the morning (`MORNING.md`).

## Decisions and plans
- Spec: `docs/spec.md` (D1–D6 Michael's, B1–B12 the builder's calls). Decisions: `docs/decisions.md`. A new default is
  recorded there as `D<n> *default*`.
- Background research (why each memory practice): `docs/background/memory-research.md`.
- Plans: `docs/plans/<date>-<milestone>-<topic>.md`.

## Off-limits
- **Secrets.** Never read, print or source `~/.config/voice-concierge/env`, any `.env`/`.env.local`, or `~/.livekit/` (the `lk` CLI config holds the API secret). Never run `lk`. The worker reads that env
  file only when Michael runs `scripts/run-worker.sh` or the systemd unit.
- **Build-only.** Never start the worker against LiveKit Cloud, run `pytest -m live`, or install, enable or start the
  systemd unit. Write the unit file in `deploy/` only.
- Never write outside this worktree and your scratch directory. `~/projects/portfolio_site` and the other projects are
  not yours.
- This repo is **public**. Commit no secrets, no personal data beyond what `knowledge/sources/` already publishes, no
  internal hostnames or IPs, and no visitor data (`*.db` is gitignored).
