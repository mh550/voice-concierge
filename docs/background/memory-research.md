# Agent memory research notes

Collected 2026-10-19 by three research passes over primary sources (engineering blogs, papers, docs). The key sources
are listed at the end. Vendor-reported numbers are marked as such.

## Taxonomy details

- **CoALA** (Sumers, Yao, Narasimhan, Griffiths, 2023; TMLR 2024). It defines four memories: working, episodic,
  semantic and procedural. Procedural memory covers the weights plus the agent's code and prompts. It separates
  internal actions (retrieve, reason, learn/write) from external ones (act on the world). It's a taxonomy, not an
  implementation.
- **LangMem** splits semantic memory into two shapes. A *collection* is many records, searched by query; new
  information has to be reconciled against the old. A *profile* is one document updated in place; it's cheap and
  editable but has a fixed schema. Episodic memory is past interactions kept as few-shot examples. Procedural memory
  is the system prompt, refined from feedback. Writes happen in the "hot path" (conscious: a tool call mid-chat) or in
  the "background" (subconscious: after the chat or after inactivity).
- The **memory survey** (arXiv 2512.13564, Dec 2025) sorts memory three ways: by form (token-level, parametric,
  latent), by function (factual, experiential, working) and by dynamics (formation, evolution, retrieval).
- **Arize's framing**: context management is a runtime concern (what is in the window now). Memory is a storage concern
  (what persists).

## Context engineering details

- **Anthropic** (Sep 2025):
  - Find "the smallest set of high-signal tokens".
  - Attention is n², so every token spends part of an attention budget.
  - Use a hybrid: preload CLAUDE.md, glob and grep the rest.
  - Tune compaction for recall first, then precision.
  - Clearing old tool results is the "lightest touch".
  - Sub-agents spend tens of thousands of tokens and return 1–2k-token summaries.
  - Tools should be minimal and non-overlapping: if a human can't pick the right tool, the model can't either.
- **Memory tool** (`memory_20250818`): file CRUD over `/memories`, stored client-side, so the developer owns storage.
  - The API auto-injects: "ALWAYS VIEW YOUR MEMORY DIRECTORY BEFORE DOING ANYTHING ELSE… ASSUME INTERRUPTION".
  - The developer is responsible for path-traversal checks, stripping sensitive data, size caps, and expiring files
    nobody has read in a long time.
- **Context editing** (`clear_tool_uses_20250919`) clears the oldest tool results once context passes a trigger
  (100k tokens by default) and keeps the last N.
  - Clearing invalidates the cached prefix. `clear_at_least` makes each clear big enough to be worth a new cache write.
  - Claude gets a warning near the threshold, so it can save to memory first.
- Anthropic's internal eval, 100 turns: memory plus context editing +39%, context editing alone +29%, 84% fewer
  tokens.
- **Server-side compaction** is in the API now: threshold, background, and on-demand
  (`compact-2026-09-04` beta).
- **Manus** (Jul 2025):
  - Input to output is about 100:1.
  - Cached Sonnet input costs $0.30/MTok vs $3 uncached.
  - Keep the prefix stable: no timestamp to the second at the top.
  - Append-only context, deterministic JSON key order.
  - Mask tools (logit masking with consistent name prefixes such as `browser_`, `shell_`) instead of removing them.
  - Use the filesystem as unlimited memory, and compress restorably: drop the page, keep the URL.
  - Recite `todo.md` at the end of context; a typical task is about 50 tool calls.
  - Keep errors in context.
  - Vary the wording of repeated templates, or the model starts copying its own history ("few-shotting itself").
- **LangChain's four moves**: write (scratchpads, memories), select (memories, tools, knowledge; RAG over tool
  descriptions roughly triples tool-selection accuracy), compress (summarize or trim; Claude Code auto-compacts at 95%)
  and isolate (sub-agents, sandboxes, state fields hidden from the model).
  - Anthropic's multi-agent researcher uses about 15× the tokens of a chat.
  - Simon Willison's example of selection going wrong: ChatGPT memory put his location into an image.
