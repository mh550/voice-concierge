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
