# Progress log: run `voice-concierge-2026-10-21`

What this is: the running record of the harness run, **newest entry first**. Every session reads it at startup and
appends its own entry at the top (what it built, what it learned, what the next session must know).

How to read the feature list: `.harness/runs/voice-concierge-2026-10-21/feature_list.json`. Array order is priority
order. A session gets the first feature with `passes: false` whose `after` dependencies pass (no `after` means every
earlier feature). A session may flip only its own feature's `passes`. Each step is checked by a verifier, so do
exactly what the step says, with the names it uses.

How Michael steers: edit `.harness/runs/voice-concierge-2026-10-21/INBOX.md` on this branch. First line
`status: run | pause | stop`; answers go under `## Answers`. Every session reads it at startup.

---
### 2026-10-21 03:10 · V1-01 · passes

- **Changed.** `concierge/departure.py` (88 lines: `DEPARTURE_GRACE_S = 20.0`, `DepartureWatcher` with `start/cancel/
  pending`; `on_left` runs in its own task once the grace ends, so `cancel()` from inside it doesn't cut it short);
  `JournalType` + `"visitor_left"`; `docs/plans/2026-10-21-V1-departure.md`; D16 in `docs/decisions.md` and its
  question in MORNING.md (`test_questions_cover_every_default` asks for one per default). Tests 940 → 952
  (`tests/test_departure.py` 11, `test_journal_takes_a_visitor_left_row`; `test_journal_type_literal_matches_spec_list` updated).
- **Verified.** `check.sh` green, 952 tests, 95 s; departure tests RED (no module) → GREEN; ruff clean.
- **V1-02 must know (new finding, plan (d)).** RoomIO closes the AgentSession itself when the linked participant
  disconnects `CLIENT_INITIATED` (`voice/room_io/room_io.py:457-488`, `RoomOptions.close_on_disconnect=True` by
  default, `room_io/types.py:267`). An unmounting page is exactly that, so with no change a reconnect inside the grace
  finds a closed session. V1-02 must set `close_on_disconnect=False` in `room_start_kwargs`. The `fakes` fixture
  patches `room_start_kwargs` to `{}`, so only a direct test of it catches this. The plan names it
  (`test_room_options_keep_the_session_through_a_disconnect`). The plan's `Closing`/`begin_end`/`end_session(..., leave=)`
  design keeps the closing task out of `tasks`, so its `gather(*tasks)` never waits for itself.
- **Question for Michael.** D16: is 20 s right (10 s frees the address sooner; 30 s is kinder to a slow reload)?
- **Proposed changes.** V1-02 step 2 should also require `RoomOptions(close_on_disconnect=False)` (plan (d));
  without it the grace can't keep a session alive in production.

### 2026-10-21 02:30 · initializer

**Scope.** `docs/specs/2026-10-21-integrated-concierge.md` (read it with `docs/spec.md`, the design it adds to), in
the brief's order: V1 → V2 → V3 → V4 → V5 → V6. 22 features: V1 3 (plan, build, review) · V2 6 (plan, contract +
schema, episodes store, events ring, about_agent + publish points, review) · V3 5 (plan, re-vendor + pack,
instructions + policy check, drift script, review) · V4 4 (runner, scripts + twin, docs, review) · V5 2 (docs, review)
· V6 2 (tool, instructions + eval + review). `after`: V2-01 ← V1, V3-01 ← V2, V4-01 ← V3, V5-01 ← V4, V6-01 ← V3,
V6-02 ← V6-01 + V4 (its eval script needs the V4 runner). Start of run: 940 tests, `.harness/check.sh` green in 107 s.

**Never park (brief).** Michael is asleep. Every open choice has a default in the spec; take it, record it in
`docs/decisions.md` as `D<n> *default*` (next free number is D16; the list reserves D16 grace, D17 contract-v2 picks,
D18 policy finding, D19 drift-not-rebuild, D20 usher; keep that order or renumber consistently and say so here) and
put the question for Michael in your progress entry, not in INBOX.

**Where things live.**
- Session lifecycle: `concierge/session.py` (246 of a 250-line cap; move code out rather than grow it),
  `concierge/session_end.py` (journal_row, write_summary), `concierge/limits.py` (10-minute timer, daily cap,
  `say_and_end(session, line, end, reason)` where `end` is `ctx.shutdown`). The worker entrypoint is
  `concierge/worker.py` (`entrypoint` → `start_session`).
- Contract: `concierge/contract.py` (MemoryPayload, topic and RPC names, 15 KiB cap, `build_memory_payload`),
  `concierge/publish.py` (`publish`, `MemoryPublisher.schedule/final/aclose`), `concierge/rpc.py` (`current_memory`,
  forget_me, get_memory). Schemas: `tests/contract/*.schema.json`, checked with jsonschema in `tests/contract/`.
- Memory: `concierge/store.py` + `store_base.py` + `store_journal.py` + `store_erasure.py` (`_CHILD_TABLES` is the
  erasure list), `concierge/schema.py` (DDL with a version guard; the `created_at` column migration is the pattern),
  `concierge/models.py` (`JournalType` Literal: add new row types there), `concierge/memory_writer.py` (`on_merged`
  callback, `MergeResult` in `merge_result.py`), `concierge/compactor.py` (`applied` counter; the apply point is
  `agent_state_changed` → listening).
