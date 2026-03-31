"""
Minimal Windows GUI for the AI Presenter Bot.

Three controls:
  1. File picker — choose a .pptx file
  2. Start Presenting button
  3. Stop Presenting button

Runs the async orchestrator on a background thread so the UI stays responsive.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

from config import AppConfig
from main import PresenterOrchestrator, _configure_logging

logger = logging.getLogger(__name__)


class PresenterApp:
    """Tkinter application that wraps :class:`PresenterOrchestrator`."""

    def __init__(self) -> None:
        self._root = tk.Tk()
        self._root.title("AI Presenter Bot")
        self._root.resizable(False, False)

        # State
        self._orchestrator: PresenterOrchestrator | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._paused = False

        self._build_ui()
        self._set_state("idle")

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        pad = {"padx": 12, "pady": 6}
        frame = tk.Frame(self._root, padx=16, pady=16)
        frame.pack()

        # Row 0 — file picker
        tk.Label(frame, text="Presentation file:", anchor="w").grid(
            row=0, column=0, sticky="w", **pad
        )
        self._file_var = tk.StringVar()
        entry = tk.Entry(frame, textvariable=self._file_var, width=52, state="readonly")
        entry.grid(row=0, column=1, **pad)
        tk.Button(frame, text="Browse...", command=self._browse).grid(
            row=0, column=2, **pad
        )

        # Row 1 — buttons
        self._btn_start = tk.Button(
            frame, text="Start Presenting", width=18,
            bg="#0078D4", fg="white", command=self._start,
        )
        self._btn_start.grid(row=1, column=0, sticky="e", **pad)

        self._btn_pause = tk.Button(
            frame, text="Pause", width=18,
            bg="#E68A00", fg="white", command=self._toggle_pause,
        )
        self._btn_pause.grid(row=1, column=1, **pad)

        self._btn_stop = tk.Button(
            frame, text="Stop Presenting", width=18,
            bg="#D42B2B", fg="white", command=self._stop,
        )
        self._btn_stop.grid(row=1, column=2, sticky="w", **pad)

        # Row 2 — status
        self._status_var = tk.StringVar(value="Ready")
        tk.Label(frame, textvariable=self._status_var, anchor="w", fg="gray").grid(
            row=2, column=0, columnspan=3, sticky="w", **pad
        )

        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _browse(self) -> None:
        path = filedialog.askopenfilename(
            title="Select a PowerPoint file",
            filetypes=[("PowerPoint files", "*.pptx"), ("All files", "*.*")],
        )
        if path:
            self._file_var.set(path)

    def _start(self) -> None:
        pptx = self._file_var.get().strip()
        if not pptx:
            messagebox.showwarning("No file selected", "Please choose a .pptx file first.")
            return

        self._set_state("running")

        config = AppConfig()
        config.slide.pptx_path = pptx
        config.tts.backend = "azure"
        config.teams.enable_simulated_events = False

        _configure_logging(config.log_level)

        self._orchestrator = PresenterOrchestrator(config)

        # Run the async orchestrator on a dedicated thread with its own event loop
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self) -> None:
        """Background thread — creates an event loop and runs the orchestrator."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._orchestrator.run())
        except Exception:
            logger.exception("Presenter crashed")
        finally:
            self._loop.close()
            self._loop = None
            self._root.after(0, lambda: self._set_state("idle"))

    def _toggle_pause(self) -> None:
        if self._orchestrator is None:
            return
        loop = self._loop
        if loop is None or loop.is_closed():
            return

        if self._paused:
            asyncio.run_coroutine_threadsafe(
                self._orchestrator.slide_ctrl.resume(), loop
            )
            self._paused = False
            self._btn_pause.config(text="Pause", bg="#E68A00")
            self._status_var.set("Presenting...")
        else:
            asyncio.run_coroutine_threadsafe(
                self._orchestrator.slide_ctrl.pause(), loop
            )
            self._orchestrator.tts.stop_playback()
            self._paused = False  # reset so next speak() works
            self._paused = True
            self._btn_pause.config(text="Resume", bg="#2D7D2D")
            self._status_var.set("Paused")

    def _stop(self) -> None:
        if self._orchestrator is not None:
            self._orchestrator._shutdown.set()
            self._orchestrator.tts.stop_playback()
        self._set_state("stopping")
        self._status_var.set("Stopping...")

    def _on_close(self) -> None:
        self._stop()
        self._root.after(500, self._root.destroy)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_state(self, state: str) -> None:
        if state == "running":
            self._btn_start.config(state="disabled")
            self._btn_pause.config(state="normal")
            self._btn_stop.config(state="normal")
            self._paused = False
            self._btn_pause.config(text="Pause", bg="#E68A00")
            self._status_var.set("Presenting...")
        elif state == "stopping":
            self._btn_start.config(state="disabled")
            self._btn_pause.config(state="disabled")
            self._btn_stop.config(state="disabled")
            self._status_var.set("Stopping...")
        else:
            self._btn_start.config(state="normal")
            self._btn_pause.config(state="disabled")
            self._btn_stop.config(state="disabled")
            self._paused = False
            self._btn_pause.config(text="Pause", bg="#E68A00")
            self._status_var.set("Ready")

    def run(self) -> None:
        """Start the Tk main loop."""
        self._root.mainloop()


if __name__ == "__main__":
    PresenterApp().run()
