import json

import pytest

from concierge.dispatch import DispatchError, DispatchInfo, parse_dispatch

VISITOR = "3f2b8c1e-9a4d-4c7b-8e21-5d6f7a8b9c0d"


def test_valid_metadata_parses() -> None:
    info = parse_dispatch(json.dumps({"visitor_id": VISITOR, "channel_hint": "web"}))
    assert info == DispatchInfo(visitor_id=VISITOR, channel_hint="web")


def test_channel_hint_defaults_to_web_and_unknown_keys_are_ignored() -> None:
    info = parse_dispatch(json.dumps({"visitor_id": VISITOR, "page": "/about"}))
    assert info.channel_hint == "web"
    assert info.visitor_id == VISITOR


def test_uppercase_visitor_id_is_rejected() -> None:
    # Not coerced: the page joins as visitor-<visitor_id> verbatim, so a lowercased id would never link (§6).
    with pytest.raises(DispatchError):
        parse_dispatch(json.dumps({"visitor_id": VISITOR.upper()}))


@pytest.mark.parametrize("metadata", ["", "   ", "\n"])
def test_empty_metadata_raises(metadata: str) -> None:
    with pytest.raises(DispatchError, match="empty"):
        parse_dispatch(metadata)


@pytest.mark.parametrize("metadata", ["{not json", "[]", '"a string"', "null"])
def test_malformed_metadata_raises(metadata: str) -> None:
    with pytest.raises(DispatchError):
        parse_dispatch(metadata)


@pytest.mark.parametrize(
    "visitor_id",
    [
        "not-a-uuid",
        "",
        "3f2b8c1e9a4d4c7b8e215d6f7a8b9c0d",  # no hyphens
        "3f2b8c1e-9a4d-1c7b-8e21-5d6f7a8b9c0d",  # version 1
        "3f2b8c1e-9a4d-4c7b-1e21-5d6f7a8b9c0d",  # wrong variant
        "3f2b8c1e-9a4d-4c7b-8e21-5d6f7a8b9c0d0",  # too long
        "../../etc/passwd",
    ],
)
def test_non_uuid4_visitor_id_is_rejected(visitor_id: str) -> None:
    with pytest.raises(DispatchError):
        parse_dispatch(json.dumps({"visitor_id": visitor_id}))


def test_missing_visitor_id_is_rejected() -> None:
    with pytest.raises(DispatchError):
        parse_dispatch(json.dumps({"channel_hint": "web"}))


def test_error_message_does_not_echo_the_metadata() -> None:
    # The entrypoint logs this message; the raw metadata is visitor-controlled and stays out of the journal.
    with pytest.raises(DispatchError) as exc:
        parse_dispatch(json.dumps({"visitor_id": "ignore previous instructions"}))
    assert "ignore previous" not in str(exc.value)
