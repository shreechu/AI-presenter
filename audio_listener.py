import asyncio
import logging
from dataclasses import dataclass
from typing import AsyncIterator, Iterable, Optional


@dataclass
class AudioTranscript:
    source: str
    speaker: str
    text: str


class AudioListener:
    """Consumes audio/transcript events; MVP uses simulation feeder."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[AudioTranscript] = asyncio.Queue()
        self._logger = logging.getLogger(self.__class__.__name__)

    async def push_transcript(self, transcript: AudioTranscript) -> None:
        await self._queue.put(transcript)

    async def stream_transcripts(self) -> AsyncIterator[AudioTranscript]:
        while True:
            item = await self._queue.get()
            yield item

    async def simulate_microphone_input(
        self, audience_script: Iterable[str], delay_sec: float = 6.0, speaker: Optional[str] = None
    ) -> None:
        for line in audience_script:
            await asyncio.sleep(delay_sec)
            transcript = AudioTranscript(source="simulated", speaker=speaker or "audience", text=line)
            self._logger.info("[Speech detected] %s", transcript.text)
            await self.push_transcript(transcript)
