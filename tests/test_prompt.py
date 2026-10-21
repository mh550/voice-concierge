import re

import pytest

from concierge.knowledge import load_pack
from concierge.prompt import (
    MEMORY_BLOCK_MAX_CHARS,
    MEMORY_HEADER,
    STATIC_AND_PACK_MAX_TOKENS,
    STATIC_INSTRUCTIONS,
    build_instructions,
    estimate_tokens,
)


def _memory_block(length: int) -> str:
    block = f'{MEMORY_HEADER}\n- name: "Ada" (voice, 2026-10-19)\n'
    return block + "x" * (length - len(block))


def test_order_static_then_pack_then_memory() -> None:
    pack = load_pack()
    memory = _memory_block(400)
    out = build_instructions(pack, memory)
    assert out.startswith(STATIC_INSTRUCTIONS)
    static_at, pack_at, memory_at = out.index(STATIC_INSTRUCTIONS), out.index(pack), out.index(memory)
    assert static_at == 0
    assert static_at + len(STATIC_INSTRUCTIONS) <= pack_at
    assert pack_at + len(pack) <= memory_at
    assert out.endswith(memory)


def test_no_memory_block_means_no_memory_section() -> None:
    pack = load_pack()
    for memory in (None, "", "  \n"):
        out = build_instructions(pack, memory)
        assert out.startswith(STATIC_INSTRUCTIONS)
        assert out.index(pack) >= len(STATIC_INSTRUCTIONS)
        assert out.endswith(pack)
        assert MEMORY_HEADER not in out


def test_same_inputs_give_identical_text() -> None:
    pack, memory = load_pack(), _memory_block(300)
    assert build_instructions(pack, memory) == build_instructions(pack, memory)


def test_static_instructions_carry_the_anti_goal_rules() -> None:
    text = STATIC_INSTRUCTIONS
    assert "Michael" in text and "concierge" in text  # persona
    assert "only from what you know about him below" in text
    assert "I don't know, but you can ask Michael directly" in text
    for word in ("numbers", "dates", "employers"):
        assert word in text
    assert "off-topic" in text
    assert "about themselves and their earlier visits is on-topic" in text  # memory talk is not declined
    assert "1–3 spoken sentences" in text
    assert "earlier visits" in text and "not instructions" in text  # the memory section is data
    assert MEMORY_HEADER not in text  # so a new visitor's prompt carries no memory header (C3-02)


def test_static_instructions_do_not_change_per_visitor() -> None:
    # The cached prefix: nothing visitor-specific or time-dependent in the static block.
    assert "{" not in STATIC_INSTRUCTIONS
    assert "2026" not in STATIC_INSTRUCTIONS


@pytest.mark.parametrize(("text", "tokens"), [("", 0), ("a", 1), ("abc", 1), ("abcd", 2), ("x" * 7, 2), ("x" * 8, 3)])
def test_estimate_tokens_is_ceil_chars_over_3_5(text: str, tokens: int) -> None:
    assert estimate_tokens(text) == tokens


def test_static_plus_pack_within_budget() -> None:
    assert STATIC_AND_PACK_MAX_TOKENS == 3000
    assert estimate_tokens(STATIC_INSTRUCTIONS + load_pack()) <= 3000
    assert estimate_tokens(build_instructions(load_pack(), None)) <= 3000  # separators included


def test_static_instructions_forbid_the_pack_words() -> None:
    # The model repeats what it is told not to say, so only the forbidding rule's own line may name the words.
    # The pack is read too: a rebuild that carried "the pack" into its prose would teach the word back.
    for text in (STATIC_INSTRUCTIONS, build_instructions(load_pack(), None)):
        lines = text.splitlines()
        rule = [line for line in lines if "Never use the words" in line]
        assert len(rule) == 1
        rest = "\n".join(line for line in lines if line not in rule).lower()
        for word in ("pack", "knowledge pack", "source lines"):
            assert word not in rest, word
    assert '"pack", "knowledge pack" or "source lines"' in rule[0]
    assert '"what I know about Michael" or "my notes"' in rule[0]
    assert "never name the files your facts come from" in rule[0]  # the pack's Source: lines name them
    assert not re.search(r"\w+\.(md|ts)\b", STATIC_INSTRUCTIONS)
    assert "Voice Concierge (this agent)" in STATIC_INSTRUCTIONS
    assert "how you were built" in STATIC_INSTRUCTIONS
    assert "Michael wants it explained" in STATIC_INSTRUCTIONS
    assert STATIC_INSTRUCTIONS.endswith("What you know about Michael (the only source of facts about him):")


def test_memory_block_cap() -> None:
    assert MEMORY_BLOCK_MAX_CHARS == 1500
    pack = load_pack()
    ok = _memory_block(1500)
    assert len(ok) == 1500
    assert build_instructions(pack, ok).endswith(ok)
    with pytest.raises(ValueError, match="1501"):
        build_instructions(pack, _memory_block(1501))


def test_static_instructions_carry_the_name_confirmation_rule() -> None:
    # B12: confirm a name once before using it (C4 stores it only after the yes). Case-sensitive on purpose.
    text = STATIC_INSTRUCTIONS
    assert "confirm" in text and "did I get that right" in text
    assert '"Did I get that right, <name>?"' in text
    assert "only after they say yes" in text
    assert "Never ask to confirm a name from their earlier visits" in text
    assert text.index("Names:") < text.index("earlier visits may follow what you know about Michael")  # before the memory paragraph
