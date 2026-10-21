# Decisions

Michael's decisions (10-19) are D1–D6 and the builder's calls are B1–B12, both in `docs/spec.md` §3. New ones go here,
numbered from D7, as `D<n> *default*` when a session takes a default Michael hasn't confirmed: the finding, the
choice, what was rejected.

## D7 *default*: turn detection is silero VAD only (2026-10-20, C1-01)

**Finding.** B1 leaves the builder a choice between LiveKit's turn-detector model and VAD-only turn detection. In the
installed livekit-agents 1.8.8, `AgentSession` defaults to `turn_detection=inference.TurnDetector()` and
`vad=inference.VAD(model="silero")` (`voice/agent_session.py:576`, `:642`). Off LiveKit Cloud hosting, the detector
resolves to the local `turn-detector-v1-mini`, whose weights ship inside the `livekit-local-inference` wheel. It
needs no `download-files` step, and building it offline works with no keys. The cloud `v1` detector is used only
when hosted or in dev mode with keys, which spends the Build plan's development allowance.

**Choice.** VAD only: `vad=silero.VAD.load()` (the model ships in the plugin wheel, so there's no download at
import or in the suite) and `turn_handling={"turn_detection": "vad"}`, set explicitly because omitting it selects
the model detector. Reasons: it's the simplest and most predictable mode for the offline suite and the first
morning test, it never touches the hosted allowance, and there's no extra model in memory.

**Rejected (for now).** The turn-detector model (`inference.TurnDetector()`, or the separate turn-detector plugin).
It's better at not cutting people off mid-thought, and in 1.8.8 it needs no download. Switching is one line in
`concierge/worker.py` (drop the `turn_detection` key or pass `inference.TurnDetector()`). If the morning test shows
the agent interrupting pauses, switch.

**Question for Michael.** Keep VAD only, or switch to the local turn-detector model now that it needs no download?

## D8 *default*: a per-fact `forget` leaves the turn's text in the journal (2026-10-20, C2-01)

**Finding.** Spec §4.2 puts turn text in the journal (`user_turn`, and `agent_turn` with the heard text), and §4.0
offers "forget" per fact. The `forget` tool really deletes the fact (B5), but the `user_turn` journal row the fact
came from still holds what the visitor said, until "Forget me" or the 30-day idle purge.

**Choice.** Keep the turn text in the journal; journal `fact_*` payloads carry ids and slots, never values (so the
fact's value isn't copied anywhere else); the README's limits section says that a per-fact forget removes the
memory, not the transcript, and that "Forget me" removes both. The journal never reaches the prompt or the page.

**Rejected.** Scrubbing journal text on every `forget` (it would need to find the fact's words inside free text,
which is guesswork), or storing no turn text at all (the spec wants the journal to keep every turn, §4.8).

**Question for Michael.** Is "forget removes the memory; Forget me removes the transcript too" the promise you
want, or should a per-fact forget also blank the text of the turn it came from?

## LLM provider: Anthropic direct (Michael, 2026-10-20)

**Decision.** Every LLM call (conversation, extractor, summarizer) goes straight to the Anthropic API through
`livekit-plugins-anthropic` 1.8.8 (spec D5, B1, B10, §4.10, amended by Michael). OpenRouter stays as a fallback:
`CONCIERGE_LLM_PROVIDER=openrouter` gives every stage `openai/gpt-4.1-mini` through `openai.LLM.with_openrouter`,
as before. `CONCIERGE_<STAGE>_MODEL` overrides a stage's model under either provider. Built in P1-01:
`concierge/config.py` (`llm_provider`, `build_llm`) and `concierge/claude_llm.py` (`ClaudeLLM`, `build_claude_llm`).

**Why.** It's paid from Michael's Claude Console credit; it's one network hop fewer than a gateway; Haiku gives the
spoken reply the fastest first token; and the extractor can't rely on a forced tool call anyway, because Sonnet 5.5
and Opus 5.5 reject `tool_choice` `any`/`tool` with a 400, so C4 asks for `emit_ops` with `tool_choice="auto"`.

**Per stage** (`concierge/claude_llm.py`):

| Stage | Model | Request settings |
|---|---|---|
| conversation | `claude-haiku-5-5` | `thinking={"type": "disabled"}` (Haiku 5.5 accepts it at its default effort); `caching="ephemeral"` on the LLM; the plugin's default `max_tokens` 1024 |
| extractor, summarizer | `claude-sonnet-5-5` | `output_config={"effort": "low"}`; `max_tokens=4096` through the constructor; server-side refusal fallback: `extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"}` and `extra_body={"fallbacks": "default"}` |

