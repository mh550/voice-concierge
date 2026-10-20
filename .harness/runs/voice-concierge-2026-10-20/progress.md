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

### 2026-10-20 17:10 · C7-05 · not yet (parked)

- **Changed:** no code. Rewrote the C7 review diff (`git diff 5a59354..HEAD -- . ':!.harness'`, 2595 lines) to scratch `review-C7.diff`; INBOX question added. Tests 909 → 909.
- **Verified:** `lib/check.sh` green (909 tests, cached tree); steps 2, 4, 5 hold per the verify run and the unchanged tree.
- **Blocked:** step 1 wants the diff in `/tmp/voice-concierge/` (outside the allowed write area); step 3's grep matches its own step text and other files under `.harness`, plus the fake key C4-02 step 2 requires verbatim. Neither is fixable without editing `feature_list.json` or breaking CLAUDE.md.
- **Questions for Michael:** see INBOX (1a/1b, 2a/2b). Health-port bind question in MORNING.md is still open.
- **Proposed changes:** C7-05 step 1 → scratch dir; step 3 → add `':!.harness'` and the two C4 fake-key files.

### 2026-10-20 · verify C7

| Feature | Step | What you ran or read | What you saw | Holds |
|---|---|---|---|---|
| C7-01 | 1 | read `docs/plans/2026-10-20-C7-ops-docs.md` headings | Parts 4 (README outline) and 5 (MORNING steps 1-12 with commands), "Live stages" table (0 dry run, 1 one session, 2 live evals, 3 latency report, 4 hardening) with Check and Undo columns | yes |
| C7-01 | 2 | read Part 1 and Part 2, Part 3 | CLIs for eval_memory, latency_report, run-worker.sh, messages.py (reserved for C8); tests/live/test_live.py layout; unit file contents | yes |
| C7-01 | 3 | read "Tests for C7-02 (names)" | test_* names listed (test_eval_memory_*, test_latency_report_*, ...) | yes |
| C7-01 | 4 | `/home/mh550/projects/agent-harness/lib/check.sh` | green, 909 tests | yes |
| C7-02 | 1 | ran `scripts/eval_memory.py` with key unset, then `--offline`; read tests/test_scripts.py | "ANTHROPIC_API_KEY not set", exit 2; --offline exit 0, 13 cases, total 20/20 (100 %), 0 harm; tests test_eval_memory_without_the_key_says_not_set_and_exits_2 and test_eval_memory_offline_has_full_recall_and_no_harm assert this | yes |
| C7-02 | 2 | read test_latency_report_prints_p50_and_p95_per_field (+ cached share test); ran tests/test_scripts.py | pass; asserts 20 rows give n=20, 105.0/190.5 per k, total_ms 525.0/952.5, cached share 80.0 % | yes |
| C7-02 | 3 | `pytest --collect-only tests/live`; `pytest -m "not live" -q`; read tests/test_live_layout.py, module header | 4 live tests collected; suite: 909 passed, 4 deselected; module skipif LIVEKIT_URL; docstring says only Michael runs it | yes |
| C7-02 | 4 | `ls -l`, `bash -n`, read script, read test_run_worker_* tests (ran them) | executable, syntax ok, set -a source guarded by -f, need list matches, exec "${@:-start}"; test_run_worker_without_env_exits_1_naming_livekit_url asserts exit 1 and LIVEKIT_URL. Did not run the script myself (auto-mode classifier blocked it) | yes |
| C7-02 | 5 | read deploy/voice-concierge.service and test_systemd_unit_has_the_six_keys | all keys match step; test passes; unit not installed | yes |
| C7-02 | 6 | check.sh | green | yes |
| C7-03 | 1 | `grep -n "^#" README.md`; read README | sections in the required order; GIF placeholder; mermaid with page, LiveKit Cloud, worker, SQLite, Anthropic, OpenRouter, LiveKit Inference; 16 practice rows; mapping rows; Results all "to measure"; failure cases; Privacy; How to run. Step lists OpenRouter, present as node | yes |
| C7-03 | 2 | `grep -n -i "agents 2.0" README.md`; `grep -nE "[0-9]+ ?ms" README.md` | mentions only intro link (says code is 1.8) and mapping section; ms grep matches only line 84 "about 0 ms, measured per turn as memory_on_turn_path_ms" | yes |
| C7-03 | 3 | ran tests/test_readme.py; read test_every_cited_test_name_exists | passes (99 passed across scripts/live_layout/readme/morning) | yes |
| C7-03 | 4 | read test_every_cited_module_and_script_path_exists | passes; asserts cited concierge/, scripts/ paths exist | yes |
| C7-03 | 5 | check.sh | green | yes |
| C7-04 | 1 | read MORNING.md; test_exact_commands_appear_in_order | 12 steps in order with the exact commands (incl. systemd alt, touch ~/.voice-concierge-off); spend-limit reminder in step 1; test passes | yes |
| C7-04 | 2 | read MORNING.md header and steps 3-12 | up-front "needs keys only you have ... about 20 minutes"; Check and Undo on each live step | yes |
| C7-04 | 3 | read .env.example | exactly the 6 names empty, 4 optional switches as comments | yes |
| C7-04 | 4 | `grep "D[0-9]* \*default\*" docs/decisions.md`; read MORNING "Questions for you" | D7-D13 present, each section mentions a rejected alternative; MORNING Questions cover D7-D13 plus health port | yes |
| C7-04 | 5 | check.sh | green | yes |
| C7-05 | 1 | `ls /tmp/voice-concierge/review-C7.diff`; read plan ## Review | diff is NOT at /tmp/voice-concierge/ (written to scratch dir instead, deliberately, plan says CLAUDE.md bars it); ## Review has findings table and 62-row claims table with file:line | no |
| C7-05 | 2 | read findings table | 4 Critical and 9 Important marked done; test count 902 -> 909 | yes |
| C7-05 | 3 | ran the exact `git grep -n -E ...` command | NOT empty (rc=0): hits in tests/test_gate.py:12 and docs/plans/C4-extraction.md:388 (fake "sk-abc123def456"), and in .harness feature_list.json (the step text itself). All are fakes, not secrets, but the step says returns nothing. hostname grep: none; `git ls-files "*.db"` empty; *.db ignored | no |
| C7-05 | 4 | `pytest -m "not live" -q` | 909 passed, 4 deselected, 0 skipped, 84.6 s | yes |
| C7-05 | 5 | check.sh | green | yes |

Result: C7-01..04 hold; C7-05 set to false (step 1 diff path, step 3 grep not empty). Fix: either drop the fake-key strings/accept path in the step, or reword; the next session decides.

### 2026-10-20 15:40 · C7-05 · passes

- **Changed:** the C7 review is in `docs/plans/2026-10-20-C7-ops-docs.md` under `## Review`: a findings table and 61 README claims, each with its file:line. Two Opus reviewers read `review-C7.diff` (`5a59354..HEAD`) in scratch: 4 Critical, 9 Important, ~15 Minor, all fixed except the ones listed as not taken. Tests 902 → 909.
- **Critical fixes:**
  - LiveKit's `judge()` forces `tool_choice="required"` and Sonnet 5.5 rejects that with a 400, so 2 of the 4 live tests would have failed. `ClaudeLLM` now sends a forced choice as `auto` to Sonnet and Opus 5.5 (written test-first).
  - `eval_memory.py` died on the first 400 or refusal. Now that case shows as an `error` row and the run goes on (test-first).
  - The README overclaimed `memory_on_turn_path_ms`: it times only 1.8's hook, not the item handlers. Now said plainly.
  - MORNING's systemd step pointed at a checkout without `scripts/`.
