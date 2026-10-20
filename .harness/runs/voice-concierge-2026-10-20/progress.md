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
