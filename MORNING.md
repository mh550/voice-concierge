# MORNING.md: Michael's checklist

This needs keys only you have (LiveKit Cloud, Anthropic) and takes about 20 minutes. Steps 1–2 are offline. From
step 3 on, steps call LiveKit Cloud or the Anthropic API, so each of those steps says what to **Check** and
how to **Undo** it. Run the commands from the repo root. Nothing here was run by the build.

The env file `~/.config/voice-concierge/env` holds plain `NAME=value` lines (no quotes, spaces or `$` in values:
systemd and bash both read it). `.env.example` lists the names.

## 1. Env check

```
test -s ~/.config/voice-concierge/env && grep -c '=' ~/.config/voice-concierge/env
grep -oE '^(LIVEKIT_URL|LIVEKIT_API_KEY|LIVEKIT_API_SECRET|ANTHROPIC_API_KEY)=.' ~/.config/voice-concierge/env | cut -d= -f1
```

All four names must print (it never prints a value). `ANTHROPIC_API_KEY` is the LLM key (D5). Also check the
Anthropic Console's spend limit and remaining credit.

## 2. Suite

```
.harness/check.sh
```

Check: exit 0, offline. Undo: none.

## 3. Start the worker

Dry run first: `scripts/run-worker.sh --help` exits 0 when the env is complete and names the missing variable
otherwise. Then, in the foreground:

```
scripts/run-worker.sh start
```

Or as a systemd user unit, once this branch is merged and checked out at `~/projects/voice-concierge` with its `.venv`
built (run `.harness/init.sh` there; until then that checkout has no `scripts/run-worker.sh` and the unit restarts
every 10 s):

```
cp deploy/voice-concierge.service ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl --user enable --now voice-concierge
```

Optionally `loginctl enable-linger "$USER"`, so the unit survives logout.

Check: the log shows the worker registered, no traceback. Undo: Ctrl-C (it waits for live sessions; a second Ctrl-C
forces), or `systemctl --user disable --now voice-concierge`.

The first start of V2 code moves the memory db to schema version 3 (it adds the `visit_summaries` table, one row per
visit; nothing existing changes). Older code then refuses that file ("schema version 3; this code knows 2"), so rolling
back to V1 code means keeping a copy of the db from before: `cp ~/.local/share/voice-concierge/concierge.db
~/.local/share/voice-concierge/concierge.db.v2` with the worker stopped, before the first V2 start. That copy holds
visitor data "Forget me" and the 30-day purge can't reach: `rm` it once V2 runs fine, and within 30 days in any case.
Until the V2 worker has started once, the scripts in §10 and §12 refuse the old file with exit 2: `memory_history.py` says "schema version 2; this code reads 3", `messages.py` and `latency_report.py` say only `not a memory store: <db> (StoreError)`.

## 4. Voice

Open the portfolio page and press talk. Say your name and a project, answer the name confirmation, hang up, and come
back.

Then, in a new call, click another link on the site without pressing Leave, and come back to the page.

Check: the memory panel lists the facts with channel and time, and the second visit greets you by name. After the
link-click round trip the page shows "Closing your earlier conversation…" at most briefly, and the memory panel fills
again. Undo: step 6.

## 5. Text

Type a message on the page. Then ask it to leave Michael a message with your email (the `leave_message_for_michael` tool).

Check: it's answered from the same memory, the new fact shows channel `text`, and step 12's `scripts/messages.py` lists
the message. Undo: step 6.

## 6. Forget me

Press "Forget me".

Check: the panel empties within a second, the agent says goodbye and leaves, and the next visit is a stranger's.
Undo: none, it's an erase (anonymous timing rows stay, B9).

## 7. Live tests

```
( set -a; . ~/.config/voice-concierge/env; set +a; .venv/bin/pytest -m live -q )
```

Check: `4 passed`. `4 skipped` means the env wasn't loaded. Undo: none; they use temp dbs.

## 8. Memory eval

```
( set -a; . ~/.config/voice-concierge/env; set +a; .venv/bin/python scripts/eval_memory.py )
```

Check: the total row, harm 0, exit 0; note the recall. A case that shows `error` and `APIStatusError` got a 400 or a refusal
from the API; if every case does (or the worker log shows `extraction failed (APIStatusError)`), look first at the
strict-schema risk (C4 plan "Risks": a 400 on the `emit_ops` schema). Undo: none.

## 9. Conversation evals

```
( set -a; . ~/.config/voice-concierge/env; set +a; .venv/bin/python scripts/eval_conversation.py )
```

It runs the 11 scripts in `evals/conversation/` through the real prompt and LLM over the text path (no STT, TTS or
room, no store).

Check: the total row reads `| total | 12 turns | 11/11 scripts passed |  | |` and the exit code is 0. A failing script
shows `fail` in its turn's result cell with the broken assertion beside it, and the total row's fourth cell reads
`failed: <names>` (exit 1). The reply column shows what the agent said, so read it to see why. Exit 2 means the key
is missing. Undo: none, there is no room and no store.

## 10. Latency report

```
.venv/bin/python scripts/latency_report.py ~/.local/share/voice-concierge/concierge.db
```

That is the `db_path` default in `concierge/config.py`; use `CONCIERGE_DB_PATH` if you set it. Paste the table into
README "Results" with the totals from step 8, add the line `Measured on <YYYY-MM-DD> on Michael's box.` above the
tables (`tests/test_readme.py` allows numbers there only with that line), run `.harness/check.sh`, and commit only
`README.md`.

