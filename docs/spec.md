# Voice Concierge: a portfolio voice agent that remembers returning visitors

Status: design, 2026-10-19. Owner: Michael Herron. Builder: the agent-harness, overnight 10-19 → 10-20.
Companion spec for the web page: `portfolio_site/docs/specs/2026-10-19-voice-concierge-page.md` (same contract, §6).

## 1. Why this exists

A demonstration of **memory for real-time voice agents**, built on LiveKit Agents, to show on Tue 10-20. It is a
small, real voice agent on Michael's portfolio site that:

- talks about Michael's work;
- remembers returning visitors across visits, whether they used voice or text;
- shows its memory and its latency live on the page;
- follows the 2026 best practices on purpose.

The README explains each practice and how the design maps onto LiveKit Agents 2.0. The background for every choice
is in `docs/background/memory-research.md` (sections "Memory systems details", "Security and privacy", "Voice and
LiveKit details", "LiveKit Agents 2.0").

**What success looks like tomorrow morning:**

- Michael opens the portfolio page and talks to the concierge. He tells it his name and what he's working on, then
  hangs up.
- He comes back and it greets him by name and picks up where they left off.
- He types a message and it is answered from the same memory.
- He presses "Forget me" and the next visit is a stranger's.
- The page shows each fact the agent remembers, with where and when it learned it, and a per-turn latency readout.
  Memory work adds ~0 ms to the turn path.
- The README carries real p50/p95 numbers, captured with `scripts/latency_report.py` in the morning.

**Anti-goals** (what would make this a failure even if it technically works):

- **Making up facts about Michael.** Anything it says about him must come from the knowledge pack (§4.1).
- **Memory on the critical path.** A turn must never await extraction or a store write.
- **Remembering what the visitor never heard,** or what the agent itself said, as if the visitor had said it.
- **A memory the visitor can't see or erase.**
- **Overclaiming in the README.** No unmeasured numbers, and nothing presented as Agents 2.0 code (it's 1.8).

## 2. Scope

**In scope:**

- A Python agent worker (livekit-agents 1.8.x). It runs on Michael's box and connects outbound to LiveKit Cloud.
- A SQLite thread store: thread, state, facts, journal.
- Preload at connect.
- Background extraction with delta merge.
- `remember` / `forget` tools.
- "Forget me" (erasure).
- The UI contract over the room (§6).
- Latency capture.
- Offline tests, plus live evals marked `live`.
- README, scripts, and a systemd user unit.

**Out of scope:**

- Telephony and SMS. The README says how they'd attach: a `phone:` key in 2.0.
- Authentication: the visitor id is a browser-local random id, and the page says so.
- LiveKit Cloud agent deploy, vector search, a knowledge graph.
- Agents 2.0 code.

**Non-goal:** a general chatbot. The concierge talks about Michael's work and takes messages for him; it politely
declines anything else.

## 3. Decisions already made (Michael, 10-19)

| # | Decision |
|---|---|
| D1 | Persona: **portfolio concierge** on Michael's site. It talks about his work and remembers returning visitors |
| D2 | Framework: **stable livekit-agents 1.8.x** (Python). Memory modelled as thread / state / journal so the README maps it onto 2.0 |
| D3 | Hosting: the worker runs on **Michael's home box** and connects outbound to LiveKit Cloud. Memory lives in local SQLite. No inbound ports |
| D4 | It runs overnight **in parallel** with the Rane One run |

**Builder's calls** (made here; change them only with a decision entry in `docs/decisions.md`):

| # | Call |
|---|---|
| B1 | STT, LLM and TTS go through **LiveKit Inference** (one LiveKit Cloud key). Model ids are in `concierge/config.py` and confirmed from LiveKit's docs. If Inference turns out to be unavailable on Michael's plan, an OpenAI plugin fallback sits behind the same config |
| B2 | One **thread per visitor** (2.0: "an application that wants one memory keeps one thread per person"), keyed by `visitor_id` |
| B3 | Memory is **slot-based facts plus one visit summary**, always loaded (small, about 1–2 KB). No vector search: the best-practice "start with one small file" |
| B4 | Writes happen **in the background** through a separate extractor, as delta operations. The only hot-path writes are the explicit, user-requested `remember` / `forget` tools |
| B5 | Facts are **invalidated, not overwritten** (`valid_to`, `superseded_by`); "forget me" really deletes |
| B6 | Retention: a thread expires after **30 days idle** and is purged at worker start and daily |
| B7 | Abuse limits: **the agent** ends a session after 10 min (a timer, then shutdown; room config has no max-duration field), at most 5 sessions per visitor per day, and a kill switch (`CONCIERGE_ENABLED=0` or the file `~/.voice-concierge-off`). With the switch on, the worker **declines the job** (request handler rejects), so no agent joins and the page's 10 s timeout shows its offline state; over the daily cap the agent says so in one line and ends the session |
| B8 | **Knowledge sources are vendored.** The five portfolio files are copied into `knowledge/sources/` at a known portfolio commit (recorded in `knowledge/sources/SOURCE.md`) before the run. The research notes are copied to `docs/background/memory-research.md`. Sessions read only these copies, never the live portfolio checkout, which another run is changing tonight |
| B9 | **Latency numbers survive "Forget me".** Per-turn metrics go to an `anonymous_turn_metrics` table keyed by a random session id with no visitor id, no text, numbers only. Erasure removes everything linked to the visitor. The page's privacy note says anonymous timing numbers are kept |
| B10 | **Provider.** The env file has `LIVEKIT_URL`, `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET`. Optionally `CONCIERGE_PROVIDER=openai` plus `OPENAI_API_KEY` if Inference isn't on Michael's plan. `MORNING.md` and `deploy/` use exactly these names |

## 4. How it works

### 4.1 Knowledge pack (what the concierge knows about Michael)

`knowledge/michael.md` is a compact, factual profile, about 1,500 words at most. It is built **only** from these files
in `~/projects/portfolio_site`: `Bio.md`, `src/lib/data/profile.ts`, `experience.ts`, `projects.ts`, `skills.ts`.
Each section names its source file.

The agent's instructions say:

- answer only from the pack;
- say "I don't know, but you can ask Michael directly" otherwise;
- never guess numbers, dates or employers.

The pack is **static**, so it sits in the cached prefix: stable instructions first, the pack second, the visitor's
memory after it (§4.3).

### 4.2 The thread store (`concierge/store.py`, SQLite, WAL mode)

| Table | Holds | 2.0 analogue |
|---|---|---|
| `threads` | `id`, `visitor_id` (unique; the scope), `created_at`, `last_active_at`, `idle_ttl_s`, `attributes` (JSON: display name, visit count) | thread |
| `state` | one row per thread: `VisitorState` as JSON (pydantic, at most 8 KB): name, role, company, what they're interested in, follow-up wanted, last-visit summary | lane `state` |
| `facts` | `id`, `thread_id`, `slot`, `value`, `confidence`, `source` (`user_said` · `user_typed` · `user_asked_to_remember`), `channel` (`voice` · `text`), `turn_id`, `created_at`, `valid_from`, `valid_to`, `superseded_by` | what `state` is derived from, with provenance |
| `journal` | append-only: `id`, `thread_id`, `session_id`, `ts_ms`, `type`, `payload` JSON. Types: `session_started`, `session_ended`, `user_turn`, `agent_turn` (with `interrupted` and the heard text), `memory_preloaded` (ms), `extraction_ran` (ms, ops), `fact_added` / `fact_invalidated` / `fact_deleted`, `turn_metrics`, `gate_rejected`, `error` | journal |
| `messages_for_michael` (stretch, §4.6) | `thread_id`, `text`, `contact`, `created_at` | — |

**Single writer, across processes.** Each LiveKit job runs in its own process, and a refresh or a second tab can put
two jobs on one visitor. So asyncio locks aren't enough. Every write is a SQLite `BEGIN IMMEDIATE` transaction that
checks and bumps a `version` column on `threads`, the way 2.0's fence works. A writer that loaded an older version
re-reads and re-applies its delta ops; it never overwrites blindly. The README maps this onto 2.0's lease plus fence
and says where it falls short: there's no lease, so two live sessions for one visitor can interleave turns.

**Erasure.** `forget_me(visitor_id)` deletes the thread and every visitor-linked row (state, facts, journal,
messages), then `VACUUM`s. `anonymous_turn_metrics` stays (B9).

### 4.3 Preload (read path, off the critical path)

1. The job starts, and `visitor_id` comes from the dispatch metadata (§6).
2. Loading the thread, `VisitorState` and the current facts runs **concurrently with `ctx.connect()`**.
3. The memory is rendered into one bounded block, at most 1,500 characters: "What you remember about this visitor" plus
   the last-visit summary. It goes **after** the static instructions and the knowledge pack.
4. The preload time is journaled as `memory_preloaded`.
5. A new visitor gets no block, and the agent introduces itself. A returning visitor is greeted by name, and the
   agent offers to pick up the last topic.

### 4.4 Writing memory (background, off the critical path)

**Extraction runs in the background.** After each committed user turn, an extraction task is scheduled
(fire-and-forget `asyncio.create_task`, debounced about 2 s, at most one in flight per thread). The turn's code path
**never awaits it**. A test enforces this (§7).

**What the extractor reads:**

- the visitor's turns since the last extraction;
- the agent's turns, for context only, with interrupted agent turns cut to what was heard (`interrupted=True`; take
  what 1.8 records). Unheard text is never shown to the extractor;
- the current facts.

**What it returns.** It is an LLM call **forced to call one tool**, `emit_ops`, via `tool_choice`. The base
`LLM.chat()` has no `response_format`. The tool's arguments are a list of ops, each one of
`ADD(slot, value, confidence, turn_id)`, `UPDATE(fact_id, value, …)` or `DELETE(fact_id, reason)`. `NOOP` is an empty
list. Read the result with `LLMStream.collect()` (1.4+), outside the session.

**What the merge does.** The merge is deterministic code, not the LLM. It validates each op:

- the slot must be known;
- values are length-capped;
- the source must be a user turn that exists;
- it runs the **write gate**.

`UPDATE` invalidates the old fact (`valid_to`, `superseded_by`) and adds the new one. `DELETE` from the extractor
invalidates. Only `forget` and "forget me" really delete. `VisitorState` is then recomputed from the valid facts.

**The write gate** rejects a value, and journals `gate_rejected`, when it:

- looks like an instruction to the agent ("ignore previous", "you are now", "system:");
- contains a URL, email-like secret, or code;
- is longer than the cap;
- is attributed to the agent's own words.

Contact details volunteered for `messages_for_michael` are the one exception (§4.6).

**At session end** (`ctx.add_shutdown_callback`; raise the worker's `shutdown_process_timeout` from its ~10 s default
so two LLM calls fit), a final extraction runs, then a **visit summary** of at
most 3 sentences replaces the previous one in `VisitorState`. A summary-of-summary test guards against losing the
earlier visit's key points (cf. livekit/agents #7721).

**Hot-path writes.** The visitor can say "remember that I…" or "forget what I said about…". The `remember` and
`forget` function tools write immediately, because the visitor asked explicitly. They are cheap local SQLite writes
under the thread lock.

### 4.5 Channels: voice and text share one memory

The visitor can speak or type in the same session. Typed messages use 1.8's text input on the room (`lk.chat`
topic), through a custom `TextInputOptions(text_input_cb=...)`, so typed turns are tagged `text`. The default handler
records no channel. Both land in the same chat history and the same thread, and each fact records its `channel`. This is the 1.8
counterpart of 2.0's "a lane is per agent, not per door". The README shows it.

