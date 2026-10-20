# voice-concierge

A voice agent that remembers returning visitors, built on LiveKit Agents. Being built; the design is in
[`docs/spec.md`](docs/spec.md).

## Mapping onto Agents 2.0

This is LiveKit Agents 1.8 code. The memory is shaped like 2.0's thread, lane, journal and fence so it maps across;
the store is SQLite in WAL mode (`concierge/store.py`, design in
[`docs/plans/2026-10-20-C2-store.md`](docs/plans/2026-10-20-C2-store.md)).

| 2.0 | Here (1.8) | Where it differs |
|---|---|---|
| thread | `threads` row, one per visitor, `visitor_id` unique (2.0's `scope`); `attributes` JSON holds the visit count | 2.0 finds a thread by id; here the visitor id from the page is the key, and `get_or_create_thread` at session start is the only call that creates one |
| lane state | `state` row: `VisitorState` (pydantic, at most 8 KB), derived from the valid rows in `facts`, which keep provenance (`source`, `channel`, `turn_id`) and validity (`valid_from`, `valid_to`, `superseded_by`) | one agent, so one lane; 2.0 caps state at 64 KiB |
| journal | `journal` table, append-only: `session_started`, `user_turn`, `fact_added`, `extraction_ran`, … with `ts_ms` and a JSON payload | rows are keyed by `session_id`, not a lane and run id |
| fence (`BEGIN IMMEDIATE` + version) | every write to a thread's rows is one `BEGIN IMMEDIATE` transaction that checks and bumps `threads.version`; a stale writer gets `VersionConflict`, and `apply_fact_ops` reloads and re-applies its delta ops (up to 5 attempts) instead of overwriting | 2.0 conditions each commit on the version **and** a lease token. 1.8 has no lease, so two live sessions for one visitor can interleave turns: each write lands, but neither session waits for the other's turn to finish |
| channels | voice and typed text (`lk.chat`) feed one session and one thread; each fact records its `channel` | the agent knows the channel; 2.0 hides it from the handler |
| `idle_ttl` | `threads.idle_ttl_s` (30 days); `purge_idle` deletes an idle thread with all its rows, `forget_me` erases a visitor on request and `VACUUM`s | the worker, not the platform, runs the purge at start and daily (wired in C6) |

## How to run

Michael runs the worker on his home box with `scripts/run-worker.sh` (added in C7), which reads the env file
`~/.config/voice-concierge/env` and starts `python -m concierge.worker start`. That file holds `LIVEKIT_URL`,
`LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` and `ANTHROPIC_API_KEY` (plus `OPENROUTER_API_KEY` only with
`CONCIERGE_LLM_PROVIDER=openrouter` and `DEEPGRAM_API_KEY` only with the speech fallback); the names are listed, empty, in `.env.example`, and no values are ever committed. The offline suite needs no
keys: `.harness/check.sh`.
