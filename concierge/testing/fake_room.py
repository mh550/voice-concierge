"""A room whose local participant records what the agent sends and registers, for tests (plan C6 "Fixtures and fakes").

Shaped from livekit rtc 1.1.20: `LocalParticipant.send_text(text, *, destination_identities, topic, attributes,
reply_to_id, compress) -> TextStreamInfo` (rtc/participant.py:864-873, raising `StreamError` on a failed send) and
`register_rpc_method(method_name, handler=None)`, usable as a decorator (participant.py:518-571). `FakeRoom` is a real
`rtc.Room` (JobContext registers its event handlers on it) that is never connected; only `local_participant` is faked,
where the real one raises before `connect()` (rtc/room.py:228-235).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from typing import Any

from livekit import rtc


class FakeLocalParticipant:
    identity = "agent-fake"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []  # (text, topic), in send order
        self.rpc_handlers: dict[str, Callable[..., Any]] = {}
        self.fail_with: Exception | None = None  # set to make send_text raise it (e.g. rtc.StreamError)

    async def send_text(
        self,
        text: str,
        *,
        destination_identities: list[str] | None = None,
        topic: str = "",
        attributes: dict[str, str] | None = None,
        reply_to_id: str | None = None,
        compress: bool = True,
    ) -> rtc.TextStreamInfo:
        if self.fail_with is not None:
            raise self.fail_with
        self.sent.append((text, topic))
        return rtc.TextStreamInfo(
            stream_id=uuid.uuid4().hex, mime_type="text/plain", topic=topic, timestamp=int(time.time() * 1000),
            size=len(text.encode()), attributes=attributes or {}, attachments=[],
        )

    def register_rpc_method(self, method_name: str, handler: Callable[..., Any] | None = None) -> Any:  # noqa: ANN401
        def register(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.rpc_handlers[method_name] = fn
            return fn

        return register(handler) if handler is not None else register

    def unregister_rpc_method(self, method: str) -> None:
        self.rpc_handlers.pop(method, None)

    def sent_on(self, topic: str) -> list[str]:
        return [text for text, t in self.sent if t == topic]


class FakeRoom(rtc.Room):
    def __init__(self, name: str = "concierge-test") -> None:
        super().__init__()
        self._fake_name = name
        self._fake_participant = FakeLocalParticipant()

    @property
    def name(self) -> str:
        return self._fake_name

    @property
    def local_participant(self) -> FakeLocalParticipant:  # type: ignore[override]
        return self._fake_participant