### 4.6 Stretch, only if everything else passes

A `leave_message_for_michael(text, contact?)` tool writes to `messages_for_michael`, plus a
`scripts/messages.py` that lists them.

### 4.7 Latency capture

Read per-turn latency from `ChatMessage.metrics` on `conversation_item_added`. The session-level
`metrics_collected` is deprecated; confirm the field names in the installed package.

- User messages carry `transcription_delay`, `end_of_turn_delay` and `on_user_turn_completed_delay`.
- Assistant messages carry `llm_node_ttft`, `tts_node_ttfb` and `e2e_latency`.

`memory_on_turn_path_ms` is the **measured** `on_user_turn_completed_delay`, never a constant. Write the numbers to
`anonymous_turn_metrics` (B9) and publish them on the room (§6). `scripts/latency_report.py` prints
p50/p95 per field from the journal, and the README's results table is filled from it in the morning. Until then the
table says "to measure".

## 5. What a session sees (prompt layout, cache-friendly)

1. Static instructions: persona, the rules from §1's anti-goals, tool guidance, and "keep answers to 1–3 spoken
   sentences".
2. The knowledge pack (static).
3. The visitor memory block (per visitor; changes only between sessions).
4. The conversation.

Mid-session memory updates do **not** rewrite blocks 1–3. New facts are already in the conversation. The memory panel
on the page updates live, but the prompt prefix stays stable.