No stage sends `temperature` or `top_k` (5.x models reject sampling parameters). No request ends on an assistant
message (5.x models reject prefill).

**What the plugin does** (read in `.venv/lib/python3.12/site-packages/livekit/plugins/anthropic/llm.py`, 1.8.8):

- `LLM.__init__` raises `ValueError("Anthropic API key is required, ... ANTHROPIC_API_KEY ...")` when neither
  `api_key` nor the env var is set, even when a `client` is passed (`llm.py:120-125`). So `build_llm` runs only inside
  a session, and offline tests set a dummy key alongside the fake client (`llm.py:127` uses `client` when given).
- `chat(extra_kwargs=...)` copies extra_kwargs into the request (`llm.py:163-166`) and passes them to
  `client.messages.create(..., **extra)` (`llm.py:273-279`). That's how `thinking`, `output_config`,
  `extra_headers` and `extra_body` reach the API; the SDK (anthropic 1.15.0) takes all four as keywords.
- It then sets `extra["max_tokens"]` from the constructor, default 1024 (`llm.py:183`), overwriting any
  `max_tokens` in extra_kwargs. So the background stages pass `max_tokens=4096` to the constructor.
- `temperature`/`top_k` go into `extra_body` only when given to the constructor (`llm.py:171-181`); `ClaudeLLM`
  doesn't accept them.