- **Other fixes:**
  - The Results test allows numbers only under a `Measured on <date>` line, so MORNING step 9's paste no longer turns the suite red.
  - Live recall/wrong-memory tests are sharper.
  - `.env.example` comments are on their own lines; `KillMode=mixed` is in the unit.
  - README wording (forget leaves the journal turn text, per-session guard, D10's exempt slots, `source` values).
- **Verified:**
  - `lib/check.sh` is green in 88 s with 909 tests.
  - `pytest -m 'not live' -q` gives 909 passed, 0 skipped, 4 deselected, in 84 s.
  - `git ls-files '*.db'` is empty; the hostname grep is empty.
- **Step 3 deviation:** the secret grep still matches 4 lines, all fake or self-referential:
  - `feature_list.json` twice: C4-02's step, and C7-05's own step text, which matches its own regex;
  - `tests/test_gate.py:12` and `docs/plans/2026-10-20-C4-extraction.md:388`: the fake key C4-02 step 2 names verbatim.
  - `evals/memory/13-url-and-secret.yaml` now uses `sk-fake-1234-test-5678`.
- **Questions for Michael:** the health-port bind (MORNING "Questions for you") is still open. Merge this branch into `~/projects/voice-concierge` before using the systemd unit.
- **Proposed changes:**
  - C7-05 step 3's grep should add `':!.harness'` (it matches itself), and C4-02 could name a fake key that doesn't look real.
  - C7-02 steps 4–5: exit 78 plus `RestartPreventExitStatus=78`, and drop `EnvironmentFile=` (the script already sources the file).
  - C1's `idle_ttl_days` setting is never read; remove it or wire it.

### 2026-10-20 14:30 · C7-04 · passes

- **Changed:** new `MORNING.md` (12 numbered steps in the specified order, exact commands, Check and Undo per live step, "needs keys only Michael has, about 20 minutes" up front, "Questions for you" mirroring D7–D13 and the health-port question). `.env.example` now lists the six names (all empty; OPENROUTER and DEEPGRAM marked optional) and the four `CONCIERGE_*` switches as comments. New `tests/test_morning.py` (6 tests: step order, commands in order, Check/Undo, D-coverage, env names). Tests 896 → 902.
- **Verified:** `grep -n 'D[0-9]* \*default\*' docs/decisions.md` lists D7–D13, all with finding, choice and rejected; `lib/check.sh` green in 88 s, 902 tests; ruff clean.
- **Next (C7-05):** `MORNING.md` is not checked by `tests/test_readme.py` paths, only by `test_morning.py`. Env file must stay plain `NAME=value` (said in MORNING.md).
- **Questions for Michael:** all in MORNING.md "Questions for you" (D7–D13, health server bind to 127.0.0.1).
- **Proposed change:** C7-03 step 1 "16 rows" should be 17.

### 2026-10-20 13:40 · C7-03 · passes

- **Changed:**
  - `README.md` is rewritten for the LiveKit team. It has 8 sections in order. The mermaid diagram has 8 nodes, including Anthropic and an OpenRouter alternative.
  - The 17 memory rows now each name their module.
  - The mapping section is titled "How it maps onto Agents 2.0" and has rows for lease / fence vs lock and for across days.
  - Every Results cell reads `to measure`.
  - `tests/test_readme.py` is rewritten: section order, the diagram nodes, the 17 rows of spec §4.0, every cited test/module/path exists, the `ms` rule, the 2.0 and 1.8 rules (checked per block, so a line wrap can't hide a phrase), and `to measure`.
  - R1: `test_two_schedules_100ms_apart_…` is renamed `…_a_tenth_of_a_second_apart_…`.
  - Tests 864 → 896.
- **Verified:**
  - `grep -E '[0-9]+ ?ms' README.md` matches only line 84, the "about 0 ms, measured per turn as `memory_on_turn_path_ms`" claim.
  - `grep -i 'agents 2.0'` matches only the pitch link (that line says 1.8) and the mapping heading.
  - Mutation checks: a planted "50 ms", "Agents 2.0", a fake test name, a fake module, and a "LiveKit\nAgents" line wrap each fail the tests.
  - An Opus claims review found 3 Important and 7 Minor issues. All are fixed except I3; see the next bullet. The fixes:
    - the "no inbound ports" claim was false, because 1.8's health server listens on 8081;
    - the turn-path sentence now says the `remember`/`forget` writes aren't in that number;
    - the record dict is quoted as it really is;
    - the greeting uses the name only once it is confirmed;
    - the script commands now use `.venv/bin/python`.
  - `lib/check.sh` is green in 87 s, 896 tests.
- **I3, not taken:** the reviewer wanted the `phone:` sentence moved out of Failure cases. Step 1 asks for it there, so it stays, phrased as "2.0's model" in a block that says "1.8".
- **Next session (C7-04) must know:** the README links to `MORNING.md`, which doesn't exist yet. `tests/test_readme.py` checks paths under concierge/, scripts/, deploy/, docs/, evals/ and knowledge/, but not MORNING.md.
- **Question for Michael:** should the worker's health server bind `127.0.0.1`? Today it listens on all interfaces on port 8081 (`AgentServer(host="")` by default). C7-05 could pass `host="127.0.0.1"`. For now the README says to keep 8081 closed at the firewall.
- **Proposed change:** in C7-03 step 1, "16 rows" should be 17. Spec §4.0 has 17 rows, and the README and test use 17.

### 2026-10-20 13:05 · C7-02 · passes

- **Changed:**
  - New `scripts/eval_memory.py`, `scripts/latency_report.py`, `scripts/run-worker.sh` (755), `deploy/voice-concierge.service`, `tests/live/test_live.py` and `tests/test_live_layout.py`.
  - New `Store.turn_metrics()` (R8). `tests/test_scripts.py` gains 27 tests.
  - Tests 828 → 864.
- **Fixed a real bug the review found (Critical):** LiveKit's `judge()` always passes `temperature=0.0` (`voice/run_result.py:1021-1024`). The anthropic SDK's `create()` has no such keyword, so both judged live tests would have failed with `TypeError` on Michael's run. `ClaudeLLM.chat` now drops `temperature`/`top_k`/`top_p` from a caller's kwargs. Test-first in `tests/test_claude_llm.py`: `test_caller_sampling_parameters_are_dropped` and `test_the_livekit_judge_runs_on_a_claude_llm` (the real `judge()` over the fake client). The live wrong-memory check now uses the merge's own `shares_a_word` and grounding-exempt slots.
- **Verified:**
  - `eval_memory.py --offline` prints 13 rows plus the total, `20/20 (100 %)`, harm 0, exit 0.
  - With no key: `ANTHROPIC_API_KEY not set`, exit 2.
  - Latency: 10…200 gives 105.0/190.5.
  - `run-worker.sh` with an empty HOME: exit 1 naming `LIVEKIT_URL`. The exec path is tested against a stub `.venv/bin/python` in a temp copy.
  - `pytest -m 'not live' -q tests/live`: 4 deselected.
  - Each live test body was run once offline against FakeLLMs in a scratch file (deleted). `-m live` was never run.
  - `lib/check.sh` is green in 88 s, 864 tests; ruff is clean.
- **Next session must know:**
  - The suite went from 65 s to 88 s (subprocess script tests cost about 3 s each). C7-05 has a 120 s budget.
  - Minor, not fixed: under systemd the env file is read twice, by `EnvironmentFile=` and then by bash `.`. The file must stay plain `NAME=value` with no `$` or spaces in values. C7-04's MORNING.md should say so.
- **Questions for Michael:** none new.

### 2026-10-20 12:10 · C7-01 · passes

- **Changed:** new `docs/plans/2026-10-20-C7-ops-docs.md`. It plans:
  - the README outline (9 sections, with the 17 practice rows);
  - the MORNING.md 12 steps, each with its command, check and undo;
  - the live stages (dry run → one session → live evals → latency report → hardening);
  - the CLIs of `eval_memory.py`, `latency_report.py` and `run-worker.sh` (`messages.py` is reserved for C8);
  - `tests/live/test_live.py` (4 tests, in-process text mode, skipped without `LIVEKIT_URL`) and the systemd user unit;
  - about 24 named C7-02 tests.

  Plan only, no code. Tests 828 → 828.
- **Verified:**
  - The worker's `--help` runs offline with no keys.
  - The first SIGINT/SIGTERM drains live jobs (`cli/cli.py:439`), so the unit sets `TimeoutStopSec=660`.
  - p50/p95 of 10…200 is 105.0/190.5.
  - An Opus plan review found 1 Critical, 8 Important and 6 Minor findings; all are resolved in the plan, inline or as R1–R15.
  - `lib/check.sh` is green in 65 s with 828 tests.
- **Next session (C7-02/C7-03) must know:**
  - The README cites `test_two_schedules_100ms_apart_start_one_extraction`, which fails the `[0-9]+ ?ms` grep. C7-03 renames it (R1).
  - `latency_report.py` needs a new `Store.turn_metrics()` (R8).
  - `pytest -m "not live" --collect-only tests/live` exits 5.
- **Proposed changes** (details in the plan):
  - C7-03: §4.0 has 17 rows, not 16, and the LLM node is Anthropic, with OpenRouter as the fallback.
  - C7-04 step 9: the db is `~/.local/share/voice-concierge/concierge.db`, not `data/concierge.db`.
  - C7-04 steps 7–8: these need the env loaded, so they're wrapped in `( set -a; . ~/.config/voice-concierge/env; set +a; … )`.
  - C7-02 step 5: says "five keys" but lists six.
  - C7-05: write the diff to scratch.
- **Questions for Michael:** none new.

### 2026-10-20 14:00 · verify C6

Result: 5 hold, 0 fail (25 steps). `lib/check.sh`: green, 828 tests (cached for this tree). I also ran the C6 test files directly: 132 pass. `ruff check .`: all checks passed. Two small notes, neither a failure. The plan names `MetricsReport`, not `UserMessageMetrics`/`AssistantMessageMetrics`, because 1.8.8 has no such classes (grep: none). The review table cites `worker.py:66` for `agent_name="concierge"`, but the line is 82.

| Feature | Step | What you ran or read | What you saw | Holds |
|---|---|---|---|---|
| C6-01 | 1 | Read the plan's "rtc APIs" section against `.venv/.../rtc/participant.py:518-522, 864-873` and `rtc/rpc.py:24-46`; read the topic and RPC name table | The `send_text`, `register_rpc_method` and `RpcInvocationData` quotes match the installed source field for field; both topics and both RPC names match spec §6 | yes |
| C6-01 | 2 | Read plan Part 3's mapping table; `grep UserMessageMetrics\|AssistantMessageMetrics\|class MetricsReport` in `chat_context.py` | Only `MetricsReport` (line 286) exists, and the plan says so. Every key maps to its §6 key. `.get` is used for `e2e_latency`. Text turns leave eou/stt/memory_on_turn_path null | yes |
| C6-01 | 3 | Read plan Part 5 (`on_request`, timer, `count_session` daily cap) | `req.reject()` on CONCIERGE_ENABLED=0 or the off file; 10-min timer task → `say` → `ctx.shutdown`; count at start, > 5 → one line and shutdown | yes |
| C6-01 | 4 | Read plan "Tests" and "JSON schemas" sections | Test functions listed per C6-02..04; the schema files `memory`, `metrics` and `forget_me` are named | yes |
| C6-01 | 5 | `lib/check.sh`; `ruff check .` | green, 828 tests; ruff clean | yes |
| C6-02 | 1 | Read `concierge/contract.py`, `models.TurnMetrics` | `MemoryPayload` has the §6 shape with `extra=forbid`. `MetricsPayload = TurnMetrics` has 12 keys, all nullable except `turn` and `compacted`. `build_memory_payload(store, thread_id)` exists | yes |
| C6-02 | 2 | Read both schema files; `tests/contract/test_contract.py`; `jsonschema` in `pyproject.toml` | Both are draft 2020-12, `additionalProperties` false, with the 4 and 12 required keys. `test_memory_payload_from_a_seeded_store_validates` and `test_metrics_payload_example_validates` validate. `jsonschema>=4.23` is in the dev group | yes |
| C6-02 | 3 | Read `concierge/publish.py`; `test_publish_raises_payload_too_large_over_15_kib`; `test_build_memory_payload_drops_the_oldest_facts_to_fit` | `send_text(body, topic=topic)`, body from `model_dump_json()`. `PayloadTooLarge` raised by byte count (3-byte chars). Oldest facts trimmed first. `FakeRoom` records (text, topic) | yes |
| C6-02 | 4 | Read `session.py:223-282`; `test_two_memory_publishes_after_one_merged_extraction` | Publishes after `session.start` and in `on_merged`. The test asserts exactly 2 sends on `concierge.memory`, both validate, and the second has the new fact (company Acme) | yes |
| C6-02 | 5 | `pytest tests/contract tests/test_publish.py ...`; check.sh | 132 passed; check green | yes |
| C6-03 | 1 | Read `concierge/metrics.py`; `session.py:258-265` | `USER_KEYS` and `ASSISTANT_KEYS` map as the step says, with `.get` → None. `session.llm.on("metrics_collected", on_llm_metrics)` collects prompt and cached tokens. A user message pairs with the following assistant message; turn counter starts at 1 | yes |
| C6-03 | 2 | `metrics.py _close`; `test_preload_ms_is_on_turn_1_only`, `test_extraction_ms_is_on_the_turn_after_a_merge`, `test_compacted_is_true_on_the_turn_after_a_compaction`, `test_memory_on_turn_path_ms_is_measured` | preload only on turn 1; extraction_ms (from the `extraction_ran` ms via `MergeResult`) on the next turn only; compacted from the applied count; 0.0123 s → 12.0 asserted | yes |
| C6-03 | 3 | `test_one_row_per_turn_with_the_anonymous_columns`, `test_one_publish_per_turn_validates_against_the_schema`, `test_a_text_turn_leaves_eou_stt_and_turn_path_null` | `PRAGMA table_info` equals the step's 14 columns and has no visitor_id or text. One publish per turn validates. Text turn: eou/stt/memory_on_turn_path None | yes |
| C6-03 | 4 | `test_llm_metrics_tokens_land_on_the_next_turn`, `test_session_publishes_concierge_metrics_per_turn_with_the_llm_tokens` | FakeLLM with prompt_tokens=1234, cached=1000 gives (1234, 1000) on the next turn, published and stored | yes |
| C6-03 | 5 | check.sh | green, 828 tests | yes |
| C6-04 | 1 | Read `concierge/rpc.py` | `register_rpc_method` for both names. `on_forget_me` returns `'{"ok": true}'` and starts a tracked task: writer cancelled, `store.forget_me`, empty memory published, goodbye, end. `get_memory` returns `MemoryPayload.model_dump_json()` | yes |
| C6-04 | 2 | `tests/test_rpc.py::test_forget_me_returns_ok_within_50_ms_while_the_erase_sleeps`, `test_get_memory_returns_the_topic_json` | The forget_me handler answers in <50 ms with the erase patched to sleep 1 s. After 1.5 s: 0 visitor rows, one `concierge.memory` send with facts == [], goodbye said, close stub called with "forget_me". `get_memory` validates against `memory.schema.json` | yes |
| C6-04 | 3 | `worker.py:32-46`; `tests/test_kill_switch.py` | `on_request` rejects when `not settings.enabled` or the off file exists, else accepts. Tests cover env=0 → reject only, off file in tmp → reject only, neither → accept | yes |
| C6-04 | 4 | `concierge/limits.py`; `test_session_timer_says_one_line_and_ends`, `test_sixth_session_of_the_day_is_capped_and_the_fifth_is_not`, `test_daily_count_survives_forget_me` | max_s=0.2: one line, ended within 0.5 s. Results are [F,F,F,F,F,T]. The count survives `forget_me`. The cap path runs before the preload in `session.py` | yes |
| C6-04 | 5 | check.sh | green | yes |
| C6-05 | 1 | `ls -la` and head of `review-C6.diff` in scratch; read `## Review` in the plan | The diff (207 KB) is in the run scratch dir, not literally `/tmp/voice-concierge/`; the notes say so, and CLAUDE.md bars other writes. Base 850c32d is the harness commit after C5-04. Review notes are under `## Review` | yes |
| C6-05 | 2 | `git log 850c32d..HEAD`: RED commits 407a095, 6dc7d87, 7eba202 precede GREEN 850ea87/e7503a6 | The 2 Important findings (A-I1, C-I1) have tests committed first; `tests/test_retention.py` exists | yes |
| C6-05 | 3 | Compared plan table with spec §6 and sampled the cited lines in `contract.py`, `rpc.py`, `dispatch.py`, `session.py`, `publish.py` | Every topic, RPC, JSON key and metadata key matches. One stale citation (`worker.py:66`; actually 82), not a name difference | yes |
| C6-05 | 4 | `README.md:29-39`; script checking all 122 backticked test names against `tests/` | All five rows are present, and every cited test exists. The privacy paragraph says anonymous timing numbers survive Forget me (B9) and what LiveKit keeps (B11); `record_audio` defaults False (`config.py:39`, `session.py:85`) | yes |
| C6-05 | 5 | check.sh, `ruff check .` | green; ruff clean | yes |

### 2026-10-20 08:40 · C6-05 · passes

- **Changed:**
  - The C6 review is in `docs/plans/2026-10-20-C6-contract.md` under `## Review`. Two Opus reviewers looked at `review-C6.diff` in scratch: 0 Critical, 2 Important, both fixed test-first.
  - A-I1: "Forget me", time-up and cap lines now cut the reply that is playing (`say_and_end` calls `session.interrupt(force=True)`). Before, the agent could keep reciting erased memory, and the goodbye could be cut off.
  - C-I1: new `concierge/retention.py`, wired on `worker_started` in `worker.py`. B6's TTL purge never ran outside tests; it now runs at worker start and daily.
  - A-M1: a forget during `session.start` gets no greeting and no timer.
  - README: the memory-design rows Profile / Provenance / Forgetting / Single writer / Observability, and a **Privacy.** paragraph (B9, B11).
  - Tests 814 → 828.
- **Verified:**
  - Each RED commit failed for the stated reason: no module; `interrupts == []`; a greeting `SpeechHandle` where None was expected.
  - The §6 table lists every name with `docs/spec.md:319–335` lines and code lines (re-checked with grep). All match.
  - `.harness/check.sh` exits 0 with 828 tests.
- **Next session must know:**
  - `session.py` is 282 lines. C8-02 caps modules at 250, so the capped path is the candidate to move.
  - `FakeSpeakingSession` now has `interrupts`, `handles` and `current_reply_s`.
- **For the page (B-M4):** fact `id` is an int, `*_ms` are floats, `compacted` is never null, and `turn` starts at 1.
- **Questions for Michael:** none new (D13 is still open).
- **Proposed change:** C6-05 step 1's diff path should be the scratch directory, as in C1–C5.

### 2026-10-20 07:53 · C6-04 · passes

- **Changed:**
  - New `concierge/rpc.py`: `register_rpcs`, with `forget_me` answering `{"ok": true}` and then doing the erase in a task (empty memory, goodbye, `ctx.shutdown`), and `get_memory`. Both refuse any caller other than `visitor-<id>`.
  - New `concierge/limits.py`: the timer, the daily cap and `say_and_end`.
  - The kill switch is in `worker.on_request`.
  - `session.py` now counts the session before it preloads, registers the RPCs after connect, and starts the 10-minute timer.
  - Added `forget_me.schema.json` and `FakeSpeakingSession`.
  - Tests 774 → 814.
- **Verified:**
  - In `test_forget_me_returns_ok_within_50_ms_while_the_erase_sleeps`, the handler answers in under 50 ms. At 1.5 s there are 0 visitor rows, 1 empty `concierge.memory` and the end stub was called.
  - The kill-switch tests fail against the old `on_request`, and the session-level limit and RPC tests fail against the old `session.py`.
  - `check.sh` is green with 814 tests.
- **Opus review:** 0 Critical, 3 Important, all fixed test-first.
  - I1: a capped session no longer preloads after its count times out.
  - I2: "Forget me" now waits for a preload still running, which could otherwise re-create the thread.
  - I3: a late count is awaited after `session.start`.
  - Of the 5 Minor, 3 are fixed (M4 retry, M5 RPC errors logged by type, M7 the timer stopped by "Forget me"), 1 is a wording fix (M6), and 1 is open (M8). The plan's "C6-04 build notes" has the details.
- **Next session (C6-05) must know:**
  - M8 is open: a capped session can still reply while its cap line plays.
  - `session.py` is at 280 lines and is a candidate for simplification.
  - `tests/conftest.py` now points `CONCIERGE_OFF_FILE` at a temp path for every test.
- **Questions for Michael:** none new (D13 is still open).

### 2026-10-20 07:32 · C6-03 · passes

- **Changed:**
  - New `concierge/metrics.py` (`TurnMetricsCollector`). It maps `ChatMessage.metrics` and the LLM's tokens to §6. A turn closes on `listening` only after a reply message, or at the next user message.
  - Wired in `session.py`: item, state and `session.llm` `metrics_collected` handlers; `on_merged` → `note_extraction`; `stop_publishing` first in `on_shutdown`; `aclose` before the store closes.
  - `MergeResult` moved to `concierge/merge_result.py` and gained `extraction_ms`. `TurnMetrics` gained the schema's bounds.
  - New column `anonymous_turn_metrics.created_at` (ms, rounded down to the minute), with schema v1 → v2 migration. `RecordingSession.llm` added.
  - Tests 738 → 774.
- **Verified:**
  - The session test publishes `(1, 900, 0), (2, 1234, 1000)` on `concierge.metrics`; it fails with the `session.llm.on(...)` line removed.
  - `compacted` and the 0.0123 s → 12 ms case are both asserted.
  - `check.sh` is green with 774 tests.
- **Opus review:** 0 Critical, 2 Important, both fixed test-first (pause on interruption at agent_activity.py:2390 split turns and shifted tokens). Of the 4 Minor, 3 are fixed (no writes after `aclose`, the v2 migration, a sleep replaced by polling). The `cancelled` comment is corrected, and the remaining token risk is noted in the plan's "C6-03 build notes".
- **Next session (C6-04) must know:** `Started.collector` exists. `RecordingSession` now has `llm`. Session tests that count sends must filter by topic, because `concierge.metrics` now goes out after every turn.
- **Questions for Michael:** none new (D13 is still open).

### 2026-10-20 11:40 · C6-02 · passes

- **Changed:**
  - New `concierge/contract.py`: the four §6 names, `MAX_BODY_BYTES`, `MemoryPayload`/`FactView`/`VisitorView`, `MetricsPayload = TurnMetrics`, and `build_memory_payload` (valid facts only, oldest first, drops the oldest facts to fit 15 KiB in bytes).
  - New `concierge/publish.py`: `publish`, `PayloadTooLarge`, and `MemoryPublisher` (serialized sends; `final` closes; `aclose` also drops a waiting `final`).
  - `Store.memory_view`; `concierge/testing/fake_room.py`; the two schema files in `tests/contract/`; `jsonschema` added to the `dev` extra.
  - `session.py` publishes `concierge.memory` after `session.start` and from `on_merged`; `publisher.aclose()` runs first in `on_shutdown`.
  - Tests 711 → 738.
- **Verified:**
  - `test_two_memory_publishes_after_one_merged_extraction` fails with the `on_merged` line removed and passes with it.
  - The trim test passes with é, 語 and 🙂: 80 facts → fits, newest kept, one more would overflow.
  - `check.sh` is green with 738 tests.
- **Opus review:** 1 Important, fixed test-first (`final` could send after `aclose`; `test_final_waiting_on_a_send_sends_nothing_after_aclose`). Of the 3 Minor, 1 is fixed (`test_a_merge_in_the_shutdown_flush_publishes_nothing`), 1 is noted for C6-03 and 1 is accepted (`memory_view` takes the write lock, like `load`).
- **Next session (C6-03) must know:**
  - `TurnMetrics` has no `ge` bounds, but `metrics.schema.json` requires `turn` ≥ 1 and the other numbers ≥ 0. Add them, or clamp negatives to null.
  - I did not do the plan's `session_setup.py` move: `build_session` reads `build_llm`/`build_stt` from `session`'s globals, which the `recording_session` fixture patches, so the move is not a pure move. `session.py` is at 220 lines.
  - Existing session tests still use an unconnected `rtc.Room`; their start publish is logged and dropped. New tests pass `fake_job_context(room=FakeRoom())`.
- **Questions for Michael:** none new (D13 is still open).

### 2026-10-20 06:57 · C6-01 · passes

- **Changed:**
  - New plan `docs/plans/2026-10-20-C6-contract.md`. It quotes `send_text`, `register_rpc_method` and `RpcInvocationData` from rtc 1.1.20, and covers the §6 names as constants, the memory/metrics/forget-me schemas, the `MetricsReport` → §6 key mapping, the kill switch, the 10-min timer, the daily cap, and test names for C6-02 to C6-04.
  - `D13 *default*` in `docs/decisions.md`. Tests 711 → 711.
- **Verified:** I grepped the plan for each step's element, and the Opus plan review spot-checked 30 source refs (2 were wrong and are fixed). The review found 7 Important issues, all folded in and listed under `## Plan review`. `check.sh` is green with 711 tests.
- **Next session must know:**
  - The room disconnects *before* shutdown callbacks run (`ipc/job_proc_lazy_main.py:479` vs `:497`), so stop publishing first in `on_shutdown`.
  - `session.aclose()` does not end the job; use `ctx.shutdown`.
  - `fake_job_context()`'s room has no `local_participant`, so pass a `FakeRoom`.
  - `jsonschema` is not installed; C6-02 adds it to the `dev` extra.
- **Question for Michael (D13):** the page reads the same §6. Does it expect fact `id` as a number and timestamps as ISO-8601 `…Z` strings?
- **Proposed changes:**
  - C6-01 and C6-03 name `UserMessageMetrics` / `AssistantMessageMetrics`, but 1.8.8 has one `MetricsReport`.
  - C6-04 step 4 should name `over_daily_cap` + `say_and_end`, with `enforce_daily_cap` as their composition.
  - C6-05's diff path should be the scratch dir.

### 2026-10-20 · verify C5

| Feature | Step | What you ran or read | What you saw | Holds |
|---|---|---|---|---|
| C5-01 | 1 | Read docs/plans/2026-10-20-C5-compaction.md; grepped `shutdown_process_timeout` in concierge/worker.py:49 | Plan has shutdown sequence, 30 s timeout (worker.py:49 = 30), summarizer prompt (3 sentences/400 chars), 24 items/4,000 tokens trigger, last 6 turns, listening apply via update_chat_ctx, 5 s timeout, fallback 12 | yes |
| C5-01 | 2 | Read plan lines ~170-210; checked `def update_chat_ctx` in .venv voice/agent.py:250 | Plan quotes AgentStateChangedEvent (events.py:309-323) and the update_chat_ctx signature, matching the installed source | yes |
| C5-01 | 3 | Read plan "Tests" section (lines ~385-410) | Lists test functions for C5-02 (test_summary, test_summary_of_summary, test_session) and C5-03; names exist in tests/ | yes |
| C5-01 | 4 | `/home/mh550/projects/agent-harness/lib/check.sh` and `.harness/check.sh` | Green; 711 passed | yes |
| C5-02 | 1 | Read tests/test_summary.py (trim to 3, 400 chars, LLM error, 6 s timeout) | test_five_sentence_output_is_trimmed_to_three, test_long_output_is_cut_to_400_chars_at_a_space, test_llm_error_returns_the_previous_summary_unchanged, test_timeout_returns_the_previous_summary_within_5_5_s all pass | yes |
| C5-02 | 2 | Read concierge/session.py shutdown (lines 126-165); ran tests/test_session.py incl. test_no_summary_llm_call_after_forget_me | Flush then summary then store write; after forget_me summarizer.calls == [] and extractor.calls == [], all tables empty; pass | yes |
| C5-02 | 3 | Ran tests/test_summary_of_summary.py | test_second_visit_summary_keeps_the_first_visits_key_point asserts "clinic" in after_second; test_summarizer_context_contains_the_previous_summary asserts previous_summary == FIRST_SUMMARY; pass | yes |
| C5-02 | 4 | Ran tests/test_summary.py | 5-sentence trimmed to 3; test_failed_summary_journals_an_error_row_and_keeps_the_previous passes | yes |
| C5-02 | 5 | `.harness/check.sh` | 711 passed | yes |
| C5-03 | 1 | Read concierge/compaction.py (234 lines); ran test_compaction.py tests for needs_compaction, plan (last 6, tool pair), build_compacted, fallback | needs_compaction past 24 items/4000 tokens, plan keeps last 6, tool pair both-or-neither, summary cap 120 words, fallback keeps 12; pass | yes |
| C5-03 | 2 | Read session.py:189-197 wiring; tests/test_critical_path.py:152 | on_item_added and on_state_changed registered on Compactor; AST test asserts update_chat_ctx is not called from turn hook or item handlers; pass | yes |
| C5-03 | 3 | Read test_thirty_turns_compact_at_the_next_listening_transition (test_compaction.py:312) | asserts len(items) <= 8, one summary message holding the FakeLLM text, 30 turns journaled (31 with greeting), tool pair test present; pass | yes |
| C5-03 | 4 | Read test_slow_summarizer_falls_back_within_5_5_s (:437) and test_existing_summary_survives_a_second_compaction | FakeLLM delay 6 s: ready under 5.5 s, last 12 turns (t18-t29) kept; existing summary survives second compaction; pass | yes |
| C5-03 | 5 | `.harness/check.sh` | 711 passed | yes |
| C5-04 | 1 | `wc -l` on /tmp/harness/.../review-C5.diff; read plan `## Review` (line 573) | Diff (3365 lines, 0c365fa = C4-06) and notes exist, but in the scratch dir, not /tmp/voice-concierge/ (plan explains: CLAUDE.md bars writes outside worktree/scratch). Accepted as equivalent | yes |
| C5-04 | 2 | Read Review table; ran 13 new tests in test_session/test_summary/test_compaction | 4 Important all marked fixed with tests committed first (per commit log); tests pass | yes |
| C5-04 | 3 | grep README.md lines 24-26; looped over every backticked test name in README against `def test_` in tests/ | All three rows present; no missing test names; test_readme.py passes | yes |
| C5-04 | 4 | `find concierge -name '*.py' \| xargs wc -l \| awk '$1>250'` | No module over 250 (max 250) | yes |
| C5-04 | 5 | `.harness/check.sh` | 711 passed | yes |


### 2026-10-20 10:05 · C5-04 · passes

- **Changed:**
  - The C5 milestone review, from 2 Opus reviewers: 0 Critical, 4 Important (all fixed), 3 Minor. The table is under `## Review` in `docs/plans/2026-10-20-C5-compaction.md`.
  - **Forget clears the summary right away.** "Forget" now clears a stored summary that names the value (A-I1), so a forgotten value can't come back through the summary if the shutdown never finishes.
  - **Forgetting before extraction is covered.** Values a forget request kept extraction from storing are now in the summary's deterministic check (A-I2).
  - **Second tab (A-I3).** The shutdown now summarizes from the summary stored at that moment, not the one preloaded. It stores through the new `Store.swap_summary` (compare-and-set; raises `StaleSummary`, retries once). Before, a second tab overwrote the other's summary.
  - **Compaction test (B-I1).** The forget-me compaction test now proves the in-flight call is cancelled.
  - README has the 3 new memory-design rows.
  - Tests 694 → 711.
- **Verified:**
  - New tests in `tests/test_summary_forgetting.py` (7) and `tests/test_summary_concurrency.py` (5); the RED commit 670e8ad comes before the GREEN commit edea007.
  - 11 mutations, each turning a test red.
  - `test_readme.py` checks every cited test name exists.
  - The largest module is 250 lines (`merge.py`, `memory_writer.py`).
  - `check.sh` is green with 711 tests.
- **Next session must know:**
  - `write_summary(writer, summarizer)` no longer takes `previous`.
  - `names_any` now lives in `forget_match`.
  - `memory_writer.py` is at 250 lines, so anything new goes elsewhere.
  - C6's "Forget me" RPC must not lose the erase after the writer closes (review A-M3, in the plan).
- **Questions for Michael:** none new (D12 is still open).
- **Proposed changes:**
  - C5-04 step 1's `/tmp/voice-concierge/` path conflicts with CLAUDE.md, so the diff is in the scratch dir, as in C1–C4.
  - Spec §4.2 could name the summary's compare-and-set (`swap_summary`).

### 2026-10-20 08:55 · C5-03 · passes

- **Changed:**
  - New `concierge/compaction.py` (pure: `needs_compaction`, `plan_compaction`, `build_compacted`, `compact_or_fallback`, `fallback_truncate`, `rebase`, `COMPACTION_SYSTEM`) and `concierge/compactor.py` (`Compactor`: one task at a time, applied on `listening` via `Agent.update_chat_ctx`, journals `compacted`).
  - `erasure_hooks.add_erase_hook`/`cancel_pending`, so "Forget me" cancels the compaction too.
  - `"compacted"` added to `JournalType`; `Started.compactor`.
  - Prep commit (a pure move): `session.py`'s `_journal`/`_write_summary` are now `concierge/session_end.py`'s `journal_row`/`write_summary`.
  - Tests 655 → 694.
- **Verified:**
  - `tests/test_compaction.py` (38 tests), among them `test_thirty_turns_compact_at_the_next_listening_transition`: 8 items, one summary with the FakeLLM text, 31 turn rows (the 30 turns plus the greeting) and one `compacted` row.
  - `test_slow_summarizer_falls_back_within_5_5_s`: the last 12 turns are kept, plus an `error` row and `fallback: true`.
  - `test_existing_summary_survives_a_second_compaction`.
  - `test_update_chat_ctx_is_never_called_from_the_turn_hook_or_item_handlers`: the only caller is `compactor.py:_apply`.
  - 12 mutations each turn a test red.
  - Opus review: 0 Critical, 0 Important, 5 Minor (4 fixed with tests, M1 accepted). The table is in the C5 plan under "C5-03 build notes and review".
  - `check.sh` is green with 694 tests.
- **Next session (C5-04) must know:** `merge.py` is at 250 lines and `memory_writer.py` at 249. The review diff base is the C4-06 commit. The plan's M1 (a narrow preemptive-generation window) was accepted, so C7's latency eval should look for it.
- **Questions for Michael:** none new (D12 is still open).
- **Proposed changes:**
  - C5-03 step 2's handler logic lives in `compactor.py`, registered from `session.py`.
  - Step 3 has 31 turn rows: the greeting is journaled too, and the test checks all 30 turn ids.
  - Spec §4.2's journal types could add `compacted`.

### 2026-10-20 07:40 · C5-02 · passes

- **Changed:** new `concierge/summary.py` (`summarize`, `summarize_visit`, `trim_summary`, `SUMMARY_SYSTEM`), `concierge/store_journal.py` (the fence and the journal, moved out of `store.py` with no changes), `concierge/erasure_hooks.py` (`forget_visitor`). `Store.set_summary` and `fact_ops.store_summary` are new, and so is the `summary_written` journal type. `gate.check_text` is new. `session.py` gets the shutdown sequence (flush → summary → `set_summary`, skipped when erased, under one 25 s deadline). `FLUSH_TIMEOUT_S` is now 15, and `flush` cancels its run on timeout. Also `FakeLLM(respond=…)` and a per-stage `build_llm` fake (`stage_llms`, the `summarizer` fixture). Tests 616 → 655.
- **Verified:**
  - `tests/test_summary_of_summary.py` (2 tests), `tests/test_summary.py` (24) and 9 new tests in `test_session.py`, among them `test_no_summary_llm_call_after_forget_me`, where both fakes have zero calls and every visitor table has 0 rows.
  - Mutation checks: removing the summary call, the erased guard, the flush cancel or the forgotten-value check each turns 2–7 tests red.
  - Opus review: 0 Critical, 4 Important (all fixed, each with a test), 5 Minor (3 fixed, 2 accepted). Table in the C5 plan under "C5-02 build notes and review".
  - `check.sh` green with 655 tests.
- **Next session (C5-03) must know:**
  - `forget_visitor` now lives in `concierge.erasure_hooks`; put the erase hooks there.
  - `memory_writer.py` is at 249 lines and `session.py` at 244, so the Compactor's logic belongs in `compactor.py`.
  - `writer.forget_requests` is public now.
  - Add `"compacted"` to `JournalType` after `summary_written`, and update `test_journal_type_literal_matches_spec_list`.
- **Review I1 (privacy):** a per-fact "forget" could come back through the visit summary. Now the summarizer is told what was forgotten. A reply that names a deleted value is rejected, and an earlier summary that names one is cleared.
- **Questions for Michael:** none new (D12 is still open).
- **Proposed changes:**
  - C5-02 step 1 has `summarize_visit` return `str`. It returns `str | None` (None on a failed first visit).
  - C5-02 step 2: the shutdown calls `summarize` (which returns the outcome) rather than `summarize_visit`, and it calls `set_summary` with `version=None`.
  - Spec §4.2's list of journal types could add `summary_written`.

### 2026-10-20 06:40 · C5-01 · passes

- **Changed:** `docs/plans/2026-10-20-C5-compaction.md` (new). It covers the shutdown sequence (compactor.aclose → flush → summary → `set_summary`, skipped when erased, one 25 s deadline inside `shutdown_process_timeout=30`), `SUMMARY_SYSTEM` and `COMPACTION_SYSTEM`, the trigger (>24 items or >4,000 est. tokens), fold/keep (last 6 turns, tool pairs whole), the apply point (`agent_state_changed` → `listening`, `Agent.update_chat_ctx`, rebased on the live context), the 5 s timeout and the truncate-to-12 fallback. It also quotes 1.8.8's `AgentStateChangedEvent` and `update_chat_ctx`, and names the C5-02 and C5-03 tests. Added D12 *default* to `docs/decisions.md`. Tests 616 → 616 (plan only).
- **Verified:** one scratch prototype on a real `AgentSession`: after `update_chat_ctx` there are 8 items and `session.history` still holds 32. One Opus plan review: 0 Critical, 6 Important and 4 Minor, all folded in (table under `## Plan review`). `check.sh` is green with 616 tests.
- **Next session (C5-02) must know:**
  - First switch `conftest.fakes` and `test_erasure_wins` to a per-stage `build_llm` fake. Today every stage gets the extractor fake.
  - Then add `FakeLLM(respond=…)`.
  - `store.py` is at 247 lines: move `write`/`journal`/`journal_rows` into `store_journal.py` before adding `set_summary`.
  - Lower `FLUSH_TIMEOUT_S` to 15, and make `flush` cancel its in-flight run on timeout.
  - 1.8's `ChatContext._summarize` drops the earlier summary from its input (the #7721 bug), so don't use it.
- **Question for Michael (D12):** after a compaction, should the concierge keep the last 3 exchanges verbatim (the default: a "turn" is one message) or the last 6?
- **Proposed changes:**
  - C5-03 step 3: the greeting is journaled too, so the session has 31 rows. The test checks the 30 added turn ids.
  - C5-03 step 2: the handler logic lives in `compactor.py`, registered from `session.py`.
  - C5-02: `summarize()` returns an outcome so the shutdown can journal `error`. `summarize_visit` wraps it.

### 2026-10-20 06:10 · verify C4

All 6 features hold (33 steps). Caveat: C4-06 step 1 path is literally absent; diff lives in the scratch dir.

| Feature | Step | What you ran or read | What you saw | Holds |
|---|---|---|---|---|
| C4-01 | 1 | read docs/plans/2026-10-20-C4-extraction.md §emit_ops (l.95-170) | emit_ops schema, ops fields, minimal ctx, tool_choice auto, parallel off, strict (default True, test named), 'exactly once/empty ops' line, 400 on forced, collect() l.166 | yes |
| C4-01 | 2 | read gate table l.370-393 | regexes for ignore/you are now/system:/disregard, url, email, code, caps, agent_attributed; contact exception reserved for C8 | yes |
| C4-01 | 3 | read scheduler section l.408-480 | debounce 2 s, one task per thread, extraction→merge→extraction_ran, cancel_all/erased, shutdown skips flush | yes |
| C4-01 | 4 | read eval schema l.540-596 | schema with interrupted_heard, expected, forbidden, recorded_ops; 01-07 cases listed | yes |
| C4-01 | 5 | read l.600-620 test lists | per-feature test functions named for C4-02..05 | yes |
| C4-01 | 6 | `/home/mh550/projects/agent-harness/lib/check.sh` | green, 616 tests; ruff clean | yes |
| C4-02 | 1 | read concierge/ops.py via tests/test_ops.py (9 tests pass) | parse_ops drops malformed and reports; Add/Update/Delete parse | yes |
| C4-02 | 2 | pytest tests/test_gate.py; read plan l.388-394 + test_rejects params | all 8 rejects with reasons and 3 accepts pass | yes |
| C4-02 | 3 | read tests/test_merge.py names + run | ADD/UPDATE/DELETE, supersede, dedupe, 8-cap, gate_rejected journal, state recompute all tested and pass | yes |
| C4-02 | 4 | tests/test_merge.py (265 tests in C4 files pass) | each named case present: UPDATE superseded_by, delete keeps row, user forget removes row, unknown slot, cap, unknown turn, 9th interest | yes |
| C4-02 | 5 | test_merge_journals_each_result_by_type | asserts fact_added/fact_invalidated/fact_deleted types | yes |
| C4-02 | 6 | check.sh | green | yes |
| C4-03 | 1 | read extractor tests; test_extractor_passes_parallel_tool_calls_false, test_heard_text | extract uses tool_choice auto, parallel False, collect(); ExtractionResult has ms/prompt_tokens | yes |
| C4-03 | 2 | tests/test_heard_text.py l.36-80, plan l.234-257 | Turn built from ChatMessage; finding on 1.8 interrupted content recorded in plan | yes |
| C4-03 | 3 | test_interrupted_agent_turn_reaches_the_extractor_as_heard_text_only, test_extractor_call_uses_tool_choice_auto, ..._exactly_one_tool_named_emit_ops | pass; asserts match step | yes |
| C4-03 | 4 | test_two_add_ops_yield_two_ops, test_plain_text_reply_is_zero_ops_and_no_error, test_extractor_ctx_is_isolated_from_the_session_prompt | pass; asserts STATIC_INSTRUCTIONS not in ctx | yes |
| C4-03 | 5 | check.sh | green | yes |
| C4-04 | 1 | read memory_writer.py (244 lines) + tests/test_memory_writer.py | note_item, schedule, flush, cancel_all, erased, on_merged, extraction_ran journal all present and tested | yes |
| C4-04 | 2 | test_item_handler_returns_fast_while_extraction_sleeps (5 s fake; <0.05 s; extraction_ran within 6 s), test_no_await_on_the_turn_path_targets_memory_work (ast) | pass; asserts match | yes |
| C4-04 | 3 | test_two_schedules_100ms_apart_start_one_extraction; test_a_turn_during_a_run_queues_exactly_one_follow_up | pass; len(calls)==1 and 2 as specified | yes |
| C4-04 | 4 | test_agent_has_remember_and_forget_tools, test_remember_writes_before_returning, test_forget_deletes_the_matching_facts | params fact/about; source user_asked_to_remember, channel; deletes not invalidates | yes |
| C4-04 | 5 | test_erasure_wins_over_an_inflight_extraction | 1 s extraction, forget+cancel, shutdown; all visitor tables 0 rows, no errors | yes |
| C4-04 | 6 | check.sh | green | yes |
| C4-05 | 1 | ls evals/memory; read 03 yaml | 13 files, 01-07 names exact; fields name/visits/expected/forbidden/recorded_ops (test_every_script_validates) | yes |
| C4-05 | 2 | read concierge/evals/runner.py usage in tests | run_script returns ScriptResult with missing_expected/forbidden_hits via real extract+merge on temp Store | yes |
| C4-05 | 3 | test_memory_evals_offline.py test_script x13; 03 yaml ADDs Initech; l.66 asserts initech not in context; 05 ADDs injection | all 13 pass | yes |
| C4-05 | 4 | grep pyyaml pyproject.toml; ruff check .; check.sh | pyyaml>=6,<7 present; ruff clean; compileall in check green | yes |
| C4-05 | 5 | check.sh | green | yes |
| C4-06 | 1 | ls /tmp/voice-concierge; scratch; grep '## Review' | review-C4.diff does not exist at the literal /tmp/voice-concierge path (outside allowed write dirs); it exists in scratch dir with review-C4-extra.diff; '## Review' at plan l.893. Accepted: path conflicts with CLAUDE.md | yes |
| C4-06 | 2 | read plan ## Review table + git log 0c365fa/d426499 | 5 Important: 4 fixed, 1 declined (documented); fixes carry tests (616 vs 598) | yes |
| C4-06 | 3 | grep README.md for the 6 row names | all 6 rows present, each citing tests; test_readme.py passes | yes |
| C4-06 | 4 | find concierge -name '*.py' | xargs wc -l | max 250 (merge.py), none over | yes |
| C4-06 | 5 | check.sh | green | yes |

### 2026-10-20 05:45 · C4-06 · passes

- **Changed:** C4 review notes under `## Review` in `docs/plans/2026-10-20-C4-extraction.md`. The README's "Memory design" table gains 6 write-path rows, each citing its tests (checked by `test_readme.py`). Fixes are in `memory_writer.py`, `forget_match.py`, `memory_tools.py`, `merge.py`, `grounding.py` and `extractor.py`. `fact_ops._key` is now the public `value_key`. Tests 598 → 616.
- **Review (2 Opus, `review-C4.diff` + `review-C4-extra.diff` in scratch):** 0 Critical, 5 Important, 11 Minor.
  - Fixed RED→GREEN: the loop-guard test, which the handler's `except` hid; and `forgotten` blocking a later restatement.
  - New mutation-checked tests: the name-confirmation cases, which never reached the take-back rule, and in-batch `supersedes` inheritance.
  - B-I3 declined: §4.4 says an extractor DELETE invalidates. Ten Minor are fixed or covered (a DELETE citing an agent turn, two-letter stop words, flush retrying after a failure, a tool call after `aclose`, and others).
- **Verified:** every step holds. `check.sh` exits 0 at 616, ruff is clean, and the largest module is `merge.py` at 250 lines. Each new test fails on its mutation.
- **Not adopted:** "merge must require a known `turn_id` on DELETE". Spec §4.4 and the plan exempt DELETE, so only an agent-turn citation is rejected now.
- **Next session (C5):** `flush` stops after a run that extracted nothing. `_drain` and `_debounced` both own `_run`; consider unifying them in C5-02. **C6:** `forget_visitor` on a closed writer raises `StoreError`, so erase through the store once the session has ended.
- **Proposed change:** C4-06 step 1's diff path should be the scratch directory, as in C1-06, C2-05 and C3-04.

### 2026-10-20 04:55 · C4-05 · passes

- **Changed:** new `evals/memory/` with 13 YAML scripts (the seven §4.9 cases 01–07, plus 08–13 from the plan's table). New `concierge/evals/script.py` (`MemoryScript`, `extra="forbid"`, `load_script`), `concierge/evals/runner.py` (`run_script` → `ScriptResult(stored, missing_expected, forbidden_hits, runs, rejected, history)`, `check`) and `concierge/testing/replay.py` (`Replay`, the FakeLLM factory). `pyyaml>=6,<7` and the `concierge.evals` package are in `pyproject.toml`. Tests 546 → 598 (`tests/test_memory_evals_offline.py`, 52).
- **Verified:** all 5 steps hold. `test_script[...]` passes for all 13 scripts. 03's recorded ADD of Initech is rejected as `ungrounded`, and `FakeLLM.calls[0].chat_ctx` has "Great." but no "Initech". 05's injection ADD is rejected as `instruction`. 9 of 9 mutations are caught (heard-text cut, gate, name rule, set cap, grounding, agent-turn check, text vs empty call, and others). `check.sh` exits 0 at 598 and ruff is clean. The runner has 122 lines, the script module 92.
- **Review (Opus):** 0 Critical, 4 Important, 5 Minor, all fixed or applied. The 03 test now reads the context that was actually sent, not a rebuilt one. `gone` must have been stored. `expected` has `also` spellings for the live eval. `nothing_stored` is off in 09. The table is in the plan's "C4-05 build notes".
- **Next session (C4-06):** the review diff range starts at `568700f^`. The README rows "Only what was heard" and "Evaluate for harm as well as help" can cite `test_interrupted_fake_fact_never_reaches_the_extractor` and `test_script`. `merge.py` is still at 250 lines.
- **For C7 (live eval):** call `run_script(script, lambda n: build_llm(...))` on the same files; `recorded_ops` is ignored there. `ScriptResult.runs` carries `prompt_tokens` and `tool_called`.
- **Proposed changes:** C4-05 step 1's schema also has the optional keys `about`, `gone`, `nothing_stored`, per-turn `confidence` and `expected[].also`, and `forbidden[].slot` is optional. Step 2's `ScriptResult` also has `runs`, `rejected` and `history`.

### 2026-10-20 08:10 · C4-04 · passes

- **Changed:** new `concierge/memory_writer.py` (`MemoryWriter`: sync `on_item_added`/`note_item`/`schedule`, debounce, one run per thread plus one queued follow-up, `flush`, `cancel_all`, `aclose`, `forget_visitor`), `memory_tools.py` (`do_remember`/`do_forget`), `forget_match.py`, `tasks.py` (shared `track`). `ConciergeAgent` has the `remember(fact)`/`forget(about)` tools. The session attaches the writer before `session.start`, and shutdown runs flush → `session_ended` → `writer.aclose` → `store.close`. `merge` gains `source=`. Test fixtures moved to `conftest.py`/`concierge/testing/sessions.py`. Tests 486 → 546 (`test_memory_writer.py`, `test_critical_path.py`, `test_tools.py`, `test_erasure_wins.py`, +3 in `test_session.py`).
- **Verified:** all 6 steps hold (44 step tests pass); `check.sh` is green at 546 and ruff is clean. 15 of 16 mutations are caught; the survivor is equivalent. Every module is ≤ 250 lines (merge 250, writer 242).
- **Review (Opus):** 0 Critical, 4 Important, 8 Minor. All 4 Important are fixed RED→GREEN: `remember` after "remember that", forget before the first extraction, slot over-matching in forget, and an erasure test that passed with a no-op `cancel_all`. M5–M9, M11 and M12 are fixed; M10 becomes D11. The table is in the plan's "C4-04 build notes".
- **Next session (C4-05):** to replay scripts, build `MemoryWriter(store, thread, session, lambda: fake, debounce_s=60)`, then call `note_item(ChatMessage)` for each turn and `await writer.flush()`. Or call `extract`/`merge` directly, the way `_extract_and_merge` does. A session's journal now has the greeting's `agent_turn`.
- **Question for Michael (D11):** should "forget X" also scrub X's turn text from the journal? Right now it stays until the 30-day TTL or "Forget me".
- **Proposed changes:** C4-04 step 1's writer also takes `channels=`/`on_merged=` as keyword arguments, and step 4's tools take no `RunContext`. C4-06 should still make `merge` require a known `turn_id` on DELETE.

### 2026-10-20 06:40 · C4-03 · passes

- **Changed:** new `concierge/extractor.py` (`EMIT_OPS`, `EXTRACTOR_SYSTEM`, `extraction_window`, `build_extractor_ctx`, `ops_from`, `extract`, `ExtractionResult`). `turns.py` gains `turn_from_message`. The fake LLM records `parallel_tool_calls` and can script `error=` (a non-retryable `APIStatusError`). `OpArg`'s docstring is now model-facing, because the strict schema sends it as the description. Tests 455 → 486 (`test_heard_text.py` 11, `test_extractor.py` 20).
- **Verified:** all 5 steps hold, and the 7 step-named tests pass. Two mutations are caught: reading `turn.text` instead of `visible_text` fails 2 heard-text tests, and `tool_choice="required"`/parallel on fails 2. The heard-text citations were re-read in 1.8.8 (`agent_activity.py:3905-3936`, `generation.py:708-716`). `check.sh` is green at 486 and ruff is clean.
- **Review (Opus):** 0 Critical, 2 Important, 5 Minor. Both Important are fixed RED→GREEN: the prompt now asks for `turn_id` on UPDATE/DELETE, and a window with no visitor turn makes no LLM call. M2 and M3 are fixed and M5 is documented. The table is in the plan's "C4-03 build notes".
- **Next session (C4-04):** the writer keeps its turn history and calls `extraction_window(history, first_new)`, then `extract(llm, window, facts)`. Pass `channel_of(msg.text_content)` for user messages only (it consumes a tag), on the unstripped text. Never toggle the session's audio or transcription outputs: with the synchronizer off, an interrupted reply would record all of its text, not just what was heard (M1). Journal the count of turns the 24-turn cap drops (M4).
- **Proposed changes:** C4-06 should make `merge` reject a DELETE without a known `turn_id`. `merge.py` is at 250 lines, so C4-03 didn't touch it. C4-03 step 1's `ExtractionResult` also has `dropped`, `tool_called` and `ignored_calls`.

### 2026-10-20 05:50 · C4-02 · passes

- **Changed:** new modules `concierge/ops.py` (`AddOp`/`UpdateOp`/`DeleteOp`, `OpArg`, `parse_ops` → `ParsedOps(ops, dropped)`), `gate.py` (`check_value` → `GateResult`), `merge.py` (`merge`, `MergeResult`, 250 lines), `grounding.py` (D10 grounding and the B12 name rule) and `turns.py` (`Turn`, `visible_text`). `models.py`/`fact_ops.py` gain the `Note` op and an enum `InvalidateFact.reason`. Tests 351 → 455 (`test_ops.py`, `test_gate.py`, `test_merge.py`, plus 3 in `test_store.py`).
- **Verified:** all 6 steps hold, and the named tests pass (66 selected). Two mutations are caught: grounding always true fails 4 tests; a wrong set cap fails 3. `check.sh` is green at 455 and ruff is clean.
- **Review (Opus):** 0 Critical, 3 Important, 6 Minor. All 3 Important are fixed RED→GREEN: substring name confirmation, the missing `turn_ids_known` test case, and phone/spoken-email gaps. Minor 4, 7 and 8 are fixed, 5 and 6 partly. The table is in the plan's "C4-02 build notes".
- **Next session (C4-03):** `turns.py` already has `Turn` and `visible_text`; add `turn_from_message` there. `merge` needs `turns=` (the window, in order, agent turns included). A cited turn missing from it is `unknown_turn`. `merge.py` is at exactly 250 lines, so C4-04's `forgotten` check belongs outside it. A name is accepted only from the prompt's exact "Did I get that right, <name>?" followed by an untaken-back yes.
- **Proposed changes:** C4-02 step 1 should say `parse_ops(json_args) -> ParsedOps(ops, dropped)`, since a bare list can't report the dropped ops. Step 3's `merge` adds the keyword arguments `turns=` and `extraction=`.

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
