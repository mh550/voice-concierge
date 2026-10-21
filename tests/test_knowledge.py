"""The knowledge pack (spec §4.1): small, sourced, and built only from knowledge/sources/."""

import re
from pathlib import Path

import pytest

from concierge import knowledge
from concierge.knowledge import PACK_PATH, load_pack, pack_stats, pack_word_count, sources_commit
from concierge.prompt import estimate_tokens

ROOT = Path(__file__).resolve().parent.parent
SOURCES_DIR = ROOT / "knowledge" / "sources"
SOURCE_FILES = ("Bio.md", "profile.ts", "experience.ts", "projects.ts", "skills.ts", "resume-v4.md", "concierge.md")
VENDORED = SOURCE_FILES[:5]
MAX_WORDS = 1200

PACK = (ROOT / "knowledge" / "michael.md").read_text(encoding="utf-8")
SOURCES_TEXT = "\n".join((SOURCES_DIR / name).read_text(encoding="utf-8") for name in SOURCE_FILES)

# Names the pack states as facts: project titles ("## Project: <title>") and companies ("at <Company>" or
# "At <Company>", a run of capitalised words). Each must appear verbatim in the sources.
PROJECT_HEADING = re.compile(r"^## Project: (.+?)\s*$", re.MULTILINE)
AT_COMPANY = re.compile(r"\b[Aa]t ((?:[A-Z][\w&]*)(?: [A-Z][\w&]*)*)")
NAMES = sorted(set(PROJECT_HEADING.findall(PACK)) | set(AT_COMPANY.findall(PACK)))

URL = re.compile(r"https?://[^\s)>\]`'\"]+")


def _sections() -> list[tuple[int, list[str]]]:
    lines = PACK.splitlines()
    return [(i, lines[i + 1 : i + 4]) for i, line in enumerate(lines) if line.startswith("## ")]


def test_pack_is_at_most_1200_words() -> None:
    assert pack_word_count() == len(PACK.split())
    assert pack_word_count() <= MAX_WORDS


def test_load_pack_returns_the_file_content() -> None:
    assert load_pack() == PACK
    assert PACK_PATH == ROOT / "knowledge" / "michael.md"


def test_load_pack_does_not_depend_on_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert load_pack() == PACK


def test_every_section_names_its_source_within_three_lines() -> None:
    sections = _sections()
    assert len(sections) >= 5
    for index, following in sections:
        sources = [line for line in following if line.startswith("Source: ")]
        assert sources, f"section on line {index + 1} has no 'Source: <file>' line within 3 lines"


def test_every_source_line_names_an_existing_source_file() -> None:
    cited = re.findall(r"^Source: (.+?)\s*$", PACK, re.MULTILINE)
    assert cited
    for name in cited:
        assert name in SOURCE_FILES, f"{name!r} is not one of {SOURCE_FILES}"
        assert (SOURCES_DIR / name).is_file()


def test_names_are_derived_from_the_pack() -> None:
    # Guards the derivation itself: if the pack's format drifts, NAMES would silently go empty.
    assert any(PROJECT_HEADING.fullmatch(f"## Project: {n}") for n in NAMES)
    for company in ("Builder Clarity", "MAXX Potential", "Duke University"):
        assert company in NAMES


@pytest.mark.parametrize("name", NAMES)
def test_every_name_appears_verbatim_in_the_sources(name: str) -> None:
    assert name in SOURCES_TEXT


def test_pack_has_no_url_absent_from_the_sources() -> None:
    for url in URL.findall(PACK):
        url = url.rstrip(".,;:")
        assert url in SOURCES_TEXT, f"{url} is not in knowledge/sources/"


DIGIT_TOKEN = re.compile(r"\S*\d\S*")
SOURCE_LINE = re.compile(r"^Source: (\S+)\s*$")


def _prose(text: str = PACK) -> str:
    """The text without its "Source: <file>" lines (they name files, e.g. resume-v4.md, and are checked apart)."""
    return "\n".join(
        line for line in text.splitlines() if not ((m := SOURCE_LINE.match(line)) and m.group(1) in SOURCE_FILES)
    )
