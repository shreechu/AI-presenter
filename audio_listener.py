"""
Audio input pipeline — captures microphone audio, transcribes it, and feeds
transcript events to the rest of the system.

Supports:
  * **Simulated** input (scripted audience lines for testing).
  * **Azure Speech** continuous recognition (preferred — uses Azure Speech SDK).
  * **Real microphone** capture via ``sounddevice`` + **Whisper** transcription.
"""

from __future__ import annotations

import asyncio
import logging
import math
import struct
from dataclasses import dataclass
from typing import AsyncIterator, Iterable, Optional

from config import AudioConfig

logger = logging.getLogger(__name__)


@dataclass
class AudioTranscript:
    """A single transcription event."""

    source: str          # "simulated" | "microphone" | "teams-audio" | "teams-chat"
    speaker: str
    text: str


class AudioListener:
    """Receives audio transcripts from any source via an async queue."""

    def __init__(self, config: AudioConfig) -> None:
        self._cfg = config
        self._queue: asyncio.Queue[AudioTranscript] = asyncio.Queue()

    # ── Public API ────────────────────────────────────────────────────────────

    async def push_transcript(self, transcript: AudioTranscript) -> None:
        """Inject a transcript event (used by Teams bot, simulation, or mic pipeline)."""
        await self._queue.put(transcript)

    async def stream_transcripts(self) -> AsyncIterator[AudioTranscript]:
        """Yield transcript events as they arrive."""
        while True:
            item = await self._queue.get()
            yield item

    # ── Simulation ────────────────────────────────────────────────────────────

    async def simulate_microphone_input(
        self,
        audience_script: Iterable[str],
        delay_sec: float = 8.0,
        speaker: Optional[str] = None,
    ) -> None:
        """Feed scripted lines as if someone spoke them."""
        for line in audience_script:
            await asyncio.sleep(delay_sec)
            transcript = AudioTranscript(
                source="simulated",
                speaker=speaker or "audience",
                text=line,
            )
            logger.info("[Simulated speech] %s: %s", transcript.speaker, transcript.text)
            await self.push_transcript(transcript)

    # ── Real microphone capture ───────────────────────────────────────────────

    async def start_microphone_capture(self) -> None:
        """Record from the default microphone, run VAD, transcribe with Whisper."""
        try:
            import numpy as np  # type: ignore[import-untyped]
            import sounddevice as sd  # type: ignore[import-untyped]
        except ImportError:
            logger.error(
                "sounddevice and numpy are required for microphone capture. "
                "Install with: pip install sounddevice numpy"
            )
            return

        whisper_model = await self._load_whisper_model()
        if whisper_model is None:
            return

        sr = self._cfg.sample_rate
        chunk_dur = self._cfg.chunk_duration_sec
        chunk_samples = int(sr * chunk_dur)
        threshold = self._cfg.vad_energy_threshold

        logger.info("Microphone capture started (sr=%d, chunk=%.1fs)", sr, chunk_dur)
        loop = asyncio.get_running_loop()

        while True:
            # Record one chunk (blocking, off-loaded to thread)
            audio: np.ndarray = await loop.run_in_executor(
                None,
                lambda: sd.rec(chunk_samples, samplerate=sr, channels=1, dtype="float32", blocking=True),
            )
            audio = audio.flatten()

            # Simple energy-based VAD
            energy = float(np.sqrt(np.mean(audio ** 2)))
            if energy < threshold:
                continue

            logger.debug("VAD triggered (energy=%.4f)", energy)

            # Transcribe with Whisper
            try:
                result = await loop.run_in_executor(
                    None,
                    lambda: whisper_model.transcribe(audio, fp16=False, language="en"),
                )
                text = (result.get("text") or "").strip()
                if text:
                    transcript = AudioTranscript(source="microphone", speaker="audience", text=text)
                    logger.info("[Mic transcription] %s", text)
                    await self.push_transcript(transcript)
            except Exception:
                logger.exception("Whisper transcription failed")

    # ── Whisper model loader ──────────────────────────────────────────────────

    async def _load_whisper_model(self):  # noqa: ANN202
        try:
            import whisper  # type: ignore[import-untyped]
        except ImportError:
            logger.error(
                "openai-whisper is required for real transcription. "
                "Install with: pip install openai-whisper"
            )
            return None

        loop = asyncio.get_running_loop()
        logger.info("Loading Whisper model '%s' …", self._cfg.whisper_model)
        model = await loop.run_in_executor(None, whisper.load_model, self._cfg.whisper_model)
        logger.info("Whisper model loaded")
        return model

    # ── Azure Speech continuous recognition ───────────────────────────────────

    async def start_azure_speech_recognition(
        self, speech_key: str, speech_region: str
    ) -> None:
        """
        Use Azure Speech SDK for continuous speech-to-text from the default
        microphone.  Recognised text is pushed as transcript events.
        """
        try:
            import azure.cognitiveservices.speech as speechsdk
        except ImportError:
            logger.error(
                "azure-cognitiveservices-speech is required. "
                "Install with: pip install azure-cognitiveservices-speech"
            )
            return

        speech_config = speechsdk.SpeechConfig(
            subscription=speech_key, region=speech_region
        )
        speech_config.speech_recognition_language = "en-US"
        audio_config = speechsdk.audio.AudioConfig(use_default_microphone=True)

        recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config, audio_config=audio_config
        )

        loop = asyncio.get_running_loop()
        done = asyncio.Event()

        def on_recognized(evt):
            text = evt.result.text.strip() if evt.result.text else ""
            if text:
                logger.info("[Azure STT] %s", text)
                transcript = AudioTranscript(
                    source="microphone", speaker="audience", text=text
                )
                asyncio.run_coroutine_threadsafe(
                    self.push_transcript(transcript), loop
                )

        def on_canceled(evt):
            logger.warning("Azure STT cancelled: %s", evt.reason)
            loop.call_soon_threadsafe(done.set)

        def on_stopped(evt):
            logger.info("Azure STT session stopped")
            loop.call_soon_threadsafe(done.set)

        recognizer.recognized.connect(on_recognized)
        recognizer.canceled.connect(on_canceled)
        recognizer.session_stopped.connect(on_stopped)

        recognizer.start_continuous_recognition()
        logger.info("Azure Speech recognition started (listening on microphone)")

        try:
            await done.wait()
        except asyncio.CancelledError:
            pass
        finally:
            recognizer.stop_continuous_recognition()
            logger.info("Azure Speech recognition stopped")
