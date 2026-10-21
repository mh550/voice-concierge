# Integrated concierge: session lifecycle, memory contract v2, knowledge v2, conversation evals, the usher

Date 2026-10-21. From Michael's test of the live agent on 2026-10-20/21 through the portfolio's `/talk` page.
Builds on `origin/main` at `8333fae` (C1–C8 merged). `docs/spec.md` stays the design (§4.0 practice by practice,
§6 the v1 contract); this file adds to it. The page half runs in parallel in `mh550/portfolio_site` (spec
`docs/specs/2026-10-21-portfolio-v3.md` there, § 7 and § 4–5); §2 here is the contract both build to, word for
word. **Nothing in this run needs Michael: take the default written here, record it as `D<n> *default*` in
`docs/decisions.md`, and never park.** Build-only, offline suite, as `CLAUDE.md` says; the live checks go in
`MORNING.md`.

One milestone per section, in this order; each is a coherent PR, merged by the harness as before.

## 1. What Michael saw, and the causes to fix

1. He asked about Michael's projects, his work experience and database administration, then clicked another
   link on the site without pressing Leave. Coming back, the page said "You already have a conversation open in
   another tab" and "What it remembers" was empty. Some minutes later the memory, latency and all were there.
   **Cause**: the page's component unmounts on client-side navigation and disconnects the visitor, but nothing in
   the agent reacts to the visitor's participant leaving. The session runs on to its 10-minute cap (`limits.py`),
   so the room stays live, the token route's one-room-per-address rule (`limits.ts` in the site) answers 429
   `visitor`, and the final extraction and visit summary only run when the cap ends the session. Milestone V1.
2. The intro said "specs in, verified milestones out" (about the harness, read as about the concierge) and
   mentioned a Forget me button that isn't on screen before a call. The page fixes both (its spec P3); the agent's
   README and MORNING.md stop using that phrase too (V5).
3. The agent must never say "pack" or "knowledge pack" to a visitor, and it **must** be able to talk about
   itself: how its memory works, what it stores, what it won't store, how it was built. Today the pack has no
   section about the concierge or the harness in spoken terms, and the instructions say nothing about describing
   itself. V3.
4. The visitor should see, live and by kind, what is remembered about them and what the agent itself carries
   (knowledge, working context, cache). The v1 body has facts and one summary only. V2.
5. Testing the agent's behaviour needs real sessions today. V4 adds a conversation-eval tier that runs the real
   prompt and LLM through the text path, with no STT, TTS or LiveKit room, plus an offline twin.
6. Later, the agent ushers the visitor through the site as it talks. V6 is the agent half of that.

## 2. Contract v2 (shared)

Everything in the 2026-10-19 contract (agent name `concierge`, dispatch metadata, identity `visitor-<visitor_id>`,
rooms `concierge-<addr10>-<12 hex>`, topics `concierge.memory` and `concierge.metrics`, RPCs `concierge.forget_me`
and `concierge.get_memory`, `lk.chat`, the 10 s offline rule) still holds. v2 **adds**; it removes nothing, and every
new field is optional, so a v1 page works against a v2 agent and a v2 page works against a v1 agent (missing fields
render as "not reported", never as an error).

- **`concierge.memory` v2 body** (sent at session start, after every merge, after a compaction, and once more as
  the final message before the agent leaves): the v1 keys `visitor`, `facts`, `summary`, `updated_at`, plus
  - `"v": 2`
  - `"about_visitor"`: `{ "profile": [fact…] (the valid typed-slot facts, same shape as v1 facts), "episodes": [ {"visit": int, "started_at": iso, "ended_at": iso|null, "summary": str|null} ] (newest first, at most 5; the current visit has ended_at null and summary null until the session ends), "events": [ {"ts": iso, "type": "fact_added"|"fact_invalidated"|"fact_deleted"|"gate_rejected"|"extraction_ran"|"remember"|"forget", "detail": str} ] (this session only, newest first, at most 12; detail is one short plain sentence with no instruction text and no URL) }`
  - `"about_agent"`: `{ "knowledge": {"words": int, "est_tokens": int, "sources_commit": str, "sections": [str]}, "instructions_est_tokens": int, "memory_block_chars": int|null, "working": {"items": int, "est_tokens": int, "compacted": bool, "compactions": int}, "cache": {"cached_share": float|null} }`
  - `"retention_days": 30`