- The prefill guard `_model_disables_prefill` matches only `claude-sonnet-4-6` and `claude-opus-4-6`
  (`llm.py:41-46`), and only then asks `to_provider_format` for a trailing user message (`llm.py:227-230`). So
  `ClaudeLLM.chat` converts the context itself and, when it ends on the assistant, sends a copy with a `"."` user
  turn appended (the plugin's own filler, `agents/llm/_provider_format/anthropic.py:107-108`).
- With `caching="ephemeral"` it puts `cache_control` on the last system block, the last tool and the last
  assistant/user pair of the history (`llm.py:239-258`), and reports cache reads as `prompt_cached_tokens`
  (`llm.py:329-342`).
- `tool_choice="auto"` maps to `{"type": "auto"}` and `parallel_tool_calls=False` to `disable_parallel_tool_use`
  (`llm.py:202-224`); `"required"` would map to `{"type": "any"}`, which Sonnet 5.5 rejects.
- The stream parser handles only `text_delta` and `input_json_delta` (`llm.py:373-395`), so thinking blocks
  (`thinking_delta`, `signature_delta`) never reach the transcript; `test_thinking_before_the_text_yields_only_the_text`
  checks it.
- `_parse_event` never reads `message_delta.delta.stop_reason` (`llm.py:357-418`), so a refusal (including one the
  server-side fallback couldn't rescue) streams like a finished reply. `ClaudeLLMStream` records `stop_reason`; for
  the extractor and summarizer (`refusal_is_error=True`) a refusal raises a non-retryable `APIStatusError`, so a
  declined or truncated result is never stored. The conversation keeps the reply (it has already been spoken) and only
  records it. The plugin's `chat()` builds its `LLMStream` itself (`llm.py:282`), so `ClaudeLLM.chat` sets the
  instance's class to `ClaudeLLMStream` before the stream's task first runs.
- Request kwargs merge: a caller's `extra_kwargs` replace the stage's, except `extra_headers`, `extra_body` and
  `output_config`, which merge one level down. A provider tool with its own beta flag would go through
  `beta.messages.create(betas=[…])` (`llm.py:263-271`), and the stage's `anthropic-beta` header would replace that
  flag, so no stage uses provider tools.

**Model ids.** `claude-haiku-5-5` and `claude-sonnet-5-5` are Michael's choice and Anthropic's current ids; the
plugin's `ChatModels` Literal (`models.py`) stops at the 4.6 ids, but `model` is typed `str | ChatModels`
(`llm.py:67`), so any id is accepted.

## D9 *default*: the preload overlaps the room connection, with a 1 s deadline (2026-10-20, C3-02)

**Finding.** Spec §4.0 and C3-02 put the preload concurrent with `ctx.connect()`. In livekit-agents 1.8.8,
`ctx.connect()` really joins the room (`job.py:691`), but RoomIO registers its `lk.chat` text handler and the
pre-connect audio byte-stream handler only inside `session.start` (`voice/room_io/room_io.py:111-118`). A stream that
arrives with no handler is dropped, and the pre-connect handler logs "registered after room connection" whenever the
page's buffer is used (`_pre_connect_audio.py:51-71`). So the time the preload takes is a window in which a typed
message or the pre-connect audio can be lost. A normal preload takes under 1 ms; a store waiting on another job's
write lock can take 5 s.

**Choice.** Keep the gather (the spec's design and the feature's step) and bound the preload with
`PRELOAD_TIMEOUT_S`, 1.0 s (now in `concierge/session.py`). On the deadline the session runs without memory, like
any other preload failure (logged by type, `TimeoutError`). The store thread can't be cancelled, so (C3-03 review)
the preload is a tracked task under `asyncio.wait`, not `wait_for`, and `on_shutdown` waits for it before closing the
store. Accepted: a late preload still counts the visit and journals `memory_preloaded`, and that session journals
no `session_started` / `session_ended` (it ran without memory).

**Rejected.** Moving the preload after `session.start` (no overlap with the connect, against §4.0), or overlapping
it only with provider construction and awaiting it before `session.start` (smaller win, more moving parts).

**Question for Michael.** Does the page send a pre-connect audio buffer or let the visitor type before the agent
joins? If yes, the safer shape is "preload before `session.start`, overlapped only with provider setup"; say so and a
later session switches it.

## D10 *default*: an extracted value must share a word with the visitor's turn (2026-10-20, C4-01)

**Finding.** Spec §4.4's merge checks that an op's source "must be a user turn that exists", and the gate rejects
values "attributed to the agent's own words". Neither stops the extractor from citing a real user turn for a value the
visitor never said: the agent's guess ("So you're a recruiter?" answered by "Anyway, what has he built?", spec §4.9) or
a fact from an interrupted agent turn's unheard part. A turn id is only a pointer; the model chooses it.

**Choice.** The merge (C4-02) checks grounding deterministically: an ADD or UPDATE value must share at least one word
(casefolded, a trailing "s" dropped, not a stop word; a 2-letter token such as "PM" or "AI" matches only the
same whole token) with the visible text of the user turn it cites. If it only shares one with an agent turn, the reason is `agent_attributed`; with neither, `ungrounded`. Names
use B12's confirmation rule instead. `follow_up_wanted` (a phrase for a request) and `asked_about` (what they
asked about Michael, naturally a paraphrase, low harm) are exempt. The `remember` tool applies the same rule against
the session's user turns. The
extractor prompt asks for the visitor's own words.

**Rejected.** Trusting the turn id (the harm case would then depend on the model), or an LLM judge (a second call per
op, and not deterministic).

**Cost.** A correct paraphrase with no shared word is lost. The live memory eval (C7) reports recall, which is where
this shows.

**Question for Michael.** Keep the grounding rule (fewer false memories, some lost paraphrases), or drop it and rely on
the extractor prompt?

## D11 *default*: `forget` deletes facts, not the turn text in the journal (2026-10-20, C4-04)

**Finding.** The journal keeps every turn's text (`user_turn`, `agent_turn`; spec §4.2, C5-03's "nothing lost"). When a
visitor says "forget where I work", the `forget` tool really deletes the company facts and the rows they superseded
(B5), but the journal row "I work at Acme." stays until the idle TTL (30 days) or "Forget me" erases the thread.

**Choice.** Keep the turn text. `forget` deletes facts only, and the writer blocks the window from re-adding them this
session. Reversible: a later feature can redact the matching `user_turn` payloads in the same `apply_fact_ops` batch.

**Rejected.** Redacting now. It needs a new op in `fact_ops`/`store.py` (store.py is at 247 of 250 lines) and a rule
for which turns "mention" a value, and it breaks C5's every-turn journal guarantee.

**Question for Michael.** Should "forget X" also scrub X's turns from the journal (stronger privacy, a gap in the
history), or is the TTL plus "Forget me" enough?

## D12 *default*: a compaction "turn" is one message, not a user+agent pair (2026-10-20, C5-01)

**Finding.** Spec §4.8 says compaction keeps "the last 6 turns" and the fallback "the last 12 turns". livekit-agents
1.8.8's own `ChatContext._summarize` counts a turn as a user+assistant pair; the journal (`user_turn`, `agent_turn`) and
C5-03's tests ("30 turns → 30 journal rows", "≤ 8 items after compaction") count one message as one turn.

