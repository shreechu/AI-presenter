"""
Centralised runtime configuration.

Values are loaded from environment variables (if set) with sensible defaults.
Every integration (Azure TTS, OpenAI, Whisper, Teams) has its own section so
each module can pull exactly the keys it needs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _env_bool(name: str, default: bool = False) -> bool:
    return _env(name, str(default)).lower() in ("1", "true", "yes")


def _env_float(name: str, default: float = 0.0) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def _env_int(name: str, default: int = 0) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


# ── Presentation ──────────────────────────────────────────────────────────────

@dataclass
class SlideConfig:
    """Slide deck and auto-advance settings."""

    pptx_path: Optional[str] = field(default_factory=lambda: _env("PPTX_PATH") or None)
    slide_interval_sec: float = field(default_factory=lambda: _env_float("SLIDE_INTERVAL_SEC", 2.0))
    auto_advance: bool = field(default_factory=lambda: _env_bool("AUTO_ADVANCE", True))


# ── TTS ───────────────────────────────────────────────────────────────────────

@dataclass
class TTSConfig:
    """Text-to-speech backend configuration."""

    backend: str = field(default_factory=lambda: _env("TTS_BACKEND", "local"))  # local | azure | openai
    voice: str = field(default_factory=lambda: _env("TTS_VOICE", "en-US-AriaNeural"))
    words_per_minute: int = field(default_factory=lambda: _env_int("TTS_WPM", 160))
    # Azure Speech
    azure_speech_key: str = field(default_factory=lambda: _env("AZURE_SPEECH_KEY"), repr=False)
    azure_speech_region: str = field(default_factory=lambda: _env("AZURE_SPEECH_REGION", "eastus"))
    # OpenAI TTS
    openai_api_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY"), repr=False)
    openai_tts_model: str = field(default_factory=lambda: _env("OPENAI_TTS_MODEL", "tts-1"))
    openai_tts_voice: str = field(default_factory=lambda: _env("OPENAI_TTS_VOICE", "alloy"))


# ── Audio / Whisper ───────────────────────────────────────────────────────────

@dataclass
class AudioConfig:
    """Microphone capture and Whisper transcription settings."""

    use_real_mic: bool = field(default_factory=lambda: _env_bool("USE_REAL_MIC", False))
    sample_rate: int = field(default_factory=lambda: _env_int("AUDIO_SAMPLE_RATE", 16000))
    chunk_duration_sec: float = field(default_factory=lambda: _env_float("AUDIO_CHUNK_SEC", 3.0))
    whisper_model: str = field(default_factory=lambda: _env("WHISPER_MODEL", "base"))
    vad_energy_threshold: float = field(default_factory=lambda: _env_float("VAD_ENERGY_THRESHOLD", 0.01))


# ── Speech detection / Question classification ────────────────────────────────

@dataclass
class DetectionConfig:
    """Thresholds for interruption and question detection."""

    speech_pause_threshold_sec: float = field(
        default_factory=lambda: _env_float("SPEECH_PAUSE_THRESHOLD_SEC", 0.8)
    )
    question_confidence_threshold: float = field(
        default_factory=lambda: _env_float("QUESTION_CONFIDENCE_THRESHOLD", 0.55)
    )
    interruption_min_chars: int = field(default_factory=lambda: _env_int("INTERRUPTION_MIN_CHARS", 6))
    answer_questions_immediately: bool = field(
        default_factory=lambda: _env_bool("ANSWER_IMMEDIATELY", True)
    )
    use_llm_classifier: bool = field(default_factory=lambda: _env_bool("USE_LLM_CLASSIFIER", False))


# ── Teams ─────────────────────────────────────────────────────────────────────

@dataclass
class TeamsConfig:
    """Microsoft Teams integration settings."""

    app_id: str = field(default_factory=lambda: _env("TEAMS_APP_ID"), repr=False)
    app_password: str = field(default_factory=lambda: _env("TEAMS_APP_PASSWORD"), repr=False)
    tenant_id: str = field(default_factory=lambda: _env("TEAMS_TENANT_ID"))
    enable_simulated_events: bool = field(default_factory=lambda: _env_bool("TEAMS_SIMULATE", True))


# ── Simulation ────────────────────────────────────────────────────────────────

@dataclass
class SimulationConfig:
    """Simulated audience events for local testing."""

    audience_script: List[str] = field(
        default_factory=lambda: [
            "Can you explain the architecture one more time?",
            "I think slide 1 mentioned compliance, right?",
            "Thanks, continue please.",
            "What about scalability?",
        ]
    )
    audience_delay_sec: float = field(default_factory=lambda: _env_float("SIM_AUDIENCE_DELAY", 8.0))


# ── OpenAI answer generation ─────────────────────────────────────────────────

@dataclass
class LLMConfig:
    """Settings for AI-generated answers to audience questions."""

    openai_api_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY"), repr=False)
    model: str = field(default_factory=lambda: _env("OPENAI_CHAT_MODEL", "gpt-4o"))
    max_answer_tokens: int = field(default_factory=lambda: _env_int("LLM_MAX_ANSWER_TOKENS", 200))


# ── Top-level composite config ────────────────────────────────────────────────

@dataclass
class AppConfig:
    """Composite configuration — one object passed around to all modules."""

    slide: SlideConfig = field(default_factory=SlideConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    teams: TeamsConfig = field(default_factory=TeamsConfig)
    simulation: SimulationConfig = field(default_factory=SimulationConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))
