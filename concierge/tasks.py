"""Background tasks kept in a set until done, their failures logged by type only (an error message can quote
visitor data, and asyncio would otherwise log it as "Task exception was never retrieved")."""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger("concierge.tasks")


def _done(tasks: set[asyncio.Task[Any]], log: logging.Logger, task: asyncio.Task[Any]) -> None:
    tasks.discard(task)
    if not task.cancelled() and (exc := task.exception()) is not None:
        log.warning("a background task failed (%s)", type(exc).__name__)


def track[T](
    tasks: set[asyncio.Task[Any]], coro: Coroutine[Any, Any, T], *, log: logging.Logger = logger
) -> asyncio.Task[T]:
    """A task kept in `tasks` until it is done (shutdown waits for, or cancels, what is left); a failure is logged
    on `log`."""
    task = asyncio.create_task(coro)
    tasks.add(task)
    task.add_done_callback(functools.partial(_done, tasks, log))
    return task