Check: `eou_ms`, `stt_ms`, `llm_ttft_ms`, `tts_ttfb_ms` and `total_ms` each have `n=` of at least 20 (`preload_ms` is one
per session and `extraction_ms` one per merge, so theirs are smaller); otherwise talk more turns first. Undo:
`git revert` the README commit.

## 11. PII redaction

In the LiveKit Cloud project `portfolio-voice-agent`, turn on PII redaction in the observability settings (B11).

Check: the setting reads on. Undo: turn it off.

## 12. Your memory history

```
.venv/bin/python scripts/memory_history.py ~/.local/share/voice-concierge/concierge.db <your visitor id>
```

The visitor id is in the page's local storage (browser dev tools). Run it to a terminal only: it prints visitor data.

`.venv/bin/python scripts/messages.py ~/.local/share/voice-concierge/concierge.db` lists the messages left for you.
Read them within 30 days: the idle purge deletes them with the visitor's thread (D15).

Check: one line per fact, corrected ones with a `valid_to`, then one `visit <n>` line per visit (started, ended or `-`,
the summary stored at its end or `-`); one line per message, newest first. Undo: none, both are read-only.

## 13. Source drift check

```
.venv/bin/python scripts/check_sources.py
```

It downloads the five vendored files (`Bio.md` and four from `src/lib/data/`) from the portfolio repo's `main` on
GitHub (public, no key) and compares them with `knowledge/sources/`, header lines aside (D22).

Check: exit 0 and `clean: 5 files match main`, or exit 1 and one `drifted: <name>` line per changed file; then
re-vendor as `docs/plans/2026-10-21-V3-knowledge-v2.md` says and rebuild the pack in a session with a review. Exit 2
means a fetch failed or a file is missing (the reason is on stderr). Undo: none, it is read-only.

## 14. Stop

- Ctrl-C, or `systemctl --user stop voice-concierge`.
- Kill switch, no restart needed: `touch ~/.voice-concierge-off`. New jobs are declined and the page shows offline after
  about 10 s. Undo: `rm ~/.voice-concierge-off`.

Check: after Ctrl-C or `stop`, the worker process is gone (`systemctl --user status voice-concierge` says inactive);
with only the kill switch, the worker keeps running and the page shows offline. Undo: step 3.

## Questions for you

Each is a default the build took (details in `docs/decisions.md`); say if you want it changed.

- **D7:** keep turn detection on VAD only, or switch to the local turn-detector model (the `turn_handling` line in `build_session`, `concierge/session.py`)?
  Switch if the agent cuts into your pauses.
- **D8 / D11:** "forget X" deletes the fact but leaves that turn's text in the journal until "Forget me" or the 30-day
  purge. OK, or should it blank the turn text too?
- **D9:** does the page send a pre-connect audio buffer, or let visitors type before the agent joins? If so, the preload
  should be awaited before `session.start`.
- **D10:** keep rejecting extracted values that share no word with the visitor's turn (fewer false memories, some lost
  paraphrases)?
- **D12:** after a compaction keep the last 6 messages verbatim (3 exchanges, the default) or the last 6 exchanges?
- **D13:** does the page expect fact `id` as a number and timestamps as ISO-8601 `…Z` strings?
- **D14:** should a message for you allow links in its text (the gate refuses them now, and "act as …")?
- **D15:** should messages outlive the 30-day idle purge, until you delete them?
- **D16:** is 20 s the right wait for the visitor to reconnect before the agent leaves (or 10 s, or 30 s)? And is
  60 s right for a visitor who isn't in the room yet when the agent starts watching (V1-03)?
- **D17:** the memory panel's event lines (contract v2): should "Took notes in the background" show on every run, even
  with no change (now only when something changed)? And should each past visit carry the rolling summary as it stood
  then (the default), or should the summarizer also write a per-visit one?
  And (D17 (i)): a v2 key with no value is sent as `null` (the default, and the page's schema must accept it), not
  left out. Is that fine for the page?
  And (D17 (l)): the forget line names the slot ("Forgot at your request: company"), or reads "Forgot something at
  your request" for "forget Acme", and earlier lines lose a forgotten value, rather than §2's literal
  "Forgot at your request: <the visitor's words>". OK?
- **D18:** the memory panel's cache share is the last turn that had LLM metrics (it keeps its value through a turn
  with none). OK, or should it be the session's cumulative share?
- **D19:** the V2 review's three fixes. (a) Over 15 KiB, the v1 `facts` keep every fact (the order is now D20's,
  below). (b) A v2 key with nothing to report (`about_agent` after "Forget me") is left out
  rather than sent as null: tell the portfolio run if its page expects null. (c) An event line never quotes a value
  that reads as a link or an order ("Node.js" shows as "Remembered your interest"). Should the write gate refuse
  such values too, so they are never stored?
- **D20** (replaces D19 (a)'s order): over 15 KiB the body drops the oldest v2 `profile` facts first (a copy of
  `facts`), then events, then episodes; the v1 `facts` stay (v1's own oldest-fact backstop runs only past all three,
  which an allowed body never reaches). A v2 page should read `facts` when `profile` is
  shorter. OK, or should both lists always match and the events pay for it?
- **D21** (not a default: your question, answered): describing its own design breaks none of LiveKit's docs, its
  terms or Anthropic's usage policy. LiveKit's terms (§2.6.2, §2.6.6) and Anthropic's AUP both ask that visitors be
  told they are talking to an AI; the greeting doesn't say "AI". Does the portfolio page label the concierge as an AI agent, or should the greeting say it?
- **D22:** the vendored sources get a drift check you run (step 13), not an automatic pack rebuild. Run it weekly from
  a systemd timer, or by hand from this list only?
