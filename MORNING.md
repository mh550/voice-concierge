# MORNING.md: Michael's checklist

This needs keys only you have (LiveKit Cloud, Anthropic) and takes about 20 minutes. Steps 1–2 are offline. From
step 3 on, the worker talks to LiveKit Cloud and the Anthropic API, so each of those steps says what to **Check** and
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

Or as a systemd user unit (the repo at `~/projects/voice-concierge` with its `.venv` built):

```
cp deploy/voice-concierge.service ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl --user enable --now voice-concierge
```

Optionally `loginctl enable-linger "$USER"`, so the unit survives logout.

Check: the log shows the worker registered, no traceback. Undo: Ctrl-C (it waits for live sessions; a second Ctrl-C
forces), or `systemctl --user disable --now voice-concierge`.

## 4. Voice

Open the portfolio page and press talk. Say your name and a project, answer the name confirmation, hang up, and come
back.

Check: the memory panel lists the facts with channel and time, and the second visit greets you by name. Undo: step 6.

## 5. Text

Type a message on the page.

Check: it's answered from the same memory, and the new fact shows channel `text`. Undo: step 6.

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

Check: the total row, harm 0, exit 0; note the recall. If every case shows recall 0 and the worker log has no
`extraction_ran`, look first at the strict-schema risk (C4 plan "Risks": a 400 on the `emit_ops` schema). Undo: none.

## 9. Latency report

```
.venv/bin/python scripts/latency_report.py ~/.local/share/voice-concierge/concierge.db
```

That is the `db_path` default in `concierge/config.py`; use `CONCIERGE_DB_PATH` if you set it. Paste the table into
README "Results" with the totals from step 8, and commit only `README.md`.

Check: `eou_ms`, `stt_ms`, `llm_ttft_ms`, `tts_ttfb_ms` and `total_ms` each have `n=` of at least 20 (`preload_ms` is one
per session and `extraction_ms` one per merge, so theirs are smaller); otherwise talk more turns first. Undo:
`git revert` the README commit.

## 10. PII redaction

In the LiveKit Cloud project `portfolio-voice-agent`, turn on PII redaction in the observability settings (B11).

Check: the setting reads on. Undo: turn it off.

## 11. Your memory history

```
.venv/bin/python scripts/memory_history.py ~/.local/share/voice-concierge/concierge.db <your visitor id>
```

The visitor id is in the page's local storage (browser dev tools). Run it to a terminal only: it prints visitor data.

Check: one line per fact, corrected ones with a `valid_to`. Undo: none, it's read-only.

## 12. Stop

- Ctrl-C, or `systemctl --user stop voice-concierge`.
- Kill switch, no restart needed: `touch ~/.voice-concierge-off`. New jobs are declined and the page shows offline after
  about 10 s. Undo: `rm ~/.voice-concierge-off`.

Check: the worker process is gone (`systemctl --user status voice-concierge` says inactive), and with the file present
the page shows offline. Undo: step 3.

## Questions for you

Each is a default the build took (details in `docs/decisions.md`); say if you want it changed.

- **D7:** keep turn detection on VAD only, or switch to the local turn-detector model (one line in `concierge/worker.py`)?
  Switch if the agent cuts into your pauses.
- **D8 / D11:** "forget X" deletes the fact but leaves that turn's text in the journal until "Forget me" or the 30-day
  purge. OK, or should it blank the turn text too?
- **D9:** does the page send a pre-connect audio buffer, or let visitors type before the agent joins? If so, the preload
  should be awaited before `session.start`.
- **D10:** keep rejecting extracted values that share no word with the visitor's turn (fewer false memories, some lost
  paraphrases)?
- **D12:** after a compaction keep the last 3 exchanges verbatim (default: a "turn" is one message) or the last 6?
- **D13:** does the page expect fact `id` as a number and timestamps as ISO-8601 `…Z` strings?
- **Health port:** the worker's health server listens on all interfaces, port 8081. Bind it to `127.0.0.1`
  (`AgentServer(host="127.0.0.1")`)? Until then, keep 8081 closed at the firewall.
