"""
Question and intent classifier.

Two modes:
  * **Heuristic** — fast, keyword/pattern-based (default, always available).
  * **LLM-backed** — sends the text to OpenAI for classification (opt-in).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class Intent(str, Enum):
    """High-level intent bucket."""

    QUESTION = "question"
    COMMAND = "command"       # "next slide", "go back", etc.
    FEEDBACK = "feedback"     # "thanks", "ok", etc.
    UNKNOWN = "unknown"


@dataclass
class ClassificationResult:
    intent: Intent
    is_question: bool
    confidence: float
    reason: str
    command: Optional[str] = None  # populated when intent == COMMAND


# ── Heuristic classifier ─────────────────────────────────────────────────────

QUESTION_WORDS = frozenset(
    "what why how when where who which can could would should do does did is are was were".split()
)

_COMMAND_MAP: dict[str, str] = {
    "next slide": "next",
    "go forward": "next",
    "advance": "next",
    "previous slide": "back",
    "go back": "back",
    "last slide": "back",
    "pause": "pause",
    "stop": "pause",
    "resume": "resume",
    "continue": "resume",
    "skip": "next",
}

_FEEDBACK_STARTERS = frozenset(
    "thanks thank ok okay got it understood sure great good nice".split()
)


class QuestionClassifier:
    """Stateless heuristic classifier — no network calls required."""

    def classify(self, text: str) -> ClassificationResult:
        normalized = (text or "").strip()
        if not normalized:
            return ClassificationResult(
                intent=Intent.UNKNOWN, is_question=False, confidence=0.0, reason="empty"
            )

        lowered = normalized.lower()

        # 1. Check for navigation / control commands first
        for trigger, cmd in _COMMAND_MAP.items():
            if trigger in lowered:
                return ClassificationResult(
                    intent=Intent.COMMAND,
                    is_question=False,
                    confidence=0.95,
                    reason=f"matched_command:{trigger}",
                    command=cmd,
                )

        # 2. Question scoring
        score = 0.0
        reasons: list[str] = []

        if lowered.endswith("?"):
            score += 0.45
            reasons.append("question_mark")

        first_word = lowered.split()[0] if lowered.split() else ""
        if first_word in QUESTION_WORDS:
            score += 0.35
            reasons.append("question_word")

        if any(kw in lowered for kw in ("explain", "clarify", "elaborate", "tell me")):
            score += 0.20
            reasons.append("clarification_keyword")

        if score >= 0.5:
            return ClassificationResult(
                intent=Intent.QUESTION,
                is_question=True,
                confidence=min(score, 1.0),
                reason=", ".join(reasons),
            )

        # 3. Feedback
        if first_word in _FEEDBACK_STARTERS:
            return ClassificationResult(
                intent=Intent.FEEDBACK,
                is_question=False,
                confidence=0.7,
                reason="feedback_starter",
            )

        return ClassificationResult(
            intent=Intent.UNKNOWN,
            is_question=False,
            confidence=max(score, 0.1),
            reason=", ".join(reasons) or "no_signal",
        )


# ── LLM-backed classifier ────────────────────────────────────────────────────

class LLMQuestionClassifier:
    """Uses OpenAI chat completions for more nuanced classification."""

    _SYSTEM_PROMPT = (
        "You are a classification engine for a live presentation bot. "
        "Given audience text, reply with EXACTLY one JSON object:\n"
        '  {"intent": "question"|"command"|"feedback"|"unknown", '
        '"confidence": 0.0-1.0, "reason": "<brief explanation>", '
        '"command": "next"|"back"|"pause"|"resume"|null}\n'
        "Do NOT add any other text."
    )

    def __init__(self, api_key: str, model: str = "gpt-4o") -> None:
        try:
            from openai import OpenAI  # type: ignore[import-untyped]
        except ImportError:
            raise ImportError("openai package is required for LLM classifier")
        self._client = OpenAI(api_key=api_key)
        self._model = model

    async def classify(self, text: str) -> ClassificationResult:
        if not text.strip():
            return ClassificationResult(
                intent=Intent.UNKNOWN, is_question=False, confidence=0.0, reason="empty"
            )

        loop = asyncio.get_running_loop()
        try:
            response = await loop.run_in_executor(
                None,
                lambda: self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": self._SYSTEM_PROMPT},
                        {"role": "user", "content": text},
                    ],
                    max_tokens=80,
                    temperature=0.0,
                ),
            )
            import json

            raw = response.choices[0].message.content or "{}"
            data = json.loads(raw)
            intent = Intent(data.get("intent", "unknown"))
            return ClassificationResult(
                intent=intent,
                is_question=intent == Intent.QUESTION,
                confidence=float(data.get("confidence", 0.5)),
                reason=data.get("reason", "llm"),
                command=data.get("command"),
            )
        except Exception:
            logger.exception("LLM classification failed — falling back to heuristic")
            return QuestionClassifier().classify(text)
