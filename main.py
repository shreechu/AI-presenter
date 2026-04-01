"""
Presenter-bot orchestrator.

  python main.py                       # run with built-in demo deck
  python main.py --pptx deck.pptx      # load a real PowerPoint file
  python main.py --tts azure           # use Azure Neural TTS
  python main.py --mic                 # use real microphone + Whisper
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from contextlib import suppress
from dataclasses import dataclass, field
from typing import List, Optional

from audio_listener import AudioListener, AudioTranscript
from config import AppConfig
from pptx_presenter import PowerPointPresenter
from question_classifier import (
    ClassificationResult,
    Intent,
    LLMQuestionClassifier,
    QuestionClassifier,
)
from slide_controller import Slide, SlideController, demo_slides, load_slides_from_pptx
from speech_detector import SpeechDetector
from teams_bot import TeamsChatMessage, TeamsPresenterBot
from tts_engine import TTSEngine

logger = logging.getLogger("presenter")


# ── Conversation context ──────────────────────────────────────────────────────

@dataclass
class PresentationContext:
    conversation_history: List[str] = field(default_factory=list)
    slides_presented: List[int] = field(default_factory=list)
    questions_answered: int = 0


# ── Orchestrator ──────────────────────────────────────────────────────────────

class PresenterOrchestrator:
    """Drives the full presentation lifecycle."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config

        # Load slides
        if config.slide.pptx_path:
            slides = load_slides_from_pptx(config.slide.pptx_path)
        else:
            slides = demo_slides()

        self.slide_ctrl = SlideController(slides)
        self.tts = TTSEngine(config.tts)
        self.audio = AudioListener(config.audio)
        self.teams = TeamsPresenterBot(config.teams, self.audio)
        self.ppt = PowerPointPresenter()
        self.context = PresentationContext()

        # Classifiers
        llm_cls: Optional[LLMQuestionClassifier] = None
        if config.detection.use_llm_classifier and config.llm.openai_api_key:
            try:
                llm_cls = LLMQuestionClassifier(
                    api_key=config.llm.openai_api_key,
                    model=config.llm.model,
                    azure_endpoint=config.llm.azure_endpoint,
                    azure_api_version=config.llm.azure_api_version,
                )
                logger.info("LLM classifier enabled (model=%s, azure=%s)", config.llm.model, config.llm.is_azure)
            except ImportError:
                logger.warning("openai package not installed — LLM classifier disabled")

        self.detector = SpeechDetector(
            min_chars=config.detection.interruption_min_chars,
            llm_classifier=llm_cls,
        )

        self._shutdown = asyncio.Event()
        self._answering = asyncio.Event()  # set while Q&A is in progress
        self._answering.set()  # starts in "not answering" state (set = clear to proceed)

    # ── Run ───────────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Entry-point: connect to Teams, start background tasks, present."""
        _install_signal_handlers(self._shutdown)

        await self.teams.join_meeting("demo-meeting-id")
        self.teams.on_chat_message(self._on_chat_message)

        # Launch PowerPoint slideshow if we loaded a real PPTX
        if self.config.slide.pptx_path:
            ok = await self.ppt.open_and_start(self.config.slide.pptx_path)
            if ok:
                _status("[PPT] Slideshow launched")
            else:
                _status("[PPT] Could not launch slideshow — continuing without it")

        tasks: list[asyncio.Task] = [
            asyncio.create_task(self._consume_audio_events(), name="audio-consumer"),
        ]

        # Simulated events
        if self.config.teams.enable_simulated_events:
            tasks.append(asyncio.create_task(
                self.audio.simulate_microphone_input(
                    self.config.simulation.audience_script,
                    delay_sec=self.config.simulation.audience_delay_sec,
                ),
                name="sim-mic",
            ))
            tasks.append(asyncio.create_task(
                self.teams.simulate_chat_and_audio_events(),
                name="sim-teams",
            ))

        # Real microphone
        if self.config.audio.use_real_mic:
            tasks.append(asyncio.create_task(
                self.audio.start_microphone_capture(),
                name="mic-capture",
            ))

        try:
            await self._presentation_loop()
        finally:
            for t in tasks:
                t.cancel()
                with suppress(asyncio.CancelledError):
                    await t
            await self.ppt.close()
            await self.teams.leave_meeting()
            self._print_summary()

    # ── Presentation loop ─────────────────────────────────────────────────────

    async def _presentation_loop(self) -> None:
        while not self._shutdown.is_set():
            # Wait while paused
            while await self.slide_ctrl.is_paused() and not self._shutdown.is_set():
                await asyncio.sleep(0.2)
            if self._shutdown.is_set():
                return

            slide = await self.slide_ctrl.current_slide()
            idx, total = await self.slide_ctrl.progress()
            self.context.slides_presented.append(slide.index)

            _status(f"[Slide {idx + 1}/{total}] {slide.title}")

            # Sync live PowerPoint slideshow
            await self.ppt.goto_slide(slide.index)

            # Notify Teams chat about current slide
            await self.teams.post_slide_highlight(slide.index, slide.title)

            # Speak the notes
            if slide.speaker_notes:
                _status("[Speaking notes...]")
                try:
                    await self.tts.speak(slide.speaker_notes)
                except Exception:
                    logger.exception("TTS playback failed on slide %d", slide.index)

            # Wait for any in-progress Q&A to finish before advancing
            await self._answering.wait()

            # If paused (by interrupt or command), wait for resume
            while await self.slide_ctrl.is_paused() and not self._shutdown.is_set():
                await asyncio.sleep(0.2)
            if self._shutdown.is_set():
                return

            # Auto-advance
            if self.config.slide.auto_advance:
                if not await self.slide_ctrl.has_next():
                    _status("[DONE] Presentation complete!")
                    return
                await asyncio.sleep(self.config.slide.slide_interval_sec)
                next_slide = await self.slide_ctrl.advance()
                if next_slide is None:
                    _status("[DONE] Presentation complete!")
                    return
            else:
                # Manual mode — wait until someone advances us
                while not self._shutdown.is_set():
                    await asyncio.sleep(0.3)

    # ── Audio event handling ──────────────────────────────────────────────────

    async def _consume_audio_events(self) -> None:
        async for transcript in self.audio.stream_transcripts():
            try:
                await self._handle_transcript(transcript)
            except Exception:
                logger.exception("Error handling transcript")

    async def _handle_transcript(self, transcript: AudioTranscript) -> None:
        event = await self.detector.process_async(transcript.speaker, transcript.text)
        _status(f"[Speech: {event.speaker}] {event.text}")

        if not event.is_interruption:
            return

        intent = event.classification.intent

        # ── Command handling ──────────────────────────────────────────────────
        if intent == Intent.COMMAND:
            await self._handle_command(event.classification)
            return

        # ── Feedback (acknowledge and continue) ──────────────────────────────
        if intent == Intent.FEEDBACK:
            logger.info("Feedback received: %s", event.text)
            return

        # ── Question or unknown interruption → pause ─────────────────────────
        self._answering.clear()  # signal presentation loop to wait
        await self.slide_ctrl.pause()
        self.tts.stop_playback()
        _status("[PAUSED] for interruption")

        try:
            if event.classification.is_question and self.config.detection.answer_questions_immediately:
                _status("[Generating answer...]")
                answer = await self._answer_question(event.text)
                self.context.conversation_history.append(f"Q: {event.text}")
                self.context.conversation_history.append(f"A: {answer}")
                self.context.questions_answered += 1

                await self.teams.post_chat_message(f"A: {answer}")

                _status(f"[Answer] {answer}")
                try:
                    await self.tts.speak(answer)
                except Exception:
                    logger.exception("TTS failed while answering")
            else:
                logger.info("Non-question interruption — resuming shortly")
        finally:
            await self.slide_ctrl.resume()
            self._answering.set()  # allow presentation loop to continue
            _status("[RESUMED]")

    # ── Command execution ─────────────────────────────────────────────────────

    async def _handle_command(self, cls: ClassificationResult) -> None:
        cmd = cls.command
        if cmd == "next":
            s = await self.slide_ctrl.advance()
            if s:
                await self.ppt.goto_slide(s.index)
                _status(f"[>> Skipped to slide {s.index + 1}] {s.title}")
            else:
                _status("Already on the last slide")
        elif cmd == "back":
            s = await self.slide_ctrl.go_back()
            if s:
                await self.ppt.goto_slide(s.index)
                _status(f"[<< Back to slide {s.index + 1}] {s.title}")
            else:
                _status("Already on the first slide")
        elif cmd == "pause":
            await self.slide_ctrl.pause()
            self.tts.stop_playback()
            _status("[PAUSED by command]")
        elif cmd == "resume":
            await self.slide_ctrl.resume()
            _status("[RESUMED by command]")
        else:
            logger.warning("Unknown command: %s", cmd)

    # ── Answer generation ─────────────────────────────────────────────────────

    async def _answer_question(self, question: str) -> str:
        """Generate an answer from slide context, optionally powered by LLM."""
        relevant = await self.slide_ctrl.find_relevant_slide(question)
        current = await self.slide_ctrl.current_slide()

        # Jump to the relevant slide if different
        if relevant and relevant.index != current.index:
            await self.slide_ctrl.jump_to(relevant.index)
            await self.ppt.goto_slide(relevant.index)
            _status(f"[-> Jumped to slide {relevant.index + 1}] {relevant.title}")

        target = relevant or current

        # Try LLM-powered answer first
        if self.config.llm.openai_api_key:
            try:
                return await self._llm_answer(question, target)
            except Exception:
                logger.exception("LLM answer generation failed — using notes excerpt")

        # Fallback: extract first sentence from notes
        snippet = target.speaker_notes.strip().split(".")[0]
        if not snippet:
            snippet = "I don't have enough context in my notes for that yet"
        return f"Based on slide {target.index + 1} ({target.title}): {snippet}."

    async def _llm_answer(self, question: str, slide: Slide) -> str:
        client = _get_openai_client(self.config.llm)
        loop = asyncio.get_running_loop()

        system = (
            "You are the AI presentation assistant. Answer audience questions "
            "concisely (2-3 sentences) using ONLY the slide context provided. "
            "Be friendly and professional."
        )
        user_msg = (
            f"## Current slide: {slide.title}\n\n"
            f"### Speaker notes:\n{slide.speaker_notes}\n\n"
            f"### Question:\n{question}"
        )

        resp = await loop.run_in_executor(
            None,
            lambda: client.chat.completions.create(
                model=self.config.llm.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=self.config.llm.max_answer_tokens,
                temperature=0.4,
            ),
        )
        return (resp.choices[0].message.content or "").strip()

    # ── Chat ──────────────────────────────────────────────────────────────────

    async def _on_chat_message(self, msg: TeamsChatMessage) -> None:
        """Route a Teams chat message into the audio pipeline."""
        await self.audio.push_transcript(
            AudioTranscript(source="teams-chat", speaker=msg.sender, text=msg.text)
        )

    # ── Summary ───────────────────────────────────────────────────────────────

    def _print_summary(self) -> None:
        print("\n" + "=" * 60)
        print("  PRESENTATION SUMMARY")
        print("=" * 60)
        print(f"  Slides presented : {len(set(self.context.slides_presented))}/{self.slide_ctrl.total_slides}")
        print(f"  Questions answered: {self.context.questions_answered}")
        if self.context.conversation_history:
            print("\n  Conversation log:")
            for entry in self.context.conversation_history:
                print(f"    {entry}")
        print("=" * 60 + "\n")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _status(msg: str) -> None:
    """Print a presenter-UI status line and log it."""
    try:
        print(f"  {msg}")
    except UnicodeEncodeError:
        # Windows console may not support emoji — strip them
        safe = msg.encode("ascii", errors="replace").decode("ascii")
        print(f"  {safe}")
    logger.info(msg)


