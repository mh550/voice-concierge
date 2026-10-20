"""Dispatch metadata (spec §6): the JSON the page's token route puts on the agent dispatch.

`{"visitor_id": "<uuid v4>", "channel_hint": "web"}`. The visitor id scopes every memory row (B2), so anything that
isn't a UUID4 is rejected rather than coerced. Error messages never echo the metadata: it is visitor-controlled and
the entrypoint logs the message.
"""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

UUID4_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


class DispatchError(ValueError):
    """The job's metadata can't identify a visitor; the entrypoint logs it and ends the job."""


class DispatchInfo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    visitor_id: str
    channel_hint: str = "web"

    @field_validator("visitor_id")
    @classmethod
    def _uuid4_shaped(cls, value: str) -> str:
        # Lowercase only, never coerced: the page joins as visitor-<visitor_id> verbatim (§6), and
        # crypto.randomUUID() is lowercase.
        if not UUID4_RE.match(value):
            raise ValueError("visitor_id is not a lowercase UUID4")
        return value


def parse_dispatch(metadata: str) -> DispatchInfo:
    if not metadata.strip():
        raise DispatchError("empty dispatch metadata")
    try:
        data = json.loads(metadata)
    except json.JSONDecodeError:
        raise DispatchError("dispatch metadata is not JSON") from None
    if not isinstance(data, dict):
        raise DispatchError("dispatch metadata is not a JSON object")
    try:
        return DispatchInfo.model_validate(data)
    except ValidationError as exc:
        fields = sorted({".".join(map(str, err["loc"])) for err in exc.errors()})
        raise DispatchError(f"invalid dispatch metadata field(s): {', '.join(fields)}") from None