- Knowledge and prompt: `knowledge/michael.md` (≤ 1,200 words, every section has a `Source:` line naming a file in
  `knowledge/sources/`), `knowledge/sources/SOURCE.md` (the commit the five portfolio files came from, now `81bb0fc`),
  `concierge/knowledge.py` (`load_pack`, `pack_word_count`), `concierge/prompt.py` (`STATIC_INSTRUCTIONS`,
  `estimate_tokens` = ceil(chars / 3.5), budget 3,000 static + pack). `tests/test_knowledge.py` checks every project
  title, "at <Company>" name, URL and digit-bearing token of the pack against the sources: a new pack sentence with
  a number needs that number in a source file.
- Evals: `concierge/evals/{script,runner}.py` + `evals/memory/*.yaml` + `scripts/eval_memory.py` (the memory tier,
  `--offline` replays recorded ops). The V4 conversation runner is a sibling, not a change to these.
- Fakes: `concierge/testing/fake_llm.py` (FakeLLM scripted replies and tool calls; `respond=` templates),
  `fake_room.py` (a real `rtc.Room` never connected, with a recording `local_participant`: `sent`, `sent_on(topic)`,
  `rpc_handlers`), `recording_session.py` (binds the real AgentSession signatures), `tests/conftest.py` fixtures
  `fakes` (a real AgentSession over FakeLLMs, `room_start_kwargs` patched to `{}`), `recording_session`, `store`, `db`.
- Docs with tests: `tests/test_readme.py` (section order in SECTIONS, cited tests/modules must exist, no unmeasured
  number in Results), `tests/test_morning.py` (12 numbered steps, exact COMMANDS in order, Check/Undo from step 3),
  `tests/test_live_layout.py` (the 4 live tests deselected offline).

**Gotchas a worker must know.**
1. **LiveKit disconnects the room before shutdown callbacks run** (1.8.8 `agents/ipc/job_proc_lazy_main.py`,
   `_shutdown_job`: `await self._room.disconnect()` at ~479, then the `_shutdown_callbacks` loop at ~497). So the
   spec's "final `concierge.memory` before the agent leaves" cannot be sent from `on_shutdown`. V1-02 moves the
   closing work (final extraction, summary, final memory) into `end_session(reason)` that runs before
   `ctx.shutdown(reason)`; `on_shutdown` stays as the fallback (server-side room close) and must be idempotent.
2. **Room events** (`.venv/.../livekit/rtc/room.py` ~56, ~768-775): `participant_disconnected` and
   `participant_connected` deliver a `RemoteParticipant`; read `.identity`. `FakeRoom` is a real `rtc.Room`, so
   `room.emit("participant_disconnected", obj)` reaches handlers registered with `room.on(...)`.
3. **Text path for evals**: `AgentSession.run(*, user_input, input_modality="text")` (`voice/agent_session.py` ~855)
   returns a `RunResult` (`voice/run_result.py`): await it, then read `.events` (`ChatMessageEvent`,
   `FunctionCallEvent`, `FunctionCallOutputEvent`). Nested runs raise. The `fakes` fixture shows how to start a
   session with no room.
4. **Turn path rule**: nothing in a `conversation_item_added` handler awaits store or LLM work;
   `tests/test_critical_path.py` reads the source of the handler path and checks a name list (`MEMORY_WORK`). New
   background work goes through `tasks.track` and the writer's thread (`MemoryWriter.call`).
5. **Journal payloads never carry values** (D8): ids, slots, reasons only. The V2 event ring may show values (they
   are the visitor's own) but it is fed from `MergeResult`, not from journal rows; a gate-rejected value is never
   shown.
6. **Module cap**: `wc -l` of every `concierge/*.py` ≤ 250 (reviews check it). `session.py` is at 246,
   `memory_writer.py` at 250.
7. **Network**: the suite runs offline. The only network a session may use is the V3 clone of the public
   `https://github.com/mh550/portfolio_site` into `$HARNESS_SCRATCH` (never `~/projects/portfolio_site`) and the
   V3-03 policy pages. If the clone fails, keep the vendored files at `81bb0fc`, say so in SOURCE.md and here.
8. **Scratch**: write review diffs and clones to `$HARNESS_SCRATCH/…`, never `/tmp` (last run's C7-05 parked on
   this). Grep-style steps must not match `.harness/` or their own text.
9. **The `llm` tier** (V4): a new pytest marker; `.harness/check.sh` must deselect it (`-m "not live and not llm"`)
   so the suite can never call the API even with a key in the environment. Only Michael runs `-m llm` and `-m live`.
10. **Public repo**: `knowledge/sources/resume-v4.md` carries the spec's §7 resume text, which has no phone number;
    never add one. No visitor data, hostnames or IPs anywhere.
11. The phrase "specs in, verified milestones out" is not in README.md or MORNING.md today (only in the spec); V4-03
    adds the test that keeps it out.

**Questions for Michael** (defaults taken; details go in `docs/decisions.md`):
- D16: 20 s departure grace, as the spec says. Shorter (10 s) frees the address faster but a slow reload re-creates
  a session.
- Closing order: the final extraction and summary (up to ~20 s) now run before the agent leaves the room, so after
  the ten-minute goodbye the agent lingers silently for a few seconds. OK, or should the final memory be skipped on
  the cap path?
- V3: the resume wins over the vendored portfolio files where they differ, and two new source files
  (`resume-v4.md`, `concierge.md`) join `knowledge/sources/`. OK?
- V4: the `llm` tier is deselected from `.harness/check.sh`; run it as `pytest -m llm` or
  `scripts/eval_conversation.py` (MORNING.md step). OK?
- V6: hrefs come only from `projects.ts` slugs; the concierge's own section has no page, so no href. Does `/talk`
  or a concierge page exist to point at?
