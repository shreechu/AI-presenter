"""
Microsoft Teams integration layer.

In simulation mode (default) every Teams interaction is logged and handled
locally.  When configured with real credentials the bot uses the
Bot Framework SDK and Graph API to:
  * Join meetings as a bot/presenter.
  * Stream TTS audio into the meeting.
  * Receive and post chat messages.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from audio_listener import AudioListener, AudioTranscript
from config import TeamsConfig

logger = logging.getLogger(__name__)


@dataclass
class TeamsChatMessage:
    sender: str
    text: str


class TeamsPresenterBot:
    """
    Adapter for Microsoft Teams.

    Simulation mode (``enable_simulated_events=True``) fires scripted
    events through the ``AudioListener`` without touching any external service.
    """

    def __init__(self, config: TeamsConfig, audio_listener: AudioListener) -> None:
        self._cfg = config
        self._audio_listener = audio_listener
        self._chat_callback: Optional[Callable[[TeamsChatMessage], Awaitable[None]]] = None
        self._connected = False

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def on_chat_message(self, callback: Callable[[TeamsChatMessage], Awaitable[None]]) -> None:
        self._chat_callback = callback

    # ── Meeting lifecycle ─────────────────────────────────────────────────────

    async def join_meeting(self, meeting_id: str) -> None:
        """Join a Teams meeting.  Uses simulation unless real credentials are set."""
        if self._cfg.app_id and self._cfg.app_password:
            await self._join_real_meeting(meeting_id)
        else:
            logger.info("[Teams SIM] Joined meeting '%s' (simulated)", meeting_id)
        self._connected = True

    async def leave_meeting(self) -> None:
        logger.info("[Teams] Left meeting")
        self._connected = False

    # ── Outbound ──────────────────────────────────────────────────────────────

    async def stream_tts_audio(self, text: str) -> None:
        """Send synthesised audio into the meeting audio channel."""
        if not self._connected:
            logger.warning("Cannot stream audio — not connected to a meeting")
            return
        logger.info("[Teams] Streaming TTS audio (%d chars)", len(text))

    async def post_chat_message(self, text: str) -> None:
        """Post a message to the meeting chat."""
        logger.info("[Teams Chat →] %s", text)

    async def post_slide_highlight(self, slide_index: int, title: str) -> None:
        """Post a slide highlight card to chat."""
        msg = f"[Slide {slide_index + 1}] {title}"
        await self.post_chat_message(msg)

    # ── Simulation ────────────────────────────────────────────────────────────

    async def simulate_chat_and_audio_events(self) -> None:
        """Push fake Teams events into the audio listener for local testing."""
        # Simulated attendee audio event
        await asyncio.sleep(7)
        await self._audio_listener.push_transcript(
            AudioTranscript(
                source="teams-audio",
                speaker="attendee_alice",
                text="Could you go back to the architecture slide?",
            )
        )

        # Simulated chat message
        await asyncio.sleep(12)
        if self._chat_callback:
            await self._chat_callback(
                TeamsChatMessage(
                    sender="attendee_bob",
                    text="How does the question detection decide to pause?",
                )
            )

        # Another audio event near the end
        await asyncio.sleep(10)
        await self._audio_listener.push_transcript(
            AudioTranscript(
                source="teams-audio",
                speaker="attendee_charlie",
                text="Can you elaborate on scalability?",
            )
        )

    # ── Real Teams integration (placeholders) ─────────────────────────────────

    async def _join_real_meeting(self, meeting_id: str) -> None:
        """
        Join via Bot Framework / Graph API.

        Requires:
          - Azure Bot Channel Registration  (TEAMS_APP_ID / TEAMS_APP_PASSWORD)
          - Calls & Online Meetings Graph permissions
        """
        logger.info(
            "[Teams] Attempting real meeting join (app_id=%s, tenant=%s, meeting=%s) …",
            self._cfg.app_id,
            self._cfg.tenant_id,
            meeting_id,
        )
        # TODO: implement Graph API call:
        #   POST /communications/calls
        #   with application/json body containing callbackUri, meeting info, etc.
        logger.warning("[Teams] Real meeting join is not yet implemented — running in simulation")
