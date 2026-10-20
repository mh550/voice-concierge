"""C7-02: tests/live/test_live.py's shape, checked without running it (plan C7 "Part 2"). Nothing here runs a live
test or passes `-m live`."""

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

LIVE = Path(__file__).resolve().parent / "live" / "test_live.py"
NAMES = [
    "test_live_two_session_recall_in_text_mode",
    "test_live_wrong_memory_is_not_attributed_to_the_visitor",
    "test_live_injection_is_not_stored",
    "test_live_forget_me_makes_the_next_session_a_stranger",
]


def module_ast() -> ast.Module:
    return ast.parse(LIVE.read_text(encoding="utf-8"))


def test_live_file_has_four_live_tests() -> None:
    tree = module_ast()
    tests = [n.name for n in tree.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
             and n.name.startswith("test_")]
    assert tests == NAMES
    assert all(isinstance(n, ast.AsyncFunctionDef) for n in tree.body if getattr(n, "name", "") in NAMES)
    # No import-time side effects: the module's top level only imports, assigns and defines.
    for node in tree.body:
        if isinstance(node, ast.Expr):
            assert isinstance(node.value, ast.Constant), ast.unparse(node)  # the docstring only
        else:
            assert isinstance(node, ast.Import | ast.ImportFrom | ast.Assign | ast.AnnAssign | ast.FunctionDef
                              | ast.AsyncFunctionDef | ast.ClassDef), ast.unparse(node)
            if isinstance(node, ast.Assign | ast.AnnAssign):
                assert "build_llm" not in ast.unparse(node)


def test_live_module_is_marked_live_and_skipped_without_livekit_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LIVEKIT_URL", raising=False)
    spec = importlib.util.spec_from_file_location("live_layout_probe", LIVE)  # a fresh copy, not pytest's
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    marks = {m.name: m for m in module.pytestmark}
    assert set(marks) == {"live", "skipif"}
    assert marks["skipif"].args == (True,)
    assert "LIVEKIT_URL" in marks["skipif"].kwargs["reason"]


def test_not_live_deselects_all_four() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-m", "not live", "--collect-only", "-q", str(LIVE.parent)],
        capture_output=True, text=True, timeout=120, check=False, cwd=LIVE.parents[2],
    )
    assert result.returncode == 5, result.stdout + result.stderr  # pytest's "no tests collected"
    assert "4 deselected" in result.stdout


def test_live_docstring_says_only_michael_runs_it() -> None:
    doc = ast.get_docstring(module_ast()) or ""
    assert "only Michael runs" in doc.replace("\n", " ")
    assert "pytest -m live" in doc
