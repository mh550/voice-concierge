"""The README, written for the LiveKit team (spec §1 anti-goals, §8; C2-05, C7-03): its sections in order, every cited
test, module and path real, no unmeasured number, and Agents 2.0 only described, never claimed as the code."""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
SPEC = ROOT / "docs" / "spec.md"

SECTIONS = [
    "What it does",
    "Architecture",
    "Memory design, practice by practice",
    "How it maps onto Agents 2.0",
    "Results",
    "Failure cases and limits",
    "Privacy",
    "How to run it",
]
TURN_PATH_CLAIM = "about 0 ms, measured per turn as memory_on_turn_path_ms"


def _section(heading: str) -> str:
    text = README.read_text()
    assert f"\n## {heading}\n" in text, heading
    return text.split(f"\n## {heading}\n", 1)[1].split("\n## ", 1)[0]


def _mapping_section() -> str:
    return _section("How it maps onto Agents 2.0")


def _table_rows(section: str) -> list[list[str]]:
    """The cells of each body row of every table in the section (header and separator rows dropped)."""
    rows: list[list[str]] = []
    lines = section.splitlines()
    for i, line in enumerate(lines):
        if not line.startswith("|") or re.fullmatch(r"\|(\s*:?-+:?\s*\|)+", line):
            continue
        if i + 1 < len(lines) and re.fullmatch(r"\|(\s*:?-+:?\s*\|)+", lines[i + 1]):
            continue  # a header row
        rows.append([cell.strip() for cell in line.split("|")[1:-1]])
    return rows


def _first_cells() -> list[str]:
    return [row[0] for row in _table_rows(_mapping_section())]


def _rows(section: str) -> dict[str, str]:
    """First cell -> last cell ('Proved by') of each body row."""
    return {row[0]: row[-1] for row in _table_rows(section)}


def _middle_cells(section: str) -> dict[str, str]:
    """First cell -> second cell ('In the concierge') of each body row."""
    return {row[0]: row[1] for row in _table_rows(section)}


def _test_names(offline_only: bool = False) -> set[str]:
    tests = Path(__file__).resolve().parent
    pattern = re.compile(r"^(?:async )?def (test_\w+)", re.MULTILINE)
    paths = [path for path in tests.rglob("test_*.py") if not (offline_only and "live" in path.parent.parts)]
    return {name for path in paths for name in pattern.findall(path.read_text())}


def _blocks_outside_the_mapping() -> list[str]:
    """Paragraphs, bullets and table rows outside the mapping section, whitespace-normalised (a wrap can't hide a
    phrase), headings dropped."""
    outside = README.read_text().replace(_mapping_section(), "")
    blocks = re.split(r"\n\s*\n|\n(?=- |\|)", outside)
    return [" ".join(block.split()) for block in blocks if block.strip() and not block.lstrip().startswith("#")]


def _spec_practices() -> list[str]:
    section = SPEC.read_text().split("### 4.0 ", 1)[1].split("\n### ", 1)[0]
    return re.findall(r"^\| \*\*([^*]+)\*\*", section, re.MULTILINE)


def test_readme_sections_are_in_order() -> None:
    headings = re.findall(r"^## (.+)$", README.read_text(), re.MULTILINE)
    assert headings == SECTIONS


def test_what_it_does_has_the_gif_placeholder_line() -> None:
    lines = _section("What it does").splitlines()
    assert any(line.startswith("> GIF placeholder:") for line in lines)


def test_what_it_does_says_the_agent_publishes_memory_and_metrics() -> None:
    section = " ".join(_section("What it does").split())
    assert "publishes" in section
    assert "`concierge.memory`" in section and "`concierge.metrics`" in section


