# V1: the session ends when the visitor leaves (spec 2026-10-21 §3, §2 "Session end on departure")

Today nothing in the agent reacts to the visitor's participant leaving: the session runs on to its 10-minute cap, the
room stays live, and the site's one-room-per-address rule answers 429 `visitor` (spec §1.1). V1 watches the visitor's
participant, waits a 20 s grace for a reconnect (D16), then runs the closing work and leaves.

| Feature | What | Tests |
|---|---|---|
| V1-01 | this plan, D16, `concierge/departure.py` (`DepartureWatcher`), `JournalType` gains `visitor_left` | `tests/test_departure.py`, `tests/test_store.py` (+1), `tests/test_models.py` (list) |
| V1-02 | `end_session` in `concierge/session_end.py`, wiring in `concierge/session.py`, `close_on_disconnect=False`, README line | `tests/test_session.py` (+), `tests/test_limits.py` (if the `End` type changes) |
| V1-03 | review of the milestone diff, fixes test-first, notes under `## Review` | as the findings need |

## What 1.8.8 does (read from `.venv/lib/python3.12/site-packages/livekit/`)

**(a) Room events.** `rtc/room.py:55-57`, the `EventTypes` literal:

```python
EventTypes = Literal[
    "participant_connected",
    "participant_disconnected",
```

and `rtc/room.py:768-775`, `Room._on_room_event`, which emits both with the `RemoteParticipant`:

```python
if which == "participant_connected":
    rparticipant = self._create_remote_participant(event.participant_connected.info)
    self.emit("participant_connected", rparticipant)
elif which == "participant_disconnected":
    identity = event.participant_disconnected.participant_identity
    rparticipant = self._remote_participants.pop(identity)
    rparticipant._info.disconnect_reason = event.participant_disconnected.disconnect_reason
    self.emit("participant_disconnected", rparticipant)
```