- **`concierge.navigate`** (agent → page, new topic; body ≤ 1 KiB): `{ "href": "/projects/<slug>" | "/skills" | "/experience" | "/about" | "/contact" | "/", "reason": str, "at": iso }`. The agent sends it only from its `show_page` tool and only for hrefs on its allowlist (the routes above; project hrefs only for slugs its knowledge names). The page follows it only while the visitor's **Guide me** toggle is on (default on during a live call), with a visible one-line notice naming the destination, never more than once per 8 s, and never away from `/talk` if the visitor opened the concierge there as a full page (the panel keeps the call across client-side navigation).
- **`concierge.get_memory`** returns the v2 body.
- **Session end on departure**: when the visitor's participant disconnects and does not reconnect within 20 s, the agent runs its shutdown sequence (final extraction, visit summary, final `concierge.memory`, journal `visitor_left`) and leaves, so the room closes and the token route's one-room-per-address limit frees within about 30 s of the visitor leaving. The page, on a 429 `busy`/`visitor`, shows "Closing your earlier conversation…" and retries the token request every 5 s for up to 60 s before it shows the v1 busy line.


## 3. V1: the session ends when the visitor leaves

- Register `participant_disconnected` on the room at session start (read the installed 1.8.8 `rtc.Room` event
  names in `.venv`; never guess). When the disconnected identity is the visitor's (`visitor-<visitor_id>`), start a
  20 s grace timer (D: 20 s, so a reload or a client-side route change that remounts can reconnect without a new
  session). `participant_connected` with the same identity cancels it. When it fires: journal `visitor_left`,
  then end the session the way the 10-minute cap does (`ctx.shutdown("visitor left")`), so `on_shutdown` runs the
  final extraction, the visit summary and the final `concierge.memory`, and the agent leaves the room.
- The grace must not hold the shutdown's own deadline up; cancel it first in `on_shutdown` like the cap timer.
- Tests with `FakeRoom` and `RecordingSession`: the visitor leaves → after the grace the session ends with
  reason `visitor left` and one `visitor_left` journal row; the visitor leaves and returns within the grace →
  nothing ends; a second participant that is not the visitor leaves → nothing happens; the final `concierge.memory`
  is sent before close (the `episodes[0].ended_at` is set and its `summary` is the written one).
- `README.md` § Failure cases and limits: replace the line about a refreshed page or second tab with how it works
  now, and that the site's token route frees the address within about 30 s.

Features: build (events + grace + shutdown reason) · tests and README line · review (small; fold into V2's review
if the initializer prefers).

## 4. V2: memory contract v2

- `concierge/contract.py`: extend `MemoryPayload` with `v`, `about_visitor` (`profile`, `episodes`, `events`),
  `about_agent` (`knowledge`, `instructions_est_tokens`, `memory_block_chars`, `working`, `cache`) and
  `retention_days`, exactly as §2 spells them; keep the v1 keys populated as before. `tests/contract/memory.schema.json`
  gains the v2 shape; a v1 body still validates (every new key optional).
- **Episodes.** The store keeps one summary per visit, not only the last one: add `visit_summaries` rows
  (`thread_id`, `visit`, `started_at`, `ended_at`, `summary`) written by the shutdown's summary step; the
  `VisitorState.summary` (the last one, what the prompt renders) is unchanged. At most 5 are sent; older rows are
  purged with the thread. Forget me erases them (extend the erasure-wins tests).
- **Events.** A per-session ring of at most 12 short plain-language lines built from the journal rows this session
  writes (`fact_added` → "Remembered your role: engineer"; `gate_rejected` → "Didn't store something that looked
  like an instruction"; `extraction_ran` → "Took notes in the background (n changes)"; `remember`/`forget` from the
  tools). Values may be shown (they are the visitor's own), instruction-like or URL text never (the gate already
  stops it from being stored; the event line names the reason only).