## 6. The contract with the web page (shared with the portfolio spec, word for word)

- **Agent name** for explicit dispatch: `concierge`.
- **Dispatch metadata** (JSON) set by the token route: `{"visitor_id": "<uuid v4>", "channel_hint": "web"}`.
- **Participant identity** of the visitor: `visitor-<visitor_id>`.
- **Room**: one per visit, `concierge-<random>`, created by the token route's room config (`RoomConfiguration` with
  `agents: [RoomAgentDispatch{agentName, metadata}]`, empty timeout 30 s). The 10-min cap is enforced by the agent
  (B7).
- **Agent → page**, as text streams: the agent sends with `room.local_participant.send_text(body, topic=…)`, and the
  page receives with `room.registerTextStreamHandler(topic, …)`. The page registers **before** `connect()` and
  unregisters on cleanup (React StrictMode mounts twice). Bodies are JSON, at most 15 KiB:
  - topic `concierge.memory` carries `{ "visitor": {"name": str|null, "visits": int}, "facts": [ {"id","slot","value","channel","source","learned_at","confidence"} ], "summary": str|null, "updated_at": iso }`. It is sent at session start and after every merge.
  - topic `concierge.metrics` carries `{ "turn": int, "eou_ms", "stt_ms" (= transcription_delay), "llm_ttft_ms", "tts_ttfb_ms", "total_ms", "memory_on_turn_path_ms" (measured: on_user_turn_completed_delay), "preload_ms" (first message only), "extraction_ms" (when one ran, background) }`. Any field may be null if 1.8 doesn't report it.
