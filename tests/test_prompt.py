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
    assert "only from the knowledge pack" in text
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


def test_memory_block_cap() -> None:
    assert MEMORY_BLOCK_MAX_CHARS == 1500
    pack = load_pack()
    ok = _memory_block(1500)
    assert len(ok) == 1500
    assert build_instructions(pack, ok).endswith(ok)
    with pytest.raises(ValueError, match="1501"):
        build_instructions(pack, _memory_block(1501))