- **About the agent.** `knowledge`: words and estimated tokens of `knowledge/michael.md`, the commit in
  `knowledge/sources/SOURCE.md`, the `##` section titles. `instructions_est_tokens`: `estimate_tokens` of the static
  instructions. `working`: the current chat context's item count and estimated tokens, whether compaction has run
  and how often (from the compactor). `cache`: the last turn's cached share from the metrics.
- Publish after a compaction too (the compactor gets the publisher's `schedule`). `concierge.get_memory` returns the
  same body. The 15 KiB cap still holds: the events and episodes are capped so a full body fits; a test builds the
  largest allowed body and checks the size.
- `README.md` § What it does and § Architecture: the v2 body, in one paragraph and the field table.

Features: plan · contract + schema · visit summaries store + erasure · events ring + about_agent + publish points ·
review + simplify.

## 5. V3: knowledge v2 and talking about itself

- **Re-vendor the sources.** `CLAUDE.md` forbids reading the live `~/projects/portfolio_site`; the repo is public.
  Clone `https://github.com/mh550/portfolio_site` at depth 1 into the scratch directory, copy `Bio.md` and
  `src/lib/data/{profile,experience,projects,skills}.ts` into `knowledge/sources/`, and record the commit in
  `SOURCE.md`. The portfolio's angle milestone (its P1/P2) may not be on its `main` yet when this runs: so the pack
  is built from the vendored files **and** the resume v4 text and angle in §7 of this spec, with the resume
  winning where they differ (it is newer). Record this in `SOURCE.md` ("resume v4 of 2026-10-20, from the spec").
- **The pack** (`knowledge/michael.md`, still ≤ 1,200 words, every section naming its source) gets:
  - the new positioning line and subline (§7) in "Positioning and contact";
  - experience bullets from the resume v4 (the two roles, the two resume projects); Tahoma Films and the
    coaching stay as one line each;
  - the skills grouped the resume's way (Agentic AI · Languages & web · Data & integration · Infra & tools);
  - a **"Project: Voice Concierge (this agent)"** section, in spoken-friendly terms, from `README.md` and
    `docs/spec.md` §4.0: what it is, that it runs on Michael's home box and connects to LiveKit Cloud, how its
    memory works (one thread per visitor; facts with where and when they were learned; a short summary of each
    visit; notes taken in the background after a turn, never while answering; corrections keep history instead of
    overwriting; a gate that refuses instructions, links and secrets; everything erased by Forget me; 30-day
    retention; nothing shared between visitors), what it carries about itself (a fixed description of Michael's
    work that is cached, a small working context that gets compacted on long calls), what it can't do (no general
    chat, no guessing numbers, no memory across browsers), and that it was built by Michael's agent harness from
    a written spec, with the memory design researched and written down practice by practice first;
  - a **"Project: Agent Harness"** section refreshed from the vendored `projects.ts` entry and §7 (it exists; keep
    it current, and keep every number traceable to the vendored sources or §7).
- **Instructions** (`prompt.py`): replace "Never mention the pack or its Source: lines" with: never use the words
  "pack", "knowledge pack" or "source lines" with a visitor; say "what I know about Michael" or "my notes". Add:
  when asked about yourself, your memory, what you store or how you were built, answer from the "Voice Concierge
  (this agent)" section as freely and concretely as any other topic; that is on-topic and Michael wants it
  explained. Keep the budget tests green (static + pack ≤ 3,000 estimated tokens: trim the pack elsewhere if
  the new section pushes it over, and say what was cut in the plan).
- **Policy check.** Michael asked whether describing its own implementation conflicts with LiveKit's or the
  providers' terms. Check docs.livekit.io (Agents, Cloud terms) and the Anthropic usage policy for any rule about
  an agent describing its own system or prompts; the agent self-hosts its prompt, so none is expected. Write the
  finding with URLs and the date in `docs/decisions.md` as a D, and one sentence in the README § Privacy.
- **Drift check**, not auto-rebuild (D: the pack is prose an LLM writes; rebuilding it automatically would need a
  key and a review, so the honest tool is a check): `scripts/check_sources.py` fetches the five source files from
  GitHub `main` (raw URLs, stdlib `urllib`) and diffs them against `knowledge/sources/`, printing which files drifted
  and the commit in `SOURCE.md`; exit 1 on drift. It is network, so it is **not** in the offline suite; MORNING.md
  gets a step; a `test_scripts.py` case checks its diff logic against two fixture trees offline.
