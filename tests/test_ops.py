"""The extractor's ops (plan C4 "The ops"): pydantic, discriminated on op; parse_ops keeps the good ones."""

import json

from concierge.ops import AddOp, DeleteOp, Dropped, OpArg, UpdateOp, parse_ops


def args(*ops: dict) -> str:
    return json.dumps({"ops": list(ops)})


def test_parse_ops_reads_add_update_delete() -> None:
    parsed = parse_ops(
        args(
            {"op": "ADD", "slot": "name", "value": " Ada ", "turn_id": "item_1", "confidence": 0.9},
            {"op": "UPDATE", "fact_id": 3, "value": "Initech", "turn_id": "item_2"},
            {"op": "DELETE", "fact_id": 4, "reason": "no_longer_true"},
        )
    )
    assert parsed.dropped == []
    add, update, delete = parsed.ops
    assert add == AddOp(op="ADD", slot="name", value="Ada", turn_id="item_1", confidence=0.9)
    assert isinstance(update, UpdateOp) and update.fact_id == 3 and update.slot is None
    assert isinstance(delete, DeleteOp) and delete.reason == "no_longer_true"


def test_parse_ops_accepts_a_dict() -> None:
    parsed = parse_ops({"ops": [{"op": "DELETE", "fact_id": 1}]})
    assert parsed.ops == [DeleteOp(op="DELETE", fact_id=1)]


def test_parse_ops_drops_a_malformed_op_and_keeps_the_rest() -> None:
    parsed = parse_ops(
        args(
            {"op": "ADD", "slot": "name", "turn_id": "item_1"},  # no value
            {"op": "ADD", "slot": "role", "value": "PM", "turn_id": "item_1"},
            {"op": "DELETE"},  # no fact_id
            "not an object",
            {"op": "DELETE", "fact_id": 2, "reason": "because I said so"},  # reason is an enum
            {"op": "ADD", "slot": "role", "value": "PM", "turn_id": "item_1", "confidence": 1.5},
        )
    )
    assert [op.value for op in parsed.ops] == ["PM"]
    assert [d.index for d in parsed.dropped] == [0, 2, 3, 4, 5]


def test_parse_ops_reports_dropped_by_error_type_only() -> None:
    secret = "Zelda Secretname"
    parsed = parse_ops(args({"op": "ADD", "slot": "name", "value": secret}))  # no turn_id
    assert parsed.dropped == [Dropped(index=0, error_type="missing")]
    assert secret not in parsed.model_dump_json()


def test_parse_ops_accepts_strict_nulls() -> None:
    nulls = {"slot": None, "value": None, "fact_id": None, "confidence": None, "turn_id": None, "reason": None}
    parsed = parse_ops(
        args(
            {**nulls, "op": "ADD", "slot": "interests", "value": "RAG", "turn_id": "item_1"},
            {**nulls, "op": "DELETE", "fact_id": 7},
        )
    )
    assert parsed.dropped == []
    assert parsed.ops[0].confidence is None and parsed.ops[1] == DeleteOp(op="DELETE", fact_id=7)


def test_parse_ops_without_an_ops_list_is_zero_ops() -> None:
    for raw in ("{}", '{"ops": "ADD"}', "not json", "[]", {"ops": None}):
        parsed = parse_ops(raw)
        assert parsed.ops == [] and [d.index for d in parsed.dropped] == [-1], raw


def test_noop_kind_is_dropped() -> None:
    parsed = parse_ops(args({"op": "NOOP"}, {"op": "add", "slot": "name", "value": "Ada", "turn_id": "item_1"}))
    assert parsed.ops == [] and [d.index for d in parsed.dropped] == [0, 1]


def test_an_unknown_slot_parses_for_the_merge_to_reject() -> None:
    # The merge journals it as gate_rejected/unknown_slot; dropping it here would leave no trace.
    parsed = parse_ops(args({"op": "ADD", "slot": "password", "value": "x", "turn_id": "item_1"}))
    assert parsed.dropped == [] and parsed.ops[0].slot == "password"


def test_op_arg_is_the_flat_wire_shape() -> None:
    schema = OpArg.model_json_schema()
    assert set(schema["properties"]) == {"op", "slot", "value", "fact_id", "confidence", "turn_id", "reason"}
    assert schema["required"] == ["op"]
