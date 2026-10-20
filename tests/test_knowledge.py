"""The knowledge pack (spec §4.1): small, sourced, and built only from knowledge/sources/."""

import re
from pathlib import Path

import pytest

from concierge.knowledge import PACK_PATH, load_pack, pack_word_count

ROOT = Path(__file__).resolve().parent.parent
SOURCES_DIR = ROOT / "knowledge" / "sources"
SOURCE_FILES = ("Bio.md", "profile.ts", "experience.ts", "projects.ts", "skills.ts")
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
SOURCES_FLAT = " ".join(SOURCES_TEXT.split())


def test_every_number_and_date_in_the_pack_is_in_the_sources() -> None:
    # §4.1: never guess numbers or dates. Each digit-bearing token, stripped of prose punctuation, must be sourced.
    missing = sorted(
        {t for t in (m.strip(".,;:()*`'\"") for m in DIGIT_TOKEN.findall(PACK)) if t and t not in SOURCES_FLAT}
    )
    assert not missing, f"not in knowledge/sources/: {missing}"