**Choice.** One user or assistant message is one turn, so compaction keeps about the last 3 exchanges verbatim and the
fallback about 6. Reversible: `KEEP_TURNS` and `FALLBACK_KEEP_TURNS` in `concierge/compaction.py` double if Michael
prefers pairs.

**Rejected.** Pairs (12 messages kept): the compacted context would rarely be far under the 24-item trigger, so
compaction would run about every 6 turns instead of every ~18.

**Question for Michael.** After a compaction, should the concierge keep the last 3 exchanges verbatim (this default) or
the last 6?

## D13 *default*: the field types §6 leaves open (2026-10-20, C6-01)

**Finding.** Spec §6 lists the `concierge.memory` and `concierge.metrics` keys but not every type: a fact's `id`, the
format of `learned_at` and `updated_at`, whether an unreported metric is `null` or absent, and whether the greeting is a
metrics turn. The portfolio page is built from the same §6 by another run tonight.

**Choice.** Fact `id` is the integer `facts.id`; `learned_at` and `updated_at` are ISO-8601 UTC strings ending in `Z`
with milliseconds (`2026-10-20T09:15:02.123Z`); `confidence` is a number 0–1; every `concierge.metrics` key is always
present, `null` when 1.8 didn't report it; the greeting is metrics turn 1 (null user fields, it carries `preload_ms`).
Reversible: `concierge/contract.py` and the schemas in `tests/contract/` (plan C6 "Part 1").

**Rejected.** String ids (`"f12"`): nothing on the page needs them, and the store's ids are integers. Omitting null
keys: the page would have to tell "not reported" from "not sent".

**Question for Michael.** Does the page's code expect these types, in particular `id` as a number, not a string?

## D14 *default*: a message's text runs the full write gate (2026-10-20, C8-02)

**Finding.** Review C8-02: spec §4.4 lifts the gate for the contact only, so the message text still runs every rule.
Ordinary messages are refused: "could you act as a mentor?" (`instruction`), "have a look at acme.dev" (`url`), "meet
2026-10-22 10:30" (`phone`, twelve digits).

**Choice.** Keep the full gate on the text, as the spec says; the reply now says why in two forms (`CONTACT_IN_TEXT`
for an email or phone, `CANT_TAKE` otherwise), so the model asks for the contact in the right field or for plain words
(`test_a_rejected_text_gets_the_reply_for_its_reason`). Reversible: `_rejection` in `concierge/message_tool.py`.

**Rejected.** Lifting the url and instruction rules for the text: the text never goes back into a prompt, but Michael
reads it, and a link from an anonymous visitor is what the gate exists to stop. Not mine to widen.

**Question for Michael.** Should a message's text allow links (and the date-like digits the phone rule catches)?

## D15 *default*: messages go with the visitor's thread at the 30-day idle purge (2026-10-20, C8-02)

**Finding.** Review C8-02: `purge_idle` (B6) deletes an idle thread with its child rows, `messages_for_michael`
included, and leaving a message doesn't count as activity beyond the session's own.

**Choice.** Keep it: a message is visitor data like the rest, and the 30-day TTL is the privacy promise. MORNING.md
says to read them within 30 days.

**Rejected.** Keeping messages past the TTL: it breaks the README's retention claim.

**Question for Michael.** Should messages outlive the 30-day purge (say, until you delete them)?

## D16 *default*: the departure grace is 20 s (2026-10-21, V1-01)

**Finding.** Spec 2026-10-21 §1.1: the page's component unmounts on a client-side route change and disconnects the
visitor, but nothing in the agent reacted, so the session ran on to its 10-minute cap and the site's token route kept
answering 429 `visitor` for that address.

**Choice.** When the visitor's participant (`visitor-<visitor_id>`) disconnects, wait `DEPARTURE_GRACE_S = 20.0`
(`concierge/departure.py`) for a `participant_connected` with the same identity; if none comes, journal
`visitor_left` and end the session (V1-02: `end_session("visitor left")`). Why a grace at all: a page reload, or a
client-side route change that remounts the page, reconnects with the same identity a few seconds later, and should
find the same session, not start a second one. 20 s covers a slow reload on a phone and still frees the address
within about 30 s, inside the page's 60 s retry window (spec §2). Reversible: one constant.

