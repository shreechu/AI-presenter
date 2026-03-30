import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from audio_listener import AudioListener, AudioTranscript


@dataclass
class TeamsChatMessage:
    sender: str
    text: str


class TeamsPresenterBot:
    """Simulated Teams adapter for MVP. Replace internals with Graph/Teams SDK later."""

    def __init__(self, audio_listener: AudioListener) -> None:
        self._audio_listener = audio_listener
        self._logger = logging.getLogger(self.__class__.__name__)
        self._chat_callback: Optional[Callable[[TeamsChatMessage], Awaitable[None]]] = None

    def on_chat_message(self, callback: Callable[[TeamsChatMessage], Awaitable[None]]) -> None:
        self._chat_callback = callback

    async def join_meeting(self, meeting_id: str) -> None:
        self._logger.info("Joined Teams meeting %s (simulation)", meeting_id)

    async def stream_tts_audio(self, text: str) -> None:
        self._logger.info("Streaming bot audio to meeting (simulation): %s", text)

    async def post_chat_message(self, text: str) -> None:
        self._logger.info("Teams chat post (simulation): %s", text)

    async def simulate_chat_and_audio_events(self) -> None:
        await asyncio.sleep(7)
        await self._audio_listener.push_transcript(
            AudioTranscript(source="teams-audio", speaker="attendee", text="Could you go back to architecture?")
        )

        await asyncio.sleep(10)
        if self._chat_callback:
            await self._chat_callback(
                TeamsChatMessage(sender="attendee", text="How does question detection decide to pause?")
            )
