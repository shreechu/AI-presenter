"""
Speech event detector — wraps the question classifier and adds
interruption logic, command extraction, and timing awareness.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from question_classifier import (
    ClassificationResult,
    Intent,
    LLMQuestionClassifier,
    QuestionClassifier,
)

logger = logging.getLogger(__name__)


@dataclass
class SpeechEvent:
    """Enriched event produced by the detector for each transcript."""

    speaker: str
    text: str
    started_speaking: bool
    stopped_speaking: bool
    is_interruption: bool
    classification: ClassificationResult
    timestamp: float = field(default_factory=time.time)


class SpeechDetector:
    """
    Converts raw transcript text into ``SpeechEvent`` objects.

    Optionally uses an LLM-backed classifier for higher-fidelity intent
    detection when ``llm_classifier`` is provided.
    """

    def __init__(
        self,
        min_chars: int = 6,
        heuristic_classifier: Optional[QuestionClassifier] = None,
        llm_classifier: Optional[LLMQuestionClassifier] = None,
    ) -> None:
        self._min_chars = min_chars
        self._heuristic = heuristic_classifier or QuestionClassifier()
        self._llm = llm_classifier
        self._last_speech_time: float = 0.0

    # ── Main entry-point ──────────────────────────────────────────────────────

    def process(self, speaker: str, text: str) -> SpeechEvent:
        """Synchronous (heuristic) classification — call from sync or async code."""
        clean = (text or "").strip()
        classification = self._heuristic.classify(clean)
        is_interruption = len(clean) >= self._min_chars

        now = time.time()
        event = SpeechEvent(
            speaker=speaker,
            text=clean,
            started_speaking=bool(clean),
            stopped_speaking=bool(clean),
            is_interruption=is_interruption,
            classification=classification,
            timestamp=now,
        )
        self._last_speech_time = now
        return event

    async def process_async(self, speaker: str, text: str) -> SpeechEvent:
        """Async-aware path — uses LLM classifier when available."""
        clean = (text or "").strip()

        if self._llm:
            try:
                classification = await self._llm.classify(clean)
            except Exception:
                logger.exception("LLM classifier failed; using heuristic")
                classification = self._heuristic.classify(clean)
        else:
            classification = self._heuristic.classify(clean)

        is_interruption = len(clean) >= self._min_chars

        now = time.time()
        event = SpeechEvent(
            speaker=speaker,
            text=clean,
            started_speaking=bool(clean),
            stopped_speaking=bool(clean),
            is_interruption=is_interruption,
            classification=classification,
            timestamp=now,
        )
        self._last_speech_time = now
        return event

    @property
    def seconds_since_last_speech(self) -> float:
        if self._last_speech_time == 0:
            return float("inf")
        return time.time() - self._last_speech_time
