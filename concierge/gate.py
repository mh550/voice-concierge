"""The write gate (spec §4.4 "Write gate", §4.0 "Memory as an attack surface"; plan C4 "The write gate").

A value the extractor proposes is data the visitor controls, and the memory block puts it back in front of the model
next visit. The gate keeps out what reads as an instruction, a link, contact details, a secret or code, and anything
over the slot's cap. Pure, no I/O. The content rules run before the cap, so a long injection is an `instruction`.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict

from concierge.models import _UNSAFE_CATEGORIES, SLOTS, SlotName, Source

GateReason = Literal[
    "agent_attributed", "empty", "unsafe_chars", "instruction", "email", "url", "phone", "secret", "code", "too_long"
]


class GateResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: bool
    reason: GateReason | None = None


_I = re.IGNORECASE


def _compile(flags: int, *patterns: str) -> list[re.Pattern[str]]:
    return [re.compile(p, flags) for p in patterns]


# Checked in this order; the first rule that matches is the reason. `email` before `url`, so an address is `email`.
_RULES: list[tuple[GateReason, list[re.Pattern[str]]]] = [
    ("instruction", _compile(
        _I,
        r"\bignore\b.{0,40}\b(previous|prior|above|earlier|all|your|the|before|everything|instead)\b",
        r"\bdisregard\b",
        r"\byou\s+are\s+now\b",
        r"\b(system|assistant|developer|user)\s*:",
        r"\b(new|updated)\s+instructions?\b",
        r"\b(forget|override)\b.{0,30}\b(instructions?|rules?|prompt)\b",
        r"\b(pretend|act)\s+(to\s+be|as|like)\b",
        r"\bfrom\s+now\s+on\b",
        r"\b(always|never)\s+(say|tell|call|respond|answer|reply|mention)\b",
        r"\b(respond|reply|answer|speak)\s+only\b",
        r"<\s*/?\s*(system|instructions?)\b",
    )),
    # Written, and as STT writes a spoken address without smart formatting ("ada at gmail dot com").
    ("email", _compile(_I, r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", r"\b\w+\s+at\s+\w+(?:\s+dot\s+\w+)+\b")),
    ("url", _compile(
        _I,
        r"\b(?:https?|ftp)://\S+",
        r"\bwww\.\S+",
        # The lookbehind keeps an email's domain out of this rule, so purpose="contact" can pass an email.
        r"(?<![@.\w-])[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|io|dev|ai|app|co|xyz|info|me|example)\b",
    )),
    # 9+ digits, up to two separators between them ("(555) 123-4567"), so "2019-2024" passes.
    ("phone", _compile(_I, r"\+?\d(?:[\s().-]{0,2}\d){8,}")),
    # Case-sensitive token prefixes with a separator and a digit, so "skateboarding" and "Skyscanner" pass.
    ("secret", _compile(
        0,
        r"\b(?:sk|pk|rk|ghp|gho|ghs|xox[abprs]|AIza)[-_](?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{6,}",
        r"\bAKIA[0-9A-Z]{16}\b",
    )),
    ("secret", _compile(
        _I,
        r"\bmy\s+(?:api\s+)?(?:key|token|password|passwd|secret|pin)\s+(?:is|was)\b",
        r"\b(?:password|passwd|api[\s_-]?key|token|secret)\s*[:=]",
        r"\bbearer\s+\S{8,}",
        # A long mixed run with no separators: "gpt-4o-realtime-preview" and "eleven_multilingual_v2" pass.
        r"\b(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{20,}\b",
    )),
    ("code", _compile(
        _I,
        r"```",
        r"`[^`]+`",
        r";\s*(?:drop|select|insert|delete|update|exec|rm|curl)\b",
        r"\b(?:def|function|class)\s+\w+\s*(?:\([^)]*\)\s*)?[:{]",  # "function calling (tool use)" passes
        r"\b(?:import|from)\s+\w+(?:\s+import\b|;)",
        r"\blambda\b\s*\w*\s*:",
        r"<\s*script\b",
        r"\$\(",
        r"\{\{",
        r"=>",
        r"\b\w+\([^)]*\)\s*[:{;]",
    )),
]
_CONTACT_EXEMPT: frozenset[GateReason] = frozenset({"email", "phone"})


def _reject(reason: GateReason) -> GateResult:
    return GateResult(ok=False, reason=reason)


def check_value(
    slot: SlotName,
    value: str,
    source: Source | Literal["agent"],
    *,
    purpose: Literal["fact", "contact"] = "fact",
) -> GateResult:
    """Whether `value` may be written. `purpose="contact"` lifts only the email and phone rules, and only for C8's
    `leave_message_for_michael` contact field; a fact never uses it."""
    if source == "agent":
        return _reject("agent_attributed")
    content = check_text(value, purpose=purpose)
    if not content.ok:
        return content
    if len(value.strip()) > SLOTS[slot].cap:
        return _reject("too_long")
    return GateResult(ok=True)


def check_text(value: str, *, purpose: Literal["fact", "contact"] = "fact") -> GateResult:
    """The content rules alone, without a slot's cap (C5's visit summary runs them too)."""
    stripped = value.strip()
    if not stripped:
        return _reject("empty")
    if any(unicodedata.category(ch) in _UNSAFE_CATEGORIES for ch in stripped):
        return _reject("unsafe_chars")
    # NFKC folds full-width letters and compatibility forms; collapsing whitespace defeats doubled spaces and tabs.
    normal = " ".join(unicodedata.normalize("NFKC", stripped).split())
    for reason, patterns in _RULES:
        if purpose == "contact" and reason in _CONTACT_EXEMPT:
            continue
        if any(p.search(normal) for p in patterns):
            return _reject(reason)
    return GateResult(ok=True)
