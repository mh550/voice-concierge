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
### 2026-10-21 05:05 · V2-01 · passes

- **Changed.** `docs/plans/2026-10-21-V2-contract-v2.md`: the §2 v2 body word for word, a key-by-key model table, the
  source of every field, the publish points (compaction is new), the 15 KiB size rule, the schema change, the
  `visit_summaries` migration (schema v3, one `CREATE TABLE` statement like `MIGRATIONS[2]`), the `_CHILD_TABLES`
  erasure change, and test names for V2-02..V2-05. `docs/decisions.md` D17 *default*; MORNING.md asks D17. Tests 972 → 972.
- **Verified.** Each §2 line found verbatim in the plan (script); every fixed event line passes `check_text`;
  the worst-case body measured at 16,671 bytes (ASCII) > 15,360, so the trimmer stays; `check.sh` green, 972 tests.
- **Next session must know.** `session_end.py` and `memory_writer.py` are at 250 lines: V2-03 moves `write_summary`
  to `concierge/summary_step.py`; the ring reaches the tools via `ConciergeAgent(events=)`. `MergeResult` has ids only:
  V2-04 adds `MergeResult.changes` (slot, value). The `begin_visit` task must be created before the start
  `publisher.schedule()` (writer executor order). V2-02 has no episodes/ring yet: events come in as `events=`.
- **Question for Michael.** D17: should "Took notes in the background" show on every run, even with no change? Should
  an episode carry the rolling summary (default) or a per-visit one?
- **Proposed changes.** V2-05's size test says episode summaries of 400 characters; stored summaries go to 500
  (`SUMMARY_CAP`). The plan adds a multibyte test too; the step could say 500.

### 2026-10-21 04:20 · verify V1

| Feature | Step | What you ran or read | What you saw | Holds |
|---|---|---|---|---|
| V1-01 | 1 | Read docs/plans/2026-10-21-V1-departure.md; opened .venv livekit at each quoted line (room.py:55-57, 768-775; participant.py:164; job_proc_lazy_main.py:477,479,497; job.py:871) | All quotes match the source at those lines. Plan names end_session in concierge/session_end.py, runs while connected, then ctx.shutdown, and lists the V1-02 test names | yes |
| V1-01 | 2 | Read docs/decisions.md:227 'D16 *default*' | 20 s DEPARTURE_GRACE_S, why (reload/remount reconnects with the same identity), rejected: ending at once and waiting for the cap, and a question for Michael | yes |
| V1-01 | 3 | Read concierge/departure.py | DEPARTURE_GRACE_S=20.0; DepartureWatcher(room, visitor_identity, on_left, grace_s, join_grace_s) (one extra optional arg from V1-03), start() registers both events via room.on, idempotent cancel(), pending property; handlers are plain defs | yes |
| V1-01 | 4 | Read tests/test_departure.py and ran it (157 pass across the V1 files) | test_the_visitor_leaving_calls_on_left_once_after_the_grace, ..returning_inside_the_grace_cancels_it (pending false), test_another_participant_leaving_starts_nothing, test_cancel_during_the_grace_stops_on_left, test_two_disconnects_in_a_row_start_one_grace: asserts match the step | yes |
| V1-01 | 5 | grep models.py, tests/test_store.py | JournalType includes 'visitor_left' (models.py:21); test_journal_takes_a_visitor_left_row asserts the row is journaled | yes |
| V1-01 | 6 | `.harness/check.sh` | exit 0; 972 passed, 4 deselected | yes |
| V1-02 | 1 | Read concierge/session_end.py; tests test_end_session_runs_its_work_once, test_two_ends_starting_in_the_same_tick_run_the_work_once | Closing.ending makes the work run once; cancels timer and watcher, compactor.aclose, writer.flush, write_summary (not erased/no user turn), session_ended, final memory via publisher.schedule+idle (a deliberate change: not publisher.final, review I1), then end(reason); shut_down calls end_session(leave=False) and closes the store last. Test asserts one summary, one session_ended, one shutdown | yes |
| V1-02 | 2 | Read concierge/session.py:130-155; test_the_time_limit_ends_through_end_session, test_the_daily_cap_ends_through_end_session | DepartureWatcher started after ctx.connect for every session; on_left -> end_session('visitor left', left_grace_s) which journals visitor_left; caps use begin_end, final memory sent before shutdown (ending.memory_sent); forget_me ends via begin_end (changed in V1-03, still erased with no summary) | yes |
| V1-02 | 3 | Read the four tests in tests/test_session.py:501-575 and ran them | Leaving: shutdown once with 'visitor left', rows [visitor_left, session_ended]; returning: no shutdown or visitor_left after 3x grace; other participant: nothing; final memory sent before shutdown, schema-validated, carries Acme and summary | yes |
| V1-02 | 4 | `git diff 21905a7..HEAD -- tests/test_critical_path.py`; `wc -l concierge/session.py` | Empty diff (unchanged), test_critical_path passes; session.py is 219 lines | yes |
| V1-02 | 5 | Read README.md:155-162; grep README.md and MORNING.md | No-lease bullet says 20 s wait for a reconnect, then saves notes and leaves, address freed in about 30 s. README line 'sooner when the visitor leaves'. No remaining 'runs on to the cap' text in either file | yes |
| V1-02 | 6 | `.harness/check.sh` | exit 0; 972 passed | yes |
| V1-03 | 1 | `git diff 21905a7..HEAD --stat`; ls scratch; read plan '## Review' | 21905a7 is the parent of V1-01; scratch review-V1.diff exists; Review notes with Critical/Important/Minor and file:line/test refs are in the plan | yes |
| V1-03 | 2 | Read the Review RED lists; ran test_departure/test_session/test_critical_path/test_limits | Each Important lists a RED test and reason; covers cap/departure/forget_me race, departure during start/preload (join grace, closing.stopped), no handler awaiting store (test_critical_path green); 157 pass | yes |
| V1-03 | 3 | Read Simplification pass; `wc -l concierge/*.py` | enforce_daily_cap, end=None paths, dead _EVENTS removed; max 250 (session_end.py, memory_writer.py) | yes |
| V1-03 | 4 | Read progress.md V1-03 entry; git log | States tests 940 -> 972 (commit messages 940->952->963->972 agree) and the final memory is sent before ctx.shutdown | yes |
| V1-03 | 5 | `.harness/check.sh` | exit 0; 972 passed in 105 s | yes |