def test_architecture_diagram_has_the_nodes() -> None:
    section = _section("Architecture")
    blocks = re.findall(r"```mermaid\n(.*?)```", section, re.DOTALL)
    assert len(blocks) == 1, "one mermaid diagram"
    diagram = blocks[0]
    assert diagram.lstrip().startswith("flowchart")
    for node in ("browser page", "LiveKit Cloud", "concierge.worker", "SQLite", "Anthropic API", "OpenRouter",
                 "LiveKit Inference"):
        assert node in diagram, node
    for name in ("concierge.memory", "concierge.metrics", "concierge.forget_me", "concierge.get_memory", "lk.chat"):
        assert name in diagram, name


def test_memory_design_has_the_rows_of_spec_4_0() -> None:
    practices = _spec_practices()
    assert len(practices) == 17
    assert set(_rows(_section("Memory design, practice by practice"))) == set(practices)


@pytest.mark.parametrize("practice", _spec_practices())
def test_memory_design_row_names_tests_that_exist(practice: str) -> None:
    proved_by = _rows(_section("Memory design, practice by practice"))[practice]
    cited = re.findall(r"`(test_\w+)`", proved_by)
    assert cited, practice
    offline = _test_names(offline_only=True)  # a live-only test proves nothing in the offline suite
    assert set(cited) <= offline, set(cited) - offline


@pytest.mark.parametrize("practice", _spec_practices())
def test_memory_design_row_names_its_module(practice: str) -> None:
    cell = _middle_cells(_section("Memory design, practice by practice"))[practice]
    assert re.search(r"`(concierge|scripts)/[\w-]+\.(py|sh)`", cell), practice


def test_preload_row_says_when_it_would_change() -> None:
    row = " ".join(_section("Memory design, practice by practice").split())
    assert "large collection" in row and "just in time" in row


def test_mapping_table_has_the_rows() -> None:
    cells = [cell.lower() for cell in _first_cells()]
    for name in ("thread", "lane state", "journal", "channels", "lease / fence vs lock",
                 "across days: ttl and returning visits"):
        assert any(cell.startswith(name) for cell in cells), (name, cells)
    assert "BEGIN IMMEDIATE" in _mapping_section()
    assert "version" in _mapping_section()


def test_mapping_says_1_8_has_no_lease_so_sessions_can_interleave() -> None:
    section = " ".join(_mapping_section().split())
    assert "1.8 has no lease" in section
    assert "two live sessions for one visitor can interleave turns" in section


def test_agents_2_0_is_only_described_in_the_mapping_section() -> None:
    """Outside the mapping section, a block that mentions 2.0 at all also says the code is 1.8."""
    mapping = " ".join(_mapping_section().split())
    assert "This is LiveKit Agents 1.8 code" in mapping
    mentions = [block for block in _blocks_outside_the_mapping() if re.search(r"\b2\.0\b", block)]
    assert mentions, "the pitch points at the mapping"
    for block in mentions:
        assert "1.8" in block, block


def test_every_mention_of_livekit_agents_outside_the_mapping_says_1_8() -> None:
    for block in _blocks_outside_the_mapping():
        assert not re.search(r"(?i)livekit agents(?! 1\.8)", block), block


MEASURED = re.compile(r"^Measured on \d{4}-\d{2}-\d{2}\b", re.M)


def unmeasured_cells(section: str) -> list[list[str]]:
    """Rows of the Results tables with a number cell that isn't `to measure`; once the section says
    "Measured on <date>" (MORNING step 9 adds it with the pasted tables), any filled cell is allowed."""
    measured = MEASURED.search(section) is not None
    bad = []
    for row in _table_rows(section):
        for cell in row[1:]:
            exempt = row[0] == "cached-token share" and cell == ""
            if not (exempt or cell == "to measure" or (measured and cell)):
                bad.append(row)
                break
    return bad


def test_results_number_cells_are_to_measure() -> None:
    section = _section("Results")
    assert len(_table_rows(section)) >= 10, "the latency table and the memory eval table"
    assert unmeasured_cells(section) == []
    assert "`scripts/latency_report.py`" in section and "`scripts/eval_memory.py`" in section


