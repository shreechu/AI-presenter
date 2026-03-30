from dataclasses import dataclass


@dataclass
class QuestionResult:
    is_question: bool
    confidence: float
    reason: str


class QuestionClassifier:
    """Heuristic question detection for MVP use."""

    QUESTION_WORDS = {
        "what",
        "why",
        "how",
        "when",
        "where",
        "who",
        "which",
        "can",
        "could",
        "would",
        "should",
        "do",
        "does",
        "did",
        "is",
        "are",
        "was",
        "were",
    }

    def classify(self, text: str) -> QuestionResult:
        normalized = (text or "").strip()
        if not normalized:
            return QuestionResult(is_question=False, confidence=0.0, reason="empty")

        lowered = normalized.lower()
        score = 0.0
        reason_parts = []

        if lowered.endswith("?"):
            score += 0.45
            reason_parts.append("ends_with_question_mark")

        first_word = lowered.split()[0] if lowered.split() else ""
        if first_word in self.QUESTION_WORDS:
            score += 0.35
            reason_parts.append("starts_with_question_word")

        if "explain" in lowered or "clarify" in lowered:
            score += 0.2
            reason_parts.append("contains_clarification_keyword")

        score = min(score, 1.0)
        return QuestionResult(
            is_question=score >= 0.5,
            confidence=score,
            reason=", ".join(reason_parts) if reason_parts else "no_question_signals",
        )
