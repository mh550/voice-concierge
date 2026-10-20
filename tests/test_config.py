import os
import subprocess
import sys
import typing
from pathlib import Path

import pytest
from livekit.agents.inference import stt as inference_stt
from livekit.agents.inference import tts as inference_tts

from concierge import config
from concierge.config import Settings, speech_classes

KEY_VARS = ("OPENROUTER_API_KEY", "DEEPGRAM_API_KEY", "LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in [*KEY_VARS, *(k for k in os.environ if k.startswith("CONCIERGE_"))]:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_import_without_keys_does_not_raise(clean_env: pytest.MonkeyPatch) -> None:
    # A fresh interpreter inherits the cleaned environment, so this is a real first import.
    code = "import concierge.config as c; print(c.Settings().conversation_model)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "openai/gpt-4.1-mini"


def test_defaults(clean_env: pytest.MonkeyPatch) -> None:
    s = Settings()
    assert s.conversation_model == "openai/gpt-4.1-mini"
    assert s.extractor_model == "openai/gpt-4.1-mini"
    assert s.summarizer_model == "openai/gpt-4.1-mini"
    assert s.stt_model == "deepgram/nova-3"
    assert s.tts_model == "cartesia/sonic-3"
    assert s.speech == "inference"
    assert s.record_audio is False
    assert s.enabled is True
    assert s.off_file == Path.home() / ".voice-concierge-off"
    assert s.db_path.is_absolute()
    assert (s.session_max_s, s.sessions_per_day, s.idle_ttl_days) == (600, 5, 30)


def _literal_values(tp: object) -> set[str]:
    values: set[str] = set()
    for arg in typing.get_args(tp):
        values |= _literal_values(arg) if typing.get_args(arg) else {arg}
    return values


def test_speech_ids_are_inference_literals() -> None:
    assert Settings.model_fields["stt_model"].default in _literal_values(inference_stt.STTModels)
    assert Settings.model_fields["tts_model"].default in _literal_values(inference_tts.TTSModels)


def test_env_overrides_model(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("CONCIERGE_CONVERSATION_MODEL", "anthropic/claude-haiku-4.5")
    assert Settings().conversation_model == "anthropic/claude-haiku-4.5"
    assert Settings().extractor_model == "openai/gpt-4.1-mini"


def test_env_bools_and_ints(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("CONCIERGE_RECORD_AUDIO", "1")
    clean_env.setenv("CONCIERGE_ENABLED", "0")
    clean_env.setenv("CONCIERGE_SESSIONS_PER_DAY", "3")
    s = Settings()
    assert (s.record_audio, s.enabled, s.sessions_per_day) == (True, False, 3)


def test_unknown_speech_rejected(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("CONCIERGE_SPEECH", "whisper")
    with pytest.raises(ValueError):
        Settings()


def test_speech_inference_selects_inference_classes(clean_env: pytest.MonkeyPatch) -> None:
    stt_cls, tts_cls = speech_classes(Settings())
    assert (stt_cls.__module__, stt_cls.__name__) == ("livekit.agents.inference.stt", "STT")
    assert (tts_cls.__module__, tts_cls.__name__) == ("livekit.agents.inference.tts", "TTS")


def test_speech_deepgram_selects_plugin_classes(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("CONCIERGE_SPEECH", "deepgram")
    stt_cls, tts_cls = speech_classes(Settings())
    assert (stt_cls.__module__, stt_cls.__name__) == ("livekit.plugins.deepgram.stt", "STT")
    assert (tts_cls.__module__, tts_cls.__name__) == ("livekit.plugins.deepgram.tts", "TTS")


@pytest.mark.parametrize("stage", ["conversation", "extractor", "summarizer"])
def test_build_llm_uses_openrouter_with_stage_model(clean_env: pytest.MonkeyPatch, stage: str) -> None:
    clean_env.setenv(f"CONCIERGE_{stage.upper()}_MODEL", f"test/{stage}")
    seen: dict[str, str] = {}

    def fake_with_openrouter(*, model: str, **_: object) -> str:
        seen["model"] = model
        return "llm"

    clean_env.setattr(config.openai.LLM, "with_openrouter", fake_with_openrouter)
    assert config.build_llm(stage) == "llm"  # type: ignore[arg-type]
    assert seen["model"] == f"test/{stage}"


def test_build_llm_without_key_raises_only_when_called(clean_env: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        config.build_llm("conversation")


def test_build_stt_tts_deepgram_pass_plugin_model_names(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("CONCIERGE_SPEECH", "deepgram")
    made: list[tuple[str, dict[str, object]]] = []

    class Spy:
        def __init__(self, name: str) -> None:
            self.name = name

        def __call__(self, **kwargs: object) -> str:
            made.append((self.name, kwargs))
            return self.name

    clean_env.setattr(config.deepgram, "STT", Spy("stt"))
    clean_env.setattr(config.deepgram, "TTS", Spy("tts"))
    assert (config.build_stt(), config.build_tts()) == ("stt", "tts")
    assert made == [("stt", {"model": "nova-3"}), ("tts", {})]


def test_build_stt_tts_inference_pass_model_ids(clean_env: pytest.MonkeyPatch) -> None:
    made: list[tuple[str, dict[str, object]]] = []

    def spy(name: str) -> typing.Callable[..., str]:
        def make(**kwargs: object) -> str:
            made.append((name, kwargs))
            return name

        return make

    clean_env.setattr(config.inference, "STT", spy("stt"))
    clean_env.setattr(config.inference, "TTS", spy("tts"))
    assert (config.build_stt(), config.build_tts()) == ("stt", "tts")
    assert made == [("stt", {"model": "deepgram/nova-3"}), ("tts", {"model": "cartesia/sonic-3"})]


def test_deepgram_speech_needs_a_deepgram_stt_id(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("CONCIERGE_SPEECH", "deepgram")
    clean_env.setenv("CONCIERGE_STT_MODEL", "assemblyai/universal-streaming")
    with pytest.raises(ValueError, match="deepgram/"):
        Settings()