- **Chroma, "Context Rot"** (Jul 2025): 18 models, about 194k calls.
  - Performance drops as input grows, even on trivial tasks such as repeating words.
  - It drops faster when the needle and the question are semantically far apart, and when distractors are present.
  - Shuffled haystacks did *better* than coherent ones.
  - On LongMemEval, focused prompts (~300 tokens) beat the full prompt (~113k) on every model.
- **Breunig's four failure modes**:
  - **Poisoning**: a hallucination enters context and keeps being re-used (Gemini playing Pokémon).
  - **Distraction**: past about 100k tokens the agent repeats its history; Databricks saw Llama 3.1 405B degrade
    around 32k.
  - **Confusion**: Llama 3.1 8B failed with 46 tools and succeeded with 19.
  - **Clash**: Microsoft/Salesforce's sharded prompts dropped scores 39% on average; o3 fell from 98.1 to 64.1.
- **ACE** (arXiv 2510.04618): a generator, a reflector and a curator maintain a "playbook" through itemized delta
  updates with grow-and-refine and dedupe.
  - Failure modes of rewriting the whole thing: *brevity bias* and *context collapse*.
  - Reported gains: +10.6% on agent tasks, +8.6% on finance.
- **Arize harness comparison** (Apr 2026): Pi, OpenClaw, Claude Code and Letta independently converged on the same
  techniques:
  - hard-capped file reads with pagination
  - capped tool results, oversized ones written to disk with a preview left in context
  - head+tail truncation
  - de-duplicating re-reads
  - isolated sub-agents
  - compaction at a token threshold
  - a deterministic fallback when the summarizer itself fails

## Memory systems details

- **MemGPT** (2023): virtual context modeled on an OS. Core memory sits in context; recall and archival stores are
  paged in through self-edit function calls.
- **Letta**:
  - Memory blocks: labeled, size-capped sections of context that agents can share.
  - Sleep-time compute (arXiv 2504.13171): a background agent owns memory edits and can run a stronger, slower model.
    The primary agent no longer edits core memory, because bundling the two was slow and unreliable.
  - Filesystem benchmark: gpt-4o-mini with grep and open/close over the raw conversation scored 74.0% on LoCoMo,
    vs Mem0's reported 68.5%.
- **Mem0** (arXiv 2504.19413):
  - Extracts salient facts, then decides ADD/UPDATE/DELETE/NOOP against similar existing memories. Mem0ᵍ is the
    graph variant.
  - Claims: 66.9 vs 52.9 for OpenAI memory on LoCoMo, 91% lower p95 latency and about 90% fewer tokens *than
    full-context*.
  - The Apr 2026 algorithm self-reports 91.6 on LoCoMo and 93.4 on LongMemEval (vendor numbers).
- **Zep's rebuttal**: Mem0 misconfigured Zep. Re-run, Zep scored 75.14 vs Mem0ᵍ 68.44, and a full-context
  gpt-4o-mini scored about 72.9, so LoCoMo doesn't stress memory. Its conversations are 16–26k tokens and it has no
  knowledge-update questions.
- **Graphiti/Zep** (arXiv 2501.13956): a temporal knowledge graph with episode, entity and community subgraphs.
  - Edges are bi-temporal (when a fact was valid vs when it was ingested), and facts are invalidated, never deleted.
  - Scores: DMR 94.8 vs MemGPT 93.4; up to +18.5% on LongMemEval with about 90% lower latency.
- **A-MEM** (NeurIPS 2025): Zettelkasten-style notes with LLM-written keywords, tags and context. Adding a note links
  it to similar ones and can rewrite their attributes ("memory evolution").
- **LlamaIndex Memory** (May 2025):
  - Short-term is a FIFO (`token_limit` 30k, `chat_history_token_ratio` 0.7). Overflow is flushed in
    `token_flush_size` chunks into long-term blocks: `StaticMemoryBlock`, `FactExtractionMemoryBlock` (summarized
    past `max_facts`) and `VectorMemoryBlock`.
  - Each block has a priority: 0 is never truncated, higher numbers go first. `insert_method` chooses whether memory
    lands in the system message or the user message.
- **Generative Agents** (Park et al. 2023): a memory's score is recency + importance + relevance, each min-max
  normalized.
  - Recency decays by 0.995 per game-hour since last access. Importance is rated 1–10 by the LLM. Relevance is
    embedding similarity. All weights are 1.
  - Reflection triggers when the summed importance of recent memories passes 150 (recalled from the paper).
