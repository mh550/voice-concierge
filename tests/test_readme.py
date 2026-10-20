"""The README's 'Mapping onto Agents 2.0' table (spec §8, C2-05)."""

import re
from pathlib import Path

import pytest

README = Path(__file__).resolve().parent.parent / "README.md"


def _mapping_section() -> str:
    text = README.read_text()
    assert "## Mapping onto Agents 2.0" in text
    section = text.split("## Mapping onto Agents 2.0", 1)[1]
    return section.split("\n## ", 1)[0]


def _first_cells() -> list[str]:
    rows = [line for line in _mapping_section().splitlines() if line.startswith("|")]
    return [row.split("|")[1].strip() for row in rows[2:]]


def test_mapping_table_has_thread_lane_state_journal_and_fence_rows() -> None:
    cells = _first_cells()
    for name in ("thread", "lane state", "journal"):
        assert any(cell.lower().startswith(name) for cell in cells), (name, cells)
    fence = [cell for cell in cells if cell.lower().startswith("fence")]
    assert fence, cells
    assert "BEGIN IMMEDIATE" in _mapping_section()
    assert "version" in _mapping_section()


def test_mapping_says_1_8_has_no_lease_so_sessions_can_interleave() -> None:
    section = " ".join(_mapping_section().split())
    assert "1.8 has no lease" in section
    assert "two live sessions for one visitor can interleave turns" in section


def _section(heading: str) -> str:
    text = README.read_text()
    assert f"## {heading}" in text
    return text.split(f"## {heading}", 1)[1].split("\n## ", 1)[0]


def _rows(section: str) -> dict[str, str]:
    """First cell -> last cell ('Proved by') of each body row."""
    rows = [line for line in section.splitlines() if line.startswith("|")][2:]
    return {row.split("|")[1].strip(): row.split("|")[-2].strip() for row in rows}


def _test_names() -> set[str]:
    tests = Path(__file__).resolve().parent
    pattern = re.compile(r"^(?:async )?def (test_\w+)", re.MULTILINE)
    return {name for path in tests.glob("test_*.py") for name in pattern.findall(path.read_text())}


@pytest.mark.parametrize(
    "practice",
    [
        "Just-in-time vs preload",
        "Stable, cached prefix",
        "Memory as an attack surface",
        "Hot path vs background writes",
        "Delta edits, not rewrites",
        "Temporal validity",
        "Only what was heard",
        "ASR errors",
        "Evaluate for harm as well as help",
    ],
)
def test_memory_design_row_names_tests_that_exist(practice: str) -> None:
    proved_by = _rows(_section("Memory design"))[practice]
    cited = re.findall(r"`(test_\w+)`", proved_by)
    assert cited, practice
    assert set(cited) <= _test_names(), set(cited) - _test_names()


def test_preload_row_says_when_it_would_change() -> None:
    row = " ".join(_section("Memory design").split())
    assert "large collection" in row and "just in time" in row
