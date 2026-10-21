"""The usher (spec 2026-10-21 §9, contract §2 `concierge.navigate`; plan V6 "The tool and its replies").

`show_page` asks the visitor's page to show one of Michael's pages while the agent talks about it. Only an href on the
allowlist is ever sent: the fixed routes, and `/projects/<slug>` for each slug the pack's Source lines cite. Anything
else is refused and journaled as its path alone. At most one send per 8 s, the page's own limit mirrored. The page
follows only while the visitor's Guide me toggle is on; that half is the page's.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit

from livekit import rtc
from pydantic import BaseModel

from concierge.contract import MAX_DETAIL, NAVIGATE_TOPIC, NavigatePayload, iso_utc
from concierge.gate import check_text
from concierge.models import Journal
from concierge.store import now_ms
from concierge.tasks import track

logger = logging.getLogger("concierge.usher")

FIXED_ROUTES = ("/skills", "/experience", "/about", "/contact", "/")
NAVIGATE_MIN_INTERVAL_S = 8.0
SEND_TIMEOUT_S = 2.0  # a send that hangs (a room going away) mustn't hold up the reply

SHOWING = "Showing them {href}"
NOT_ON_LIST = "That page is not one I can show"
TOO_SOON = "Already showing a page; keep talking"
NOT_SENT = "That page didn't open; keep talking"

_SLUG = re.compile(r"^Source: \S+ \(slug: ([a-z0-9][a-z0-9-]*)\)\s*$", re.MULTILINE)

Publish = Callable[[rtc.Room, str, BaseModel], Awaitable[None]]


def allowlist_from_pack(pack: str) -> frozenset[str]:
    """FIXED_ROUTES plus `/projects/<slug>` for each `Source: <file> (slug: <slug>)` line of the pack."""
    return frozenset(FIXED_ROUTES) | {f"/projects/{slug}" for slug in _SLUG.findall(pack)}


def _path(href: str) -> str:
    """What a refusal journals: a site path ("/..." with no scheme, or an http(s) URL's), at most 120 characters,
    and only if the write gate passes it. No host, query or reason text; "" for anything else (mailto:, tel:, ...)."""
    try:
        parts = urlsplit(href)
    except ValueError:  # "http://[" and the like
        return ""
    path = parts.path[:MAX_DETAIL]
    if parts.scheme not in ("", "http", "https") or not path.startswith("/") or not check_text(path).ok:
        return ""
    return path


def _reason(reason: str) -> str:
    """Stripped and cut to 120 characters; one the write gate rejects is not sent at all (D23 (a))."""
    capped = reason.strip()[:MAX_DETAIL]
    return capped if check_text(capped).ok else ""


class Usher:
    """One session's navigations. `publish` is `publish.publish(room, topic, payload)`; `journal(kind, payload)` the
    session's `journal_row`, or None without memory (nothing to journal into), run in the background on `tasks` (the
    session's, so its shutdown waits for the row); `clock` is monotonic seconds."""

    def __init__(
        self, room: rtc.Room, allowlist: frozenset[str], publish: Publish, journal: Journal | None,
        clock: Callable[[], float], *, tasks: set[asyncio.Task[Any]] | None = None,
    ) -> None:
        self._room = room
        self._allowlist = allowlist
        self._publish = publish
        self._journal = journal
        self._clock = clock
        self._tasks: set[asyncio.Task[Any]] = set() if tasks is None else tasks
        self._last_sent: float | None = None
        self._refused: set[str] = set()  # paths journaled this session: a model looping on one writes one row

    async def show_page(self, href: str, reason: str) -> str:
        if href not in self._allowlist:
            path = _path(href)
            if self._journal is not None and path not in self._refused:
                self._refused.add(path)
                track(self._tasks, self._journal("navigate_refused", {"path": path}), log=logger)  # off the turn
            return NOT_ON_LIST
        now = self._clock()
        last = self._last_sent
        if last is not None and now - last < NAVIGATE_MIN_INTERVAL_S:
            return TOO_SOON
        payload = NavigatePayload(href=href, reason=_reason(reason), at=iso_utc(now_ms()))
        self._last_sent = now  # taken before the await: a second call in the same turn sees it (no lock to hang on)
        try:
            await asyncio.wait_for(self._publish(self._room, NAVIGATE_TOPIC, payload), SEND_TIMEOUT_S)
        except Exception as exc:  # StreamError, a timeout, a room that never connected: the slot is given back
            if self._last_sent == now:  # unless a later send has taken it since
                self._last_sent = last
            logger.warning("a concierge.navigate send was dropped (%s)", type(exc).__name__)
            return NOT_SENT
        return SHOWING.format(href=href)