def test_results_numbers_need_the_measured_line() -> None:
    table = "| field | n | p50 | p95 |\n|---|---|---|---|\n| `eou_ms` | n=24 | 310.0 | 540.5 |\n"
    assert unmeasured_cells(table) == [["`eou_ms`", "n=24", "310.0", "540.5"]]
    assert unmeasured_cells("Measured on 2026-10-21 with `scripts/latency_report.py`.\n\n" + table) == []


def test_results_latency_rows_are_the_report_fields() -> None:
    source = (ROOT / "scripts" / "latency_report.py").read_text()
    assigned = next(node for node in ast.parse(source).body
                    if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "FIELDS")
    fields = ast.literal_eval(assigned.value)
    labels = [row[0].strip("`") for row in _table_rows(_section("Results"))]
    for field in (*fields, "cached-token share"):
        assert field in labels, field


def test_no_ms_number_except_the_turn_path_claim() -> None:
    text = README.read_text().replace("`", "")
    assert TURN_PATH_CLAIM in text
    rest = text.replace(TURN_PATH_CLAIM, "")
    assert not re.findall(r".{0,30}[0-9]+ ?ms.{0,10}", rest)


def test_failure_cases_name_each_limit() -> None:
    section = " ".join(_section("Failure cases and limits").split())
    for phrase in ("isn't auth", "mishears", "extractor can miss", "single box", "No lease", "`phone:`",
                   "Agent Insights"):
        assert phrase in section, phrase
    assert not re.search(r"(?i)agents 2\.0", section)


def test_privacy_section_says_what_survives_forget_me_and_what_livekit_keeps() -> None:
    text = " ".join(_section("Privacy").split())
    assert "anonymous timing numbers survive" in text and "(B9)" in text
    assert "Agent Insights" in text and "(B11)" in text
    assert "can't erase" in text


def test_how_to_run_it_names_the_commands() -> None:
    section = _section("How to run it")
    for command in (".harness/check.sh", "scripts/run-worker.sh start", "deploy/voice-concierge.service",
                    "~/.voice-concierge-off", "MORNING.md", ".env.example"):
        assert command in section, command


def test_every_cited_test_name_exists() -> None:
    cited = set(re.findall(r"`(test_\w+)`", README.read_text()))
    assert cited
    assert cited <= _test_names(), sorted(cited - _test_names())


def test_every_cited_test_file_exists() -> None:
    paths = set(re.findall(r"(?<![\w/.-])tests/[\w/]+\.py", README.read_text()))
    assert paths
    assert all((ROOT / path).is_file() for path in paths), sorted(p for p in paths if not (ROOT / p).is_file())


def test_every_cited_module_and_script_path_exists() -> None:
    text = README.read_text()
    paths = set(re.findall(r"(?<![\w/.~%-])(?:concierge|scripts|deploy|docs|evals|knowledge)/[\w./*-]*[\w*]", text))
    assert any(p.startswith("concierge/") for p in paths) and any(p.startswith("scripts/") for p in paths)
    missing = [p for p in paths if not (list(ROOT.glob(p)) if "*" in p else (ROOT / p).exists())]
    assert not missing, sorted(missing)


V2_KEYS = ["v", "about_visitor", "about_agent", "retention_days"]


def test_the_field_table_names_the_v2_keys() -> None:
    """V2-05: § Architecture has one row per top-level v2 key with the module its value comes from."""
    rows = {row[0].strip("`"): row for row in _table_rows(_section("Architecture"))}
    assert [key for key in rows if key in V2_KEYS] == V2_KEYS
    for key in ("about_visitor", "about_agent", "retention_days"):
        assert re.search(r"`concierge/[\w-]+\.py`", " ".join(rows[key][1:])), key


def test_what_it_does_describes_the_v2_body_by_kind() -> None:
    section = " ".join(_section("What it does").split())
    for phrase in ("`about_visitor`", "`about_agent`", "this session's memory events", "`concierge.get_memory`"):
        assert phrase in section, phrase
