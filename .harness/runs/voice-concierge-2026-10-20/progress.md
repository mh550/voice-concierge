# Progress log: run `voice-concierge-2026-10-20`

What this is: the running record of the harness run, **newest entry first**. Every session reads it at startup and
appends its own entry at the top (what it built, what it learned, what the next session must know).

How to read the feature list: `.harness/runs/voice-concierge-2026-10-20/feature_list.json`. Array order is priority
order. A session gets the first feature with `passes: false` whose `after` dependencies pass (no `after` means every
earlier feature). A session may flip only its own feature's `passes`. Each step is checked by a verifier, so do
exactly what the step says, with the names it uses.

How Michael steers: edit `.harness/runs/voice-concierge-2026-10-20/INBOX.md` on this branch. First line
`status: run | pause | stop`; answers go under `## Answers`. Every session reads it at startup.

---

### 2026-10-20 04:55 · C4-01 · passes

- **Changed:** new `docs/plans/2026-10-20-C4-extraction.md` (740 lines). It covers the `emit_ops` tool and its exact strict JSON schema, the extractor's two-message context, `tool_choice="auto"` with parallel tool calls off and the "call emit_ops exactly once" line, how `collect()` is read, the deterministic merge (10 ordered checks), the write-gate regexes plus the contact exception reserved for C8, the scheduler and erasure flow, `remember`/`forget`, the YAML eval schema with 13 scripts, and test names for C4-02 to C4-05. Also new: `docs/decisions.md` D10 *default* (grounding). Docs only, so tests stay at 351 → 351.
- **Verified:** all 6 steps hold, checked with a keyword grep of every element the steps name; `check.sh` is green at 351. Two scratch prototypes ran against 1.8.8 (`proto-c4/`). In the first, a typed `@function_tool emit_ops(ops: list[OpArg])` printed the strict Anthropic schema. In the second, a FakeLLM `emit_ops` call came back through `chat(...).collect()`, and the agent's `remember`/`forget` tools had the params `fact`/`about`. `gate_check.py` runs the plan's regexes: 13 required rejections get the right reason and 20 accepts pass.
- **Review (Opus):** 0 Critical, 6 Important, 9 Minor, all applied (table in the plan's "Plan review"). The Important ones: 2-letter grounding ("PM"), the critical-path test's debounce, false-positive secret and phone regexes, DELETE reasons as an enum (D8), `forget` matching whole words and deleting the superseded chain, and the heard-text citations (LLM replies go through `_pipeline_reply_task_impl:3905-3936` and `_ForwardOutput.forwarded_text`).
- **Next session (C4-02):** the heard-text finding is that 1.8 already stores only the heard text (it's the synchronized transcript) as an interrupted message's content; a turn nobody heard is never added. `store.py` is at 247 lines, so C4 adds nothing to it. Every write goes through `apply_fact_ops`, with journal rows as a new `Note` op in `models.py`/`fact_ops.py`.
- **Question for Michael (D10):** should the merge keep rejecting extracted values that share no word with the visitor's turn? That means fewer false memories, but some lost paraphrases.
- **Proposed changes:** C4-02 `merge` gains a `turns=` keyword argument, and `reason` becomes an enum. C4-04 `remember(fact)` takes the slot as a `"slot: value"` prefix. C4-05 YAML gains the optional keys `about`, `gone`, `nothing_stored` and per-turn `confidence`.

### 2026-10-20 04:10 · verify C3

| Feature | Step | What you ran or read | What you saw | Holds |
|---|---|---|---|---|
| C3-01 | 1 | Read docs/plans/2026-10-20-C3-preload.md: 'The preload sequence', 'The memory block', '1,500-character rule', 'Greetings' | Sequence parse dispatch → gather(connect, preload) → render → agent → session.start → greeting; template with `- name: "Ada" (voice, 2026-10-19)` lines + `Last visit:`; trim oldest set items then shorten summary; new vs returning greeting texts | yes |
| C3-01 | 2 | Read plan 'Name confirmation (B12)' | Rule text for STATIC_INSTRUCTIONS (ask "Did I get that right, <name>?" once, use only after yes); extractor sees user/agent/user three-turn exchange, ADD name from the 'Yes' turn | yes |
| C3-01 | 3 | Read plan 'Tests' (C3-02, C3-03); compared names with `grep -n def tests/...` | Test functions listed for both; the named ones exist in test_memory_block/test_preload/test_greeting/test_session/test_prompt | yes |
| C3-01 | 4 | `.harness/check.sh`; `/home/mh550/projects/agent-harness/lib/check.sh` | exit 0; green, 351 tests | yes |
| C3-02 | 1 | Read concierge/memory_block.py and tests/test_memory_block.py (`_maximal`, test_maximal_memory_is_capped_and_keeps_the_newest_set_items); ran file | None for empty; starts with MEMORY_HEADER; quoted lines with channel/day; `Last visit:`; test builds 8×60-char interests, 8 asked_about, 600-char summary and asserts len<=1500, oldest dropped, ids 24/25 survive; all pass | yes |
| C3-02 | 2 | Read concierge/preload.py; tests test_preload_runs_the_store_reads_off_the_event_loop, test_preload_journals_memory_preloaded_with_ms | Preloaded(thread_id, version, visits, state, facts, block, ms) (superset of the step's fields); preload uses asyncio.to_thread and journals memory_preloaded with ms; tests pass | yes |
| C3-02 | 3 | Read session.py:168 and worker.py; test_entrypoint_connects_and_preloads_concurrently | gather(ctx.connect(), preload) lives in session.start_session, which worker.entrypoint awaits (plan documents the move). Test uses fake_job_context, 0.2 s stub connect + preload, asserts 0.2 <= elapsed < 0.35; passes | yes |
| C3-02 | 4 | Read test_new_visitor_instructions_have_no_memory_header, test_returning_visitor_instructions_order_static_pack_memory, test_memory_text_never_appears_above_the_pack | New visitor text == build_instructions(pack, None), no header; returning: index(STATIC)<index(pack)<index(MEMORY_HEADER); memory values only after pack end; pass | yes |
| C3-02 | 5 | Read test_every_fact_line_is_quoted, test_injection_value_renders_inside_quotes_under_the_header, test_a_value_cannot_close_its_quotes | Each fact line matches `- slot: ".*" (chan, date)`; 'ignore previous instructions...' appears only as a quoted value on a line after MEMORY_HEADER; pass | yes |
| C3-02 | 6 | `.harness/check.sh`; targeted `pytest tests/test_memory_block.py test_preload.py test_greeting.py test_session.py test_prompt.py test_readme.py` | check exit 0; 74 passed | yes |
| C3-03 | 1 | Read concierge/session.py:144-180 and test_first_session_creates_the_thread_and_journals_session_started, test_shutdown_callback_journals_session_ended_and_closes_the_store | start_session: preload → agent → session.start → generate_reply(instructions=greeting_instructions(preloaded)); session_started {visits, preload_ms, returning}; on_shutdown registered via ctx.add_shutdown_callback journals session_ended; tests pass | yes |
| C3-03 | 2 | Read concierge/greeting.py and tests/test_greeting.py | New: 'Introduce yourself in one sentence...'; named: 'Greet "Ada" by name and offer to pick up ...'; summary-only: 'Welcome the visitor back without using a name...'; three cases tested (+ nothing-to-recall); pass | yes |
| C3-03 | 3 | Read tests/test_session.py first/second session tests | First start_session: visits==1 and session_started row; second: visits==2, FakeLLM calls[0] last item starts 'Greet "Ada" by name' with seeded name; pass | yes |
| C3-03 | 4 | `grep -n 'confirm\|did I get that right' concierge/prompt.py`; read test_static_instructions_carry_the_name_confirmation_rule and test_static_plus_pack_within_budget | Lines 27-28 contain 'confirm' and 'did I get that right'; test asserts them and static+pack <= 3000 tokens; pass | yes |
| C3-03 | 5 | `.harness/check.sh` | exit 0 | yes |
| C3-04 | 1 | `ls` of review-C3.diff paths; read plan '## Review'; wc -l of diff | /tmp/voice-concierge/review-C3.diff does not exist, but scratch .../voice-concierge-2026-10-20/review-C3.diff exists (2135 lines, git diff 329c715..HEAD); written there because CLAUDE.md bars writes elsewhere; '## Review' is appended with 6 findings | yes |
| C3-04 | 2 | `git show efe7a3b --stat`, `git log` ordering; read Review table | RED efe7a3b (tests only) precedes GREEN 1fd0d1b for the one Important (#1) and Minors #2/#3; no Critical | yes |
| C3-04 | 3 | Read README.md 'Memory design' rows; tests/test_readme.py passes | Rows 'Just-in-time vs preload', 'Stable, cached prefix', 'Memory as an attack surface' each cite test names; test_readme checks they exist | yes |
| C3-04 | 4 | `wc -l concierge/*.py | sort -n | tail` | largest is store.py at 247 (<=250) | yes |
| C3-04 | 5 | `.harness/check.sh` | exit 0 (check=0) | yes |

Result: 20 steps, all hold; no `passes` changed.

### 2026-10-20 03:25 · C3-04 · passes

- **Changed:** the README has a new "Memory design" section with the rows Just-in-time vs preload, Stable, cached prefix and Memory as an attack surface. Each row cites the tests that prove it, and `tests/test_readme.py` fails if a cited test doesn't exist. `greeting._topic` now reads the rendered block. `session._done` logs a failed background task by type. `_preload_or_none` falls back to no memory on any error. The plan's `## Review` is written. Tests 342 → 351.
- **Verified:** all 5 steps hold. `check.sh` is green at 351. The largest module is `store.py` at 247 lines. The diff is in the scratch dir as `review-C3.diff`, the same path deviation as C1-06 and C2-05. RED `efe7a3b` comes before GREEN `1fd0d1b`, and both RED failures reproduced the bug: the greeting pointed at a missing asked_about line, and asyncio logged "boom Zephyrine". Swapping one cited test name in the README fails `test_memory_design_row_names_tests_that_exist`.
- **Review (Opus):** 0 Critical, 1 Important (fixed), 5 Minor: #2, #3 and #5 fixed, #4 and #6 declined with reasons in the plan. The Important finding: the greeting could offer "the last asked_about line" after trimming had dropped every asked_about item, or offer a summary that `_clean` had blanked.
- **Next session (C4-01):** the README's "Memory design" table is where C4-06 adds its write-path rows, and `test_readme.py`'s parametrize list grows with it. The attack-surface row already says the write gate and the name-after-a-yes rule arrive in C4.
- **Proposed changes:** (1) C3-04 step 1's diff path should be the scratch dir. (2) Spec §4.0's trim rule could keep the newest asked_about item, which is the greeting's "last topic". Right now 8 newer interests can push it out, and the greeting falls back to the Last visit line.

### 2026-10-20 02:57 · C3-03 · passes

- **Changed:** new `concierge/session.py` (`start_session`, `Started`, `room_start_kwargs`, `build_session`, `recording_options`, one ordered `on_shutdown`), `concierge/greeting.py` (`greeting_instructions`, `INTRODUCTION`); the B12 name rule in `STATIC_INSTRUCTIONS`; `worker.py` shrinks to parse → open store → `await start_session` (66 lines). The test seams (`AgentSession`, `build_*`, `ChannelTags`, `preload`, `PRELOAD_TIMEOUT_S`, logger `concierge.session`) moved to `concierge.session`; `RecordingSession.generate_reply`. Tests 324 → 342 (`test_greeting.py` 7, `test_session.py` 8, `test_prompt.py` +1, `test_preload.py` +1, `test_worker.py` +1 param).
- **Verified:** all 5 steps hold; `check.sh` green (342). `test_session.py` drives a real `AgentSession` over the FakeLLM (room kwargs patched to `{}`): visits 1 then 2, `calls[0]`'s last item is `Greet "Ada" by name…`, prefix byte-identical across calls. Static + pack = 2,635 of 3,000 tokens. 7 mutants of `session.py` (no `session_started`, journal awaited before greeting, no close, no `session_ended`, greeting ignores preload, sequential connect/preload, callback not registered) all caught. Timing tests 5 of 5.
- **Review (Opus):** 1 Important, 4 Minor. Important, fixed RED→GREEN: on the D9 deadline `wait_for` left the store thread running and shutdown closed the store under it (reproduced). The preload is now a tracked task under `asyncio.wait`; `on_shutdown` waits for it, logs failed tasks by type, then closes (D9 text updated). Minor fixed: failed background tasks logged by type, a blocked-thread deadline test (`test_a_preload_thread_that_outlives_the_deadline_finishes_before_the_store_closes`), the unused helper. Not fixed (low odds, for C3-04): a job cancelled during the entrypoint's store open (≤ 5 s busy timeout) never closes that `Store`.
- **Next session (C3-04):** the plan's `test_bad_dispatch_ends_the_job_before_any_store_or_provider` lives in `tests/test_worker.py` (`test_entrypoint_logs_and_ends_the_job_on_bad_metadata`, which asserts no db dir). A late (timed-out) preload still journals `memory_preloaded` and counts the visit; that session journals no `session_started`/`session_ended` (accepted in D9). Diff for this feature: scratch `review-C3-03.diff`.
- **Proposed changes:** C3-03 step 2's "offer to pick up <last topic>" is a pointer to the memory section ("the last asked_about line in your notes"), not the copied topic text, per the plan's "Visitor data in the greeting".

### 2026-10-20 03:40 · C3-02 · passes

- **Changed:** new `concierge/memory_block.py` (`render_memory_block`), `concierge/preload.py` (`Preloaded`, `preload`), `Store.load` + `fact_ops.snapshot` + `models.ThreadSnapshot`; `worker.py` opens the store off-loop, `asyncio.gather(ctx.connect(), _preload_or_none(...))`, `_agent_or_memoryless`, a `close_store` shutdown callback. `RecordingSession` moved to `concierge/testing/recording_session.py`; conftest has an autouse `CONCIERGE_DB_PATH` temp fixture. Tests 290 → 324 (`test_memory_block.py` 16, `test_preload.py` 17, one in `test_store.py`).
- **Verified:** all 6 steps hold; `check.sh` green (324). Mutation checks: making connect+preload sequential fails the timing test (0.42 s > 0.35 s); rendering days in local time fails `test_days_are_utc`. The timing test passed 5 of 5 repeats.
- **Review (Opus):** 1 Important, 3 Minor, all fixed with tests. Important (checked in 1.8.8 source): `ctx.connect()` joins the room before `session.start` registers RoomIO's `lk.chat` and pre-connect audio handlers, so a slow preload drops typed text or the pre-connect buffer → **D9 *default***: the preload gets a 1 s deadline (`PRELOAD_TIMEOUT_S`), then the session runs without memory.
- **Next session (C3-03):** move the gather, `_open_or_none`/`_preload_or_none`/`_agent_or_memoryless`, `close_store` (becomes `on_shutdown`) and the conftest `recording_session` patches into `concierge/session.py`. `store.py` is at 247/250 lines. If `ctx.connect()` raises, the preload thread may still count a visit and journal `memory_preloaded` for a session that never started (accepted).
- **Question for Michael (D9):** does the page send a pre-connect audio buffer, or let visitors type before the agent joins? If yes, a later session should await the preload before `session.start` and overlap it only with provider setup.
- **Proposed changes:** C3-02 step 2's field list should include `visits` (the plan's `Preloaded` has it).

### 2026-10-20 02:32 · C3-01 · passes

- **Changed:** `docs/plans/2026-10-20-C3-preload.md` (414 lines, plan only, no code). Tests 290 → 290.
- **Verified:** all 4 steps hold. The plan has the preload sequence (parse → `gather(ctx.connect(), preload)` → render → agent → `session.start` → greeting), the block template (`- name: "Ada" (voice, 2026-10-19)`, `Last visit: "…"`), the 1,500-char rule, both greetings, the B12 rule text plus the C4 extractor flow, and test names for C3-02/C3-03. `check.sh` is green. I checked the 1.8.8 APIs in source, then ran two prototypes in scratch: a real `AgentSession.start(room=ctx.room)` raises under `fake_job_context` (hence the `room_start_kwargs` seam), and the greeting reaches the LLM as a trailing system message, outside the cached prefix. An Opus plan review found 1 Critical, 6 Important and 7 Minor; all are applied (listed under `## Plan review`).
- **Next session must know:**
  - Render from the derived `VisitorState`, not from every valid fact: the store applies ops literally.
  - `Store.load` uses `_transaction()`. No store write sits between the gather and the greeting.
  - Shutdown callbacks run concurrently, so everything that touches the store goes in one ordered `on_shutdown`.
  - An autouse conftest fixture must set `CONCIERGE_DB_PATH` to a temp file.
  - C3-03 moves the gather into `session.start_session` and the test seams with it (listed in the plan).
  - Name rule: 281 chars; static + pack goes to about 2,635 of 3,000 tokens.
- **Proposed changes:**
  - C3-02 step 3: allow the gather to sit "directly or through `start_session`".
  - C3-02 step 1: the summary should be 500 chars (`SUMMARY_CAP`), not 600; the test uses `model_construct`.
  - C3-04 diff path: the scratch dir, as C1-06 and C2-05 did.
  - C4: a `name_unconfirmed` merge check.

### 2026-10-20 · verify C2

All 26 steps hold; no feature flipped. Note: C2-05 step 1 path deviation is documented and justified by CLAUDE.md.

| Feature | Step | What you ran or read | What you saw | Holds |
|---|---|---|---|---|
| C2-01 | 1 | read plan `docs/plans/2026-10-20-C2-store.md` §Schema, §The fence, §Erasure, §TTL purge | 7 CREATE TABLE IF NOT EXISTS (threads, state, facts, journal, anonymous_turn_metrics, daily_session_counts, messages_for_michael) with spec columns; fence: BEGIN IMMEDIATE, read version, fn, `UPDATE threads SET version = version + 1 WHERE id = ? AND version = ?`, VersionConflict + apply_fact_ops 5-attempt reapply; erasure steps 1-7; purge_idle/purge_daily_counts | yes |
| C2-01 | 2 | read plan slot catalogue table (l.211-220) and caps (l.185) | name/role/company/follow_up_wanted single 120; interests/asked_about set, 60 chars, at most 8, oldest invalidated on 9th; follow_up_wanted superseded on add | yes |
| C2-01 | 3 | read plan §Tests (l.391-484) | per-feature test files and function names listed for C2-02 (test_models/test_store), C2-03 (test_store/test_concurrent_writers), C2-04 (erasure/ttl/scripts); all names exist in tests/ | yes |
| C2-01 | 4 | `.harness/check.sh` | exit 0 | yes |
| C2-02 | 1 | read concierge/models.py; ran python building maximal VisitorState; read test_models.py names | VisitorState and Fact fields as specified; SLOTS kinds/caps correct; maximal state dumps 2098 bytes; test_maximal_visitor_state_is_under_8_kib and test_visitor_state_over_8_kib_is_rejected pass | yes |
| C2-02 | 2 | python: Store(tmp) then sqlite_master + PRAGMA journal_mode; read test_schema_creates_the_seven_tables, test_journal_mode_is_wal | 7 tables listed, journal_mode ('wal',); tests assert the same and pass | yes |
| C2-02 | 3 | python get_or_create_thread; read test_new_thread_row_defaults, test_get_or_create_counts_visits_and_touches_last_active, test_threads_visitor_id_is_unique | version 0, idle_ttl_s 2592000, visits 1; tests assert visits==2 after two calls, UNIQUE raises IntegrityError | yes |
| C2-02 | 4 | read test_journal_rows_come_back_in_insertion_order, test_journal_rejects_an_unknown_type, test_journal_type_literal_matches_spec_list | order and Literal constraint asserted; pass | yes |
| C2-02 | 5 | python pragma table_info(anonymous_turn_metrics); read test_anonymous_turn_metrics_columns | no visitor_id or text column; test asserts exact column list | yes |
| C2-02 | 6 | `.harness/check.sh` | exit 0 (290 passed) | yes |
| C2-03 | 1 | read plan fence code + concierge/store.py write/apply_fact_ops; test_write_bumps_version_once, test_apply_fact_ops_gives_up_after_5_attempts | BEGIN IMMEDIATE, version-guarded UPDATE, VersionConflict; 5 attempts then raise; tests pass | yes |
| C2-03 | 2 | read tests test_add_fact_sets_valid_from_to_now, test_invalidate_fact_sets_valid_to_and_keeps_the_row, test_delete_fact_removes_the_row, test_valid_facts_excludes..., test_recompute_state_* | each primitive asserted (invalidate keeps row, delete removes, newest wins for single, sets <=8); pass | yes |
| C2-03 | 3 | read and ran tests/test_concurrent_writers.py | two spawn processes x20 facts via apply_fact_ops; asserts len(valid)==40, values match, version==40; passes | yes |
| C2-03 | 4 | read test_stale_expected_version_raises_version_conflict_and_leaves_no_row, test_add_fact_on_missing_thread_raises_thread_missing | VersionConflict, no fact row; ThreadMissing with threads count 0; pass | yes |
| C2-03 | 5 | `.harness/check.sh` | exit 0 | yes |
| C2-04 | 1 | read test_forget_me_erases_visitor_tables_and_keeps_anonymous_ones | seeds 5 visitor tables + 3 metrics + 1 daily count; asserts 0 in five, 3 and 1 in survivors; vacuum test also present; pass | yes |
| C2-04 | 2 | read test_writes_after_forget_me_raise_thread_missing | add_fact/journal/apply_fact_ops raise ThreadMissing, threads count 0; pass | yes |
| C2-04 | 3 | read test_ttl.py 31d/29d and test_purge_daily_counts_drops_rows_older_than_2_days | 31 days purged, 29 stays; daily counts older than 2 days dropped; pass | yes |
| C2-04 | 4 | read test_count_session_survives_forget_me and key test | count==3 after 2, forget_me, 1; key is sha256(visitor_id+day); pass | yes |
| C2-04 | 5 | read tests/test_scripts.py::test_memory_history_prints_one_line_per_fact (subprocess, seeded db) | 2 lines ordered by valid_from, 2nd has `current` and `-`, 1st has superseded_by id; pass | yes |
| C2-04 | 6 | `.harness/check.sh` | exit 0 | yes |
| C2-05 | 1 | ls diff path; read plan ## Review | diff exists at scratch `.../review-C2.diff`, not literal `/tmp/voice-concierge/review-C2.diff` (plan l.512 explains: CLAUDE.md bars writes outside worktree/scratch); '## Review' with 14 findings appended | yes |
| C2-05 | 2 | git log; read ## Review table; git log RED/GREEN pairs | Important #1,#2: RED 841613b before GREEN aa81a14; Minor fixes RED de4e705 -> GREEN fa413d7; tests named | yes |
| C2-05 | 3 | read README.md 'Mapping onto Agents 2.0'; tests/test_readme.py | rows thread, lane state, journal, fence (BEGIN IMMEDIATE + version); contains 'Here 1.8 has no lease, so two live sessions for one visitor can interleave turns'; tests pass | yes |
| C2-05 | 4 | wc -l concierge/*.py | largest store.py 238, store_base.py 220; none over 250 | yes |
| C2-05 | 5 | `.harness/check.sh` and `pytest -m 'not live' -q` | exit 0; 290 passed | yes |

### 2026-10-20 07:05 · C2-05 · passes

- **Changed:** README "Mapping onto Agents 2.0" table (thread, lane state, journal, fence, channels, idle_ttl; "1.8 has
  no lease, so two live sessions for one visitor can interleave turns") + `tests/test_readme.py`; `apply_fact_ops`
  checkpoints the WAL after any delete (`ApplyResult.deleted`), without waiting; `AddFact.supersedes` deduped;
  `memory_history.py` guards both reads; `Store` docstring gives blocking bounds and error types. Tests 281 → 290.
- **Verified:** `check.sh` green (290). Opus review of `review-C2.diff` (in the scratch dir, as C1-06 did): 0 Critical,
  2 Important, 12 Minor. Important #1 RED 841613b → GREEN aa81a14; #2 (a test gap) fails on a no-compaction mutant.
  4 Minor fixed (2 RED → GREEN), the rest assigned to C3–C8 in the plan's `## Review`. Largest module: store.py, 238 lines.
- **Next session must know:** a `DeleteFact` through any path now leaves the disk; if a reader blocks the checkpoint, the next
  write finishes it. C4's `forget` must delete the slot's supersession chain, and its callable must re-check targets (`based_on`
  doesn't). C5 adds `set_summary` with character checks. C6 `close()`s the store at job end and passes the UTC day.
  C8 answers the forget_me RPC as soon as the delete commits.
- **Proposed change:** later review steps should name the scratch dir, not `/tmp/voice-concierge/`. D8 still open.

### 2026-10-20 06:10 · C2-04 · passes

- **Changed:** new `concierge/store_erasure.py` (`forget_me`, `purge_idle`, `count_session`, `purge_daily_counts`;
  `Store` now inherits from it), `store_base.py` (`open_readonly`, `_immediate`, an owed-checkpoint retry in
  `_settle`), new `scripts/memory_history.py`, and new test files `tests/test_erasure.py`, `tests/test_ttl.py` and
  `tests/test_scripts.py`, plus count tests in `test_store.py`. Tests 238 → 281.
- **Verified:** `check.sh` green (281). Ran `memory_history.py` by hand: exits 0, 1 and 2 as specified. 11 mutants,
  all 11 caught. The new test files passed 10 of 10 runs in a loop. Opus review: 0 Critical, 1 Important (a
  checkpoint blocked by a reader left the erased value on disk until restart; it is now retried by the next write,
  the daily purge and close), 5 Minor. All 6 fixed with tests written first (RED → GREEN). Details in the plan's
  "C2-04 build notes".
- **Next session must know:** C6 calls `purge_idle(now_ms())` and `purge_daily_counts(now_ms())` at worker start and
  daily; both take ms, and passing seconds raises. If `forget_me` can't take the write lock, it raises and erases
  nothing, so C8's RPC must answer not-ok then. `forget_me` can hold the store lock for up to 5 s while a reader
  blocks its checkpoint.
- **Questions / proposed changes:** none new. D8 is still open.

### 2026-10-20 04:05 · C2-03 · passes

- **Changed:** `Store.apply_fact_ops` (fence + reload/reapply, 5 attempts, jittered backoff, list or callable ops),
  `add_fact` / `invalidate_fact` / `delete_fact` / `valid_facts` / `fact_history` / `recompute_state`, new
  `concierge/fact_ops.py` (in-transaction ops, journal, `derive_state`), `store.py` split into `store_base.py`
  (connection, lock, errors incl. new `FactMissing`, `_checkpoint`, metrics) + `store.py`; `write_facts` child target;
  `tests/test_concurrent_writers.py`. Tests 208 → 238.
- **Verified:** `check.sh` green (238). Concurrency test 20/20 in a loop (40 facts, version 40). 24 mutants: 22 caught,
  2 equivalent. Opus review: 0 Critical, 2 Important (a deleted value lingered in `-wal`; a Store call from inside
  `write` deadlocked), 7 Minor; both Important + 5 Minor fixed RED→GREEN, the rest noted in the plan's "C2-03 build notes".
- **Next session must know:** C2-04's `forget_me` reuses `StoreBase._checkpoint()`. Re-entrant Store calls now raise
  `StoreError`. C4's `forget` tool must pass `thread_id` to `delete_fact`; an `apply_fact_ops` callable must be fast
  and pure (it holds the write lock). Mutation runs need `PYTHONPATH=<copy>` or pytest imports the worktree.
- **Questions / proposed changes:** none new. D8 is still open.

### 2026-10-20 03:10 · C2-02 · passes

- **Changed:** new `concierge/models.py` (SLOTS, VisitorState with its 8 KB validator, Fact, the ops models,
  JournalType, Thread, JournalRow, TurnMetrics), `concierge/schema.py` (the plan's DDL), `concierge/store.py`
  (`Store`: WAL, schema, `get_or_create_thread`, `thread_for`, `version`, `state`, `write` (the fence), `journal`,
  `journal_rows`, `add_turn_metrics`), `concierge/testing/store_writers.py`, `tests/conftest.py` (FakeClock, store
  fixture), `tests/test_models.py`, `tests/test_store.py`. Tests 135 → 208.
- **Verified:** `check.sh` green (208 tests). 13 mutants: 12 caught at first; the 13th (a revisit that doesn't bump
  the version) survived, so I added an assertion that now catches it. A maximal state is 2098 bytes in ASCII and
  7918 in 4-byte UTF-8. The multi-process fresh-open test passed 10 of 10 runs in a loop. Opus review: 0 Critical,
  2 Important (several processes opening a new file together got `database is locked`; values with U+2028,
  bidi or surrogate characters were accepted), 9 Minor. Both Important and 7 Minor fixed with tests written first
  (21 RED → GREEN); 1 documented, 1 deferred. Details in the plan's "C2-02 build notes".
- **Next session must know:** `store.py` is 249 lines, so the fact helpers go in `concierge/fact_ops.py`.
  `write(fn)`: `fn` may use only `conn`, because calling a Store method from it deadlocks. `recompute_state` must
  build the state with `model_validate` (VisitorState isn't frozen). A revisit bumps the version. `add_turn_metrics`
  needs `uuid.uuid4().hex` as the session id. `store_writers.py` exists; add `write_facts` there.
- **Questions / proposed changes:** none new. D8 is still open.

### 2026-10-20 verify P1

| Feature | Step | What you ran or read | What you saw | Holds |
|---|---|---|---|---|
| P1-01 | 1 | `grep anthropic pyproject.toml`; `pip list`; read llm.py lines 41-46,120-127,163-183,227-279,329-342 vs decisions.md cites | pin ==1.8.8 present, installed 1.8.8, import ok; every cited file:line matches the source | yes |
| P1-01 | 2 | `env -u ANTHROPIC_API_KEY python` importing config+worker; Settings() under both providers; CONCIERGE_EXTRACTOR_MODEL override; read config.py build_llm | import ok; anthropic defaults haiku/sonnet/sonnet; openrouter all gpt-4.1-mini; override x/y works; build_llm returns Claude wrapper or with_openrouter | yes |
| P1-01 | 3 | read concierge/claude_llm.py | conversation thinking disabled + caching ephemeral; background effort low, max_tokens=4096 in constructor, fallback header+body; no temperature; ends_on_user appends user turn | yes |
| P1-01 | 4 | `pytest tests/test_claude_llm.py` (read assertions) | tests for model id, thinking, cache_control, effort/max_tokens/header/body, no sampling keys, trailing user, thinking-block text-only all match the step; pass | yes |
| P1-01 | 5 | `pytest tests/test_config.py` (read test_defaults, openrouter, build_llm tests); ran build_llm with key unset | 51 pass across both files; defaults, openrouter with_openrouter monkeypatch, ValueError naming ANTHROPIC_API_KEY | yes |
| P1-01 | 6 | read .env.example, README.md line 10, docs/decisions.md 44-84 | ANTHROPIC_API_KEY= empty, OPENROUTER commented with required note; README names it; decisions entry has per-stage table and reasons | yes |
| P1-01 | 7 | `.harness/check.sh` | exit 0, 135 passed | yes |

### 2026-10-20 01:26 · P1-01 · passes

- **Changed:** pinned `livekit-plugins-anthropic==1.8.8` (+ `anthropic>=1.15,<2`); new `concierge/claude_llm.py`
  (`ClaudeLLM`, `ClaudeLLMStream`, `build_claude_llm`); `config.py` gains `llm_provider` (anthropic default: Haiku 5.5 /
  Sonnet 5.5; openrouter restores `openai/gpt-4.1-mini`); `concierge/testing/fake_anthropic.py` (a real AsyncAnthropic
  whose `messages.create` binds kwargs against the SDK signature); `.env.example`, README, decisions entry "LLM provider:
  Anthropic direct" with file:line cites into the plugin. Tests 99 → 135.
- **Verified:** `check.sh` green (135); `import livekit.plugins.anthropic` ok; `concierge.worker` imports with
  ANTHROPIC_API_KEY unset; 11 mutants, all caught. Opus review: 0 Critical, 1 Important fixed RED→GREEN (the plugin never
  reads `stop_reason`, so a refusal looked like success: background stages now raise a non-retryable APIStatusError),
  5 Minor fixed, 2 deferred (below).
- **Next session must know:** C4/C5 get `build_llm("extractor"|"summarizer")`; `collect()` raises `APIStatusError` on
  a refusal, so treat that as zero ops / keep the old summary. Pass `tool_choice="auto"`, `parallel_tool_calls=False`.
  Caller `extra_kwargs` merge with the stage's only for extra_headers/extra_body/output_config.
- **Deferred (Minor):** a leftover `/`-style OpenRouter model id under provider anthropic fails at the first live call,
  not at startup; provider tools with their own beta flag would lose it to the stage header (none used).
- **For Michael (MORNING):** the live check of this is the first voice turn: a 400 naming `thinking`, `output_config`
  or `fallbacks` means the 5.5 request shape needs a tweak in `concierge/claude_llm.py` (rollback:
  `CONCIERGE_LLM_PROVIDER=openrouter` plus OPENROUTER_API_KEY in the env file).

### 2026-10-20 02:05 · C2-01 · passes

- **Changed:** new `docs/plans/2026-10-20-C2-store.md` (schema DDL for all seven tables, models, slot catalogue,
  store API, fence + reload-and-reapply, erasure, TTL purge, 56 named tests for C2-02…C2-04); D8 *default* in
  `docs/decisions.md`. No code; tests 99 → 99.
- **Verified:** grepped each step's items in the plan (7 `CREATE TABLE`s, fence, erasure/TTL sections, 6 slot rows,
  test lists per feature); `check.sh` green (99). Prototyped in scratch first: two spawned writers × 20 fenced writes,
  30 runs, always 40 rows / version 40 (never a 2nd retry); WAL erasure leaves no bytes only after
  `wal_checkpoint(TRUNCATE)`. Opus plan review: 0 Critical, 4 Important, all applied (see the plan's last section).
- **Next session must know:** the store applies ops literally (slot ADD rules are C4's merge, via the callable form of
  `apply_fact_ops`), because C2-03's 40-valid-facts step rules out slot rules in the store. Thread ids are uuid4
  hex and fact ids AUTOINCREMENT so nothing is reused after erasure. Times are ms; `idle_ttl_s` stays seconds.
- **Question for Michael (D8):** a per-fact `forget` deletes the fact but the journal still holds that turn's text
  until "Forget me" or the 30-day purge. OK, or should `forget` blank the turn text too?
- **Proposed changes:** C5 should add `compaction_ran` to the `JournalType` Literal (§4.8 needs it, §4.2's list lacks
  it); C2-05 step 1's `/tmp/voice-concierge/review-C2.diff` is outside the scratch dir (use the run's scratch dir, as
  C1-06 did).

### 2026-10-20 · verify C1

Re-ran `check.sh` (99 passed, ruff clean) and read each named test's assertions. Result: 33 steps, 33 hold, 0 fail. Notes: C1-01 step 6 says "reports 1 passed", which was true when the feature shipped; now the suite has 99 tests, so I ran `pytest tests/test_smoke.py` (1 passed) plus the full check (exit 0). C1-06 step 1: the diff is in the scratch dir, not `/tmp/voice-concierge/` (the plan's `## Review` says why: CLAUDE.md forbids writing elsewhere); counted as holding.

| Feature | Step | What you ran or read | What you saw | Holds |
|---|---|---|---|---|
| C1-01 | 1 | read `docs/plans/2026-10-20-C1-skeleton.md` | module layout lists config/prompt/agent/worker/knowledge/testing/fake_llm; fake LLM section cites llm.py ChatChunk, ChoiceDelta, CompletionUsage, `_run`; turn-detection section present | yes |
| C1-01 | 2 | `grep -A8 D7 docs/decisions.md` | "D7 *default*: turn detection is silero VAD only", finding, choice, alternative | yes |
| C1-01 | 3 | read `pyproject.toml` | all five pins present (==1.8.8, pydantic>=2), dev extra with pytest/pytest-asyncio/ruff, setuptools backend, `live` marker, asyncio_mode auto, `[tool.ruff]` | yes |
| C1-01 | 4 | read `.harness/init.sh`; init output | prints `livekit-agents 1.8.8` after venv/pip install of pyproject | yes |
| C1-01 | 5 | `ls`; read `tests/test_smoke.py` | concierge/__init__.py, scripts/__init__.py exist; test asserts `livekit.agents.__version__ == "1.8.8"` | yes |
| C1-01 | 6 | `.harness/check.sh`; `pytest tests/test_smoke.py` | check exit 0 (99 passed); smoke test 1 passed | yes |
| C1-02 | 1 | `wc -w`; grep `^## ` and `Source:` in `knowledge/michael.md` | 1121 words; all 14 sections followed by Source: line, files in the allowed five | yes |
| C1-02 | 2 | read `tests/test_knowledge.py`; read Experience/Education against `experience.ts` | NAMES derived from project headings and `at <Company>`; `test_every_name_appears_verbatim_in_the_sources` parametrized, passes; companies match experience.ts | yes |
| C1-02 | 3 | read `concierge/knowledge.py` | `load_pack()`, `pack_word_count()`; path from `__file__`; `test_load_pack_does_not_depend_on_cwd` | yes |
| C1-02 | 4 | read test file | word count, Source files exist, load_pack equals file, no URL absent from sources, all assert as written | yes |
| C1-02 | 5 | `.harness/check.sh` | exit 0 | yes |
| C1-03 | 1 | read `concierge/config.py`, `test_defaults` | all fields/defaults as listed, env prefix CONCIERGE_, speech Literal; `test_speech_ids_are_inference_literals` checks STT/TTS Literals | yes |
| C1-03 | 2 | read factories; `test_import_without_keys_does_not_raise` (fresh interpreter, env cleaned) | factories call `with_openrouter`/inference lazily; import with no keys exits 0 | yes |
| C1-03 | 3 | `test_env_overrides_model`, `test_speech_deepgram_selects_plugin_classes` | override asserted; deepgram classes asserted by module/name without construction | yes |
| C1-03 | 4 | read `fake_llm.py` | FakeLLM(llm.LLM), FakeLLMStream(llm.LLMStream), `_run` pushes ChatChunk/ChoiceDelta/FunctionToolCall/CompletionUsage, `calls` records chat_ctx/tools/tool_choice | yes |
| C1-03 | 5 | read `tests/test_fake_llm.py` | concat equals script; collect() text; tool call name/args; `metrics_collected` has prompt_tokens 1200 / cached 1024 | yes |
| C1-03 | 6 | `.harness/check.sh` | exit 0 | yes |
| C1-04 | 1 | read `concierge/prompt.py` | STATIC_INSTRUCTIONS has persona and all rules, estimate_tokens = ceil(len/3.5), MEMORY_HEADER exact, build_instructions order static, pack, memory | yes |
| C1-04 | 2 | read `concierge/agent.py` | ConciergeAgent(pack, memory_block=None) passes build_instructions; no tools | yes |
| C1-04 | 3 | read `tests/test_prompt.py` | order by index, token budget <=3000, 1500 accepted / 1501 ValueError, all assert | yes |
| C1-04 | 4 | read `tests/test_agent.py` (`test_prefix_is_stable_across_two_turns`) | two `session.run` under `fake_job_context`; call 1 items are a prefix of call 2, same instructions item; instructions unchanged | yes |
| C1-04 | 5 | `.harness/check.sh` | exit 0 | yes |
| C1-05 | 1 | read `worker.py`; `env -u ... python -c 'import concierge.worker'` | `AgentServer(shutdown_process_timeout=30,...)`, `rtc_session(agent_name='concierge', on_request=on_request)`; import ok with no keys | yes |
| C1-05 | 2 | read `dispatch.py`, `tests/test_dispatch.py` | DispatchInfo UUID4 str + channel_hint 'web'; valid, empty, non-uuid cases covered; entrypoint bad-metadata test logs and calls shutdown | yes |
| C1-05 | 3 | read `recording_options()`, `tests/test_worker.py` | `{'audio': False,'redaction': True}` default, audio True under env=1; keys within RecordingOptions annotations | yes |
| C1-05 | 4 | read `text_input.py`; `test_text_cb_tags_before_the_default_generates_a_reply` | order `on_text`, claim, interrupt, generate_reply; entrypoint passes RoomOptions(text_input=TextInputOptions(text_input_cb=...)) | yes |
| C1-05 | 5 | read entrypoint; `grep with_openrouter` ; `test_no_provider_is_built_at_import` | awaits `session.start(agent=ConciergeAgent(...), room=ctx.room, room_options=..., record=...)`; with_openrouter only inside config function | yes |
| C1-05 | 6 | `.harness/check.sh` | exit 0 | yes |
| C1-06 | 1 | `ls` scratch; `git cat-file 447c2ad`; read `## Review` | diff exists in scratch dir (path deviation explained in plan); review table with severities, fixed/deferred | yes |
| C1-06 | 2 | `git log 447c2ad..HEAD` | RED 0aaa6ee (test_non_uuid4_visitor_id_is_rejected trailing newline) precedes GREEN 1b8326a; only Important finding | yes |
| C1-06 | 3 | `wc -l concierge/**`; `ruff check .` with ANN | max 138 lines; ruff passes with ANN selected for concierge/ | yes |
| C1-06 | 4 | `grep README.md`; `git diff 447c2ad..HEAD --stat -- CLAUDE.md` | README names scripts/run-worker.sh and ~/.config/voice-concierge/env, no values; CLAUDE.md unchanged | yes |
| C1-06 | 5 | `.harness/check.sh` | exit 0 | yes |

### 2026-10-20 01:20 · C1-06 · passes

- **Changed:** `concierge/dispatch.py` (`UUID4_RE.fullmatch`), `concierge/text_input.py` (`on_dropped`,
  `ChannelTags.on_dropped`), `concierge/worker.py` (wires it), `concierge/testing/fake_llm.py` (deep snapshots).
  `pyproject.toml` turns on ruff `ANN` for `concierge/` only; README gains "How to run"; the C1 plan gains `## Review`. Tests 95 → 99.
- **Verified:** `check.sh` green, 99 tests. The Important finding has a RED commit (0aaa6ee) before its GREEN (1b8326a).
  Mutants, each caught: an unwired `on_dropped`, `turn_handlin=`, `room_input_options=`, a changed year and a changed
  `$` figure in the pack, and a dropped return hint (ANN201). The largest module is 138 lines. CLAUDE.md is unchanged.
- **Opus review:** 1 Important (a trailing newline passed the UUID check), fixed. 7 Minor: 4 fixed, 3 deferred with
  reasons in the plan (`speech_classes`, the private `_default_text_input_cb` import, re-checking the OpenRouter model id in MORNING.md for C7).
- **Next session:** `make_text_input_cb` now takes `on_dropped=`. Wire it to whatever `ChannelTags` C4 uses.
- **Proposed change (C1-06 step 1):** the diff path `/tmp/voice-concierge/review-C1.diff` is outside this session's
  scratch directory, and `/tmp/voice-concierge/` is shared with other runs. I wrote it to
  `/tmp/harness/voice-concierge/voice-concierge-2026-10-20/review-C1.diff` instead; later review steps should name the scratch dir.

### 2026-10-20 00:46 · C1-05 · passes

- **Added:** `concierge/worker.py` (`server = AgentServer(shutdown_process_timeout=30, setup_fnc=prewarm)`,
  `@server.rtc_session(agent_name="concierge", on_request=on_request)`, `recording_options()`, silero VAD prewarm),
  `concierge/dispatch.py` (`DispatchInfo`, `parse_dispatch` → `DispatchError`), `concierge/text_input.py`
  (`make_text_input_cb`, `ChannelTags`), `tests/test_dispatch.py` (19), `tests/test_worker.py` (16), "C1-05 as built" in
  the C1 plan. Tests 60 → 95.
- **Verified:** `check.sh` green (95). `env -i … .venv/bin/python -c 'import concierge.worker'` succeeds; no
  `with_openrouter(` in worker.py, and an AST test finds no provider call at module level. Six mutants were each caught (tag after the
  default, redaction False, no participant identity, no return on bad metadata, loose UUID regex, no VAD turn mode). A
  real `AgentSession` + `FakeLLM` typed turn through the wrapper comes back tagged `text`.
- **Opus review:** no Critical. Important, fixed test-first: `turn_handling` now also sets `interruption.mode="vad"`
  (otherwise dev/console mode builds the hosted `AdaptiveInterruptionDetector`). Minor fixes applied: uppercase UUIDs
  rejected (not lowercased, so `visitor-<id>` matches the page), `ChannelTags` bounded at 32, `on_text` failure never
  drops the turn, plus stronger tests.
- **Next session:** nothing calls `ChannelTags.channel_of` yet. C4 wires it from `conversation_item_added`.
  `session.start` connects the room itself, and C3-02 replaces that with `gather(ctx.connect(), preload)`. Entry
  point: `python -m concierge.worker start|dev`.

### 2026-10-20 03:15 · C1-04 · passes

- **Added:** `concierge/prompt.py` (`STATIC_INSTRUCTIONS`, 1,263 chars; `MEMORY_HEADER`; `MEMORY_BLOCK_MAX_CHARS = 1500`;
  `STATIC_AND_PACK_MAX_TOKENS = 3000`; `estimate_tokens` = ceil(len/3.5); `build_instructions(pack, memory_block)`),
  `concierge/agent.py` (`ConciergeAgent(pack, memory_block=None)`, no tools), `tests/test_prompt.py` (13),
  `tests/test_agent.py` (2), "C1-04 as built" in the C1 plan. Tests 45 → 60.
- **Verified:** `.harness/check.sh` exit 0 (60 passed, ruff clean). Static + pack = 2,554 estimated tokens of 3,000.
  In two `session.run(user_input=…)` turns, the `lk.agent_task.instructions` system item is the same in both calls and
  call 2's items begin with call 1's (compared by `model_dump_json`). Two mutants fail the test: `update_instructions`
  between the turns, and a system item inserted at index 1. An Opus review found no Critical issues. I applied its
  Important finding (talk about the visitor's own earlier visits is now explicitly on-topic, so the off-topic rule no
  longer declines it) and 3 Minor ones.
- **Next session:** `build_instructions` takes the memory block **already rendered** with `MEMORY_HEADER` (C3-02) and
  only places it and checks the cap. `STATIC_INSTRUCTIONS` must not contain `MEMORY_HEADER` (C3-02 asserts this). About
  1,550 chars of budget are left for C3-03's name rule and C4's tool guidance. Typed turns never call
  `on_user_turn_completed`. `fake_job_context` leaks a `TemporaryDirectory` (a ResourceWarning under `-W error`, upstream).
- **Proposed change (C1-06 review):** `FakeLLM.calls` stores `chat_ctx.copy()`, which is shallow. Storing a
  `model_dump_json()` snapshot per call would make the prefix check catch in-place edits too.

### 2026-10-20 02:30 · C1-03 · passes

- **Added:** `concierge/config.py` (pydantic-settings `Settings`, prefix `CONCIERGE_`, all fields from the step;
  `build_llm(stage)` → `openai.LLM.with_openrouter`, `build_stt`/`build_tts` → Inference or Deepgram plugin, built only
  when called; `speech_classes()` for the class-name test), `concierge/testing/fake_llm.py` (`FakeResponse`,
  `FakeToolCall`, `FakeLLM`, `FakeLLMStream`, `FakeLLM.calls`), `tests/test_config.py` (15), `tests/test_fake_llm.py` (8).
  `pyproject.toml`: + `pydantic-settings>=2,<3`, + `concierge.testing` package. Tests 22 → 45.
- **Verified:** `check.sh` green (45 passed, ruff clean); new tests also pass with `-W error`. The no-key import test
  runs in a fresh interpreter after `monkeypatch.delenv`. A scratch probe ran two `AgentSession.run(user_input=…)` turns
  with `FakeLLM` under `fake_job_context`, offline. An Opus review found no Critical/Important; 5 Minor applied
  (deepgram-id validator with a test, direct construction instead of `type: ignore`, yield between chunks, docs).
- **Next session (C1-04):** each `chat()` uses up one script entry; `FakeLLM.calls[i].chat_ctx` is a copy. Usage
  comes on a separate last chunk, as in `inference/llm.py`; `metrics_collected` comes from the base class. Turn off
  preemptive generation in audio-path tests. `db_path` defaults to `~/.local/share/voice-concierge/concierge.db`
  (expanded), and so does `off_file`.

### 2026-10-20 01:45 · C1-02 · passes

- **Added:** `knowledge/michael.md` (1,121 words, 14 `## ` sections, each followed by `Source: <file>`: profile, about,
  experience, education, skills, and one `## Project: <exact title>` per project in projects.ts), `concierge/knowledge.py`
  (`PACK_PATH` resolved from the package; `load_pack()` cached; `pack_word_count()` = `wc -w`), `tests/test_knowledge.py`.
  Tests 1 → 22.
- **Verified:** `check.sh` green (22 passed, ruff clean); `wc -w` 1121; awk check shows 14/14 sections cite a source. An
  Opus fact-check of every claim against the sources found no errors; its 3 wording tweaks were applied (dated "not yet
  built" items so the agent doesn't repeat stale status).
- **Next session:** NAMES = `## Project:` titles plus every capitalised run after "at"/"At", each grepped verbatim in
  the sources. A new pack line like "at Some Place" must therefore be in the sources too. The pack includes the public
  email, LinkedIn, GitHub and site URLs from profile.ts, and says he lists no phone number.
- **Note:** Bio.md spells it "Maxx Potential"; the pack uses experience.ts's "MAXX Potential".

### 2026-10-20 01:10 · C1-01 · passes

- **Added:** `pyproject.toml` (livekit-agents, plugins-openai, silero and deepgram all `==1.8.8`; pydantic>=2; setuptools; dev
  extra; pytest `asyncio_mode=auto` + `live` marker; ruff E/F/W/I/B/UP), `concierge/__init__.py`, `scripts/__init__.py`,
  `tests/test_smoke.py`, `docs/plans/2026-10-20-C1-skeleton.md`, D7 in `docs/decisions.md`. Tests 0 → 1.
- **Verified:** `.harness/init.sh` built `.venv` and printed `livekit-agents 1.8.8`; `check.sh` green (ruff clean, 1 passed).
- **Next session (C1-03):** add `"concierge.testing"` to `[tool.setuptools] packages`. Read `.venv/…/livekit/`, not the
  probe venv. `LLMStream.__init__` starts tasks, so build fake streams inside async tests.
- **Correction to the initializer's note:** in 1.8.8 the turn-detector model needs **no download**. `AgentSession`
  defaults to `inference.TurnDetector()` (the local v1-mini, bundled in `livekit-local-inference`). So VAD-only must be
  set explicitly: `turn_handling={"turn_detection": "vad"}`. Details are in the plan and D7.
- **Question for Michael (D7):** keep silero VAD only, or switch to the local turn-detector model now that it needs no
  download?

## 2026-10-20 00:40 — initializer

### Feature counts

| Milestone | Features | Builds on | What it ships |
|---|---|---|---|
| C1 | 6 (C1-01…C1-06) | — | skeleton, config, knowledge pack, prompt + budgets, fake LLM, worker entry |
| C2 | 5 | C1 | SQLite store, fence, erasure, TTL, `memory_history.py` |
| C3 | 4 | C2 | preload concurrent with connect, memory block as data, greeting |
| C4 | 6 | C2 (not C3) | extractor, merge, gate, heard-text, background writer, remember/forget, offline eval twin |
| C5 | 4 | C4 | visit summary at shutdown, in-call compaction |
| C6 | 5 | C3 + C4 | room contract (topics, RPCs), metrics capture, kill switch, limits |
| C7 | 5 | C5 + C6 | scripts, live test file, deploy unit, README, MORNING.md |
| C8 | 2 | C7 | stretch: messages for Michael |

37 features. Brief: C1–C7 tonight, C8 only if everything else passes. Every milestone ends in a review + simplify
feature, and the harness merges a milestone into `main` when all its features pass, so each milestone must leave
`main` shippable (nothing half-wired; the suite green).

### State of the repo at start

Only docs and vendored sources exist: `docs/spec.md`, `docs/decisions.md`, `docs/background/memory-research.md`,
`knowledge/sources/*` (five portfolio files + `SOURCE.md`), `.env.example`, `.gitignore`, `README.md` (two lines),
`.harness/*`. **No Python yet.** C1-01 creates `pyproject.toml`, the venv, `concierge/`, `scripts/`, `tests/`.

### Environment facts a worker needs

- **Python 3.12.3** at `/usr/bin/python3`. There is no system `pip3`; use `.venv/bin/pip`. **PyPI is reachable**
  (checked: `pip download livekit-agents==1.8.8` works). The suite itself must stay offline.
- **Until `.venv` exists, read the LiveKit source from the probe venv:**
  `/tmp/voice-concierge/probe-venv/lib/python3.12/site-packages/livekit/` (livekit-agents 1.8.8, livekit-plugins-openai
  1.8.8, livekit 1.1.20, pydantic 2.14.1). After C1-01, read `.venv/lib/python3.12/site-packages/livekit/`. The
  spec's API notes (§4.10) were checked against this version.
- `.harness/init.sh` runs before every session: creates `.venv` and `pip install -e ".[dev]"` whenever
  `pyproject.toml`'s hash changes. So `pyproject.toml` needs a build backend (setuptools), `packages = ["concierge"]`
  (plus subpackages), and a `dev` extra with pytest, pytest-asyncio, ruff (and later jsonschema).
- `.harness/check.sh` runs `compileall -q concierge scripts tests`, then `ruff check .` if `.venv/bin/ruff` exists,
  then `pytest -m "not live" -q`. All three directories must exist. Register the `live` marker in
  `[tool.pytest.ini_options]` so `-m "not live"` doesn't warn, and set `asyncio_mode = "auto"`.
- Permissions (`.claude/settings.json`): shell redirection to write files may be denied; use the Write/Edit tools
  for file content. `curl` to the public internet is not in the allow list; don't rely on it. `lk`, `systemctl`,
  `pytest -m live`, `scripts/run-worker.sh` and reading `~/.config/voice-concierge/**`, `~/.livekit/**`, `.env*`
  are denied. Never try to work around a denial.
- Scratch directory: `/tmp/voice-concierge` (`HARNESS_SCRATCH`). Review diffs go there.

### LiveKit 1.8.8 API map (file paths under `site-packages/livekit/`)

Read the source before using any of these; the spec forbids guessing.

| Need | Where | Notes |
|---|---|---|
| Entry point | `agents/worker.py:300` `class AgentServer`, `:456` `rtc_session(agent_name=, on_request=)`; `agents/cli/cli.py:471` `run_app(server)` | `AgentServer(shutdown_process_timeout=…)` default 10 s (`worker.py:212`); raise to 30 for the shutdown summary |
| Job | `agents/job.py:202` `JobContext` (`.connect()`, `.room`, `.job.metadata`, `add_shutdown_callback` at :622), `:1044` `JobRequest` (`.reject()` at :1077, `.accept()`) | dispatch metadata is `ctx.job.metadata` (a str) |
| Session | `agents/voice/agent_session.py:877` `AgentSession.start(agent=, room=, room_options=, record=)`, `:120` `RecordingOptions` TypedDict (`audio`, `traces`, `logs`, `transcript`, `redaction`), `:855` `session.run(user_input=)` returns `RunResult` (`voice/run_result.py:98`) for tests | `record={"audio": False, "redaction": True}` |
| Room options | `agents/voice/room_io/types.py:110` `RoomOptions`, `:53` `TextInputOptions(text_input_cb=)`, `:46` `_default_text_input_cb(sess, ev)` (claims the turn, interrupts, `generate_reply(user_input=ev.text)`), `:25` `TextInputEvent` | **wrap** the default callback; typed turns never reach `on_user_turn_completed` |
| Events | `agents/voice/events.py:416` `ConversationItemAddedEvent(item=ChatMessage…)`, `:319` `AgentStateChangedEvent`, `:397` `MetricsCollectedEvent` (session-level, deprecated for our use) | subscribe with `session.on("conversation_item_added")` |
| Chat items | `agents/llm/chat_context.py:407` `ChatMessage` (`interrupted` :412, `transcript_confidence` :413 default None→treat as 1.0, `.metrics`), `:302` `UserMessageMetrics` (`transcription_delay`, `end_of_turn_delay`, `on_user_turn_completed_delay`), `AssistantMessageMetrics` (`llm_node_ttft` :308, `tts_node_ttfb` :330, `e2e_latency` :346) | read metrics with `.get`; `e2e_latency` may be absent |
| LLM base | `agents/llm/llm.py:34` `CompletionUsage`, `:76` `ChoiceDelta`, `:84` `ChatChunk`, `:111` `LLM`, `:155` `LLM.chat(chat_ctx=, tools=, tool_choice=, …)`, `:235` `LLMStream` (implement `_run`, push chunks to `self._event_ch`), `:545` `LLMStream.collect()`; `LLM` emits `"metrics_collected"` (:487) with `LLMMetrics` (`agents/metrics/base.py:21`: `prompt_tokens`, `prompt_cached_tokens`) | the fake LLM mirrors these exactly |
| Tool choice | `agents/llm/tool_context.py:114` `NamedToolChoice` TypedDict, `:119` `ToolChoice` | forced: `{"type": "function", "function": {"name": "emit_ops"}}` |
| Agent | `agents/voice/agent.py` `Agent(instructions=, tools=, …)`, `update_chat_ctx` at :250; `llm.function_tool` decorator | compaction applies via `update_chat_ctx` only when listening |
| OpenRouter | `plugins/openai/llm.py:469` `LLM.with_openrouter(model=, api_key=, …)` | raises `ValueError` without `OPENROUTER_API_KEY`: build lazily |
| Inference STT/TTS | `agents/inference/stt.py`, `tts.py` (model Literals; `deepgram/nova-3`, `cartesia/sonic-3` exist) | `livekit.agents.inference.STT(model=…)`, `TTS(model=…)` |
| Testing | `agents/testing.py:27` `fake_job_context(room=, job_metadata=, …)` context manager; `agents/evals/judge.py` (live only) | use with `AgentSession(llm=FakeLLM(...))` and `session.run` |
| Room RPC / text | `rtc/participant.py:518` `LocalParticipant.register_rpc_method`, `:864` `send_text(text, topic=)`, `:429` `perform_rpc` | fake these in tests with a small object that records calls |

Silero VAD ships its model inside the wheel (no download at import). The turn-detector plugin downloads models on
`download-files`, which the suite must never do. D7 default: silero VAD only (C1-01 records it).

### Design constraints that cut across milestones

- **Memory never on the turn path.** `conversation_item_added` handlers and any `on_user_turn_completed` override
  may only `create_task`, never await extraction, merge or a store write. `tests/test_critical_path.py` (C4-04)
  enforces it with a 5 s fake extractor and a static check; keep handlers trivially short.
- **Erasure wins.** The thread is created only by the preload's get-or-create. Every later write is fenced on the
  loaded version and raises `ThreadMissing` for an erased thread; nothing re-creates it. `forget_me` cancels the
  writer and sets `erased` so the shutdown callback skips extraction and summary.
- **Prefix stability.** Blocks 1–3 (`STATIC_INSTRUCTIONS`, pack, memory block) are set once at session start and
  never rewritten mid-session. New facts reach the model through the conversation.
- **The pack is the only source of facts about Michael**, built from `knowledge/sources/` only. The live portfolio
  checkout is off-limits (another run is changing it).
- **Budgets offline:** tokens ≈ characters ÷ 3.5 (`estimate_tokens`). No tiktoken.
- **pydantic for anything serialized** (state, facts, ops, contract payloads, settings). Modules ≤ 250 lines.
- **Public repo:** no hostnames, IPs, keys, visitor data. `*.db` is gitignored; tests use `tmp_path`.
- Review features write the milestone diff to `/tmp/voice-concierge/review-<M>.diff`, read it as a reviewer,
  fix Critical/Important findings test-first, apply simplifications, and append `## Review` to the plan file.
  "`<X commit>`" in a step means the merge-base or last commit of the previous milestone; find it with
  `git log --oneline` (commit messages carry the feature id).

### Suggested module map (plans may refine, keep names where steps cite them)

```
concierge/
  config.py        Settings + lazy provider factories (C1-03)
  knowledge.py     load_pack() (C1-02)
  prompt.py        STATIC_INSTRUCTIONS, MEMORY_HEADER, estimate_tokens, build_instructions (C1-04)
  agent.py         ConciergeAgent(Agent) + function tools remember/forget (C1-04, C4-04)
  dispatch.py      DispatchInfo from job metadata (C1-05)
  text_input.py    wrapped text callback tagging channel=text (C1-05)
  worker.py        AgentServer, rtc_session entrypoint, on_request kill switch (C1-05, C6-04)
  testing/fake_llm.py  FakeLLM / FakeLLMStream (C1-03)
  models.py        VisitorState, Fact, SLOTS, journal types (C2-02)
  store.py (or store/)  Store: schema, fence, facts, journal, metrics, erasure, TTL (C2)
  memory_block.py  render_memory_block (C3-02)
  preload.py       preload() concurrent with connect (C3-02)
  greeting.py      greeting_instructions (C3-03)
  session.py       start_session: wiring of everything per job (C3-03 onward)
  ops.py, gate.py, merge.py, extractor.py, turns.py, memory_writer.py (C4)
  evals/runner.py  offline eval twin (C4-05)
  summary.py, compaction.py (C5)
  contract.py, publish.py, metrics.py, rpc.py, limits.py (C6)
scripts/  memory_history.py (C2-04), eval_memory.py, latency_report.py, run-worker.sh (C7-02), messages.py (C8)
evals/memory/*.yaml (C4-05)   tests/contract/*.schema.json (C6-02)   deploy/voice-concierge.service (C7-02)
```

### Questions for Michael (defaults taken; reversible)

1. **Turn detection.** Default D7: silero VAD only, because the turn-detector plugin needs a model download and the
   suite is offline. Switching later is one line in `config.py` plus `download-files` in MORNING.md. OK?
2. **Models.** Conversation, extractor and summarizer all default to `openai/gpt-4.1-mini` on OpenRouter (B1);
   STT `deepgram/nova-3`, TTS `cartesia/sonic-3` on LiveKit Inference (ids present in the 1.8.8 Literals). Sessions
   cannot reach OpenRouter's model list from here, so the OpenRouter id is taken from the spec, not re-verified.
   Change via `CONCIERGE_*_MODEL` env vars.
3. **Session cap on an erased visitor.** Daily counts are keyed by a hash of the visitor id and survive "Forget me"
   (B7). A visitor who presses "Forget me" and returns the same day keeps counting toward 5. Intended?
4. **C8** (messages for Michael) runs only after C7 passes, per the brief.

Answer in `INBOX.md` under `## Answers`; sessions check it at startup.
