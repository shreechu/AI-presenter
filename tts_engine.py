"""
Text-to-speech engine with three backends:

  * **local**  — pyttsx3 offline synthesis (falls back to console simulation).
  * **azure**  — Azure Cognitive Services Speech SDK.
  * **openai** — OpenAI TTS API.

All backends honour ``stop_playback()`` for mid-utterance cancellation.
"""

from __future__ import annotations

import asyncio
import io
import logging
import tempfile
from pathlib import Path
from typing import Optional

from config import TTSConfig

logger = logging.getLogger(__name__)


class TTSEngine:
    """Unified TTS facade.  Backends are chosen via ``TTSConfig.backend``."""

    def __init__(self, config: TTSConfig) -> None:
        self._cfg = config
        self._stop = asyncio.Event()
        self._speaking = False

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    def stop_playback(self) -> None:
        """Request the current utterance to stop as soon as possible."""
        self._stop.set()

    async def speak(self, text: str) -> None:
        """Convert *text* to audio and play it.  Blocks until done or stopped."""
        self._stop.clear()
        self._speaking = True
        try:
            backend = self._cfg.backend.lower().strip()
            if backend == "azure":
                await self._speak_azure(text)
            elif backend == "openai":
                await self._speak_openai(text)
            else:
                await self._speak_local(text)
        finally:
            self._speaking = False

    # ── Local backend (pyttsx3 → fallback console) ────────────────────────────

    async def _speak_local(self, text: str) -> None:
        try:
            import pyttsx3  # type: ignore[import-untyped]
            await self._speak_pyttsx3(text, pyttsx3)
        except ImportError:
            logger.debug("pyttsx3 not installed — falling back to console simulation")
            await self._speak_console(text)

    async def _speak_pyttsx3(self, text: str, pyttsx3_mod) -> None:  # noqa: ANN001
        """Offload blocking pyttsx3 to a thread; chunk text so we can cancel."""
        engine = pyttsx3_mod.init()
        engine.setProperty("rate", self._cfg.words_per_minute)

        sentences = _split_sentences(text)
        for sentence in sentences:
            if self._stop.is_set():
                logger.info("TTS stopped (pyttsx3)")
                break
            logger.info("[TTS pyttsx3] %s", sentence)
            await asyncio.get_running_loop().run_in_executor(
                None, lambda s=sentence: (engine.say(s), engine.runAndWait()),  # type: ignore[misc]
            )
        engine.stop()

    async def _speak_console(self, text: str) -> None:
        """Print words to the log at speaking-pace (no audio)."""
        words = text.split()
        if not words:
            return
        wps = max(self._cfg.words_per_minute / 60.0, 1.0)
        step = 5
        for i in range(0, len(words), step):
            if self._stop.is_set():
                logger.info("TTS stopped (console)")
                return
            chunk = " ".join(words[i : i + step])
            logger.info("[TTS] %s", chunk)
            await asyncio.sleep(step / wps)

    # ── Azure backend ─────────────────────────────────────────────────────────

    async def _speak_azure(self, text: str) -> None:
        try:
            import azure.cognitiveservices.speech as speechsdk  # type: ignore[import-untyped]
        except ImportError:
            logger.warning("azure-cognitiveservices-speech not installed — falling back to local TTS")
            await self._speak_local(text)
            return

        if not self._cfg.azure_speech_key:
            logger.warning("AZURE_SPEECH_KEY not set — falling back to local TTS")
            await self._speak_local(text)
            return

        speech_config = speechsdk.SpeechConfig(
            subscription=self._cfg.azure_speech_key,
            region=self._cfg.azure_speech_region,
        )
        speech_config.speech_synthesis_voice_name = self._cfg.voice

        synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config)

        sentences = _split_sentences(text)
        loop = asyncio.get_running_loop()
        for sentence in sentences:
            if self._stop.is_set():
                logger.info("TTS stopped (Azure)")
                break
            logger.info("[TTS Azure] %s", sentence)
            result = await loop.run_in_executor(None, synthesizer.speak_text_async(sentence).get)
            if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
                logger.error("Azure TTS failed: %s", result.reason)
                break

    # ── OpenAI backend ────────────────────────────────────────────────────────

    async def _speak_openai(self, text: str) -> None:
        try:
            from openai import OpenAI  # type: ignore[import-untyped]
        except ImportError:
            logger.warning("openai package not installed — falling back to local TTS")
            await self._speak_local(text)
            return

        if not self._cfg.openai_api_key:
            logger.warning("OPENAI_API_KEY not set — falling back to local TTS")
            await self._speak_local(text)
            return

        client = OpenAI(api_key=self._cfg.openai_api_key)
        loop = asyncio.get_running_loop()

        sentences = _split_sentences(text)
        for sentence in sentences:
            if self._stop.is_set():
                logger.info("TTS stopped (OpenAI)")
                break

            logger.info("[TTS OpenAI] %s", sentence)
            try:
                response = await loop.run_in_executor(
                    None,
                    lambda s=sentence: client.audio.speech.create(
                        model=self._cfg.openai_tts_model,
                        voice=self._cfg.openai_tts_voice,
                        input=s,
                    ),
                )
                # Write to temp file and play via platform player
                await self._play_audio_bytes(response.content)
            except Exception:
                logger.exception("OpenAI TTS request failed")
                break

    # ── Audio playback helper ─────────────────────────────────────────────────

    async def _play_audio_bytes(self, audio_bytes: bytes) -> None:
        """Play audio bytes through available player (sounddevice → playsound → skip)."""
        try:
            import sounddevice as sd  # type: ignore[import-untyped]
            import soundfile as sf  # type: ignore[import-untyped]

            data, samplerate = sf.read(io.BytesIO(audio_bytes))
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: sd.play(data, samplerate))
            await loop.run_in_executor(None, sd.wait)
            return
        except ImportError:
            pass

        # Fallback: save to temp file (skip actual playback)
        tmp = Path(tempfile.gettempdir()) / "tts_output.mp3"
        tmp.write_bytes(audio_bytes)
        logger.info("Audio saved to %s (no playback library available)", tmp)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _split_sentences(text: str) -> list[str]:
    """Split text on sentence boundaries for chunked TTS with cancellation points."""
    import re
    raw = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s for s in raw if s]