The identity is `RemoteParticipant.identity` (`rtc/participant.py:163-165`: `def identity(self) -> str: return
self._info.identity`); the visitor's is `visitor-<visitor_id>` (contract §6, `room_start_kwargs` in `session.py`).
`EventEmitter.on` refuses a coroutine function (`rtc/event_emitter.py:172-178`: "Cannot register an async callback
with `.on()`"), so the handlers are plain defs that start or cancel a task.

**(b) The room is disconnected before the shutdown callbacks run.** `agents/ipc/job_proc_lazy_main.py:422`,
`_shutdown_job(self, job_entry_task, shutdown_info)`: it waits up to 15 s for the entrypoint (:426-431), closes the
primary `AgentSession` (:437-439), then

```python
await self._client.send(Exiting(reason=shutdown_info.reason))   # :477
with tracer.start_as_current_span("room_disconnect"):
    await self._room.disconnect()                               # :479
...
for callback in self._job_ctx._shutdown_callbacks:              # :497
    shutdown_tasks.append(asyncio.create_task(_traced_shutdown_callback(callback), ...))
await asyncio.gather(*shutdown_tasks)
```

So a `concierge.memory` sent from `on_shutdown` can never reach the page (the C6 publisher already drops it:
`MemoryPublisher.aclose` runs first). The spec's §3 text ("`ctx.shutdown("visitor left")`, so `on_shutdown` runs the
final extraction, the visit summary and the final `concierge.memory`") can't hold as written: **the final
`concierge.memory` must be sent before `ctx.shutdown()`**, which is what V1-02 builds.

**(c) `JobContext.shutdown(reason)`.** `agents/job.py:871-872`:

```python
def shutdown(self, reason: str = "user requested") -> None:
    self._on_shutdown(reason)
```

Sync, returns at once; the reason reaches every callback added with `add_shutdown_callback` (`agents/job.py:622-630`,
"Optionally the callback can take a single argument, the shutdown reason").

**(d) RoomIO closes the AgentSession on the disconnect itself.** `agents/voice/room_io/room_io.py:457-488`,
`RoomIO._on_participant_disconnected`: for the linked participant, when `self._options.close_on_disconnect` and the
reason is in `DEFAULT_CLOSE_ON_DISCONNECT_REASONS` (`room_io/types.py:17-21`: `CLIENT_INITIATED`, `ROOM_DELETED`,
`USER_REJECTED`), it calls `self._agent_session._close_soon(reason=CloseReason.PARTICIPANT_DISCONNECTED)`.
`RoomOptions.close_on_disconnect` defaults to `True` (`room_io/types.py:267`). A page that unmounts calls
`room.disconnect()`, which is `CLIENT_INITIATED`: today the AgentSession closes at once while the job (and the
room) stays up to the cap, which is exactly §1.1. With a grace, a reconnecting visitor would find a closed session.
So V1-02 sets `RoomOptions(close_on_disconnect=False, ...)` in `room_start_kwargs`; RoomIO then re-links the same
identity on `participant_connected` (`room_io.py:435-455`: `_participant_available_fut` is reset on the disconnect,
:469, and set again for `participant_identity`), and the DepartureWatcher owns the end.

## The watcher (V1-01, built)

`concierge/departure.py`: `DEPARTURE_GRACE_S = 20.0` (D16), and

```python
class DepartureWatcher:
    def __init__(self, room: rtc.Room, visitor_identity: str, on_left: Callable[[], Awaitable[None]],
                 grace_s: float = DEPARTURE_GRACE_S) -> None
    def start(self) -> None          # room.on("participant_disconnected" / "participant_connected", plain defs)
    def cancel(self) -> None         # idempotent: cancels the grace, takes the handlers off; later events ignored
    @property
    def pending(self) -> bool        # True while the grace runs
```

- The visitor's disconnect starts one grace task; a second disconnect while it runs doesn't restart it.
- `participant_connected` with the same identity cancels it; any other identity changes nothing either way.
- When the grace runs out, `on_left` runs in its own task, after the grace task has let go of it: a `cancel()` from
  inside `on_left` (end_session cancels the watcher first) does not cut the closing work short.
- A failing `on_left` is logged by type only.
- `JournalType` gains `"visitor_left"` (payload `{"grace_s": float}`, no values, D8).

## The V1-02 design: one `end_session`

Every end runs the same closing work, **while the room is still connected**, then leaves:

```python
# concierge/session_end.py
@dataclass
class Closing:                       # what the closing work needs; session.py fills it in as the objects exist
    end: Callable[[str], None]       # ctx.shutdown
    store: Store | None
    session_id: str
    began: float                     # time.monotonic() at start
    tasks: set[asyncio.Task[Any]]
    build_summarizer: Callable[[], llm.LLM]
    preloaded: Preloaded | None = None
    writer: MemoryWriter | None = None
    compactor: Compactor | None = None
    publisher: MemoryPublisher | None = None
    collector: TurnMetricsCollector | None = None
    timer: asyncio.Task[None] | None = None
    watcher: DepartureWatcher | None = None
    visitor_id: str = ""
    ending: asyncio.Task[None] | None = None   # the one run of the closing work

def begin_end(closing: Closing, reason: str) -> asyncio.Task[None]   # sync: what `say_and_end`'s `end` calls
async def end_session(closing: Closing, reason: str, *, leave: bool = True) -> None
```

- **Once.** The first call starts `closing.ending` (a task kept **outside** `closing.tasks`, so the closing work's
  `gather(*tasks)` never waits for itself); every later call awaits that same task (shielded) and adds nothing. So the
  departure, the 10-minute cap, the daily cap and `on_shutdown` racing run the work once.
- **The work, in order:** cancel the cap timer and the DepartureWatcher; `gather(*tasks)`; `compactor.aclose()`;
  `writer.flush()` (the final extraction); `write_summary` unless erased or no user turn; journal `session_ended`
  `{reason, duration_s}` (not when erased); then `publisher.final(await current_memory(store, writer, visitor_id))`,
  the last `concierge.memory`, unless erased (forget_me already sent the empty one and closed the publisher). All of
  it under `SHUTDOWN_WORK_S`. Then, with `leave=True`, `end(reason)` (`ctx.shutdown`).
- **on_shutdown** (`session.py`) calls `await end_session(closing, reason, leave=False)`: after a departure or a cap
  the work is already done and it only waits; after a server-side close (room deleted, worker drained) it runs the
  work then, the room is gone, so `publisher.aclose()` comes first and the final send is dropped (logged by type).
  It still closes the collector, compactor, writer, summarizers and the store last.
- **Call sites.** `DepartureWatcher(ctx.room, f"visitor-{info.visitor_id}", on_left)` started right after
  `ctx.connect()` for every session with a room, the capped one too; `on_left` journals `visitor_left`
  `{"grace_s": DEPARTURE_GRACE_S}` (when there is a thread) and awaits `end_session(closing, "visitor left")`.
  `start_session_timer(session, max_s, end)` and both daily-cap `say_and_end` calls get `end=begin_end-bound`
  instead of `ctx.shutdown`. `serve_rpcs(..., end=ctx.shutdown)` stays (the forget_me path is unchanged: erased, no
  summary, the empty memory is already the last). `room_start_kwargs` sets `close_on_disconnect=False`.
- **Size.** `session.py` is at 246 of 250: the on_shutdown body moves into `session_end.py` (now 98 lines), so
  session.py shrinks. If `session_end.py` would pass 250, `Closing` and `begin_end` go to `concierge/closing.py`.
- **Timing.** The closing work now runs before `ctx.shutdown`, so the worker's `shutdown_process_timeout=30` is no
  longer spent on it; after the 10-minute goodbye the agent stays silent in the room for the few seconds the final
  extraction and summary take (question for Michael in the progress entry).

### V1-02 test names (`tests/test_session.py`, the `fakes` fixture, a `FakeRoom` as `ctx.room`, `DEPARTURE_GRACE_S` monkeypatched to 0.1)

- `test_visitor_leaving_ends_the_session_after_the_grace`: `ctx.shutdown` called once with `"visitor left"`; one
  `visitor_left` row, then one `session_ended` row with reason `"visitor left"`.
- `test_visitor_returning_within_the_grace_keeps_the_session`: no shutdown, no `visitor_left` after 3x the grace.
- `test_another_participant_leaving_changes_nothing`.
- `test_the_final_memory_is_sent_before_shutdown`: the last `concierge.memory` body on the FakeRoom is sent before
  the recorded `ctx.shutdown` call and validates against `tests/contract/memory.schema.json`.
- `test_end_session_runs_its_work_once` (the departure and the cap racing; then `on_shutdown`): one
  `session_ended`, one summary call, one shutdown.
- `test_the_time_limit_ends_through_end_session` and `test_the_daily_cap_ends_through_end_session`: the final
  memory goes out before the shutdown on both paths.
- `test_on_shutdown_after_a_server_side_close_still_journals_and_closes` (no `end_session` before it: the work runs
  in `on_shutdown`, the final send is dropped, the store is closed).
- `test_room_options_keep_the_session_through_a_disconnect`: `room_start_kwargs(...)["room_options"]
  .close_on_disconnect is False`.

README.md § Failure cases and limits: the "No lease" bullet says that when the visitor's page disconnects the agent
waits 20 s for a reconnect, then saves its notes and leaves, so the site's token route frees the address within
about 30 s; nothing in README.md or MORNING.md says a session runs on to the cap after the page closes.

## For Michael (live; build-only, so not run here)

After V1 merges and the worker is restarted (`scripts/run-worker.sh`, MORNING.md):
1. Start a call on the site, say a sentence with your name, then click another link on the site (don't press
   Leave). Check: the worker log shows "the visitor left" about 20 s later, then the session's shutdown; the
   journal has `visitor_left` then `session_ended` `{"reason": "visitor left"}`.
2. Come back to the page within 60 s. Check: "Closing your earlier conversation…" (the page's half), then a new call
   whose greeting knows your name, and "What it remembers" shows it.
3. Reload the page during a call. Check: if the page rejoins the same room within 20 s, the same session carries
   on (no new `session_started` row, the log says "the visitor reconnected inside the departure grace"); if it asks
   for a new room, step 2's "Closing your earlier conversation…" applies. Which one happens is the page's half.
Undo: revert the V1 merge commit and restart the worker; the old behaviour (session runs to the cap) returns.

## V1-02 as built (2026-10-21)

`Closing`, `begin_end`, `end_session`, `visitor_left` and `shut_down` (the old on_shutdown body) are in
`concierge/session_end.py` (249 lines); `SHUTDOWN_WORK_S` moved there with them; `session.py` went 246 → 210 lines.
An Opus review of the build diff found no Critical and three Important points; the build changed after it:

- **I1, fixed.** The cap paths run their closing work while the room is connected, so the page can still press
  "Forget me" then. `publisher.final(...)` for the closing send would close the publisher, and a forget_me landing
  while that body was built would have its empty `concierge.memory` dropped (the stale memory last). The closing send
  is now `publisher.schedule(); await publisher.idle()` (built and re-checked under the publisher's lock like every
  other send), so forget_me's `final` still lands last. `test_a_forget_me_during_the_closing_send_still_sends_the_empty_memory_last`
  (RED: the page's last body still had the erased fact).
- **I2, fixed.** After the time-up line the AgentSession kept listening during the closing work, so a visitor could
  get answers after "I'll say goodbye here", and turns added after the flush would miss the final extraction. With
  `leave`, the closing run now closes the AgentSession first (`AgentSession.aclose` is idempotent,
  agent_session.py:1309, and leaves the room and the job up: no `delete_room_on_close`, room_io.py:552).
  `test_the_time_limit_ends_through_end_session` asserts the session closed before `session_ended` (RED before).
- **Minor 1, fixed.** `visitor_left` journaled before claiming the closing run, so a cap starting during that write
  left a `visitor_left` row beside `session_ended` with another reason. The row is now written inside the one run
  (`_begin(..., left_grace_s=...)`). `test_two_ends_starting_in_the_same_tick_run_the_work_once` (RED before).
- **Minor 2, fixed.** `test_end_session_runs_its_work_once` waits for `closing.ending` instead of a sleep.
- **I3, left for V1-03.** `DepartureWatcher.start()` only subscribes: a visitor who closes the tab during
  `ctx.connect()`/the preload, or who never joins, is never seen to leave, and the session runs to the cap. A fix
  (start the grace when the visitor isn't in `room.remote_participants`) needs a join deadline that a slow page
  (a mic prompt before the join?) won't trip, so V1-03 should choose it (a longer join grace, e.g. 60 s).
- **Also for V1-03:** a departure whose grace runs out before `start_session` returns ends the session, but the
  timer and `session_started` are still created after it (`shut_down` cancels the timer; only the journal order is
  off). Unlikely with a 20 s grace.

## Review

V1-03 (2026-10-21). An Opus reviewer read the milestone diff (`git diff 21905a7..HEAD -- . ':!.harness'`, 1362
lines) from `$HARNESS_SCRATCH/review-V1.diff` and returned findings only. Each fix below was RED first. The new or
changed test failed for the reason given before the code changed.

### Critical

None. The closing work runs once: `_begin` (`concierge/session_end.py`) creates `closing.ending` one time, and every
other entry waits on that task. forget_me leaks nothing:
- the extraction is skipped once erased (`memory_writer.py:196`);
- `write_summary`, and `session_ended`, are skipped once erased;
- a closing row on an erased thread is `ThreadMissing` and is only logged;
- `publisher.final` closes the publisher before it takes the lock, so the empty body is the last one.

A second `ctx.shutdown` is a no-op (`job_proc_lazy_main.py:297-303`).

### Important

**I1: a visitor gone before the watch starts was never seen to leave** (V1-02's open I3). This covers a visitor who
left during `ctx.connect()` or the preload, and one who never joined. `concierge/departure.py:start()` now checks
`room.remote_participants` (rtc/room.py:249). If the visitor isn't in it, the watcher starts `JOIN_GRACE_S = 60.0`.
A `participant_connected` with the same identity cancels that grace (D16, extended).
- RED: `tests/test_departure.py::test_a_visitor_absent_at_start_gets_the_join_grace_then_on_left` and
  `::test_a_visitor_joining_inside_the_join_grace_cancels_it` (ImportError: no `JOIN_GRACE_S`).
- RED: `tests/test_session.py::test_a_visitor_gone_before_the_watch_starts_still_ends_the_session` (no shutdown).
- The reviewer thought 60 s was probably longer than needed, since the room exists only once the page has
  connected. It was kept as the safe side, and the question went to Michael.

**I2: start_session went on after an end began.** An end that began during `session.start` or the late daily count
(up to 5 s) still produced a greeting. If the closing had already closed the AgentSession, `generate_reply` raised
"AgentSession isn't running" and the entrypoint failed. It also still started the timer and journaled
`session_started` after `session_ended`. A forget_me during the late count had the agent greet the visitor after
"I've forgotten everything about you", because forget_me ended through a bare `ctx.shutdown` and never marked the
session as ending.
- Fix part 1: forget_me now ends through `begin_end` (`end=end` in `serve_rpcs`), the last end path outside
  `end_session`. A forget_me during a running closing therefore no longer calls `ctx.shutdown("forget_me")` in the
  middle of that work.
- Fix part 2: `Closing.stop()` sets `stopped`. `_begin` calls it at once, and so does forget_me (`stop_timer`).
  `start_session` checks `closing.stopped` after `session.start`, before the late count's cap line and before the
  greeting.
- RED: `test_an_end_during_the_start_starts_nothing_after_it` (a greeting handle).
- RED: `test_an_end_during_the_late_count_starts_nothing_after_it` (`RuntimeError: AgentSession isn't running`).
- RED: `test_a_forget_me_during_the_late_count_ends_without_a_greeting` (a greeting).
- RED: `test_a_forget_me_after_a_cap_began_runs_the_work_once` (`['forget_me', 'time limit']`).
- Changed: `test_a_forget_me_during_the_closing_send_still_sends_the_empty_memory_last` now expects the one end,
  `"time limit"`.

**I3, found while fixing I2: forget_me during a cap's closing could still lose its empty memory.** The race goes:
1. The closing send reads the stale memory while forget_me is still erasing.
2. `publisher.idle()` returns, and `ctx.shutdown` runs.
3. `publisher.aclose()` drops forget_me's `final`.

Before V1-03 the test waited for forget_me's own `ctx.shutdown`, which hid this; production never waited. Now
`_close` awaits the session's tracked tasks once more before it leaves, and forget_me is one of them.
- RED: `test_a_forget_me_during_the_closing_send_still_sends_the_empty_memory_last`, with the erase slowed by 0.2 s
  (the last body still had `Ada`; before the slowdown it failed about 1 run in 10).

### Minor (all fixed)

- **M1.** `visitor_left` journaled `grace_s: 20` after the 60 s join grace. The watcher now records `waited_s`, and
  `on_left` passes it on. `test_waited_s_is_the_departure_grace_after_a_departure`, plus the payload assert in the
  gone-before test (RED: `{'grace_s': 0.1}`).
- **M2.** Dead `_EVENTS` in `departure.py`, removed.
- **M3.** Dead code in `limits.py`:
  - `enforce_daily_cap` was used only by its test. Removed, with `test_enforce_daily_cap_says_the_line_and_ends_on_the_sixth`.
  - The `end is None` branch of `say_and_end` and the `end=None` default of `start_session_timer` and
    `build_handlers` were reachable only from tests. `end` is now required, and `test_session_timer_without_end_closes_the_session`
    and `Speaker.aclose` are gone.
- **M4.** The `visitor_left` wrapper was folded into `end_session(..., left_grace_s=)`. Slimming `Started`, which
  duplicates fields of `Closing`, was not done: it is optional churn, and the tests read `started.timer`.
- **M5.** `FakeRoom.emit` now keeps `remote_participants` as `rtc.Room` does (room.py:769, :773), and `FakeRoom.seat`
  puts a visitor in the room. `test_the_fake_room_tracks_who_is_in_it`. The V1 session tests use `seated_room()`.
- **M6.** `session_started` is journaled on the writer's store thread, in order with the writer's rows.

### Checked, clean

- Every `room.on` / `session.on` handler is a plain def that only schedules or cancels work (`EventEmitter.on`
  refuses coroutines, rtc/event_emitter.py:172-178).
- The departure grace running out while the time-up line plays ends once, with "visitor left": the timer is
  cancelled and its `say_and_end` never calls `end`. New test `test_the_grace_running_out_during_the_time_up_line_ends_once`
  (GREEN on arrival; it covers a gap and needed no fix).

### Simplification pass

- The end paths now all go through `end_session`: the departure, both caps, forget_me and `on_shutdown`.
- Dead code removed: `enforce_daily_cap`, the `end=None` paths, `Speaker.aclose`, `_EVENTS`, the `visitor_left`
  wrapper.
- `wc -l concierge/*.py`: every module is at most 250 lines (`session_end.py` 250, `session.py` 219).
