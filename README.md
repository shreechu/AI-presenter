# AI Presenter Bot for Microsoft Teams

An async, event-driven Python bot that autonomously presents slide decks, speaks
speaker notes via TTS, listens for audience questions and commands, pauses /
resumes on interruptions, generates answers from slide context (optionally via
OpenAI), and integrates with Microsoft Teams meetings.

---

## Features

| Capability | What it does |
|---|---|
| **Slide control** | Auto-advance, pause / resume, jump to relevant slide, load from `.pptx` or use built-in demo deck |
| **Text-to-speech** | Local (pyttsx3 / console), Azure Neural TTS, or OpenAI TTS — mid-sentence cancellation on interruption |
| **Real-time audio** | Microphone capture via `sounddevice` + Whisper transcription, or simulated audience input |
| **Question & intent detection** | Heuristic classifier (always available) + optional LLM classifier via OpenAI |
| **Command recognition** | Voice / chat commands: *next slide*, *go back*, *pause*, *resume* |
| **Answer generation** | TF-IDF slide search + LLM-powered answers (falls back to note excerpts) |
| **Teams integration** | Simulated meeting join, chat posting, slide highlights; real Graph API placeholders ready |
| **Presenter UI** | Terminal status line: 📑 slide, 🔊 TTS, 🎤 speech, ⏸️ pause, ▶️ resume, ✅ done |
| **Conversation tracking** | Full Q&A history, slides-presented count, post-presentation summary |

---

## Architecture

```
main.py ← orchestrator + CLI
 ├─ config.py            ← env-var-driven composite configuration
 ├─ slide_controller.py  ← PPTX loader, navigation, TF-IDF relevance search
 ├─ tts_engine.py        ← local / Azure / OpenAI TTS with cancellation
 ├─ audio_listener.py    ← mic capture, Whisper, simulation feeder
 ├─ speech_detector.py   ← interruption detector + async LLM path
 ├─ question_classifier.py ← heuristic + LLM question/command/feedback classifier
 └─ teams_bot.py         ← Teams adapter (simulation + Graph API placeholders)
```

All modules use **async / await** and communicate through `asyncio.Queue` events.

---

## Quick start

```bash
# 1. Clone
git clone https://github.com/shreechu/AI-presenter.git
cd AI-presenter

# 2. Create a virtual environment (recommended)
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # macOS / Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run with the built-in demo deck
python main.py
```

### Load a PowerPoint file
```bash
python main.py --pptx path/to/deck.pptx
```

### Use Azure Neural TTS
```bash
set AZURE_SPEECH_KEY=<your-key>
set AZURE_SPEECH_REGION=eastus
python main.py --tts azure
```

### Use OpenAI TTS + LLM answers
```bash
set OPENAI_API_KEY=<your-key>
python main.py --tts openai --llm
```

### Enable real microphone + Whisper
```bash
pip install openai-whisper sounddevice numpy
python main.py --mic
```

### Disable simulated events (silent mode)
```bash
python main.py --no-sim
```

---

## CLI flags

| Flag | Description |
|---|---|
| `--pptx PATH` | Load slides from a `.pptx` file |
| `--tts {local,azure,openai}` | Choose TTS backend |
| `--mic` | Enable real microphone capture + Whisper |
| `--no-sim` | Disable simulated audience events |
| `--no-auto` | Disable auto-advance (manual slide control) |
| `--llm` | Enable LLM-based classification & answer generation |
| `--log {DEBUG,INFO,WARNING,ERROR}` | Set log verbosity |

---

## Environment variables

All configuration can be set via env vars (see `config.py` for full list):

| Variable | Default | Description |
|---|---|---|
| `PPTX_PATH` | *(none)* | Path to `.pptx` file |
| `SLIDE_INTERVAL_SEC` | `2.0` | Seconds between slides |
| `TTS_BACKEND` | `local` | `local` / `azure` / `openai` |
| `TTS_VOICE` | `en-US-AriaNeural` | Azure voice name |
| `TTS_WPM` | `160` | Speaking rate (words per minute) |
| `AZURE_SPEECH_KEY` | — | Azure Cognitive Services key |
| `AZURE_SPEECH_REGION` | `eastus` | Azure region |
| `OPENAI_API_KEY` | — | OpenAI API key (TTS + LLM) |
| `OPENAI_TTS_MODEL` | `tts-1` | OpenAI TTS model |
| `OPENAI_TTS_VOICE` | `alloy` | OpenAI TTS voice |
| `OPENAI_CHAT_MODEL` | `gpt-4o` | LLM model for answers |
| `USE_REAL_MIC` | `false` | Enable microphone capture |
| `WHISPER_MODEL` | `base` | Whisper model size |
| `TEAMS_APP_ID` | — | Bot Framework App ID |
| `TEAMS_APP_PASSWORD` | — | Bot Framework App Password |
| `TEAMS_TENANT_ID` | — | Azure AD tenant |
| `TEAMS_SIMULATE` | `true` | Enable simulated Teams events |

---

## Replacing simulation with real services

1. **Audio input** — Set `USE_REAL_MIC=true`, install `sounddevice`, `numpy`, and `openai-whisper`.
2. **TTS** — Set `TTS_BACKEND=azure` (or `openai`) and provide API keys.
3. **Teams** — Register a Bot Channel in Azure, set `TEAMS_APP_ID` / `TEAMS_APP_PASSWORD` / `TEAMS_TENANT_ID`, then implement the Graph API calls in `teams_bot.py._join_real_meeting()`.

---

## License

MIT