**Rejected.** Ending at once on the disconnect: every reload or remount would end the session and start a new one
(a new visit, a second summary). Waiting for the 10-minute cap (today's behaviour): the cause of §1.1.

**Question for Michael.** Is 20 s right? 10 s frees the address sooner but a slow reload then starts a new session;
30 s is safer for reloads but the page's "Closing your earlier conversation…" wait grows to about 40 s.

**Extended in V1-03 (review I1): the join grace.** The watcher only hears events, so a visitor who left during
`ctx.connect()` or the preload (rtc.Room removes them from `remote_participants` before it emits, rtc/room.py:773), or
who never joined, was never seen to leave and the session ran to the 10-minute cap. Now, when the watch starts and
`visitor-<visitor_id>` is not in `room.remote_participants` (rtc/room.py:249), it starts `JOIN_GRACE_S = 60.0`
(`concierge/departure.py`); a `participant_connected` with that identity cancels it, and when it runs out the session
ends as after a departure (`visitor_left` carries the grace that ran out). 60 s, not 20 s: the room is created by the
page's own connect (spec.md §6: the token route's `RoomConfiguration` dispatch), so the visitor is almost always there
already, and a long join grace only costs a stray session's address for a minute; a short one could end a session whose
page is slow to join. Rejected: no join check (I3's bug); the 20 s departure grace (a slow join would end a live call).
Question for Michael: is 60 s right?

## D17 *default*: what contract v2 (§2) leaves open (2026-10-21, V2-01)

**Finding.** Spec 2026-10-21 §2 and §4 fix the v2 keys and types but not the event wording, how the current visit's
episode row comes to exist, what a failed summary leaves, or how the 15 KiB cap trims the new lists. The plan
(`docs/plans/2026-10-21-V2-contract-v2.md`) had to pick.

**Choice.**
- (a) **Event lines** (`concierge/events.py`), slot words `name`, `role`, `company`, `interest`, `follow-up`, and
  `what you asked about` (which drops "your": "Remembered what you asked about: Rust"):

  | type | line | value-free form |
  |---|---|---|
  | `fact_added` | `Remembered your <slot>: <value>` | `Remembered your <slot>` |
  | `fact_invalidated` | `Updated your <slot>` | (same) |
  | `fact_deleted` | `Forgot your <slot>` | (same) |
  | `gate_rejected` | `Didn't store something that looked like <an instruction \| a link \| contact details \| a secret \| code>` | (same; never a value) |
  | `extraction_ran` | `Took notes in the background (<n> change \| changes>)` | (same) |
  | `remember` | `Remembered at your request: <slot>` | (same) |
  | `forget` | `Forgot at your request: <about>` | `Forgot something at your request` |

  Gate reasons in words: `instruction` → an instruction, `url` → a link, `email`/`phone` → contact details, `secret`
  → a secret, `code` → code. Other rejections (`agent_attributed`, `empty`, `unsafe_chars`, `too_long` and the
  merge's own rules: grounding, the name rule, an unknown slot) get no line: they are the model's mistakes, not
  something the visitor said that was refused. A line that `check_text` rejects or that is over 120 characters falls
  back to the value-free form. Every fixed line above passes `check_text` today (checked in V2-01).
- (b) **The current visit's episode row** is inserted at session start by the `session_started` background task
  (`begin_visit`, idempotent), queued on the writer's thread before the start `concierge.memory` read, and completed by
  `end_visit` after the summary step. `end_visit` only updates: if `begin_visit` failed there is no episode for that
  visit, and an erased thread raises `ThreadMissing` and re-creates nothing. The visit number is `preloaded.visits`.
- (c) **A failed summary leaves that episode's `summary` null** (so does a skipped one: no visitor turn, or erased);
  `ended_at` is still set. An episode's summary is the text the summary step stored at that visit's end, which is the
  rolling summary (it starts from the previous one, `write_summary`), not a summary of that visit alone.
- (d) **`extraction_ran` is noted only when the run changed or rejected something** (n = added + invalidated).
- (e) **Events come from the `MergeResult` and the tools, not by reading the journal back**: same rows, no store read
  on the event loop. `MergeResult.changes` carries slot and value in memory only; the journal still holds no values (D8).
- (f) **The trimmer** drops the oldest facts from `facts` and `profile` together (they stay equal), then the oldest
  events, then the oldest episodes; never a v1 key. *Superseded by D19 (a) (V2 review).*
- (g) **The empty body** (after "Forget me", or a session without memory) is v2: `v: 2`, `about_visitor` with three
  empty lists, `retention_days: 30`, `about_agent` null. A forget_me also clears the event ring.
- (h) **`remember` and `forget` publish at once** (the tools call the publisher's `schedule` after noting their
  events), so the page doesn't wait for the next merge.
- (i) **A top-level v2 key may be null** (V2-02): `v`, `about_visitor`, `about_agent` and `retention_days` default to
  `None` on `MemoryPayload`, pydantic dumps that as `null`, and `memory.schema.json` accepts `null` for each, which a
  page reads like a missing key: "not reported". Our builders always fill `v`, `about_visitor` and `retention_days`;
  only `about_agent` is null in practice (no agent view yet, or a body built outside a session). *Sending changed by D19
  (b) (V2 review): a null top-level v2 key is left out of the JSON; the schema still accepts null.*
- (j) **`forget` clears the episode summaries too** (V2-03 review): each ended episode keeps the rolling summary as it
  stood at that visit's end, so a forgotten value could sit in several rows. The `forget` tool nulls the `summary` of
  every episode that names a deleted value or the value the request names, in the same store-thread call that clears
  `last_visit_summary` (one fenced write, then the checkpoint), and the reply counts it as forgotten.
- (k) **An episode left open stays open** (V2-03): a worker killed before `end_visit` (crash, SIGKILL, the 25 s closing
  deadline) leaves that visit's `ended_at` null, so a later body can show two visits with no end. Nothing closes it
  after the fact: a later session can't tell a dead session from another tab's live one without a lease.
- (l) **A forgotten value leaves the event lines too** (V2-04): the ring shows values ("Remembered your company:
  Acme"), and each such line keeps its value; every body checks it against the thread's fact history on the writer's
  thread (`events.shown`, `memory_view.memory_with_events`), so a value deleted by `forget`, here or in another tab's session,
  goes out as the value-free form ("Remembered your company"), even in a send whose lines were read before the forget
  ran (review I1). The `forget` line names the slot the request names, never the visitor's words, which can hold a
  value ("forget where I work" → "Forgot at your request: company"; "forget I work in IT" would echo "IT"); a request
  that names a value ("forget Acme") gets "Forgot something at your request". `remember` notes nothing when nothing changed ("I already have that", or refused), and
  `fact_invalidated` lines for what it replaced, then `remember`. Every type has a value-free form (`PLAIN` in
  `concierge/events.py`), the last guard when a caller's line fails `check_text` or the 120-character cap.

**Rejected.** Noting every extraction run (a 10-minute call has ~30 runs, mostly with no change: they would push the
real lines out of the 12-line ring). Creating the episode row in the summary step only (the start body could not show
the current visit, and a session that dies before its summary would leave no episode at all). Keeping the last good
summary in a failed visit's episode (it would describe an earlier visit as this one). A line per non-gate rejection
(noise the visitor can't act on). Trimming `profile` before `facts` (a v2 page would show less than a v1 page). Dropping null keys with `exclude_none`
(it would drop v1's `summary: null` too, which the schema requires) or keeping the schema non-null (a body re-dumped
from a parsed v1 one would fail it). For (l): echoing `about` as §2's wording has it (the page would show the value the visitor
just asked to forget, for the rest of the session), rewriting the ring on the event loop after the forget (a send
already building would still carry the value, and another session's forget is never seen), and dropping the older
lines instead (the count of what happened this session would change under the visitor).

**Question for Michael.** Are these lines how you want the page to read? In particular: should "Took notes in the
background" show on every run (including no change), and should an episode carry the rolling summary or should the
summarizer write a per-visit one as well? (k): should an episode a crash left open be shown as "ended: unknown" by
the page, or should the worker close stale open rows (older than the 10-minute cap plus the grace) at the next start?

## D18 *default*: what `about_agent` reports where §2 is silent (2026-10-21, V2-05)

**Decision.** (a) `cache.cached_share` is the last closed turn **that had LLM metrics**: a turn with no LLM call
(none in 1.8 today, but a tool-only turn could be) keeps the share before it; a turn whose `prompt_tokens` were 0 sets
it to null; it is capped at 1. (b) `knowledge.sources_commit` is the first 7-40 character lower-case hex word in
`knowledge/sources/SOURCE.md`, or `"unknown"` when there is none (a missing commit must not cost every memory send).
(c) `working` is read when the body is built: the start body is built before the greeting lands, so it counts the
instructions and the config update only. `working.items` is every item in the agent's context (the instructions
item and config updates too, as the plan's `len(agent.chat_ctx.items)` has it), while `working.est_tokens` is
`estimate_ctx_tokens`, the conversation part only (the instructions are `instructions_est_tokens` plus the pack's
`est_tokens`; review M4). (d) A session over the daily cap, and one without memory, still report
`about_agent` (the agent exists; only the visitor's memory is missing); the empty body after "Forget me" does not, and
`concierge.get_memory` answers with that empty body once it was sent (review M2). (e) `memory_block_chars` is null for a blank block too, as `build_instructions` drops it.

**Rejected.** Null after any turn without LLM metrics (the page would flicker between a share and "not reported").
Failing the build on a SOURCE.md without a commit. Leaving `about_agent` out of a memoryless session's body. Failing the whole body when
`about_agent` can't be read (it is optional in the contract: it goes out null and the read is logged by type, review
I1). Taking the first hex word anywhere in SOURCE.md (a word like "defaced" would pass for a commit, review M3).

**Question for Michael.** Is "the last turn with LLM metrics" the share you want the page to show, or would you
rather see the session's cumulative cached share?

## D19 *default*: the V2 review's three fixes (2026-10-21, V2-06)

**Finding.** The V2 review (Opus, `$HARNESS_SCRATCH/review-V2.diff`; notes under "## Review" in
`docs/plans/2026-10-21-V2-contract-v2.md`) found three Important gaps against spec 2026-10-21 §2 and §4.

**Decision.**
- (a) **The trimmer keeps the v1 facts** (replaces D17 (f)). Over 15 KiB, `contract.trim_to_fit` drops the oldest
  events, then the oldest episodes, then the oldest `profile` items, and the oldest v1 `facts` only after all of
  those, one item at a time, re-measured. §4 says "keep the v1 keys populated as before" and "the events and episodes
  are capped so a full body fits"; D17 (f) dropped v1 facts first, so the largest ASCII body lost facts a v1 agent
  sent, and a 4-byte one sent `facts: []`. Now the largest bodies keep all 20 facts (ASCII: a few of the oldest
  events go; 4-byte: every event and episode, then the oldest `profile` items). So `profile` can be shorter than
  `facts`, and only in a body over the cap.
- (b) **A top-level v2 key with nothing to report is left out, not sent as null** (changes how D17 (i) is sent).
  `MemoryPayload` serializes without a `None` `v`, `about_visitor`, `about_agent` or `retention_days`; v1's
  `summary: null` and every nested `|null` that §2 spells stay. §2 says "missing fields render as 'not reported'", and a v1
  agent leaves them out, so a page must take a missing key; a page that takes `.optional()` but not null would
  reject a null one. The schema still accepts null (tolerant reader).
- (c) **An event line never quotes a value that reads as a link or an order**, which is stricter than the write gate.
  `events.plain_enough`: no `.`, `:`, `/`, `\` or `@` between two non-spaces, no spaced `.tld` or "dot tld", no
  scheme word, no "always/never/must/should/you will … say/speak/reply/…", and no word that mixes Latin, Cyrillic or
  Greek letters (lookalikes); NFKC first. Otherwise the line falls back to its value-free form. "Node.js" or
  "Ph.D." read "Remembered your interest" without the value; names in any one script show.

**Rejected.** For (a), lower caps (5 episodes at 400 characters are what §2 and the summarizer allow) and trimming
`facts` together with `profile` after the events and episodes (a 4-byte body would still lose v1 facts). For (b),
a blanket `exclude_none` (it would drop v1's `summary: null`). For (c), tightening the write gate itself in V2: it
also guards the memory block, and changing what is stored belongs in its own feature (proposed for V3).

**Question for Michael.** (a): with more than 15 KiB, should a v2 page see a short `profile` (as now), or should
both lists stay equal and the v1 facts pay for it? (c): should the write gate refuse these values too, so they are
never stored, and not only never shown?

## Health port: loopback only (Michael, 2026-10-20)

**Decision.** The worker's health endpoint (8081 under `start`) binds 127.0.0.1: `AgentServer(host="127.0.0.1")` in
`concierge/worker.py` (1.8.8's default `host=""` is every interface, `livekit/agents/worker.py:323`). Michael's INBOX
answer of 2026-10-20; built in C8-01, asserted by `test_import_needs_no_keys`. MORNING.md no longer asks about it.
