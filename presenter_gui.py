"""
Windows GUI for the AI Presenter Bot.

Controls:
  1. File picker + Load button (opens PPT in slideshow mode)
  2. Start Presenting / Pause / Stop buttons
  3. Status bar

Runs the async orchestrator on a background thread so the UI stays responsive.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

from config import AppConfig
from pptx_presenter import PowerPointPresenter
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
        self._ppt = PowerPointPresenter()  # shared instance for Load button

        self._build_ui()
        self._set_state("idle")

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        pad = {"padx": 12, "pady": 6}
        frame = tk.Frame(self._root, padx=16, pady=16)
        frame.pack()

        # Row 0 — file picker + Load
        tk.Label(frame, text="Presentation file:", anchor="w").grid(
            row=0, column=0, sticky="w", **pad
        )
        self._file_var = tk.StringVar()
        entry = tk.Entry(frame, textvariable=self._file_var, width=48, state="readonly")
        entry.grid(row=0, column=1, **pad)

        btn_frame = tk.Frame(frame)
        btn_frame.grid(row=0, column=2, **pad)
        tk.Button(btn_frame, text="Browse...", command=self._browse).pack(side="left", padx=(0, 4))
        self._btn_load = tk.Button(
            btn_frame, text="Load", width=8,
            bg="#5B5FC7", fg="white", command=self._load,
        )
        self._btn_load.pack(side="left")

        # Row 1 — Start / Pause / Stop
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
            self._set_state("idle")  # reset if re-browsing

    def _load(self) -> None:
        """Open the selected PPTX in PowerPoint slideshow mode."""
        pptx = self._file_var.get().strip()
        if not pptx:
            messagebox.showwarning("No file selected", "Please choose a .pptx file first.")
            return
        self._status_var.set("Loading slideshow...")
        self._btn_load.config(state="disabled")
        # Run COM call on a thread to keep UI responsive
        threading.Thread(target=self._load_sync, args=(pptx,), daemon=True).start()

    def _load_sync(self, pptx: str) -> None:
        loop = asyncio.new_event_loop()
        try:
            ok = loop.run_until_complete(self._ppt.open_and_start(pptx))
        except Exception:
            ok = False
            logger.exception("Failed to load slideshow")
        finally:
            loop.close()
        if ok:
            self._root.after(0, lambda: self._set_state("loaded"))
        else:
            self._root.after(0, lambda: self._set_state("idle"))
            self._root.after(0, lambda: messagebox.showerror(
                "Load failed", "Could not open PowerPoint in slideshow mode."
            ))

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
        # Share the already-loaded PPT instance so run() doesn't re-open it
        self._orchestrator.ppt = self._ppt

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
            self._root.after(0, lambda: self._set_state(
                "loaded" if self._ppt.is_active else "idle"
            ))

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
        # Close slideshow if still active
        if self._ppt.is_active:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(self._ppt.close())
            finally:
                loop.close()
        self._root.after(500, self._root.destroy)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_state(self, state: str) -> None:
        if state == "loaded":
            # PPT is in slideshow mode, ready to start narration
            self._btn_load.config(state="disabled")
            self._btn_start.config(state="normal")
            self._btn_pause.config(state="disabled")
            self._btn_stop.config(state="disabled")
            self._paused = False
            self._btn_pause.config(text="Pause", bg="#E68A00")
            self._status_var.set("Slideshow loaded — click Start Presenting")
        elif state == "running":
            self._btn_load.config(state="disabled")
            self._btn_start.config(state="disabled")
            self._btn_pause.config(state="normal")
            self._btn_stop.config(state="normal")
            self._paused = False
            self._btn_pause.config(text="Pause", bg="#E68A00")
            self._status_var.set("Presenting... (listening on microphone)")
        elif state == "stopping":
            self._btn_load.config(state="disabled")
            self._btn_start.config(state="disabled")
            self._btn_pause.config(state="disabled")
            self._btn_stop.config(state="disabled")
            self._status_var.set("Stopping...")
        else:  # idle
            self._btn_load.config(state="normal")
            self._btn_start.config(state="disabled")
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
