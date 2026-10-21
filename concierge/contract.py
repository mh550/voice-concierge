"""The contract with the web page (spec §6, shared word for word with the portfolio spec; plan C6 Part 1).

The topic and RPC method names, the 15 KiB body cap and the two topic payloads. Nothing else in `concierge/` spells
these names. Field types §6 leaves open are D13 *default*: fact `id` is the integer `facts.id`, times are ISO-8601 UTC
strings with milliseconds and a `Z`, and every `concierge.metrics` key is always present (`null` when unreported).

Contract v2 (spec 2026-10-21 §2, plan `docs/plans/2026-10-21-V2-contract-v2.md`) adds the optional keys `v`,
`about_visitor`, `about_agent` and `retention_days` after the v1 ones: a v1 page reads a v2 body and a v2 page reads a
v1 body. Inside a v2 object every key is required; a v2 key left at the model's default dumps as null, which the
schema reads as "not reported" (D17 (i)).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from itertools import islice
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from concierge.models import Channel, Fact, SlotName, Source, TurnMetrics, VisitEpisode
from concierge.store import Store, ThreadMissing, now_ms

MEMORY_TOPIC = "concierge.memory"
METRICS_TOPIC = "concierge.metrics"
FORGET_ME_METHOD = "concierge.forget_me"
GET_MEMORY_METHOD = "concierge.get_memory"
MAX_BODY_BYTES = 15 * 1024  # §6 "at most 15 KiB", counted in UTF-8 bytes (LiveKit's RPC payload limit too)
RETENTION_DAYS = 30  # §2 "retention_days": 30, the B6 idle TTL (Settings.idle_ttl_days; a test keeps them equal)
MAX_EPISODES = 5  # §2: newest first, at most 5
MAX_EVENTS = 12  # §2: this session only, newest first, at most 12

EventType = Literal[
    "fact_added", "fact_invalidated", "fact_deleted", "gate_rejected", "extraction_ran", "remember", "forget"
]

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


class Episode(BaseModel):
    """One visit; the current one has `ended_at` and `summary` null until the session ends (D17 (b), (c))."""

    model_config = ConfigDict(extra="forbid")

    visit: int
    started_at: str
    ended_at: str | None
    summary: str | None


class MemoryEvent(BaseModel):
    """One line of this session's memory work: a short plain sentence, no instruction text, no URL (D17 (a))."""

    model_config = ConfigDict(extra="forbid")

    ts: str
    type: EventType
    detail: str = Field(max_length=120)


class AboutVisitor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: list[FactView]  # the valid facts: the same list as `facts`
    episodes: list[Episode] = Field(max_length=MAX_EPISODES)
    events: list[MemoryEvent] = Field(max_length=MAX_EVENTS)


class Knowledge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    words: int = Field(ge=0)
    est_tokens: int = Field(ge=0)
    sources_commit: str
    sections: list[str]


class Working(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: int = Field(ge=0)
    est_tokens: int = Field(ge=0)
    compacted: bool
    compactions: int = Field(ge=0)


class Cache(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cached_share: float | None = Field(ge=0, le=1)


class AboutAgent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    knowledge: Knowledge
    instructions_est_tokens: int = Field(ge=0)
    memory_block_chars: int | None = Field(ge=0)
    working: Working
    cache: Cache


class MemoryPayload(BaseModel):
    """`concierge.memory`, and the `concierge.get_memory` response: the v1 keys, then the optional v2 ones."""

    model_config = ConfigDict(extra="forbid")

    visitor: VisitorView
    facts: list[FactView]
    summary: str | None
    updated_at: str
    v: Literal[2] | None = None
    about_visitor: AboutVisitor | None = None
    about_agent: AboutAgent | None = None
    retention_days: int | None = Field(default=None, ge=1)


def iso_utc(ms: int) -> str:
    """Epoch milliseconds as `2026-10-20T09:15:02.123Z`."""
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _fact_view(fact: Fact) -> FactView:
    return FactView(
        id=fact.id, slot=fact.slot, value=fact.value, channel=fact.channel, source=fact.source,
        learned_at=iso_utc(fact.created_at), confidence=fact.confidence,
    )


def _episode(row: VisitEpisode) -> Episode:
    return Episode(
        visit=row.visit, started_at=iso_utc(row.started_at),
        ended_at=None if row.ended_at is None else iso_utc(row.ended_at), summary=row.summary,
    )


def empty_memory_payload() -> MemoryPayload:
    """Nobody: after "Forget me", and for a session without memory. A v2 body with nothing in it (D17 (g))."""
    return MemoryPayload(
        visitor=VisitorView(name=None, visits=0), facts=[], summary=None, updated_at=iso_utc(now_ms()), v=2,
        about_visitor=AboutVisitor(profile=[], episodes=[], events=[]), retention_days=RETENTION_DAYS,
    )


def body_bytes(payload: BaseModel) -> int:
    return len(payload.model_dump_json().encode())


def build_memory_payload(
    store: Store,
    thread_id: str,
    *,
    max_bytes: int | None = MAX_BODY_BYTES,
    about_agent: AboutAgent | None = None,
    events: Iterable[MemoryEvent] = (),
) -> MemoryPayload:
    """The thread's memory as the page shows it: the valid facts only (superseded and invalidated ones are history),
    oldest first by (created_at, id), repeated as `about_visitor.profile`; the newest 5 visits as `episodes` (V2-03,
    read right after the view on the same thread: an erase in between leaves none); `events` (newest first, the ring)
    keeps its newest 12; `about_agent` stays null when none is given. Over `max_bytes` the oldest facts are dropped,
    from `facts` and `profile` together, until the JSON body fits. An erased thread gives `empty_memory_payload()`.
    Blocks on the store: call it on the writer's thread or in a thread."""
    try:
        thread, snapshot, now = store.memory_view(thread_id)
    except ThreadMissing:
        return empty_memory_payload()
    facts = [_fact_view(f) for f in sorted(snapshot.facts, key=lambda f: (f.created_at, f.id))]
    episodes = [_episode(row) for row in store.visit_episodes(thread_id, limit=MAX_EPISODES)]
    about = AboutVisitor(profile=facts, episodes=episodes, events=list(islice(events, MAX_EVENTS)))
    payload = MemoryPayload(
        visitor=VisitorView(name=snapshot.state.name, visits=thread.visits),
        facts=facts,
        summary=snapshot.state.last_visit_summary,
        updated_at=iso_utc(now),
        v=2,
        about_visitor=about,
        about_agent=about_agent,
        retention_days=RETENTION_DAYS,
    )
    if max_bytes is None or body_bytes(payload) <= max_bytes:
        return payload
    # One pass instead of a re-dump per dropped fact: each fact costs its JSON plus a comma, twice (facts, profile).
    excess = body_bytes(payload) - max_bytes
    drop = 0
    while excess > 0 and drop < len(facts):
        excess -= 2 * (len(facts[drop].model_dump_json().encode()) + 1)
        drop += 1
    kept = facts[drop:]
    return payload.model_copy(update={"facts": kept, "about_visitor": about.model_copy(update={"profile": list(kept)})})
