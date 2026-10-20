"""The contract with the web page (spec §6, shared word for word with the portfolio spec; plan C6 Part 1).

The topic and RPC method names, the 15 KiB body cap and the two topic payloads. Nothing else in `concierge/` spells
these names. Field types §6 leaves open are D13 *default*: fact `id` is the integer `facts.id`, times are ISO-8601 UTC
strings with milliseconds and a `Z`, and every `concierge.metrics` key is always present (`null` when unreported).
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from concierge.models import Channel, Fact, SlotName, Source, TurnMetrics
from concierge.store import Store, ThreadMissing, now_ms

MEMORY_TOPIC = "concierge.memory"
METRICS_TOPIC = "concierge.metrics"
FORGET_ME_METHOD = "concierge.forget_me"
GET_MEMORY_METHOD = "concierge.get_memory"
MAX_BODY_BYTES = 15 * 1024  # §6 "at most 15 KiB", counted in UTF-8 bytes (LiveKit's RPC payload limit too)

MetricsPayload = TurnMetrics  # one model, so the anonymous table and the topic can't drift


class VisitorView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None
    visits: int = Field(ge=0)


class FactView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    slot: SlotName
    value: str
    channel: Channel
    source: Source
    learned_at: str
    confidence: float = Field(ge=0, le=1)


class MemoryPayload(BaseModel):
    """`concierge.memory`, and the `concierge.get_memory` response."""

    model_config = ConfigDict(extra="forbid")

    visitor: VisitorView
    facts: list[FactView]
    summary: str | None
    updated_at: str


def iso_utc(ms: int) -> str:
    """Epoch milliseconds as `2026-10-20T09:15:02.123Z`."""
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _fact_view(fact: Fact) -> FactView:
    return FactView(
        id=fact.id, slot=fact.slot, value=fact.value, channel=fact.channel, source=fact.source,
        learned_at=iso_utc(fact.created_at), confidence=fact.confidence,
    )


def empty_memory_payload() -> MemoryPayload:
    """Nobody: after "Forget me", and for a session without memory."""
    return MemoryPayload(visitor=VisitorView(name=None, visits=0), facts=[], summary=None, updated_at=iso_utc(now_ms()))


def body_bytes(payload: BaseModel) -> int:
    return len(payload.model_dump_json().encode())


def build_memory_payload(store: Store, thread_id: str, *, max_bytes: int | None = MAX_BODY_BYTES) -> MemoryPayload:
    """The thread's memory as the page shows it: the valid facts only (superseded and invalidated ones are history),
    oldest first by (created_at, id). Over `max_bytes` the oldest facts are dropped until the JSON body fits. An erased
    thread gives `empty_memory_payload()`. Blocks on the store: call it on the writer's thread or in a thread."""
    try:
        thread, snapshot, now = store.memory_view(thread_id)
    except ThreadMissing:
        return empty_memory_payload()
    facts = sorted(snapshot.facts, key=lambda f: (f.created_at, f.id))
    payload = MemoryPayload(
        visitor=VisitorView(name=snapshot.state.name, visits=thread.visits),
        facts=[_fact_view(f) for f in facts],
        summary=snapshot.state.last_visit_summary,
        updated_at=iso_utc(now),
    )
    if max_bytes is None or body_bytes(payload) <= max_bytes:
        return payload
    # One pass instead of a re-dump per dropped fact: each fact costs its JSON plus a comma.
    excess = body_bytes(payload) - max_bytes
    drop = 0
    while excess > 0 and drop < len(payload.facts):
        excess -= len(payload.facts[drop].model_dump_json().encode()) + 1
        drop += 1
    return payload.model_copy(update={"facts": payload.facts[drop:]})