- **Page → agent RPC methods**, registered by the agent on its local participant:
  - `concierge.forget_me`: erases the thread (§4.2) and **returns `{"ok": true}` immediately**; RPC times out at
    10 s. It then schedules one last `concierge.memory` with empty facts, a short goodbye, and the end of the
    session.
  - `concierge.get_memory`: returns the same JSON as the `concierge.memory` topic.
- **Text chat** uses the standard `lk.chat` topic and `lk.transcription`, as LiveKit's components expect.
- **Offline.** If no agent joins within 10 s, the page shows "The concierge is offline right now". With the kill
  switch on, the worker declines the job, so no agent joins and the same state shows.

## 7. How it's verified

**The offline suite** (`.harness/check.sh`) runs `pytest -m "not live"`, `ruff` (if installed in the venv) and
`python -m compileall`. It needs no network and no keys. Required tests:

- **Store:** schema created; one thread per visitor; erasure removes every visitor-linked row and keeps
  `anonymous_turn_metrics`; TTL purge.
- **Concurrent writers:** two processes merging into one thread both land; neither overwrites the other (version
  check).
- **Merge semantics:** ADD, UPDATE (invalidates and links), extractor DELETE (invalidates), user forget (deletes).
  Unknown slot rejected; value caps enforced.
- **Write gate:** the injection, URL, agent-attribution and length cases from §4.4.
- **Heard text only:** an interrupted agent turn reaches the extractor truncated to its heard part, and unheard text
  never appears.