def _install_signal_handlers(shutdown_event: asyncio.Event) -> None:
    """Allow Ctrl+C to trigger graceful shutdown."""
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown_event.set)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler for SIGTERM
            pass


def _get_openai_client(llm_cfg):
    """Return an AzureOpenAI or OpenAI client depending on config."""
    if llm_cfg.is_azure:
        from openai import AzureOpenAI  # type: ignore[import-untyped]
        return AzureOpenAI(
            api_key=llm_cfg.openai_api_key,
            azure_endpoint=llm_cfg.azure_endpoint,
            api_version=llm_cfg.azure_api_version,
        )
    else:
        from openai import OpenAI  # type: ignore[import-untyped]
        return OpenAI(api_key=llm_cfg.openai_api_key)


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AI Presenter Bot for Microsoft Teams")
    p.add_argument("--pptx", help="Path to a .pptx file to present")
    p.add_argument("--tts", choices=["local", "azure", "openai"], default=None, help="TTS backend")
    p.add_argument("--mic", action="store_true", help="Enable real microphone capture + Whisper")
    p.add_argument("--no-sim", action="store_true", help="Disable simulated audience events")
    p.add_argument("--no-auto", action="store_true", help="Disable auto-advance (manual mode)")
    p.add_argument("--llm", action="store_true", help="Enable LLM-based question classification & answers")
    p.add_argument("--log", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default=None)
    return p.parse_args()


async def _main() -> None:
    args = parse_args()

    config = AppConfig()

    # CLI overrides
    if args.pptx:
        config.slide.pptx_path = args.pptx
    if args.tts:
        config.tts.backend = args.tts
    if args.mic:
        config.audio.use_real_mic = True
    if args.no_sim:
        config.teams.enable_simulated_events = False
    if args.no_auto:
        config.slide.auto_advance = False
    if args.llm:
        config.detection.use_llm_classifier = True
    if args.log:
        config.log_level = args.log

    _configure_logging(config.log_level)

    logger.info("Configuration: %s", config)

    orchestrator = PresenterOrchestrator(config)
    await orchestrator.run()


if __name__ == "__main__":
    asyncio.run(_main())
