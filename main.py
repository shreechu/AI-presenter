import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass
from typing import List

from audio_listener import AudioListener, AudioTranscript
from config import AppConfig
from slide_controller import Slide, SlideController
from speech_detector import SpeechDetector
from teams_bot import TeamsChatMessage, TeamsPresenterBot
from tts_engine import TTSEngine


@dataclass
class PresentationContext:
    conversation_history: List[str]


class PresenterOrchestrator:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.slide_controller = SlideController(_demo_slides())
        self.tts_engine = TTSEngine(config)
        self.audio_listener = AudioListener()
        self.speech_detector = SpeechDetector(min_chars=config.interruption_min_chars)
        self.teams_bot = TeamsPresenterBot(self.audio_listener)

        self.context = PresentationContext(conversation_history=[])
        self._logger = logging.getLogger(self.__class__.__name__)

    async def run(self) -> None:
        await self.teams_bot.join_meeting("demo-meeting-id")
        self.teams_bot.on_chat_message(self._on_chat_message)

        listener_task = asyncio.create_task(self._consume_audio_events())
        simulated_audio_task = asyncio.create_task(
            self.audio_listener.simulate_microphone_input(
                self.config.simulated_audience_script,
                delay_sec=8.0,
            )
        )
        simulated_teams_task = asyncio.create_task(self.teams_bot.simulate_chat_and_audio_events())

        try:
            await self._presentation_loop()
        finally:
            for task in (listener_task, simulated_audio_task, simulated_teams_task):
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    async def _presentation_loop(self) -> None:
        while True:
            if await self.slide_controller.is_paused():
                await asyncio.sleep(0.2)
                continue

            slide = await self.slide_controller.current_slide()
            self._logger.info("[Presenting speaker notes...] slide=%s title=%s", slide.index, slide.title)

            try:
                await self.tts_engine.play_text(slide.speaker_notes)
                await self.teams_bot.stream_tts_audio(slide.speaker_notes)
            except Exception as exc:
                self._logger.exception("TTS playback failed: %s", exc)

            if await self.slide_controller.is_paused():
                continue

            if not self.config.auto_advance:
                await asyncio.sleep(0.2)
                continue

            next_slide = await self.slide_controller.advance()
            if next_slide is None:
                self._logger.info("Presentation finished")
                return
            await asyncio.sleep(self.config.slide_interval_sec)

    async def _consume_audio_events(self) -> None:
        async for transcript in self.audio_listener.stream_transcripts():
            try:
                await self._handle_transcript(transcript)
            except Exception as exc:
                self._logger.exception("Audio event handling failed: %s", exc)

    async def _handle_transcript(self, transcript: AudioTranscript) -> None:
        event = self.speech_detector.process_transcript(transcript.speaker, transcript.text)
        self._logger.info("[Speech detected] speaker=%s text=%s", event.speaker, event.text)
        if not event.is_interruption:
            return

        if event.question.is_question:
            self._logger.info(
                "[Question detected] confidence=%.2f reason=%s",
                event.question.confidence,
                event.question.reason,
            )

        await self.slide_controller.pause()
        self.tts_engine.stop_playback()
        self._logger.info("[Slide paused]")

        if event.question.is_question and self.config.answer_questions_immediately:
            answer = await self._answer_question(event.text)
            self.context.conversation_history.append(f"Q: {event.text}")
            self.context.conversation_history.append(f"A: {answer}")
            await self.teams_bot.post_chat_message(answer)
            await self.tts_engine.play_text(answer)
        else:
            self._logger.info("Interruption ignored for immediate answer; waiting to resume")

        await self.slide_controller.resume()
        self._logger.info("[Slide resumed]")

    async def _answer_question(self, question: str) -> str:
        relevant_slide = await self.slide_controller.find_relevant_slide(question)
        current_slide = await self.slide_controller.current_slide()

        if relevant_slide and relevant_slide.index != current_slide.index:
            await self.slide_controller.jump_to(relevant_slide.index)
            self._logger.info("Jumped to relevant slide: %s", relevant_slide.index)

        target = relevant_slide or current_slide
        snippet = target.speaker_notes.strip().split(".")[0]
        if not snippet:
            snippet = "I do not have enough note context for that answer yet"
        return (
            f"Great question. Based on slide {target.index} ({target.title}), "
            f"the key point is: {snippet}."
        )

    async def _on_chat_message(self, msg: TeamsChatMessage) -> None:
        await self.audio_listener.push_transcript(
            AudioTranscript(source="teams-chat", speaker=msg.sender, text=msg.text)
        )


def _demo_slides() -> List[Slide]:
    return [
        Slide(
            index=0,
            title="Vision and Problem",
            speaker_notes=(
                "Welcome everyone. We are building an AI-powered Teams presenter bot that can "
                "narrate slides, monitor audience signals, and adapt in real time."
            ),
        ),
        Slide(
            index=1,
            title="Architecture",
            speaker_notes=(
                "The architecture is event-driven and modular, with independent components for "
                "slide control, speech detection, question classification, and Teams integration."
            ),
        ),
        Slide(
            index=2,
            title="Safety and Reliability",
            speaker_notes=(
                "The system logs every important event and handles API or playback errors "
                "gracefully so the presentation can continue without crashing."
            ),
        ),
    ]


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


async def _main() -> None:
    config = AppConfig()
    _configure_logging(config.log_level)
    orchestrator = PresenterOrchestrator(config)
    await orchestrator.run()


if __name__ == "__main__":
    asyncio.run(_main())
