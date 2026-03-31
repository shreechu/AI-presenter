"""
PowerPoint COM automation — opens a deck in slideshow mode and
advances / jumps slides in sync with the presenter bot.

Uses ``win32com`` (pywin32) on Windows.  On other platforms the module
gracefully degrades to a no-op logger.

All COM calls are dispatched to a single dedicated thread to avoid
marshalling errors (COM objects are apartment-threaded).
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Single-thread pool shared by all COM operations so every call runs
# on the thread that called CoInitialize.
_com_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ppt-com")


class PowerPointPresenter:
    """Drive a live PowerPoint slideshow via COM automation."""

    def __init__(self) -> None:
        self._app = None          # PowerPoint.Application COM object
        self._slideshow = None    # SlideShowWindow
        self._total_slides = 0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def open_and_start(self, pptx_path: str) -> bool:
        """
        Open *pptx_path* in PowerPoint and start the slideshow.

        Returns ``True`` on success, ``False`` if COM is unavailable.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_com_executor, self._open_sync, pptx_path)

    def _open_sync(self, pptx_path: str) -> bool:
        try:
            import win32com.client  # type: ignore[import-untyped]
            import pythoncom        # type: ignore[import-untyped]
            pythoncom.CoInitialize()
        except ImportError:
            logger.warning(
                "pywin32 not installed — PowerPoint automation disabled. "
                "Install with: pip install pywin32"
            )
            return False

        abs_path = str(Path(pptx_path).resolve())
        logger.info("Opening PowerPoint: %s", abs_path)

        try:
            self._app = win32com.client.Dispatch("PowerPoint.Application")
            self._app.Visible = True

            presentation = self._app.Presentations.Open(abs_path, WithWindow=True)
            self._total_slides = presentation.Slides.Count

            # Start slideshow from slide 1
            ss_settings = presentation.SlideShowSettings
            ss_settings.StartingSlide = 1
            ss_settings.EndingSlide = self._total_slides
            ss_settings.AdvanceMode = 1  # Manual advance (we control it)
            self._slideshow = ss_settings.Run()

            logger.info(
                "Slideshow started (%d slides)", self._total_slides
            )
            return True

        except Exception:
            logger.exception("Failed to open PowerPoint slideshow")
            return False

    async def close(self) -> None:
        """End the slideshow (leave PowerPoint open)."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(_com_executor, self._close_sync)

    def _close_sync(self) -> None:
        try:
            if self._slideshow:
                self._slideshow.View.Exit()
                logger.info("Slideshow ended")
        except Exception:
            logger.debug("Slideshow already closed")
        self._slideshow = None

    # ── Navigation ────────────────────────────────────────────────────────────

    async def goto_slide(self, slide_index: int) -> None:
        """
        Navigate the live slideshow to *slide_index* (0-based).

        PowerPoint COM uses 1-based slide numbers internally.
        """
        if not self._slideshow:
            return
        ppt_num = slide_index + 1  # convert 0-based → 1-based
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(_com_executor, self._goto_sync, ppt_num)

    def _goto_sync(self, ppt_slide_number: int) -> None:
        try:
            view = self._slideshow.View
            view.GotoSlide(ppt_slide_number)
            logger.info("PowerPoint → slide %d", ppt_slide_number)
        except Exception:
            logger.exception("Failed to navigate PowerPoint to slide %d", ppt_slide_number)

    async def next_slide(self) -> None:
        """Advance to the next slide in the live slideshow."""
        if not self._slideshow:
            return
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(_com_executor, self._next_sync)

    def _next_sync(self) -> None:
        try:
            self._slideshow.View.Next()
            logger.info("PowerPoint → next slide")
        except Exception:
            logger.exception("Failed to advance PowerPoint slide")

    async def previous_slide(self) -> None:
        """Go back one slide in the live slideshow."""
        if not self._slideshow:
            return
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(_com_executor, self._prev_sync)

    def _prev_sync(self) -> None:
        try:
            self._slideshow.View.Previous()
            logger.info("PowerPoint → previous slide")
        except Exception:
            logger.exception("Failed to go back in PowerPoint")

    @property
    def is_active(self) -> bool:
        return self._slideshow is not None
