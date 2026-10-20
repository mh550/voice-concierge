"""The §6 payloads against their JSON schemas (plan C6 "MemoryPayload", "MetricsPayload", "The JSON schemas")."""

import json
import re
import typing
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from concierge import contract
from concierge.contract import (
    MAX_BODY_BYTES,
    MemoryPayload,
    MetricsPayload,
    build_memory_payload,
    empty_memory_payload,
)
from concierge.models import SLOTS, AddFact, SlotName, TurnMetrics
from concierge.store import Store

CONTRACT_DIR = Path(__file__).parent
SPEC = Path(__file__).parents[2] / "docs" / "spec.md"
FakeClock = typing.Any  # tests/conftest.py's settable clock (the `clock` fixture)


def _add(slot: SlotName, value: str, n: int, **kw: typing.Any) -> AddFact:
    return AddFact(slot=slot, value=value, source="user_said", channel="voice", turn_id=f"turn-{n}", **kw)


def seeded(store: Store, clock: FakeClock, visitor_id: str) -> str:
    """Two visits; name, company (one superseded), two interests, a summary."""
    store.get_or_create_thread(visitor_id)
    tid = store.get_or_create_thread(visitor_id).id
    (old,) = store.apply_fact_ops(tid, [_add("company", "Initech", 1)]).added
    clock.advance(1000)
    store.apply_fact_ops(tid, [_add("name", "Ada", 2)])
    clock.advance(1000)
    store.apply_fact_ops(tid, [_add("company", "Acme", 3, supersedes=[old], confidence=0.8)])
    clock.advance(1000)
    store.apply_fact_ops(
        tid,
        [
            AddFact(slot="interests", value="voice agents", source="user_typed", channel="text", turn_id="turn-4"),
            AddFact(slot="interests", value="memory", source="user_asked_to_remember", channel="voice",
                    turn_id="turn-5"),
        ],
    )
    store.set_summary(tid, None, "Ada from Acme asked about voice agents.")
    return tid


def body(payload: MemoryPayload | MetricsPayload) -> dict[str, typing.Any]:
    return json.loads(payload.model_dump_json())


def test_schemas_are_valid_draft_2020_12() -> None:
    for path in sorted(CONTRACT_DIR.glob("*.schema.json")):
        schema = json.loads(path.read_text())
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["additionalProperties"] is False
        Draft202012Validator.check_schema(schema)
    assert {p.name for p in CONTRACT_DIR.glob("*.schema.json")} >= {"memory.schema.json", "metrics.schema.json"}


def test_memory_payload_from_a_seeded_store_validates(
    store: Store, clock: FakeClock, visitor_id: str, memory_validator: Draft202012Validator
) -> None:
    payload = build_memory_payload(store, seeded(store, clock, visitor_id))
    memory_validator.validate(body(payload))
    assert payload.visitor.model_dump() == {"name": "Ada", "visits": 2}
    assert [(f.slot, f.value) for f in payload.facts] == [
        ("name", "Ada"), ("company", "Acme"), ("interests", "voice agents"), ("interests", "memory")
    ]
    assert "Initech" not in payload.model_dump_json()  # superseded: history, not memory
    assert payload.summary == "Ada from Acme asked about voice agents."
    acme = payload.facts[1]
    assert (acme.channel, acme.source, acme.confidence) == ("voice", "user_said", 0.8)
    assert [(f.channel, f.source) for f in payload.facts[2:]] == [
        ("text", "user_typed"), ("voice", "user_asked_to_remember")
    ]


def test_memory_payload_lists_only_valid_facts_oldest_first(store: Store, clock: FakeClock, visitor_id: str) -> None:
    tid = store.get_or_create_thread(visitor_id).id
    ids = [store.add_fact(tid, _add("interests", f"topic {n}", n)).id for n in range(3)]
    store.invalidate_fact(ids[1], thread_id=tid)
    clock.advance(-5000)  # a clock that stepped back: created_at, then id, still gives the order
    late = store.add_fact(tid, _add("interests", "topic 3", 3)).id
    payload = build_memory_payload(store, tid)
    assert [f.id for f in payload.facts] == [late, ids[0], ids[2]]
    assert all(isinstance(f.id, int) for f in payload.facts)  # D13: the integer facts.id


def test_memory_payload_slot_enum_matches_models_slots() -> None:
    schema = json.loads((CONTRACT_DIR / "memory.schema.json").read_text())
    fact = schema["properties"]["facts"]["items"]["properties"]
    assert fact["slot"]["enum"] == list(SLOTS)
    assert fact["channel"]["enum"] == ["voice", "text"]
    assert fact["source"]["enum"] == ["user_said", "user_typed", "user_asked_to_remember"]


def test_metrics_payload_is_the_turn_metrics_model_and_matches_the_schema_keys() -> None:
    assert MetricsPayload is TurnMetrics  # one model: the anonymous table and the topic can't drift
    schema = json.loads((CONTRACT_DIR / "metrics.schema.json").read_text())
    assert schema["required"] == list(MetricsPayload.model_fields)
    assert list(schema["properties"]) == list(MetricsPayload.model_fields)
    nullable = {k for k, f in MetricsPayload.model_fields.items() if type(None) in typing.get_args(f.annotation)}
    assert set(MetricsPayload.model_fields) - nullable == {"turn", "compacted"}