- **ChatGPT**:
  - Saved memories since 2024; "reference chat history" since Apr 2025.
  - The June 2026 update: memories are managed automatically, time-sensitive ones are revised, and there's an
    editable memory summary.
  - ChatGPT *pre-injects* a profile and recent-chat summaries into every chat. Claude's chat recall uses *visible*
    tool calls (`conversation_search`, `recent_chats`) over raw history; Willison prefers that.
  - OpenAI's FAQ: "Don't mention this again" does not delete; full erasure means clearing chats, the summary, files
    and connected apps.
- **Claude**:
  - Consumer memory: Sep 2025 for Team/Enterprise, Oct 2025 for Pro/Max. Isolated per project, editable, with an
    incognito mode.
  - Claude Code auto memory: a `MEMORY.md` index (the first 200 lines or 25 KB load each session) plus topic files
    typed user / feedback / project / reference. It skips anything derivable from code or git.
  - Keep CLAUDE.md under about 200 lines. Imports don't reduce its context cost, and contradictions get resolved
    "arbitrarily".
  - Managed Agents memory stores (Apr 2026): file-based, immutable versions, a redact endpoint, read-only org stores
    plus read-write user stores.
- **Google Vertex Memory Bank**: LLM extraction plus consolidation, generated asynchronously, with custom topics, TTL,
  memory revisions and per-identity scopes.
