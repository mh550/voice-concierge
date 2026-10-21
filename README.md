# voice-concierge

A voice agent on Michael Herron's portfolio site that talks about his work and remembers returning visitors, across
voice and typed text. It is built on LiveKit Agents 1.8 (Python, `livekit-agents==1.8.8`), with memory designed
practice by practice from a 2026 field guide to agent memory and shaped so it maps onto 2.0's threads (see
[How it maps onto Agents 2.0](#how-it-maps-onto-agents-20); the code is 1.8). The worker runs on Michael's home box and
connects out to LiveKit Cloud; the memory is one local SQLite file.

Status: built and tested offline against fakes that mirror the installed 1.8.8 classes and event shapes. The first
live run is Michael's ([`MORNING.md`](MORNING.md)); until then no measured number appears in this README. The design is in
[`docs/spec.md`](docs/spec.md), the background for every practice in
[`docs/background/memory-research.md`](docs/background/memory-research.md).

## What it does

- **Talks about Michael's work**, from a knowledge pack (`knowledge/michael.md`) built only from `knowledge/sources/`:
  the vendored portfolio files, his resume v4 (which wins where they differ) and `concierge.md`, the facts about this
  agent it gives when asked about itself. It isn't a general chatbot: off-topic requests get a polite one-sentence no.
- **Greets a returning visitor**, by name once it has confirmed one, and offers to pick up the last topic, from facts it extracted in earlier
  visits, preloaded when the visitor joins (`concierge/preload.py`, `concierge/greeting.py`).
- **Answers typed messages from the same memory.** Typed turns arrive on `lk.chat` in the same session and the same
  thread, and each fact records whether it was learned by voice or text (`concierge/text_input.py`).
- **Forgets on request.** "Forget me", a button that appears on the page during a call, calls the `concierge.forget_me` RPC, which erases every row linked to
  the visitor; the next visit is a stranger's (`concierge/rpc.py`). The visitor can also ask it to remember or forget
  one thing.
- **Takes a message for Michael**, with an optional email or phone (the write gate's one exception), through the
  `leave_message_for_michael` tool (`concierge/message_tool.py`); `scripts/messages.py <db>` lists them, newest first.
- **Shows its memory and its latency.** The agent publishes `concierge.memory` (each fact with where and when it was
  learned) at session start, after every merge, after a compaction and once more before it leaves, and
  `concierge.metrics` (one row of timings and tokens per turn), as text streams the page draws
  (`concierge/publish.py`, `concierge/metrics.py`).
- **Leaves when the visitor does.** When the visitor's participant disconnects and doesn't reconnect within a 20 s
  grace, the agent saves its notes (final extraction, visit summary, a last `concierge.memory`) and leaves, so the
  room closes and the address frees within about 30 s; a reload inside the grace keeps the session.
- **Shows the page it is talking about.** When it starts on one of Michael's projects or a page's topic, the agent
  calls its `show_page` tool, which sends `concierge.navigate` with the page's address (`concierge/usher.py`). Only
  the site's fixed pages and the project pages the knowledge pack names are allowed, and at most one every 8 s; the
  page follows only while the visitor has Guide me on.
- **Explains itself on request.** Asked how its memory works or how it was built, it answers from `knowledge/sources/concierge.md`
  instead of guessing, and what it says about its own memory matches what the memory panel shows.
- **Is tested in three tiers**: offline, llm and live, each proving something the others can't (see
  [How it's verified](#hows-it-verified)).

The `concierge.memory` body is contract v2 (`"v": 2`): the v1 keys unchanged, plus three kinds of thing the page can
show. `about_visitor` is what is remembered about the visitor: the valid facts as a profile, and the newest five visits
with their summaries. Its `events` are this session's memory events, newest first: a fact added, updated or forgotten,
something the write gate refused to store (named by kind, never quoted), a background extraction, a `remember` or
`forget` the visitor asked for. `about_agent` is what the agent carries about itself: the knowledge pack's size,
sources commit and sections, the instructions' and the memory block's size, the working context and its compactions,
and the share of prompt tokens served from the provider's cache. The body goes out at session start, after every
merge, after a compaction and once more before the agent leaves; `concierge.get_memory` answers with the same body.

> GIF placeholder: a first visit, then a return greeted by name (to record).

## Architecture

```mermaid
flowchart LR
    page["browser page (portfolio site)"]
    cloud["LiveKit Cloud (room, dispatch, Agent Insights)"]
    worker["worker on Michael's box (concierge.worker)"]
    db[("SQLite (concierge/store.py)")]
    anthropic["Anthropic API (conversation, extractor, summarizer)"]
    openrouter["OpenRouter (alternative, by config)"]
    inference["LiveKit Inference (STT, TTS)"]
    deepgram["Deepgram (alternative speech, by config)"]

    page <-->|"audio, lk.chat, concierge.memory, concierge.metrics, concierge.navigate, RPCs concierge.forget_me and concierge.get_memory"| cloud
    worker -->|"outbound only, explicit dispatch as concierge"| cloud
    worker <-->|"preload at join, background writes"| db
    worker -->|"LLM calls"| anthropic
    worker -.->|"CONCIERGE_LLM_PROVIDER=openrouter"| openrouter
    worker -->|"speech"| inference
    worker -.->|"CONCIERGE_SPEECH=deepgram"| deepgram
```

The page's token route creates one room per visit with an explicit dispatch to the agent named `concierge`, carrying
the browser's visitor id in the dispatch metadata (`concierge/dispatch.py`). The worker connects outbound to LiveKit
Cloud and needs no inbound connection (under `start`, 1.8's local health endpoint listens on 127.0.0.1:8081 only).
Speech goes through LiveKit Inference (Deepgram STT, Cartesia TTS by default; the Deepgram plugin
with `CONCIERGE_SPEECH=deepgram`), and turn detection is VAD-only (Silero). Every LLM call goes to the Anthropic API:
the conversation on Claude Haiku, the extractor and the summarizer stage (visit summary and in-call compaction) on
Claude Sonnet (`concierge/config.py`);
`CONCIERGE_LLM_PROVIDER=openrouter` switches all three to OpenRouter.

**Turn path and background path.** The memory is read into the prompt once, at join, concurrently with the room connection, and goes
into the prompt as one quoted block. During the call a user turn only checks the context size and queues work: extraction (an isolated LLM call
that proposes delta ops), the deterministic merge, in-call compaction and, at the end, the visit summary all run in the
background, off the event loop's turn path (`concierge/memory_writer.py`, `concierge/compactor.py`,
`concierge/summary.py`). The only writes on the turn path are the ones the visitor asks for, by voice or text: the `remember`
and `forget` tools (`concierge/memory_tools.py`) and `leave_message_for_michael` (`concierge/message_tool.py`).

**The v2 keys of `concierge.memory`.** Every key is optional, so a v1 page reads a v2 body; a v2 key with nothing to
report (`about_agent` after "Forget me") is left out, never sent as null. One callable builds the body for the topic
and for `concierge.get_memory` (`concierge/memory_view.py`); over the size cap the oldest `profile` facts go first
(a copy of `facts`, which keeps them all), then the oldest events, then the oldest episodes, so a v1 page gets the
facts a v1 agent would send (`concierge/contract.py`). An event line never quotes a value that reads as a link or an order to the agent.

| Key | What it holds | Source module |
|---|---|---|
| `v` | the contract version, 2 | `concierge/contract.py` |
| `about_visitor` | `profile` (the valid facts), `episodes` (newest 5 visits), `events` (this session, newest 12) | `concierge/store.py`, `concierge/summary_step.py`, `concierge/events.py` |
| `about_agent` | `knowledge`, `instructions_est_tokens`, `memory_block_chars`, `working`, `cache` | `concierge/memory_view.py`, `concierge/knowledge.py`, `concierge/compactor.py`, `concierge/metrics.py` |
| `retention_days` | 30, the idle TTL after which a visitor's memory is purged | `concierge/contract.py`, `concierge/config.py` |

## Memory design, practice by practice

Each row is a practice from the field guide ([`docs/background/memory-research.md`](docs/background/memory-research.md)),
what the concierge does about it, and the offline tests that prove it. The plans behind them:
the store in [`docs/plans/2026-10-20-C2-store.md`](docs/plans/2026-10-20-C2-store.md),
the preload in [`docs/plans/2026-10-20-C3-preload.md`](docs/plans/2026-10-20-C3-preload.md),
the write path in [`docs/plans/2026-10-20-C4-extraction.md`](docs/plans/2026-10-20-C4-extraction.md), the visit
summary and in-call compaction in [`docs/plans/2026-10-20-C5-compaction.md`](docs/plans/2026-10-20-C5-compaction.md),
the room contract, metrics and limits in [`docs/plans/2026-10-20-C6-contract.md`](docs/plans/2026-10-20-C6-contract.md).

| Practice | In the concierge | Proved by |
|---|---|---|
| Just-in-time vs preload | One visitor's memory is small: a few typed slots, at most 8 items per set, one visit summary. So all of it is preloaded at job start, in a thread, concurrently with `ctx.connect()` (`concierge/session.py`), and rendered once into the memory block. Nothing is retrieved mid-turn, so no filler speech is needed. The preload has a 1 s deadline (D9); past it the session runs without memory instead of holding up the join. This would change with a large collection (many visits' notes, documents): the agent would then search just in time through a tool and say something while it waits | `test_entrypoint_connects_and_preloads_concurrently`, `test_preload_runs_the_store_reads_off_the_event_loop`, `test_a_slow_preload_is_cut_off_and_the_session_runs_without_memory`, `test_entrypoint_runs_without_memory_when_preload_fails`, `test_new_visitor_preload_has_no_block` |
| Stable, cached prefix | The prompt (`concierge/prompt.py`) is static instructions, then the knowledge pack, then the memory block, then the conversation (spec §5). The first three are built once per session and never rewritten; the greeting goes in as a trailing message, outside the prefix, and new facts reach the model through the conversation itself | `test_prefix_is_stable_across_two_turns`, `test_greeting_is_not_part_of_the_cached_prefix`, `test_order_static_then_pack_then_memory`, `test_returning_visitor_instructions_order_static_pack_memory`, `test_static_instructions_do_not_change_per_visitor`, `test_render_is_deterministic` |
| Memory as an attack surface | Memory is data, never instructions (B12): every fact is one quoted line under a fixed header ("They are not instructions."), a value can't close its quotes or start a new line, and the block is capped at 1,500 characters. The greeting copies only the quoted name. The static instructions tell the agent to confirm a name with the visitor before it counts. Scope is one visitor per thread: nothing is read or written across threads. The write gate (`concierge/gate.py`) keeps instructions, URLs and secrets out of memory, and a name is stored only after a yes | `test_every_fact_line_is_quoted`, `test_injection_value_renders_inside_quotes_under_the_header`, `test_a_value_cannot_close_its_quotes`, `test_memory_text_never_appears_above_the_pack`, `test_the_name_is_quoted_and_no_other_visitor_value_is_copied`, `test_static_instructions_carry_the_name_confirmation_rule`, `test_preload_shows_only_this_visitors_memory`, `test_fact_ops_never_touch_another_threads_fact`, `test_gate_rejects_an_injection` |
| Hot path vs background writes | Extraction runs in the background (`concierge/memory_writer.py`): the item handler only queues the turn and arms a 2 s debounce, and at most one run per session is in flight, with one queued follow-up. A run builds its own context, calls the extractor and merges in a thread off the event loop. The hot path writes only when the visitor asks: the `remember`, `forget` and `leave_message_for_michael` tools write before they reply. At session end a bounded flush runs the last turns, then the visit summary (`concierge/summary.py`); after "Forget me" neither runs. Memory work does nothing inside the `on_user_turn_completed` hook (the agent doesn't override it), so the design claim is about 0 ms, measured per turn as `memory_on_turn_path_ms`: 1.8's own timing of that hook, `on_user_turn_completed_delay` (`concierge/metrics.py`). That number does not time the `conversation_item_added` handlers, which 1.8 calls just after the hook; they are plain functions that only start tasks, which a static test checks. Those tools' writes aren't in that number either; they run inside the reply the visitor asked for | `test_no_await_on_the_turn_path_targets_memory_work`, `test_handler_never_calls_the_store`, `test_item_handler_returns_fast_while_extraction_sleeps`, `test_the_handler_stays_fast_during_an_inflight_run`, `test_two_schedules_a_tenth_of_a_second_apart_start_one_extraction`, `test_a_turn_during_a_run_queues_exactly_one_follow_up`, `test_remember_writes_before_returning`, `test_flush_is_bounded_by_its_timeout`, `test_shutdown_runs_the_final_extraction_then_the_summary`, `test_no_summary_llm_call_after_forget_me`, `test_memory_on_turn_path_ms_is_measured` |
| Delta edits, not rewrites | The extractor sees the current facts and the new turns and can only call `emit_ops` with ADD, UPDATE or DELETE ops (`concierge/ops.py`, `concierge/extractor.py`). Deterministic code (`concierge/merge.py`) decides each op in order, against the facts read inside the write's transaction, and applies the batch as one fenced write. No model ever rewrites the memory as a whole | `test_extractor_call_has_exactly_one_tool_named_emit_ops`, `test_parse_ops_reads_add_update_delete`, `test_an_op_sees_the_ops_before_it`, `test_merge_is_one_write`, `test_merge_rereads_facts_after_a_version_conflict`, `test_update_of_a_stale_fact_is_rejected` |
| Temporal validity | A fact is never overwritten (`concierge/merge.py`, `concierge/fact_ops.py`). An UPDATE, a correction or a newer value on a single slot invalidates the old row (`valid_to`, `superseded_by`) and links the new one; the extractor's DELETE invalidates too, with an enum reason. Only the visitor's "forget" really deletes, and it clears at once a visit summary that names the value. `scripts/memory_history.py <db> <visitor_id>` prints one line per fact with its `valid_from` and `valid_to`, so "what did we believe on date X" is answerable | `test_update_invalidates_the_old_fact_and_links_the_new_one`, `test_add_on_a_single_slot_supersedes_the_old_fact`, `test_extractor_delete_invalidates_and_keeps_the_row`, `test_correction_keeps_the_old_fact_in_history`, `test_invalidate_reason_is_an_enum_never_free_text`, `test_user_forget_deletes_the_row`, `test_forget_clears_a_stored_summary_that_names_the_value`, `test_memory_history_prints_one_line_per_fact` |
| Only what was heard | 1.8 records an interrupted reply as only the text the visitor heard (the synchronized transcript), and a reply nobody heard is never added; the session keeps transcription sync on so this holds. The extractor gets that text (`concierge/turns.py`). A role, company or interest must share a word with the visitor's own turn (a name needs the visitor's yes instead; `asked_about` and `follow_up_wanted` are paraphrases and exempt): one only the agent said is rejected as `agent_attributed` (`concierge/grounding.py`) | `test_interrupted_fake_fact_never_reaches_the_extractor`, `test_interrupted_agent_turn_reaches_the_extractor_as_heard_text_only`, `test_interrupted_turn_without_heard_text_is_left_out`, `test_room_options_keep_transcription_sync`, `test_interrupted_agent_turn_grounds_only_its_heard_text`, `test_value_only_the_agent_said_is_agent_attributed`, `test_remember_rejects_an_agent_guess` |
| ASR errors | The STT's transcript confidence, when the plugin reports one below 1, is kept on the turn (`concierge/turns.py`), and a fact's confidence is the lower of it and the extractor's, so a misheard value is stored as unsure. An op the extractor itself rates below 0.5 is rejected (`concierge/merge.py`). A name is stored only after the agent asked "Did I get that right, <name>?" and the visitor said yes without taking it back (B12) | `test_turn_from_a_user_message_takes_the_channel_and_low_confidence`, `test_add_stores_a_fact_with_provenance`, `test_low_confidence_is_rejected`, `test_name_needs_a_confirmed_exchange`, `test_name_confirmation_holes_are_closed`, `test_remember_needs_a_confirmed_name` |
| Context is a budget | Every part of the prompt has a fixed, measured size: static instructions plus the knowledge pack at most 3,000 estimated tokens, the memory block at most 1,500 characters, the visit summary at most 3 sentences and 400 characters. The conversation itself is the one part that grows, so past 24 items or about 4,000 estimated tokens (characters / 3.5) it is compacted (`concierge/compaction.py`). Prompt and cached tokens are logged per turn in `anonymous_turn_metrics` and published on `concierge.metrics` | `test_static_plus_pack_within_budget`, `test_memory_block_cap`, `test_worst_case_escaping_stays_within_the_cap`, `test_long_output_is_cut_to_400_chars_at_a_space`, `test_estimate_tokens_is_ceil_chars_over_3_5`, `test_needs_compaction_past_24_items`, `test_needs_compaction_past_4000_estimated_tokens`, `test_instructions_are_not_counted`, `test_llm_metrics_tokens_land_on_the_next_turn`, `test_tokens_of_two_calls_in_one_turn_are_summed` |
| Write / select / compress / isolate | *Write*: facts and the journal in SQLite, each batch one fenced transaction. *Select*: the preload (`concierge/preload.py`) takes only the valid facts, the newest set items under the cap, and the last visit's summary. *Compress*: in-call compaction (`concierge/compaction.py`) folds all but the last 6 turns into one summary message of at most 120 words, carrying an earlier one forward, and is applied when the agent is back to listening, never inside a turn; a 5 s timeout falls back to keeping the last 12 turns. At session end the visit summary replaces the previous one and is asked to keep its key points; it starts from the summary stored at that moment and is swapped in compare-and-set, so a second tab's summary is carried forward, never overwritten. *Isolate*: extraction (`concierge/extractor.py`), the visit summary (`concierge/summary.py`) and compaction are each a separate LLM call with its own minimal context (its own system prompt, none of the session's instructions or pack) and a structured or bounded return | `test_merge_is_one_write`, `test_valid_facts_excludes_invalidated_facts`, `test_maximal_memory_is_capped_and_keeps_the_newest_set_items`, `test_last_visit_line_holds_the_quoted_summary`, `test_thirty_turns_compact_at_the_next_listening_transition`, `test_existing_summary_survives_a_second_compaction`, `test_tool_call_and_output_are_both_folded_or_both_kept`, `test_slow_summarizer_falls_back_within_5_5_s`, `test_update_chat_ctx_is_never_called_from_the_turn_hook_or_item_handlers`, `test_second_visit_summary_keeps_the_first_visits_key_point`, `test_a_summary_stored_during_the_call_is_carried_forward_not_overwritten`, `test_extractor_ctx_is_isolated_from_the_session_prompt`, `test_summary_ctx_is_isolated_from_the_session_prompt`, `test_summarizer_ctx_is_isolated_from_the_session_prompt` |
| History vs journal | Compaction (`concierge/compactor.py`) edits only the agent's in-call context (the history the model sees). The journal is append-only and gets every turn from the MemoryWriter, `session.history` keeps every item, and the visit summary reads the writer's own record of the visit, so nothing a compaction folds is lost. A `compacted` row records each one (items and estimated tokens before and after) | `test_thirty_turns_compact_at_the_next_listening_transition`, `test_the_visit_summary_after_a_compaction_reads_every_turn`, `test_run_journals_the_new_turns_in_order`, `test_a_turn_during_the_final_flush_is_journaled` |
| Evaluate for harm as well as help | `evals/memory/*.yaml` holds 13 scripted visits, each with the facts that must be stored and the ones that must not (false facts, the agent's guesses, injections, URLs and secrets, a forgotten value). The offline twin replays each script's recorded ops through the real extractor call and merge on a temporary store; `scripts/eval_memory.py` runs the same files against the live extractor and prints recall and harm hits by name (`--offline` for the replay) | `test_script`, `test_interrupted_fake_fact_never_reaches_the_extractor`, `test_injection_is_rejected_by_the_gate`, `test_runner_detects_a_forbidden_hit`, `test_runner_detects_a_forbidden_value_even_when_invalidated`, `test_runner_detects_a_value_still_valid_that_should_be_gone` |
| Profile, not collection | Typed slots (`concierge/models.py`). `name`, `role`, `company` and `follow_up_wanted` hold one valid value each, and a new ADD supersedes the old one. `interests` and `asked_about` are small sets: an ADD appends with a case-insensitive dedupe, a DELETE removes one item, and a ninth item invalidates the oldest. An unknown slot is rejected. A collection plus search is the next step if slots stop fitting | `test_slots_catalogue_kinds_and_caps`, `test_fact_rejects_unknown_slot`, `test_add_on_a_single_slot_supersedes_the_old_fact`, `test_two_adds_on_a_single_slot_in_one_batch_keep_the_later`, `test_set_add_dedupes_case_insensitively`, `test_ninth_interest_invalidates_the_oldest`, `test_visitor_state_rejects_a_ninth_set_item` |
| Provenance and confidence | Every fact row (`concierge/models.py`, stored by `concierge/fact_ops.py`) keeps its `source` (`user_said` or `user_typed` for an extracted fact, `user_asked_to_remember` for the visitor's own "remember"), `channel` (voice or text), `turn_id`, `valid_from` and a confidence between 0 and 1. The page gets the same fields on `concierge.memory` (`source`, `channel`, `learned_at`, `confidence`), so its memory panel can show where and when each fact was learned | `test_add_stores_a_fact_with_provenance`, `test_fact_source_and_channel_are_closed_literals`, `test_fact_confidence_is_between_0_and_1`, `test_memory_payload_from_a_seeded_store_validates`, `test_learned_at_and_updated_at_are_iso_utc`, `test_one_quoted_line_per_valid_fact_with_channel_and_date` |
| Forgetting | Three ways, all real deletes. A thread idle for 30 days is purged with all its rows (`purge_idle`, run by `concierge/retention.py` at worker start and daily). The visitor's "forget" deletes the matching facts and their superseded history, and a visit summary that names the value; the journal keeps that turn's text until "Forget me" or the 30-day purge (D11). "Forget me" (the page's `concierge.forget_me` RPC, `concierge/rpc.py`, `concierge/store_erasure.py`) answers `{"ok": true}` at once, then cancels the background writer, erases every row linked to the visitor, `VACUUM`s, sends an empty `concierge.memory`, says goodbye and ends the session; nothing is written for that visitor after it | `test_thread_idle_31_days_is_purged`, `test_thread_idle_29_days_stays`, `test_purge_idle_removes_every_row_of_a_purged_thread`, `test_the_worker_starts_the_daily_purge_when_it_starts`, `test_daily_purge_runs_at_once_and_again_after_each_interval`, `test_user_forget_deletes_the_row`, `test_forget_deletes_the_superseded_history`, `test_forget_clears_a_stored_summary_that_names_the_value`, `test_forget_me_returns_ok_within_50_ms_while_the_erase_sleeps`, `test_forget_me_erases_visitor_tables_and_keeps_anonymous_ones`, `test_forget_me_leaves_no_bytes_on_disk`, `test_writes_after_forget_me_raise_thread_missing`, `test_no_merge_publish_after_the_forget_publish` |
| Single writer | Every write to a thread is one `BEGIN IMMEDIATE` transaction (`concierge/store_journal.py`) that checks and bumps `threads.version` (the 1.8 counterpart of 2.0's lease plus fence). A stale writer gets `VersionConflict` and re-applies its delta ops against a fresh read instead of overwriting; the visit summary is swapped compare-and-set. 1.8 has no lease, so two tabs for one visitor can interleave turns, but every write lands once | `test_two_processes_writing_one_thread_both_land`, `test_stale_expected_version_raises_version_conflict_and_leaves_no_row`, `test_apply_fact_ops_reapplies_after_a_conflict`, `test_merge_rereads_facts_after_a_version_conflict`, `test_the_fence_alone_keeps_an_erased_thread_empty`, `test_a_summary_stored_during_the_call_is_carried_forward_not_overwritten` |
| Observability | Three places. The journal records each memory event with its timing (`memory_preloaded`, `extraction_ran`, …). Every turn writes one row of numbers to `anonymous_turn_metrics` and publishes the same on `concierge.metrics` for the page: end of utterance, STT, LLM first token, TTS first byte, total, 1.8's timing of the `on_user_turn_completed` hook (`memory_on_turn_path_ms`), preload and extraction times, prompt and cached tokens, and whether a compaction ran (`concierge/metrics.py`). LiveKit Agent Insights gets transcripts, traces and metrics, with visitor audio off unless `CONCIERGE_RECORD_AUDIO=1` (B11) | `test_preload_journals_memory_preloaded_with_ms`, `test_run_journals_extraction_ran_with_ms_and_ops`, `test_one_row_per_turn_with_the_anonymous_columns`, `test_memory_on_turn_path_ms_is_measured`, `test_one_publish_per_turn_validates_against_the_schema`, `test_session_publishes_concierge_metrics_per_turn_with_the_llm_tokens`, `test_recording_options_default_keeps_audio_off`, `test_recording_options_audio_on_for_michaels_tests` |

## How it maps onto Agents 2.0

This is LiveKit Agents 1.8 code. Nothing here is 2.0 code: the table only describes how the 1.8 memory, shaped like
2.0's thread, lane, journal and fence, would map across. The store is SQLite in WAL mode (`concierge/store.py`, design
in [`docs/plans/2026-10-20-C2-store.md`](docs/plans/2026-10-20-C2-store.md)).

| 2.0 | Here (1.8) | Where it differs |
|---|---|---|
| thread | `threads` row, one per visitor, `visitor_id` unique (2.0's `scope`); `attributes` JSON holds the visit count | 2.0 finds a thread by id; here the visitor id from the page is the key, and `get_or_create_thread` at session start is the only call that creates one |
| lane state | `state` row: `VisitorState` (pydantic, under 8 KiB), derived from the valid rows in `facts`, which keep provenance (`source`, `channel`, `turn_id`) and validity (`valid_from`, `valid_to`, `superseded_by`) | one agent, so one lane; 2.0 caps state at 64 KiB |
| journal | `journal` table, append-only: `session_started`, `user_turn`, `fact_added`, `extraction_ran`, … with `ts_ms` and a JSON payload | rows are keyed by `session_id`, not a lane and run id |
| channels | voice and typed text (`lk.chat`) feed one session and one thread; each fact records its `channel` | the agent knows the channel; 2.0 hides it from the handler |
| lease / fence vs lock | every fact and state write to a thread is one `BEGIN IMMEDIATE` transaction (SQLite's write lock, held for that transaction only) that checks and bumps `threads.version`; a stale writer gets `VersionConflict`, and `apply_fact_ops` reloads and re-applies its delta ops (up to 5 attempts) instead of overwriting | 2.0 conditions each commit on the version **and** a lease token, and the lease holds the lane for a whole turn. 1.8 has no lease, so two live sessions for one visitor can interleave turns: each write lands, but neither session waits for the other's turn to finish |
| across days: TTL and returning visits | `threads.idle_ttl_s` (30 days); `purge_idle` deletes an idle thread with all its rows, at worker start and daily (`concierge/retention.py`). A return within the TTL counts a visit on the thread, preloads the facts and the last visit summary, and greets by name if one was confirmed | 2.0's platform expires a thread after `idle_ttl`; here the worker runs the purge. 2.0 would carry the visit summary in lane state; here it is a field of `VisitorState` |

## Results

No number appears here before it is measured. The latency table is filled from `scripts/latency_report.py` (p50 and
p95 per field over the `anonymous_turn_metrics` table, in this shape), and the memory table from
`scripts/eval_memory.py` (the 13 scripted visits in `evals/memory/` run against the live extractor) and the live tests
in `tests/live/test_live.py`, all on Michael's box ([`MORNING.md`](MORNING.md)).

| field | n | p50 | p95 |
|---|---|---|---|
| `eou_ms` | to measure | to measure | to measure |
| `stt_ms` | to measure | to measure | to measure |
| `llm_ttft_ms` | to measure | to measure | to measure |
| `tts_ttfb_ms` | to measure | to measure | to measure |
| `total_ms` | to measure | to measure | to measure |
| `memory_on_turn_path_ms` | to measure | to measure | to measure |
| `preload_ms` | to measure | to measure | to measure |
| `extraction_ms` | to measure | to measure | to measure |
| cached-token share | to measure | to measure | |

| memory eval | result |
|---|---|
| recall (`scripts/eval_memory.py`, live extractor) | to measure |
| harm hits (false facts, agent-said facts, stored injections, kept forgotten values) | to measure |
| live tests passing (`pytest -m live`) | to measure |

## How it's verified

| Tier | Run with | What it proves | What it cannot prove |
|---|---|---|---|
| offline | `.harness/check.sh` (no network, no keys; anyone runs it) | The code against fakes: the fake LLM, fake rooms and recorded extractor ops. It includes the two offline eval twins, `scripts/eval_memory.py --offline` and `scripts/eval_conversation.py --offline`, which replay recorded answers. | Anything about a real model, a real voice or a real room. |
| llm | `pytest -m llm` or `scripts/eval_conversation.py` (Michael's) | The real prompt and LLM, through the text path: the 11 scripts in `evals/conversation/` check what it says, what it refuses and that it uses its tools. | Speech: there is no STT, TTS or room, so mishearing and latency are untested. |
| live | `pytest -m live` (Michael's) | The real session code in text mode, with the real conversation LLM, extractor, merge and summarizer on a temporary store: a returning visitor is greeted by name, nothing the agent said is stored as the visitor's, an injection isn't stored, and after "Forget me" the next visit is a stranger's. | Speech, a real LiveKit room and the page: it runs in-process on a fake room, so the RPCs and topics end to end are checked by hand (MORNING steps 4–6). Model quality across many conversations: it runs four fixed cases. |

## Failure cases and limits

- **The visitor id isn't auth.** It's a random id kept in the browser: clearing storage makes a stranger of a regular,
  and anyone holding the id is that visitor.
- **ASR mishears.** A misheard value is stored with the STT's lower confidence when the plugin reports one, and a name
  is stored only after the agent asked "Did I get that right, <name>?" and the visitor said yes (B12). Other slots
  aren't confirmed.
- **The extractor can miss things**, or rate them below the 0.5 floor and drop them. The grounding rule (D10: a role,
  company or interest must share a word with the visitor's own turn) trades some recall for fewer false memories. The live eval's recall
  number is the measure.
- **"Forget" leaves the turn text.** Forgetting one fact deletes the fact, its history and a summary naming it, but
  the journal keeps the visitor's turn text until "Forget me" or the 30-day purge (D11).
- **A single box.** If the worker is down, the page shows its offline state. There's no failover, and the SQLite file
  is local to that box.
- **No lease.** Two tabs open for one visitor run two sessions that can interleave turns. The version fence makes
  every write land once, but neither agent's prompt has the other's new facts until the next visit. When the
  visitor's page disconnects (a closed tab, a reload, a link to another page), the agent waits 20 s for a reconnect
  (D16), then saves its notes (the final extraction, the visit summary, a last `concierge.memory`) and leaves, so
  the site's token route frees the address within about 30 s (`concierge/departure.py`, `end_session` in
  `concierge/session_end.py`). A reload that rejoins the same room inside the 20 s carries on the same session. A
  visitor who is not in the room when the agent starts watching (gone during the connect, or never joined) gets 60 s
  to join before the agent leaves the same way.
- **No telephony or SMS.** Neither is built in this 1.8 code. In 2.0's model a `phone:` key on the visitor's thread would attach a call
  or a text to the same memory.
- **Abuse limits are simple:** a session ends after 10 minutes at most (sooner when the visitor leaves), a visitor gets 5 sessions a day, and a kill switch
  makes the worker decline jobs (`concierge/limits.py`, `concierge/worker.py`, B7).
- **Agent Insights isn't erased by "Forget me".** What LiveKit keeps is outside this store (see Privacy).

## Privacy

"Forget me" erases everything linked to the visitor, but anonymous timing numbers survive it (B9): the
`anonymous_turn_metrics` rows are keyed by a random session id, hold no visitor id and no text, only numbers, and the
TTL purge keeps them too. A small per-day session count, keyed by a SHA-256 of the visitor id and the day and kept 2 days, also
survives, so "Forget me" can't reset the daily cap. What LiveKit keeps is separate (B11): sessions start with
`record={"audio": False, "redaction": True}` (audio on only with `CONCIERGE_RECORD_AUDIO=1`), so no visitor audio is
stored at LiveKit, but transcripts, traces and metrics go to LiveKit
Agent Insights and are kept there for 30 days. "Forget me" can't erase those; the page's privacy note says so, and
[`MORNING.md`](MORNING.md) asks Michael to turn on PII redaction in the project's observability settings. No visitor
data is committed: `*.db` is gitignored. On request, the concierge describes its own memory design and how it was
built; that was checked against LiveKit's docs and terms and Anthropic's usage policy, and none of them forbids
it (`docs/decisions.md` D21).

## How to run it

Prerequisites: Python 3.12, a LiveKit Cloud project (its URL, API key and secret) and an Anthropic API key.

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.harness/check.sh                       # the offline suite: no network, no keys
```

The worker reads its keys from `~/.config/voice-concierge/env`, outside the repo. The names are in `.env.example`
(`LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `ANTHROPIC_API_KEY`; `OPENROUTER_API_KEY` only with
`CONCIERGE_LLM_PROVIDER=openrouter`, `DEEPGRAM_API_KEY` only with `CONCIERGE_SPEECH=deepgram`). No value is ever
committed.

```bash
mkdir -p ~/.config/voice-concierge
cp .env.example ~/.config/voice-concierge/env && chmod 600 ~/.config/voice-concierge/env   # then fill it in
scripts/run-worker.sh start             # foreground; checks the keys are set, then runs python -m concierge.worker
```

Or as a systemd user unit: `deploy/voice-concierge.service` assumes this code is checked out at `~/projects/voice-concierge` with its `.venv` built
(copy it to `~/.config/systemd/user/`, then `systemctl --user daemon-reload` and
`systemctl --user enable --now voice-concierge`). On stop, the worker lets live sessions finish first.

The kill switch: after `touch ~/.voice-concierge-off` the worker declines the next job, without a restart; remove the
file to turn it back on. `CONCIERGE_ENABLED=0` in the env file does the same from the next start.

The scripts:

- `.venv/bin/python scripts/latency_report.py <db>`: the p50/p95 table above, from the store (normally at
  `~/.local/share/voice-concierge/concierge.db`).
- `.venv/bin/python scripts/eval_memory.py`: the memory eval against the live extractor; `--offline` replays recorded ops with no key.
- `.venv/bin/python scripts/memory_history.py <db> <visitor_id>`: every fact of one visitor with its `valid_from` and `valid_to`.

The page side lives in the portfolio site's own repo and speaks the contract in [`docs/spec.md`](docs/spec.md) §6
(`concierge/contract.py` holds the names on this side). Michael's first live run, step by step with checks and undos,
is [`MORNING.md`](MORNING.md).
