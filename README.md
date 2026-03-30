# AI Presentation Assistant (MVP)

Async, event-driven Python prototype for a Teams presenter bot that:

- Reads slide speaker notes with TTS
- Auto-advances slides
- Listens for audience interruptions/questions (simulated)
- Pauses/resumes presentation
- Maps questions to relevant slides and answers
- Simulates Teams audio/chat integration

## Project Structure

- `audio_listener.py` - transcript/audio input stream abstraction
- `speech_detector.py` - interruption and speech event extraction
- `question_classifier.py` - heuristic question detection
- `slide_controller.py` - current slide state, pause/resume, jump, notes
- `tts_engine.py` - local/Azure/OpenAI TTS abstraction (Azure/OpenAI stubs)
- `teams_bot.py` - simulated Teams integration layer
- `main.py` - orchestrator and event loop
- `config.py` - runtime configuration

## Run

```bash
python main.py
```

## Configuration

Edit values in `AppConfig` in `config.py`:

- `slide_interval_sec`
- `tts_backend` and `tts_voice`
- `question_confidence_threshold`
- `interruption_min_chars`
- `answer_questions_immediately`
- `simulated_audience_script`

## Replace Simulation with Real Services

1. Audio input:
- Replace `AudioListener.simulate_microphone_input` with Teams media stream or microphone capture.
- Add Whisper real-time transcription and push text via `push_transcript`.

2. TTS:
- Replace `_play_azure_stub` with Azure Speech SDK synthesis and stream chunks to Teams.
- Replace `_play_openai_stub` with OpenAI TTS generation and playback/streaming.

3. Teams:
- Replace `TeamsPresenterBot` simulation methods with Microsoft Graph/Teams bot APIs.

## Notes

This MVP is intentionally simple and focuses on architecture and control flow.
