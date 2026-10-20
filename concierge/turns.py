"""A conversation turn as the extractor and the merge see it (plan C4 "Heard text").

C4-03 builds these from LiveKit's ChatMessage (`turn_from_message`). The merge reads a turn only through
`visible_text`: an interrupted agent turn shows what the visitor heard, never what was generated.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from concierge.models import Channel


class Turn(BaseModel):
    model_config = ConfigDict(frozen=True)

    turn_id: str  # ChatMessage.id; facts cite it
    role: Literal["user", "agent"]
    text: str  # what was generated (for a live interrupted message: equal to heard_text)
    channel: Channel  # user turns: the door it came through; agent turns: "voice"
    interrupted: bool = False
    heard_text: str | None = None  # set only when interrupted
    confidence: float | None = None  # user turns: the STT's transcript confidence, kept only below 1.0


def visible_text(turn: Turn) -> str:
    """What the other side saw or heard: an interrupted turn shows only its heard text (none: nothing)."""
    if turn.interrupted:
        return turn.heard_text or ""
    return turn.text