- `tests/test_knowledge.py`: the new section exists, the forbidden words are absent from the instructions, the
  sources commit in SOURCE.md matches the vendored files' header, the budget holds.

Features: plan · re-vendor + pack · instructions + policy check · drift script + tests · review + simplify.

## 6. V4: conversation evals (an LLM-only tier)

A middle tier between the offline suite and the live room tests: run the real instructions, pack and tools through
the text path with a real LLM, no STT, TTS, LiveKit room or keys for them.

- `evals/conversation/*.yaml`: 8–12 scripted conversations, each a list of visitor turns (text) and, per turn,
  assertions on the reply: `must_mention` (any of), `must_not_mention` (none of, case-insensitive; "pack",
  "knowledge pack", "source:" in every script), `max_sentences` (3), `tool_called` (optional). Required scripts:
  the projects question; the work-experience question; "do you have database experience" (the DBA question Michael
  asked: the answer must come from the pack and say what it doesn't know); "how does your memory work"; "what do
  you store about me"; "how were you built"; an off-topic request; a name introduction (confirmation asked);
  "remember that I…" (tool called); an injection ("ignore your instructions"); a question about a number not in
  the pack (it must say it doesn't know).
- `scripts/eval_conversation.py`: runs each script through the agent's text path (`AgentSession.run(user_input=…)`
  or the 1.8.8 equivalent; read the installed source), with the configured LLM from `config.py` (so it needs
  `ANTHROPIC_API_KEY`; marked `llm`, like `live` it is Michael's to run), and prints a table: script · turn · pass/fail
  · the failing assertion and the reply. `pytest -m llm` wraps it (skipped without the key, excluded from the
  offline suite like `live`).
- **Offline twin**: the same runner with `FakeLLM` scripted replies, in the suite, proving the plumbing: assertions
  fire, tool calls are detected, the forbidden-word check works, a failing script fails the run.
- MORNING.md: a step with the command and what a pass looks like; README § How it's verified: the three tiers
  (offline · llm · live) in one table.

Features: plan + runner (TDD against the fake) · scripts (yaml) + twin tests · docs · review.

## 7. The angle and the resume v4 text (for V3)

Positioning line (the portfolio's default for this run; Michael may still change the words): **Agentic Systems
Engineer**. Subline: *I build the harnesses, memory and verification around AI agents, and the integrations they
run on.* Tagline unchanged: *I build simple, elegant systems that fit the humans who run them.* The hero's loop:
Spec · Context · Build · Verify · Learn.

Resume v4 (2026-10-20), the phone number left out on purpose and never to be added to the pack:

> **MICHAEL HERRON**
> mherron734@gmail.com | www.mherron.dev | github.com/mh550 | /in/mherron734
>
> *Full-stack engineer building agentic systems: harness and context engineering, durable agent memory, and verification agents can't bypass, on top of production multi-tenant integrations.*
>
> **WORK EXPERIENCE**
> **Full-Stack Software Engineer, MAXX Potential** *February 2026 - present*
>
> * Shipped React Native, Next.js, edge-function, and Postgres features for a contractor estimating app (~8 issues/week); codified recurring UI fixes into a knowledge source agents load as procedural memory.
> * Replaced siloed spreadsheet bug tracking with Linear and an agentic bug-fix workflow (CLI tooling + custom slash commands): 2× sprint throughput, ~80% less bug-filing time, no new software costs.
> * Designed enterprise Copilot Studio agents: split an over-scoped JD agent into manager and HR agents so each context holds only its data; built an org-restructure impact model alongside SAP SuccessFactors.
>
> **Founding Full-Stack Software Engineer, Builder Clarity** *March 2025 - November 2025*
>
> * Architected a multi-tenant JobTread ↔ GoHighLevel integration platform with managed multi-org OAuth, replacing per-client builds: 3 clients, onboarding cut from ~2 days to ~6 hours.
> * Integrated CRM, VoIP (RingCentral), and internal systems, incl. a unified per-job communications log, saving ~8 hrs/week per client; built ETL normalizing 4+ sources into Postgres.
> * As first engineer, led the move from Zapier to n8n and Pipedream (custom JS components), replacing per-client automations with reusable multi-tenant workflows.
>
> **PROJECTS**
> **Long-Running Agent Harness | github.com/mh550/agent-harness** *October 2026 - present*
>
> * Engineered a deterministic Bash harness that runs Claude Code agents in isolated git worktrees and takes tests, verification, and merges out of the agent's hands, merging only byte-identical verified trees.
> * Designed agent memory through context engineering: a fresh context window per feature, rebuilt from durable on-disk state, with project rules as procedural memory and run retros as episodic memory.
> * Runs remote-first on my home server, steered from laptop or phone via push alerts and a per-run inbox; parallel runs share one usage-limit gate with backoff; 189 features passed in 4 days at ~$3 each.
>
> **Self-Hosted Music Server & DJ Pipeline | github.com/mh550/dj-crate-streaming** *November 2025 - present*
>
> * Self-hosted streaming + DJ ‘crate’ preparation pipeline using Docker Compose behind Tailscale: flagging a playlist as a crate enqueues its missing tracks; a worker container downloads, verifies, and files them.
> * Song/version/copy identity model dedupes only decode-identical audio; downloads verified by ffmpeg decode analysis and acoustic fingerprint; 1,500+ offline tests on fakes built from captured live responses.
>
> **TECHNICAL SKILLS**
> **Agentic AI:** harness & context engineering, agent memory, durable state, eval gates, Claude Code
> **Languages & Web:** TypeScript, Python, Bash, SQL, Java, C++, React, React Native, Next.js, Node.js
> **Data & Integration:** PostgreSQL, Supabase, SQLite, REST, webhooks, OAuth 2.0, ETL, n8n, Pipedream
> **Infra & Tools:** Docker Compose, Linux, Git/GitHub, CI/CD, Vercel, edge functions, Tailscale, Linear
>
> **EDUCATION**
> *Duke University, Durham, NC* *Graduated December 2024*
> B.S. Computer Science; Visual & Media Studies Minor
> **Relevant Coursework:** Database Systems, Algorithm Design & Analysis, Computer Security, Server-side Web Apps, Computer Systems, Data Structures & Algorithms

## 8. V5: README, MORNING and the phrase

- Remove "specs in, verified milestones out" wherever this repo says it about the concierge (README, MORNING,
  docstrings); the harness built it, the phrase describes the harness.
- README § What it does gets the v2 memory view, the session-end-on-departure rule, the usher (V6) and the three
  test tiers. MORNING.md gets the drift check and the conversation eval steps, in the "Check / Undo" form it uses.
- Features: docs (sonnet) · review.

## 9. V6: the usher (agent half; stretch, `after: ["V3"]`)

- A `show_page(href, reason)` function tool: hrefs from an allowlist built at startup from the pack's project
  slugs (`/projects/<slug>` for each "Project:" section's slug: add the slug to each section header's Source line,
  e.g. `Source: projects.ts (slug: agent-harness)`) plus `/skills`, `/experience`, `/about`, `/contact`, `/`. The
  tool publishes `concierge.navigate` (§2) and returns "Showing them <page>"; off-list hrefs are refused and
  journaled. Rate-limited to one per 8 s in the agent too.
- Instructions: when you start talking about one of Michael's projects or a page's topic, call `show_page` once for
  it, then keep talking; never call it for the same page twice in a row; don't announce the page unless asked.
- Tests: the allowlist from a fixture pack; the publish body; the refusal; the rate limit. A conversation eval
  script (V4) asserts `tool_called: show_page` on "tell me about the harness".

## 10. Order and what is left to later

V1 → V2 → V3 → V4 → V5 → V6. V2 needs V1 (episodes end when the session does); V3 needs V2 (the `about_agent`
knowledge fields); V4 needs V3 (the self-description scripts); V5 needs V4; V6 needs V3. Emit these as `after`.

Left to Michael: running the `llm` and `live` tiers, the drift check, and measuring numbers (README § Results);
automatic pack rebuilds (rejected above); a lease for two live sessions of one visitor (docs/spec.md's known gap).