- **Arize Alyx** (Oct 2026): one structured file per user × space.
  - Capped at 8,000 characters and loaded in full every turn.
  - Updated after each turn with anchored edit operations, serialized by locks.
  - Compacted past 7k characters, protecting the profile, goals and `[user]` lines.
  - Writes are screened by a safety classifier. IDs, URLs and live metrics are excluded.
  - Graphiti had cost about 10 LLM calls per turn, which is why they left it.
  - Lessons: test memory for harm as well as help (it can record the agent's mistakes as rules), and a fact being in
    memory doesn't mean the agent applies it.

## Benchmarks

- **LoCoMo** (2024):
  - Conversations are short, so full-context wins.
  - No update questions, and category 5 has no ground truth.
  - The Penfield Labs audit (Apr 2026) found 6.4% of the answer key wrong, and the gpt-4o-mini judge accepted 62.8%
    of deliberately wrong but plausible answers.
- **LongMemEval** (ICLR 2025): 500 questions covering extraction, multi-session reasoning, temporal reasoning,
  knowledge updates and abstention.
  - Commercial assistants and long-context models drop about 30%.
  - It breaks memory design into indexing, retrieval and reading.
- **MemoryAgentBench** (ICLR 2026): tests accurate retrieval, test-time learning, long-range understanding and
  selective forgetting. No system masters all four.
- **MemoryArena** (arXiv 2602.16313): models near the ceiling on LoCoMo do poorly on interdependent multi-session
  tasks.
- **DMR** is saturated.
- The ETH study "Evaluating AGENTS.md" (arXiv 2602.11988): context files generally don't improve success, add more
  than 20% cost, and repository overviews don't help. They help only for non-standard practices.

## Security and privacy

- **Attacks**:
  - SpAIware (Rehberger, Sep 2024): indirect prompt injection wrote persistent exfiltration instructions into
    ChatGPT memory.
  - A delayed-trigger memory write in Gemini (Feb 2025).
  - MINJA (NeurIPS 2025): over 95% injection success into shared memory through queries alone.
- **Mitigations**: screen writes with a classifier, record provenance, scope per user or session, never write from
  untrusted tool output without a gate, version and audit memory, redact.
- Voss: "Treat memory as an attack surface, because it is one."

## Harness and supervisor details

- **Anthropic, "Effective harnesses"** (Justin Young, Nov 2025):
  - An initializer plus coding sessions; a JSON feature list where agents may flip only `passes` (models "less likely
    to improperly alter" JSON); a progress file; `init.sh`.
  - Every session starts the same way: progress, git log and features, start the server, run a basic e2e test.
  - It targets four failures: declaring victory early, leaving broken state, marking features done without e2e tests,
    and not knowing how to run the app.
- **Anthropic, "Harness design for long-running apps"** (Rajasekaran, Mar 2026):
  - A planner, a generator and an evaluator communicate through files.
  - **Sprint contracts**: the generator proposes what "done" means and the evaluator agrees before work starts. One
    sprint had 27 criteria, each a hard threshold.
  - Claude out of the box "talked itself into approving" work. Tuning a standalone evaluator to be skeptical is "far
    more tractable".
  - Context anxiety on Sonnet 4.5 is why they used resets. Opus 4.5 mostly removed it.
  - With Opus 4.6 they dropped sprints, kept the planner, and moved to a single evaluator pass at the end.
    Components were removed one at a time.
  - Cost: a solo run was 20 minutes and $9 and the result was broken; the full harness was 6 hours and $200.
  - "Every component in a harness encodes an assumption about what the model can't do."
- **Managed Agents** (Apr 2026): an append-only session event log outside the window, a stateless harness and
  replaceable sandboxes. Nothing is lost to compaction because the log can be re-read. Resets added for Sonnet 4.5
  "had become dead weight" on Opus 4.5.
- **Carlini's C compiler** (Feb 2026):
  - About 2,000 sessions, 16 agents, about $20k. A bash loop starts a fresh session per task; lock files in
    `current_tasks/`, synced through git; no orchestrator.
  - Memory: READMEs, progress files, and a running doc of failed approaches.
  - Test output is a few lines with details in log files; `--fast` samples 1–10% of the tests, a different sample
    per agent.
  - "Claude can't tell time."
  - GCC served as an oracle so agents could split work across files.
- **Anthropic's science post** (Mar 2026): CLAUDE.md holds the plan and CHANGELOG.md the lab notes. "The failed
  approaches are important—without them, successive sessions will re-attempt the same dead ends." A Ralph loop
  re-prompts the agent when it claims it's done.
- **Multi-agent research system** (Jun 2025):
  - 90.2% better than a single agent on their eval.
  - Token usage explained about 80% of BrowseComp variance.
  - The lead saves its plan to memory because context past 200k is truncated.
  - Subagents write to storage and return references, which avoids the telephone game.
  - A delegation names the objective, the output format, tool guidance and boundaries.
  - About 20 eval queries to start; a single LLM judge scoring 0–1 plus pass/fail.
- **Claude Code after compaction**:
  - Re-injected: the root CLAUDE.md, auto memory, the plan, and up to 5 recent files.
  - Skill bodies come back capped at 5k tokens each, 25k total.
  - Path-scoped rules are lost.
  - A SessionStart hook with the `compact` matcher can re-inject state.
- **Claude Code subagents**: no parent history is passed in; only a summary comes back; there's optional
  per-agent memory.
- **Agent teams**: experimental, not spawned in `-p` mode. Guidance is 3–5 teammates with 5–6 tasks each.
- **"Prompt caching is everything"** (Apr 2026):
  - Put static content first.
  - Put updates in messages, not the system prompt.
  - Never add or remove tools, or switch models, mid-session.
  - Compaction reuses the parent's prefix.
  - The team alerts on cache hit rate and declares SEVs when it drops.
- **Cognition**:
  - "Don't build multi-agents" (Jun 2025): share full traces; actions carry implicit decisions; prefer one thread
    plus a compression model.
  - Apr 2026: multi-agent works when "writes stay single-threaded and the additional agents contribute intelligence
    rather than actions".
  - The reviewer works best sharing no context with the coder.
  - Manager failures: over-prescriptive, assuming children share its state, children not reporting discoveries.
- **Cursor, "Scaling agents"** (Jan 2026):
  - Flat peers with a locked shared file: 20 agents ran at the throughput of 2–3.
  - What worked: planners and sub-planners, workers that don't coordinate, a judge, and fresh starts.
  - An integrator role was a bottleneck.
  - "The prompts matter more."
- **Cursor, dynamic context discovery**: long outputs go to files; history is saved to a file on summarization; MCP
  tools load by name only (−46.9% tokens).
- **OpenAI, "Harness engineering"** (Feb 2026; read via a secondary summary):
  - A ~100-line AGENTS.md "as a map" into a versioned `docs/` with exec-plans.
  - "Anything it can't access in-context… doesn't exist."
  - Review comments are promoted into docs and lint rules; background doc-gardening agents keep them current.
- **Codex AGENTS.md** is concatenated from the root down, capped at 32 KiB.
- **HumanLayer**:
  - 12-factor agents: own your context window (#3), contact humans with tools (#7), compact errors (#9), small
    focused agents (#10), the agent as a stateless reducer (#12).
  - ACE-FCA: research → plan → implement at 40–60% context use. "A bad line of a plan could lead to hundreds of bad
    lines of code."
- **Amp Handoff** (Oct 2025): replaced compaction with a goal-directed new thread.
- **Beads** (Yegge): a git-backed JSONL issue tracker with dependencies; agents query for ready work.
- **Cline Memory Bank**: projectbrief, productContext, activeContext, systemPatterns, techContext, progress.
- **Aider**: a repo map ranked by graph, within a token budget (1k by default).
- **Factory, "Evaluating compression"** (Dec 2025):
  - Argues for tokens per completed task, not per request.
  - Probe-based eval with recall, artifact, continuation and decision probes, judged by an LLM.
  - Artifact/file tracking was the weakest dimension for every method (2.19–2.45 out of 5).
- **Anthropic, "Demystifying evals"** (Jan 2026):
  - Start with 20–50 tasks drawn from real failures.
  - Grade outcomes, not paths, and read transcripts.
  - pass@k vs pass^k.
  - A near-0% pass rate usually means a broken task.

## Voice and LiveKit details

- **Latency**: Pipecat's guide targets about 1.5 s voice-to-voice with time-to-first-token ≤ 600 ms. Practitioners
  cite ≤ 800 ms, e.g. endpointing 300 + TTFT 250 + TTS 150 + network 80. p99s of 2–4 s are common.
  - LiveKit's own latency post gives no target. Its levers: shorter context, `max_tool_steps`, and co-locating
    regions (the biggest win).
- **Pipecat summarization**: triggers at 8k tokens or 20 messages and rebuilds context as [system] + [summary] +
  [recent], keeping function-call pairs intact.
- **OpenAI Realtime**: `conversation.item.truncate` plus `audio_end_ms` (automatic over WebRTC/SIP); sessions are
  capped at 60 minutes; `conversation:"none"` gives out-of-band responses.
- **OpenAI Agents SDK**:
  - Session backends: SQLite, Redis, SQLAlchemy, the Conversations API, compaction, encrypted.
  - Handoffs: `input_filter`, `nest_handoff_history`, which notes that summaries don't redact PII.
  - Auto-compaction can hold streams open, so turn it off for low latency.
- **ASR**:
  - EgoMem: memory accuracy tracked the word error rate until transcripts were repaired.
  - arXiv 2607.26410: unconstrained LLM correction breaks correct tokens in up to 64% of its edits.
  - Speechify extracts 0–5 facts per turn with confidence and ranks them by confidence × recency.
- **Identity**:
  - ElevenLabs uses a conversation-initiation webhook with `caller_id` and a post-call webhook.
  - Retell warns that a slow lookup at call start is audible.
  - Caller ID is spoofable.
- **LiveKit 1.x versions**:
  - 1.4: `LLMStream.collect()` outside a session; `AgentConfigUpdate`; job migration.
  - 1.5: adaptive interruption (86% precision / 100% recall at 500 ms, under 30 ms inference); dynamic endpointing;
    preemptive generation on by default.
  - 1.6: async tools.
  - 1.7: PII redaction.
  - 1.8: OTel GenAI conventions and in-process PII stripping.
- **ChatContext**:
  - `ChatMessage.interrupted`.
  - `truncate(max_items)` keeps the leading system message (bug #4843 is closed).
  - `_summarize(llm, keep_last_turns=2)`; PR #7721 fixed lost earlier summaries.
- **Preemptive generation** is thrown away if `on_user_turn_completed` changes the chat context or tools.
- **`close_on_disconnect=True`** by default: a refresh gives a fresh agent with no memory. A crashed agent is
  redispatched with no memory.
- **LiveKit memory blog posts** (Jesse Hall, Jun 2026):
  - Slots, one value per (user, tenant, type).
  - `preload_user` runs before `ctx.connect()`, injected as assistant messages.
  - Writes only through the `remember_detail` / `forget_detail` tools.
  - Hybrid `$rankFusion` search, with a filler line past 500 ms.
  - A session report in `on_session_end`.
  - A cookie identity, "not authentication".
  - Supabase version: pgvector and RLS, with the verified user id passed in dispatch metadata so the preload runs in
    parallel with connect.
- **Zep × LiveKit**: `ZepUserAgent` makes one round trip per turn. Extraction is async, so this turn's facts aren't
  searchable yet. Injecting into the system message gives retrieved text instruction priority.
- **Mem0 × LiveKit guide**: `add` and `search` are awaited in the turn hook (on the critical path), with a hard-coded
  shared `user_id`.
- **Durable workflows**:
  - Temporal × OpenAI Agents SDK: the agent runs as a Workflow and model calls as Activities.
  - Restate journals every LLM call and tool step and suspends while waiting.
  - LangGraph: checkpointers hold thread *state*; a Store holds cross-thread *memory*.
- **A2A**: donated to the Linux Foundation in Jun 2025, v1.0 in early 2026, 150+ organizations. Its pieces are the
  Agent Card, Task, Message, Part, Artifact and `contextId`.

## LiveKit Agents 2.0 (PR #7757, branch docs, read 2026-10-19)

- **Words.**
  - **thread**: the conversation. It has a platform-minted id `AT_…`, which is the A2A `contextId`.
  - **lane**: one agent's part of a thread.
  - **run**: one input to one result, tools included.
  - **transition**: what a tool or hook returns: `Completed`, `InputRequired`, `Working`, `Failed`, `Rejected`.
- **What a thread is.** "A text today, a call tomorrow that continues it: one thread, one memory."
  - **It is not:** a call (that's a job, a worker attached to a room); a request (a text message is a run); a person
    (one person may have several threads); or an agent's (any agent may continue it, each in its own lane).
  - **What it holds:** an id; a `scope` (an opaque person or account id, the only dimension threads are listed by);
    `attributes` (a small string map); `lanes`; and the `journal`.
  - **How it's found:** by id only. A message without a `contextId` starts a new thread. A call gets the `thread_id`
    from its dispatch metadata, otherwise a new thread.
  - **Lifecycle:** created on first contact, never by agent code. It expires after `idle_ttl`; any update counts as
    activity. Deleting a thread deletes everything in it. There is nothing to open or close.
- **One memory per thread.** "An application that wants one memory keeps one thread per person."
- **Lane**:
  - Holds: history (what the model sees), state (typed), the agent stack (who's speaking; pushed on a handoff), tasks
    (one row per turn or background task, as A2A tasks), an inbox (messages that arrive during a turn under `batch`),
    and the lease.
  - A lane belongs to an agent, not to a door: the phone line and the text endpoint write the same lane.
  - A handoff on the same worker stays inside one lane and moves the agent stack. Delegating to another registered
    agent creates a new lane.
- **Single writer.**
  - The **lease** lasts 10 s and is renewed every 3. Being the holder means having the token, not winning on the
    clock.
  - The **fence**: each commit is conditional on the loaded version and the lease token, and bumps the version.
    Otherwise it fails with `VersionConflict`.
  - Waiters run in arrival order. Under interrupt/queue they give up after 60 s with `lease-timeout`.
  - A run whose worker died is not re-run: it fails `worker-lost` and the client resends.
  - The `concurrent` policy takes no lease, commits append-only and writes no state.
- **Voice and text share a lane.** A call's `LiveSession(thread=ctx.thread)` takes the lease for each voice turn.
  When it finds a newer version, it reloads history and state before the model reads them.
- **State vs deps.**
  - `state` is "what the agent has learned": typed, loaded before every run, saved after any run that changed it,
    at most 64 KiB. A `NotSerializable` error almost always means the field belongs in deps.
  - `deps` are per-run services, never saved; tests pass fakes.
- **Journal vs history.**
  - History is the model's view; the developer edits it (truncate, summarize, delete).
  - The journal is the framework's append-only record, shared by every lane, and survives compaction.
  - Each event carries `id`, `ts_ms`, `lane`, `run_id`, `type` and `payload`. Types: `run_started` (task id,
    channel), `run_ended` (outcome and reason), `usage` (tokens, requests, tool calls), `conversation_item_added`,
    `tool_execution_updated`, `error`, plus the voice runtime's events.
  - A `run_started` with no `run_ended` after it is how an interrupted run is found.
  - The journal holds no audio, no state and no hand edits.
- **Channels.** The handler never knows which channel a message came from: one thread, history and state across all
  of them. Built today: web chat, API, partner agents, phone calls. Each message carries `livekit/channel`.
  - A reply goes back on the channel the message came from.
  - A text during a call is answered by text; the call learns of it on its next turn.
  - A call after a text sees what was said by text.
- **Planned channels.**
  - SMS, WhatsApp and calls share a `phone:+E164` key, so one number is one thread. Email is keyed
    `email:<address>`. A thread has at most one key, and it never changes. The ingress resolves the key to a thread
    (get-or-create); the key never appears on the wire.
  - The default policy for these channels is `batch` (a 2 s debounce).
  - "A text during a call, heard live" uses `LiveSession.on_inbox_message`.
  - A call can answer a text question that's still pending.
  - Email threads on `Message-ID` and `In-Reply-To`.
- **Turn policies.**
  - `interrupt`: the default for web and API; a new message cancels the running turn.
  - `queue`: the default for delegations.
  - `batch`: the default for SMS, WhatsApp and email.
  - `concurrent`: opt-in.
- **"Across days" means background tasks (planned).**
  - An `AgentTask` returns `Working(tool=..., timeout=timedelta(days=3))`. `on_timeout` gives the next transition.
  - A delegation that isn't awaited, `A2ADelegate.send()`, runs on its own lane and survives the turn, the worker and
    deploys. Its result arrives later as a message on the caller's lane.
  - **The clock** (`delay=` / `timeout=`) is owned by agent-service, not by a worker.
  - Outside calls are keyed on `ctx.task_id`, because a hook may run again after a crash.
  - A backend can start a task from outside with `livekit/task`.
  - Example: a prescription refill that waits days for the prescriber.
- **Multi-agent.**
  - **Delegation**: the expert runs on a fresh history, and the caller sees only the tool call and result.
  - **Handoff**: a tool returns an `Agent`, which continues on the same history.
  - **Remote experts**: `A2ADelegate(url)`. If the expert's card offers the Live extension, it shares the caller's
    thread and gets its own lane.
  - `input-required` sends the expert's question to the person word for word.
- **Earlier work.**
  - `livekit-durable` (pickled coroutines, Dec 2025) and draft PR #4343, a durable scheduler.
  - 2.0 says "no frame or local variable survives a run", so state is committed at run boundaries.

## Key sources

- Anthropic:
  - [Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) (Sep 2025)
  - [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) (Nov 2025)
  - [Harness design for long-running apps](https://www.anthropic.com/engineering/harness-design-long-running-apps) (Mar 2026)
  - [Scaling Managed Agents](https://www.anthropic.com/engineering/managed-agents) (Apr 2026)
  - [C compiler with parallel Claudes](https://www.anthropic.com/engineering/building-c-compiler) (Feb 2026)
  - [Multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system) (Jun 2025)
  - [Demystifying evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) (Jan 2026)
  - [Memory tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool) and [context editing](https://platform.claude.com/docs/en/build-with-claude/context-editing)
  - [Claude Code memory](https://code.claude.com/docs/en/memory)
  - [Prompt caching is everything](https://claude.dev/blog/lessons-from-building-claude-code-prompt-caching-is-everything) (Apr 2026)
- [Manus: context engineering lessons](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus) (Jul 2025)
- Cognition: [Don't build multi-agents](https://cognition.com/blog/dont-build-multi-agents) (Jun 2025), [Multi-agents: what's actually working](https://cognition.com/blog/multi-agents-working) (Apr 2026)
- [LangChain: write/select/compress/isolate](https://www.langchain.com/blog/context-engineering-for-agents) · [LangMem concepts](https://langchain-ai.github.io/langmem/concepts/conceptual_guide/)
- [Chroma: Context Rot](https://www.trychroma.com/research/context-rot) · [Breunig: How long contexts fail](https://www.dbreunig.com/2025/06/22/how-contexts-fail-and-how-to-fix-them.html)
- [ACE: Agentic Context Engineering](https://arxiv.org/abs/2510.04618) · [CoALA](https://arxiv.org/abs/2309.02427) · [Memory survey (Dec 2025)](https://arxiv.org/abs/2512.13564)
- Letta: [sleep-time compute](https://letta.com/blog/sleep-time-compute), [filesystem beats memory on LoCoMo](https://www.letta.com/blog/benchmarking-ai-agent-memory) · [Mem0 paper](https://arxiv.org/abs/2504.19413) · [Zep rebuttal](https://www.getzep.com/blog/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory/) · [Graphiti](https://arxiv.org/abs/2501.13956)
- Benchmarks: [LongMemEval](https://arxiv.org/abs/2410.10813) · [MemoryAgentBench](https://arxiv.org/abs/2507.05257) · [LoCoMo audit](https://dev.to/penfieldlabs/we-audited-locomo-64-of-the-answer-key-is-wrong-and-the-judge-accepts-up-to-63-of-intentionally-33lg) · [Evaluating AGENTS.md (ETH)](https://arxiv.org/abs/2602.11988)
- Practitioners: [HumanLayer ACE-FCA](https://github.com/humanlayer/advanced-context-engineering-for-coding-agents/blob/main/ace-fca.md) · [12-factor agents](https://github.com/humanlayer/12-factor-agents) · [Cursor: scaling agents](https://cursor.com/blog/scaling-agents) · [Factory: evaluating compression](https://factory.com/news/evaluating-compression) · [Ralph](https://ghuntley.com/ralph/)
- LiveKit:
  - [Agents 2.0 beta PR #7757](https://github.com/livekit/agents/pull/7757) and its docs: [lanes](https://github.com/livekit/agents/blob/agents-2.0/docs/lanes.md), [state and deps](https://github.com/livekit/agents/blob/agents-2.0/docs/state-and-deps.md), [journal](https://github.com/livekit/agents/blob/agents-2.0/docs/journal.md), [multi-agent](https://github.com/livekit/agents/blob/agents-2.0/docs/multi-agent.md), [text endpoints](https://github.com/livekit/agents/blob/agents-2.0/docs/text-endpoints.md)
  - Docs: [handoffs](https://docs.livekit.io/agents/logic/agents-handoffs/), [workflows](https://docs.livekit.io/agents/build/workflows/), [tasks](https://docs.livekit.io/agents/logic/tasks/), [external data](https://docs.livekit.io/agents/logic/external-data/), [test framework](https://docs.livekit.io/agents/start/testing/test-framework/)
  - Blog: [MongoDB memory](https://livekit.com/blog/mongodb-voice-agent-memory), [Supabase memory](https://livekit.com/blog/supabase-voice-agent-memory), [handoff pattern](https://livekit.com/blog/handoff-pattern-voice-agents), [supervisor pattern](https://livekit.com/blog/supervisor-pattern-voice-agents), [reconnect](https://livekit.com/blog/keep-your-agent-in-the-room-on-reconnect)
  - Community: [interrupted-text thread](https://community.livekit.io/t/chat-context-contains-text-that-wasnt-spoken-due-to-interruption/165), issue [#6424](https://github.com/livekit/agents/issues/6424)
- Voice: [Pipecat voice AI guide](https://voiceaiandvoiceagents.com/) · [Pipecat context summarization](https://docs.pipecat.ai/guides/fundamentals/context-summarization) · [Zep × LiveKit](https://help.getzep.com/livekit-memory) · [Mem0 × LiveKit](https://docs.mem0.ai/integrations/livekit.md)

**Unverified:**

- the content of Voss's and Warraky's talks (abstracts only)
- the "Dreaming" naming for ChatGPT and Claude Code
- OpenAI's harness-engineering post (the page returned 403)
- vendor-reported benchmark numbers (Mem0 2026, Cognition, Factory)
- whether Agents 2.0 ships as described
