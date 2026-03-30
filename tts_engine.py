import asyncio
import logging

from config import AppConfig


class TTSEngine:
    """Abstracts text-to-speech for local simulation and future cloud backends."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._stop_requested = asyncio.Event()
        self._logger = logging.getLogger(self.__class__.__name__)

    def stop_playback(self) -> None:
        self._stop_requested.set()

    async def play_text(self, text: str) -> None:
        self._stop_requested.clear()

        backend = self._config.tts_backend.lower().strip()
        if backend == "local":
            await self._play_local(text)
            return
        if backend == "azure":
            await self._play_azure_stub(text)
            return
        if backend == "openai":
            await self._play_openai_stub(text)
            return

        raise ValueError(f"Unsupported TTS backend: {backend}")

    async def _play_local(self, text: str) -> None:
        words = text.split()
        if not words:
            return

        words_per_second = max(self._config.words_per_minute / 60.0, 1.0)
        step = 4

        for i in range(0, len(words), step):
            if self._stop_requested.is_set():
                self._logger.info("TTS playback stopped due to interruption")
                return
            chunk = " ".join(words[i : i + step])
            self._logger.info("TTS[%s]: %s", self._config.tts_voice, chunk)
            await asyncio.sleep(step / words_per_second)

    async def _play_azure_stub(self, text: str) -> None:
        # Replace with Azure Speech SDK streaming to Teams audio sink.
        self._logger.info("Azure TTS stub called")
        await self._play_local(text)

    async def _play_openai_stub(self, text: str) -> None:
        # Replace with OpenAI audio generation and stream pipeline.
        self._logger.info("OpenAI TTS stub called")
        await self._play_local(text)