SOURCES_FLAT = " ".join(SOURCES_TEXT.split())


def test_every_number_and_date_in_the_pack_is_in_the_sources() -> None:
    # §4.1: never guess numbers or dates. Each digit-bearing token, stripped of prose punctuation, must be sourced.
    missing = sorted(
        {t for t in (m.strip(".,;:()*`'\"") for m in DIGIT_TOKEN.findall(_prose())) if t and t not in SOURCES_FLAT}
    )
    assert not missing, f"not in knowledge/sources/: {missing}"


# --- pack_stats (V2-05: about_agent.knowledge, plan V2 "Where each value comes from") ------------------------------

SOURCE_MD = (SOURCES_DIR / "SOURCE.md").read_text(encoding="utf-8")


def test_pack_stats_words_match_the_word_count() -> None:
    assert pack_stats().words == pack_word_count() == len(PACK.split())


def test_pack_stats_tokens_match_the_estimate() -> None:
    assert pack_stats().est_tokens == estimate_tokens(PACK) > 0


def test_pack_stats_commit_is_the_one_in_source_md() -> None:
    (cited,) = set(re.findall(r"commit `([0-9a-f]{7,40})`", SOURCE_MD))
    assert pack_stats().sources_commit == cited


def test_pack_stats_sections_are_the_h2_titles_in_order() -> None:
    titles = [line[3:].strip() for line in PACK.splitlines() if line.startswith("## ")]
    assert pack_stats().sections == titles and len(titles) >= 5
    assert pack_stats().sections[0] == "Positioning and contact"


def test_a_source_md_without_a_commit_reports_unknown() -> None:
    assert sources_commit("Copied from the site, no commit recorded.") == "unknown"
    assert sources_commit("from `abc` then at commit `0123abcd` and `fedcba9`") == "0123abcd"
    assert sources_commit("A defaced page, ID 12345678, copied at commit `81bb0fc`.") == "81bb0fc"  # review M3


