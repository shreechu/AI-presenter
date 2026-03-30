import asyncio
import re
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Slide:
    index: int
    title: str
    speaker_notes: str


class SlideController:
    """Tracks slide state and speaker notes with async-safe controls."""

    def __init__(self, slides: List[Slide]) -> None:
        if not slides:
            raise ValueError("At least one slide is required")
        self._slides = slides
        self._current_idx = 0
        self._paused = False
        self._lock = asyncio.Lock()

    async def current_slide(self) -> Slide:
        async with self._lock:
            return self._slides[self._current_idx]

    async def is_paused(self) -> bool:
        async with self._lock:
            return self._paused

    async def pause(self) -> None:
        async with self._lock:
            self._paused = True

    async def resume(self) -> None:
        async with self._lock:
            self._paused = False

    async def advance(self) -> Optional[Slide]:
        async with self._lock:
            if self._current_idx + 1 >= len(self._slides):
                return None
            self._current_idx += 1
            return self._slides[self._current_idx]

    async def jump_to(self, slide_index: int) -> Slide:
        async with self._lock:
            if slide_index < 0 or slide_index >= len(self._slides):
                raise IndexError(f"Slide index {slide_index} is out of range")
            self._current_idx = slide_index
            return self._slides[self._current_idx]

    async def has_next(self) -> bool:
        async with self._lock:
            return self._current_idx + 1 < len(self._slides)

    async def find_relevant_slide(self, question: str) -> Optional[Slide]:
        """Simple keyword overlap matcher for MVP slide routing."""
        normalized_question_tokens = _tokenize(question)
        if not normalized_question_tokens:
            return None

        best_slide = None
        best_score = 0
        async with self._lock:
            for slide in self._slides:
                haystack = f"{slide.title} {slide.speaker_notes}"
                slide_tokens = _tokenize(haystack)
                overlap = len(normalized_question_tokens & slide_tokens)
                if overlap > best_score:
                    best_score = overlap
                    best_slide = slide

        return best_slide if best_score > 0 else None


_WORD_RE = re.compile(r"[a-zA-Z0-9]{3,}")


def _tokenize(text: str) -> set:
    return {m.group(0).lower() for m in _WORD_RE.finditer(text or "")}
