"""The worker entry point: `python -m concierge.worker start` (scripts/run-worker.sh wraps it).

Explicit dispatch as `concierge` (spec §6). Providers need keys, so they're built only inside the entrypoint, never
at import; importing this module needs no LIVEKIT_*,
ANTHROPIC_API_KEY or OPENROUTER_API_KEY. The session itself is `concierge/session.py`.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from pathlib import Path

from livekit.agents import AgentServer, JobContext, JobProcess, JobRequest, cli
from livekit.plugins import silero
from pydantic import ValidationError

from concierge.config import Settings
from concierge import retention
from concierge.dispatch import DispatchError, parse_dispatch
from concierge.session import start_session
from concierge.store import Store, StoreError

logger = logging.getLogger("concierge.worker")


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()  # D7: VAD-only turn detection; the model ships in the wheel


async def on_request(req: JobRequest) -> None:
    """The kill switch (B7): decline the job under CONCIERGE_ENABLED=0 or when the off file exists, so no agent joins
    and the page shows its offline state (§6). Settings are read per request: creating the off file takes effect at
    the next job with no restart. Fails closed: settings that don't validate decline too."""
    try:
        settings = Settings()
    except ValidationError:
        logger.warning("declining job %s: the settings do not validate", req.id)
        await req.reject()
        return
    if not settings.enabled or settings.off_file.exists():
        logger.info("declining job %s: the kill switch is on", req.id)
        await req.reject()
        return
    await req.accept()


def _open_store(path: Path) -> Store:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    return Store(path)


async def _open_or_none(path: Path) -> Store | None:
    """The store, opened off the loop; None (a session without memory) when it can't open. Only the error type is
    logged: a message can quote a path or visitor data."""
    try:
        return await asyncio.to_thread(_open_store, path)
    except (StoreError, sqlite3.Error, OSError) as exc:
        logger.warning("no memory this session: the store did not open (%s)", type(exc).__name__)
        return None


server = AgentServer(shutdown_process_timeout=30, setup_fnc=prewarm)
_background: set[asyncio.Task[None]] = set()


@server.on("worker_started")
def _start_retention() -> None:
    """B6: the TTL purge at worker start and daily. `worker_started` is emitted in the main process with its loop
    running (AgentServer.run, worker.py:862 in 1.8.8)."""
    try:
        path = Settings().db_path
    except ValidationError:
        logger.warning("no retention purge: the settings do not validate")
        return
    task = asyncio.get_running_loop().create_task(retention.run_daily_purge(path), name="retention_purge")
    _background.add(task)
    task.add_done_callback(_background.discard)


@server.rtc_session(agent_name="concierge", on_request=on_request)
async def entrypoint(ctx: JobContext) -> None:
    try:
        parse_dispatch(ctx.job.metadata)  # before any store or provider exists (C1-05)
    except DispatchError as exc:
        logger.warning("ending job %s: %s", ctx.job.id, exc)
        ctx.shutdown(reason="bad dispatch metadata")
        return

    settings = Settings()
    await start_session(ctx, await _open_or_none(settings.db_path), settings)  # it closes the store at shutdown


if __name__ == "__main__":
    cli.run_app(server)
