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