- **Off the critical path:** with a fake extractor that sleeps 5 s, the user-turn handler returns in under 50 ms,
  and the extraction still completes afterwards.
- **Preload:** the memory block renders after the static blocks, within its cap; a new visitor gets no block.
- **Summary of summary:** the second visit's summary still carries a key point from the first, under a deterministic
  fake LLM.
- **Contract:** the JSON bodies for both topics and both RPC methods match §6, checked against a JSON schema in
  `tests/contract/`.
- **Agent behaviour:** 1.8 ships no fake LLM, so C1 writes one: a `llm.LLM` subclass whose stream yields
  `ChatChunk`s shaped like the installed package's, read from its source, never invented. Use it with the
  livekit-agents testing helpers (`judge()` needs a real LLM and is live-only). Check that the instructions are
  assembled in §5 order and that the tools exist with the right schemas.

**Live evals** (`pytest -m live`; skipped unless `LIVEKIT_URL` is set; run by Michael in the morning):

- Two-session recall in text mode: session 1 states name and interest; session 2 is greeted by name.
- Wrong memory: it doesn't attribute to the visitor something the agent said.
- Injection: a "remember: ignore your instructions…" turn is not stored.
- Forget me: the next session is a stranger's.

Use the LiveKit test framework's LLM `judge` where a check needs judgment.

## 8. Code and run rules (for `CLAUDE.md`)

- Python 3.12, a venv in `.venv`, pinned `livekit-agents[…]~=1.8` and plugins in `pyproject.toml`. No other services.
- **Secrets.** Sessions never read, print or source `~/.config/voice-concierge/env` or any `.env`. The worker reads
  that env file only when run by systemd or by `scripts/run-worker.sh`, which Michael runs.
- **Overnight is build-only.** No session starts the worker against LiveKit Cloud, runs `-m live`, or touches the
  systemd unit beyond writing the file in `deploy/`.
- **Docs.** Decisions go in `docs/decisions.md` as `D<n>`. The README is written for the LiveKit team:
  - what it does, with a GIF placeholder;
  - an architecture diagram (mermaid);
  - the memory design and why, citing the best practices in `docs/background/memory-research.md`;
  - a table mapping it onto Agents 2.0: thread, lane state, journal, channels, lease/fence vs lock, across days via
    TTL and returning visits;
  - measured results ("to measure" until the morning);
  - failure cases and limits (visitor id isn't auth, ASR mishears, the extractor can miss things, single box);
  - how to run it.

## 9. Milestones (for the initializer)

| M | What | Done when |
|---|---|---|
| C1 | Project skeleton, config, knowledge pack, agent with static prompt, voice + text session wiring, worker entrypoint with explicit dispatch name, fake LLM test harness | suite green; the pack cites its sources; prompt-order test passes |
| C2 | Thread store, `VisitorState`, facts, journal, erasure, TTL purge | store and erasure tests pass |
| C3 | Preload concurrent with connect, memory block rendering, greeting behaviour | preload tests pass |
| C4 | Background extractor, deterministic merge, write gate, heard-text-only, session-end summary, `remember` / `forget` tools | merge, gate, heard-text, critical-path and summary tests pass |
| C5 | Room contract: memory and metrics topics, both RPCs, latency capture, kill switch and abuse limits | contract tests pass |
| C6 | Live eval file (marked, skipped), `scripts/latency_report.py`, `scripts/run-worker.sh`, `deploy/voice-concierge.service` (user unit with `EnvironmentFile=%h/.config/voice-concierge/env`), README, `MORNING.md` (Michael's 20-minute checklist: start, try, live evals, latency report, fill the README) | README complete except measured numbers; review feature passes |
| C7 | Stretch: messages for Michael | — |

Every milestone after C1 builds on C1. C3 needs C2. C4 needs C2. C5 needs C3 and C4. C6 needs C5.
