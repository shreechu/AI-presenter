from dataclasses import dataclass
from typing import Optional

from question_classifier import QuestionClassifier, QuestionResult


@dataclass
class SpeechEvent:
    speaker: str
    text: str
    started_speaking: bool
    stopped_speaking: bool
    is_interruption: bool
    question: QuestionResult


class SpeechDetector:
    """Converts transcript text into speech and interruption signals."""

    def __init__(self, classifier: Optional[QuestionClassifier] = None, min_chars: int = 6) -> None:
        self.classifier = classifier or QuestionClassifier()
        self.min_chars = min_chars

    def process_transcript(self, speaker: str, text: str) -> SpeechEvent:
        clean_text = (text or "").strip()
        question = self.classifier.classify(clean_text)
        is_interruption = len(clean_text) >= self.min_chars

        return SpeechEvent(
            speaker=speaker,
            text=clean_text,
            started_speaking=bool(clean_text),
            stopped_speaking=bool(clean_text),
            is_interruption=is_interruption,
            question=question,
        )