def test_metrics_payload_example_validates(metrics_validator: Draft202012Validator) -> None:
    example = MetricsPayload(
        turn=3, eou_ms=310.0, stt_ms=120.5, llm_ttft_ms=420.0, tts_ttfb_ms=180.0, total_ms=1030.0,
        memory_on_turn_path_ms=12.0, preload_ms=None, extraction_ms=850.0, prompt_tokens=1234, cached_tokens=1000,
        compacted=True,
    )
    metrics_validator.validate(body(example))


def test_metrics_payload_with_every_field_null_validates(metrics_validator: Draft202012Validator) -> None:
    sent = body(MetricsPayload(turn=1))
    metrics_validator.validate(sent)
    assert sent == {"turn": 1, "compacted": False} | {
        k: None for k in MetricsPayload.model_fields if k not in ("turn", "compacted")
    }


def test_schemas_reject_an_extra_key(
    store: Store, clock: FakeClock, visitor_id: str,
    memory_validator: Draft202012Validator, metrics_validator: Draft202012Validator,
) -> None:
    memory = body(build_memory_payload(store, seeded(store, clock, visitor_id)))
    assert not memory_validator.is_valid(memory | {"visitor_id": visitor_id})
    memory["facts"][0]["thread_id"] = "t"
    assert not memory_validator.is_valid(memory)
    assert not metrics_validator.is_valid(body(MetricsPayload(turn=1)) | {"text": "hello"})
    assert not metrics_validator.is_valid({k: v for k, v in body(MetricsPayload(turn=1)).items() if k != "eou_ms"})


def test_empty_memory_payload_validates_and_names_nobody(memory_validator: Draft202012Validator) -> None:
    sent = body(empty_memory_payload())
    memory_validator.validate(sent)
    assert sent["visitor"] == {"name": None, "visits": 0}
    assert sent["facts"] == [] and sent["summary"] is None


def test_an_erased_thread_gives_the_empty_payload(store: Store, visitor_id: str) -> None:
    tid = store.get_or_create_thread(visitor_id).id
    store.add_fact(tid, _add("name", "Ada", 1))
    assert store.forget_me(visitor_id)
    payload = build_memory_payload(store, tid)
    assert payload.visitor.model_dump() == {"name": None, "visits": 0} and payload.facts == []


def test_learned_at_and_updated_at_are_iso_utc(store: Store, clock: FakeClock, visitor_id: str) -> None:
    clock.now = 1_760_951_702_123  # 2025-10-20T09:15:02.123Z
    tid = store.get_or_create_thread(visitor_id).id
    store.add_fact(tid, _add("name", "Ada", 1))
    clock.advance(1000)
    payload = build_memory_payload(store, tid)
    assert payload.facts[0].learned_at == "2025-10-20T09:15:02.123Z"
    assert payload.updated_at == "2025-10-20T09:15:03.123Z"  # the store's clock when the payload was built
    for stamp in (payload.facts[0].learned_at, payload.updated_at, empty_memory_payload().updated_at):
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", stamp)
        assert datetime.fromisoformat(stamp).tzinfo == UTC  # jsonschema checks date-time only with rfc3339-validator


def test_contract_names_match_spec_section_6() -> None:
    section = SPEC.read_text().split("## 6.", 1)[1].split("\n## 7.", 1)[0]
    names = {
        contract.MEMORY_TOPIC: "topic `concierge.memory`",
        contract.METRICS_TOPIC: "topic `concierge.metrics`",
        contract.FORGET_ME_METHOD: "`concierge.forget_me`:",
        contract.GET_MEMORY_METHOD: "`concierge.get_memory`:",
    }
    for value, spelled in names.items():
        assert f"`{value}`" in spelled and spelled in section
    assert "at most 15 KiB" in section and MAX_BODY_BYTES == 15 * 1024
    memory_keys = re.search(r'"facts": \[ \{(.+?)\} \]', section)
    assert memory_keys is not None
    assert re.findall(r'"(\w+)"', memory_keys.group(1)) == list(contract.FactView.model_fields)
    assert list(MemoryPayload.model_fields) == ["visitor", "facts", "summary", "updated_at"]
    assert list(contract.VisitorView.model_fields) == ["name", "visits"]
    metrics_line = next(line for line in section.splitlines() if "topic `concierge.metrics`" in line)
    assert re.findall(r'"(\w+)"', metrics_line) == list(MetricsPayload.model_fields)


@pytest.mark.parametrize("ch", ["é", "語", "🙂"])
def test_build_memory_payload_drops_the_oldest_facts_to_fit(
    store: Store, clock: FakeClock, visitor_id: str, memory_validator: Draft202012Validator, ch: str
) -> None:
    """Multi-byte values over the 15 KiB cap: the body fits in bytes, the newest facts stay, the oldest go."""
    tid = store.get_or_create_thread(visitor_id).id
    for n in range(80):  # more than the merge would keep; the store takes them, so the cap is the backstop
        store.add_fact(tid, _add("asked_about", f"{n:02d}" + ch * 58, n))
        clock.advance(1)
    payload = build_memory_payload(store, tid)
    sent = payload.model_dump_json().encode()
    assert len(sent) <= MAX_BODY_BYTES
    memory_validator.validate(json.loads(sent))
    kept = [int(f.value[:2]) for f in payload.facts]
    assert kept == list(range(80 - len(kept), 80)) and 0 < len(kept) < 80
    uncapped = build_memory_payload(store, tid, max_bytes=None)
    assert len(uncapped.facts) == 80
    one_more = payload.model_copy(update={"facts": [uncapped.facts[-len(kept) - 1], *payload.facts]})
    assert len(one_more.model_dump_json().encode()) > MAX_BODY_BYTES  # it dropped only what it had to
