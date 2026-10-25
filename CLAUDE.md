# voice-concierge

A voice agent for Michael Herron's portfolio site that talks about his work and remembers returning visitors, built on
LiveKit Agents 1.8 (Python). The worker runs on Michael's home box and connects out to LiveKit Cloud. Nothing here is
live until Michael starts the worker. **Spec: `docs/spec.md`** (read it first; §6 is a contract shared word for word
with the portfolio site's page).

## Code rules
- Python 3.12 in `.venv`, dependencies pinned in `pyproject.toml`. No other services: memory is SQLite.
- **Never guess a LiveKit API.** Read the installed package's source in `.venv` (or docs.livekit.io) and match it.
  Fakes (the fake LLM, fake rooms) mirror the real classes and event shapes, read from that source.
- Memory work never runs on the turn path: nothing in a user-turn handler awaits extraction or a store write
  (spec §4.4; a test enforces it).
- Anything said about Michael comes from `knowledge/michael.md`, which is built only from `knowledge/sources/`
  (spec §4.1, B8), never from the live portfolio checkout.
- Small modules, type hints throughout, pydantic for anything serialized.

## How to verify
- Suite: `.harness/check.sh`, which runs `pytest -m "not live and not llm" -q`, ruff if present, and `compileall`.
  It is offline: no network, no keys.
- Live evals (`pytest -m live`) need LiveKit keys; the llm tier (`pytest -m llm`, `scripts/eval_conversation.py`
  without `--offline`) needs the LLM key. Both spend API credit (see Off-limits); `MORNING.md` is the runbook.

## Decisions and plans
- Decisions: `docs/decisions.md`, the current rule set (D1–D6 Michael's, B1–B12 the builder's calls, then D7 on).
  Spec: `docs/spec.md`, and `docs/specs/2026-10-21-integrated-concierge.md` for V1–V6.
- Background research (why each memory practice): `docs/background/memory-research.md`.
- Plans: `docs/plans/<date>-<milestone>-<topic>.md`.

## Where things go
- What happened, what you tried, what failed → your run entry (`entry.json`); outside a run, the PR description.
- A decision → `docs/decisions.md`, the next free `D<n>` (`D<n> *default*` for a default). An overturned one is rewritten
  in place with one `Updated in place <date>: …` line, never a new entry beside a dead one.
- A fact a fresh session would otherwise rediscover → one line in `## Gotchas`, edited in place (verify and retro
  sessions: your entry's `discoveries`, affecting `"run"`).
- A run's scope (what to build or drop) → its brief, never this file. How to work here → Michael's: say it in `proposed_changes`.
- Anything the code, git or the suite can tell → nowhere (no test counts, file lists or constants).

## Gotchas
- `concierge/*.py` modules stay at or under 250 lines (review steps check `wc -l`); several sit at the cap, so new code
  goes in a new module (voice-concierge-2026-10-20 2026-10-20)
- Review diffs and scratch clones go in `$HARNESS_SCRATCH`, never `/tmp/voice-concierge/` (not writable) or the repo
  (voice-concierge-2026-10-20 2026-10-20)
- A step may name a decision number that is taken (V3 and V6 named D18–D20): take the next free `D<n>` and quote the
  step's name in the heading (voice-concierge-2026-10-21 2026-10-21)
- `FakeLLM` uses one script entry per `chat()`, and the greeting is a session's first call: a session test's script
  starts with the greeting reply (voice-concierge-2026-10-20 2026-10-20)

## Off-limits
- **Secrets.** The worker's env file (`~/.config/voice-concierge/env`) and `~/.livekit/` hold secrets: never print or
  source them.
- **API credit.** `pytest -m live`, `pytest -m llm`, `scripts/run-worker.sh`, the systemd unit and `lk` use LiveKit
  Cloud or the LLM and spend API credit: run them only when the task asks. Write the unit file in `deploy/`; installing
  or enabling it is Michael's.
- This repo is **public**. Commit no secrets, no personal data beyond what `knowledge/sources/` already publishes, no
  internal hostnames or IPs, and no visitor data (`*.db` is gitignored).