def test_a_missing_source_md_reports_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review I1: a deployed tree without SOURCE.md still reports the pack (D18 (b))."""
    monkeypatch.setattr(knowledge, "SOURCE_MD_PATH", tmp_path / "missing.md")
    pack_stats.cache_clear()
    try:
        assert pack_stats().sources_commit == "unknown" and pack_stats().words == pack_word_count()
    finally:
        pack_stats.cache_clear()


# --- knowledge v2 (V3-02, plan V3 "Re-vendoring the sources" and "The pack's new outline") ----------------------------

HEADER = re.compile(r"^(?://|<!--) vendored from mh550/portfolio_site@([0-9a-f]{7,40}) (\S+)(?: -->)?$")
LONG_DIGITS = re.compile(r"\d{7,}")
PHONE = re.compile(r"\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}")
POSITIONING = "Agentic Systems Engineer"
SUBLINE = "I build the harnesses, memory and verification around AI agents, and the integrations they run on."
SKILL_GROUPS = ("Agentic AI", "Languages & Web", "Data & Integration", "Infra & Tools")
RETIRED = ("knowledge pack", "specs in, verified milestones out")


def _section(title: str) -> str:
    """The text of '## <title>' up to the next '## ' heading."""
    match = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", PACK, re.MULTILINE | re.DOTALL)
    assert match, f"no '## {title}' section"
    return match.group(1)


def _source_lines(title: str) -> list[str]:
    return [line[len("Source: ") :].strip() for line in _section(title).splitlines()[:3] if line.startswith("Source: ")]


def test_sources_commit_matches_the_headers() -> None:
    (cited,) = set(re.findall(r"commit `([0-9a-f]{7,40})`", SOURCE_MD))
    for name in VENDORED:
        first = (SOURCES_DIR / name).read_text(encoding="utf-8").splitlines()[0]
        match = HEADER.match(first)
        assert match, f"{name}: first line {first!r} is not a vendored-from header"
        commit, path = match.groups()
        assert commit == cited, f"{name}: header commit {commit} != SOURCE.md {cited}"
        assert path.rsplit("/", 1)[-1] == name
        assert first.startswith("//") == name.endswith(".ts")
    assert pack_stats().sources_commit == cited


def test_source_md_records_the_resume_and_the_rule() -> None:
    assert "resume v4 of 2026-10-20, from the spec" in SOURCE_MD
    assert "the resume wins" in SOURCE_MD.lower()


def test_resume_has_no_phone_number() -> None:
    resume = (SOURCES_DIR / "resume-v4.md").read_text(encoding="utf-8")
    assert not LONG_DIGITS.search(resume)
    assert not PHONE.search(resume)
    assert PHONE.search("call 919-555-0100") and not PHONE.search("2026-10-20")  # the pattern itself


def test_concierge_source_names_its_basis() -> None:
    first = (SOURCES_DIR / "concierge.md").read_text(encoding="utf-8").splitlines()[0]
    assert "README.md" in first and "docs/spec.md §4.0" in first


def test_the_pack_carries_the_new_positioning() -> None:
    section = _section("Positioning and contact")
    assert POSITIONING in section and SUBLINE in section
    assert "resume-v4.md" in _source_lines("Positioning and contact")


def test_the_pack_has_the_self_description_section() -> None:
    assert re.search(r"^## Project: Voice Concierge \(this agent\)$", PACK, re.MULTILINE)
    assert _source_lines("Project: Voice Concierge (this agent)") == ["concierge.md"]
    text = _section("Project: Voice Concierge (this agent)")
    needles = ("Forget me", "30", "background", "LiveKit", "30 days", "SQLite", "write gate", "browsers", "harness")
    for needle in needles:
        assert needle in text, needle


def test_the_experience_carries_the_resume_roles() -> None:
    experience = _section("Experience")
    for needle in ("MAXX Potential", "Builder Clarity", "Tahoma Films", "Copilot Studio", "multi-org OAuth"):
        assert needle in experience, needle  # the last two are resume v4's, not experience.ts'
    assert "coach" in experience.lower()
    skills = _section("Skills")
    positions = [skills.find(group) for group in SKILL_GROUPS]
    assert -1 not in positions and positions == sorted(positions), positions


def test_the_pack_has_no_phone_number_or_retired_words() -> None:
    assert not LONG_DIGITS.search(PACK)
    assert not PHONE.search(PACK)
    prose = _prose().lower()
    for words in RETIRED:
        assert words not in prose, words


def test_resume_matches_the_spec() -> None:
    spec = (ROOT / "docs" / "specs" / "2026-10-21-integrated-concierge.md").read_text(encoding="utf-8").splitlines()
    start = spec.index(next(line for line in spec if line.startswith("> **MICHAEL HERRON**")))
    end = spec.index(next(line for line in spec if line.startswith("> **Relevant Coursework:**")))
    quoted = [line[2:] if line.startswith("> ") else line[1:] for line in spec[start : end + 1]]
    resume = (SOURCES_DIR / "resume-v4.md").read_text(encoding="utf-8").splitlines()
    assert resume[2 : 2 + len(quoted)] == quoted


def test_concierge_numbers_are_in_readme_or_spec() -> None:
    basis = " ".join((ROOT / name).read_text(encoding="utf-8") for name in ("README.md", "docs/spec.md"))
    basis = " ".join(basis.split())
    text = "\n".join((SOURCES_DIR / "concierge.md").read_text(encoding="utf-8").splitlines()[1:])  # first line: basis
    missing = sorted({t for t in (m.strip(".,;:()*`'\"") for m in DIGIT_TOKEN.findall(text)) if t not in basis})
    assert not missing, f"not in README.md or docs/spec.md: {missing}"


def test_forget_me_is_not_claimed_to_erase_what_livekit_keeps() -> None:
    """Review I1: README § Privacy: Agent Insights transcripts survive "Forget me"; the agent must not say otherwise."""
    for text in (_section("Project: Voice Concierge (this agent)"), (SOURCES_DIR / "concierge.md").read_text("utf-8")):
        assert "LiveKit keeps" in text and "not erased" in text