17 steps, 17 hold, 0 fail. No feature flipped.

### 2026-10-21 03:45 · V1-03 · passes

- **V1 as a whole.** Tests 940 before V1 → 972 after (V1-01 +12, V1-02 +11, V1-03 +9). Design fact: every end runs
  its closing work once, while the room is still connected, and sends the final `concierge.memory` before
  `ctx.shutdown(reason)`, because the job disconnects the room before its shutdown callbacks run
  (job_proc_lazy_main.py:477-497). The ends are the departure, both caps and forget_me. A server-side close runs the
  same work in `on_shutdown`, with no final send.
- **Changed (V1-03).** Opus review of `$HARNESS_SCRATCH/review-V1.diff` (1362 lines): no Critical, 3 Important, 6
  Minor, all fixed test-first. Notes are under "## Review" in `docs/plans/2026-10-21-V1-departure.md`.
  - I1: `JOIN_GRACE_S = 60.0` for a visitor not in `room.remote_participants` when the watch starts.
  - I2: forget_me ends through `begin_end`, and `start_session` checks `closing.stopped` after `session.start` and
    after the late count: no greeting, timer or cap line after an end.
  - I3: the closing waits for a forget_me in flight before it leaves.
  - Simplification: `enforce_daily_cap` and the `end=None` paths removed; `visitor_left` folded into
    `end_session(..., left_grace_s=)`.
- **Verified.** `check.sh` green, 972 tests, 102 s; ruff clean; the V1 test files 3x in a row green. Every
  `concierge/*.py` is ≤ 250 lines (`session_end.py` 250, `session.py` 219).
- **Next session must know.** `FakeRoom.emit` now keeps `remote_participants`. A session test whose visitor should be
  present uses `seated_room()`: an empty room starts the 60 s join grace, which `shutdown` cancels.
- **Question for Michael.** D16, extended: is 60 s right for a visitor not yet in the room when the watch starts (as
  well as the 20 s departure grace)?
- **Proposed changes.** None.

### 2026-10-21 02:52 · V1-02 · passes

- **Changed.** `concierge/session_end.py` (98 → 249 lines): `Closing`, `begin_end`, `end_session(closing, reason, *,
  leave=True)` (one `ending` task outside `tasks`, so racing ends run the work once), `visitor_left`, `shut_down` (the
  old on_shutdown body; `SHUTDOWN_WORK_S` moved here). `concierge/session.py` (246 → 210): a `DepartureWatcher` right
  after `ctx.connect()`, both caps end through `begin_end`, `RoomOptions(close_on_disconnect=False)`. README "No lease"
  bullet. Tests 952 → 963 (`tests/test_session.py` +11; `until`/`emit_add` now in `concierge/testing/sessions.py`).
- **Verified.** `check.sh` green, 963 tests, 101 s; ruff clean; `test_critical_path.py` unchanged and green. The new
  tests were RED first (no `end_session`; then three more RED for the review's findings).
- **Review (Opus, diff in scratch).** No Critical. Fixed test-first: I1 forget_me during a cap's closing send could
  leave the erased memory last; I2 the AgentSession kept answering after the time-up line (closing now closes it
  first); visitor_left written outside the one run. Notes in the plan's "V1-02 as built".
- **V1-03 must know.** Open: I3, a visitor who leaves during `ctx.connect()`/the preload or never joins is never
  seen to leave (the watcher only subscribes). Fixing it needs a join deadline (60 s?). Also: a departure before
  `start_session` returns still writes `session_started` after `session_ended`.
- **Question for Michael.** None new (D16's 20 s question stands).
- **Proposed changes.** V1-02 step 1 names `publisher.final(current_memory(...))` for the last memory. Built as
  `publisher.schedule(); await publisher.idle()` instead, so a forget_me racing the closing send still sends the
  empty memory last (review I1).

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
