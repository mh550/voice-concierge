"""The kill switch (spec B7, §6 "Offline"; plan C6 "on_request(req)"): the worker declines the job."""

from __future__ import annotations  # string annotations, as in agents/job.py, so the signatures compare equal

from pathlib import Path
from typing import Any

import pytest
from livekit.agents import JobRequest

from concierge import worker


class FakeRequest:
    """JobRequest's two answers (agents/job.py:1077-1089), each recording that it was awaited."""

    id = "job-test"

    def __init__(self) -> None:
        self.awaited: list[str] = []

    async def accept(self, *, name: str = "", identity: str = "", metadata: str = "",
                     attributes: dict[str, str] | None = None) -> None:
        self.awaited.append("accept")

    async def reject(self, *, terminate: bool = True) -> None:
        self.awaited.append("reject")


def test_fake_request_matches_job_request() -> None:
    import inspect

    for name in ("accept", "reject"):
        assert inspect.signature(getattr(FakeRequest, name)) == inspect.signature(getattr(JobRequest, name))


@pytest.fixture(autouse=True)
def _no_switch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    off = tmp_path / "voice-concierge-off"
    monkeypatch.setenv("CONCIERGE_OFF_FILE", str(off))  # never ~/.voice-concierge-off
    monkeypatch.delenv("CONCIERGE_ENABLED", raising=False)
    return off


async def answer() -> list[str]:
    req: Any = FakeRequest()
    await worker.on_request(req)
    return req.awaited


async def test_kill_switch_env_rejects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONCIERGE_ENABLED", "0")
    assert await answer() == ["reject"]


async def test_kill_switch_off_file_rejects(_no_switch: Path) -> None:
    _no_switch.touch()
    assert await answer() == ["reject"]


async def test_the_off_file_takes_effect_without_a_restart(_no_switch: Path) -> None:
    assert await answer() == ["accept"]
    _no_switch.touch()
    assert await answer() == ["reject"]
    _no_switch.unlink()
    assert await answer() == ["accept"]


async def test_no_kill_switch_accepts() -> None:
    assert await answer() == ["accept"]


async def test_invalid_settings_reject(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONCIERGE_ENABLED", "maybe")  # fail closed: a bad env declines
    assert await answer() == ["reject"]
