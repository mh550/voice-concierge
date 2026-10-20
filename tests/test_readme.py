"""The README's 'Mapping onto Agents 2.0' table (spec §8, C2-05)."""

from pathlib import Path

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
