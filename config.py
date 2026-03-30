from dataclasses import dataclass, field
from typing import List


@dataclass
class AppConfig:
    """Runtime configuration for the presenter bot."""

    slide_interval_sec: float = 2.0
    tts_backend: str = "local"  # local | azure | openai
    tts_voice: str = "en-US-AriaNeural"
    words_per_minute: int = 160

    speech_pause_threshold_sec: float = 0.8
    question_confidence_threshold: float = 0.55
    interruption_min_chars: int = 6

    auto_advance: bool = True
    answer_questions_immediately: bool = True

    enable_simulated_teams_events: bool = True
    simulated_audience_script: List[str] = field(
        default_factory=lambda: [
            "Can you explain the architecture one more time?",
            "I think slide 1 mentioned compliance, right?",
            "Thanks, continue please.",
        ]
    )

    log_level: str = "INFO"
