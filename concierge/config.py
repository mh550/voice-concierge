"""Settings, one per stage (spec D5, B1, B7, B11), and lazy provider factories.

Nothing here builds a provider at import: the Anthropic plugin raises without ANTHROPIC_API_KEY and
`openai.LLM.with_openrouter` without OPENROUTER_API_KEY, so `build_llm`, `build_stt` and `build_tts` are called only
inside a session. Settings come from the process
environment (prefix CONCIERGE_) and never from a dotenv file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from livekit.agents import inference, llm, stt, tts
from livekit.agents.voice.agent_session import RecordingOptions
from livekit.plugins import deepgram, openai
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from concierge.claude_llm import build_claude_llm

Stage = Literal["conversation", "extractor", "summarizer"]
STAGES: tuple[Stage, ...] = ("conversation", "extractor", "summarizer")
OPENROUTER_MODEL = "openai/gpt-4.1-mini"  # every stage's default under llm_provider=openrouter
LLM_KEY = {"anthropic": "ANTHROPIC_API_KEY", "openrouter": "OPENROUTER_API_KEY"}  # the key each llm_provider needs


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CONCIERGE_", validate_default=True)

    # LLM ids are Anthropic ids (OpenRouter ids under llm_provider=openrouter, whose defaults _openrouter_defaults
    # fills in); speech ids are LiveKit Inference ids (Literals in livekit/agents/inference/).
    llm_provider: Literal["anthropic", "openrouter"] = "anthropic"
    conversation_model: str = "claude-haiku-5-5"
    extractor_model: str = "claude-sonnet-5-5"
    summarizer_model: str = "claude-sonnet-5-5"
    stt_model: str = "deepgram/nova-3"
    tts_model: str = "cartesia/sonic-3"
    speech: Literal["inference", "deepgram"] = "inference"  # deepgram: the plugin, with DEEPGRAM_API_KEY (B1)

    record_audio: bool = False  # B11: audio goes to LiveKit only for Michael's own test sessions
    enabled: bool = True  # B7 kill switch, together with off_file
    off_file: Path = Path("~/.voice-concierge-off")
    db_path: Path = Path("~/.local/share/voice-concierge/concierge.db")

    session_max_s: int = 600
    sessions_per_day: int = 5
    idle_ttl_days: int = 30

    @model_validator(mode="before")
    @classmethod
    def _openrouter_defaults(cls, data: object) -> object:
        """Under openrouter, a stage model not set explicitly defaults to OPENROUTER_MODEL."""
        if isinstance(data, dict) and data.get("llm_provider") == "openrouter":
            for stage in STAGES:
                data.setdefault(f"{stage}_model", OPENROUTER_MODEL)
        return data

    @field_validator("off_file", "db_path")
    @classmethod
    def _expand_home(cls, value: Path) -> Path:
        return value.expanduser()

    @model_validator(mode="after")
    def _deepgram_stt_id(self) -> Settings:
        if self.speech == "deepgram" and not self.stt_model.startswith("deepgram/"):
            raise ValueError(f"speech=deepgram needs a deepgram/ stt_model, got {self.stt_model!r}")
        return self


def build_llm(stage: Stage, settings: Settings | None = None) -> llm.LLM:
    s = settings or Settings()
    model: str = getattr(s, f"{stage}_model")
    if s.llm_provider == "openrouter":
        return openai.LLM.with_openrouter(model=model)
    return build_claude_llm(stage, model)


def speech_classes(settings: Settings) -> tuple[type[stt.STT], type[tts.TTS]]:
    """The STT and TTS classes the speech setting selects, without constructing them."""
    if settings.speech == "deepgram":
        return deepgram.STT, deepgram.TTS
    return inference.STT, inference.TTS


def build_stt(settings: Settings | None = None) -> stt.STT:
    s = settings or Settings()
    if s.speech == "deepgram":
        return deepgram.STT(model=s.stt_model.removeprefix("deepgram/"))
    return inference.STT(model=s.stt_model)


def build_tts(settings: Settings | None = None) -> tts.TTS:
    s = settings or Settings()
    if s.speech == "deepgram":
        return deepgram.TTS()  # the plugin's default Aura voice; tts_model is an Inference id
    return inference.TTS(model=s.tts_model)


def recording_options(settings: Settings | None = None) -> RecordingOptions:
    """B11: no visitor audio at LiveKit unless CONCIERGE_RECORD_AUDIO=1; transcripts, traces and logs stay on
    (unset keys default to True in `_resolve_recording_options`), with redaction requested."""
    s = settings or Settings()
    return {"audio": s.record_audio, "redaction": True}
