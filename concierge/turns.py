"""A conversation turn as the extractor and the merge see it (plan C4 "Heard text").

`turn_from_message` builds one from LiveKit's ChatMessage. livekit-agents 1.8.8 already records an interrupted reply's
content as the text that was played (`_ForwardOutput.forwarded_text`, the synchronized transcript:
voice/agent_activity.py:3905-3936, voice/generation.py:708-716), and never adds a reply nobody heard. So for an
interrupted message the recorded content *is* the heard text. The extractor and the merge read a turn only through
`visible_text`: an interrupted agent turn shows what the visitor heard, never what was generated.
"""

from __future__ import annotations

from typing import Literal

from livekit.agents import llm
from pydantic import BaseModel, ConfigDict

from concierge.models import Channel, Note


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


def turn_from_message(msg: llm.ChatMessage, channel: Channel = "voice") -> Turn | None:
    """The Turn for a user or assistant message (None for other roles and for empty text).

    `channel` is the user turn's door: ChannelTags.channel_of(msg.text_content), on the unstripped text (it matches the
    typed text exactly); agent turns are always "voice". `text_content` strips
    LiveKit's `<expr/>` markup from assistant messages. A transcript confidence of 1.0 (the STT gave none) or None
    (typed) is not kept."""
    text = (msg.text_content or "").strip()
    if not text:
        return None
    if msg.role == "user":
        confidence = msg.transcript_confidence
        low = confidence if confidence is not None and confidence < 1.0 else None
        return Turn(turn_id=msg.id, role="user", text=text, channel=channel, confidence=low)
    if msg.role == "assistant":
        heard = text if msg.interrupted else None  # 1.8 recorded only what played (module docstring)
        return Turn(
            turn_id=msg.id, role="agent", text=text, channel="voice", interrupted=msg.interrupted, heard_text=heard
        )
    return None


def journal_note(turn: Turn) -> Note:
    """The journal row for a turn: an agent turn keeps only what was heard (spec §4.2)."""
    if turn.role == "user":
        payload = {"turn_id": turn.turn_id, "channel": turn.channel, "text": turn.text, "confidence": turn.confidence}
        return Note(type="user_turn", payload=payload)
    return Note(type="agent_turn", payload={"turn_id": turn.turn_id, "interrupted": turn.interrupted,
                                            "text": visible_text(turn)})
