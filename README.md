# Voice Help Agent

This repo now has a clean `app/` scaffold for the voice helpdesk pipeline:

```text
app/
├── main.py
├── config.py
├── stt/whisper_local.py
├── llm/local_llm.py
├── tts/local_tts.py
├── kb/veelead_client.py
└── pipeline.py
```

## What each piece does

- `app/main.py` is the Flask entrypoint.
- `app/config.py` loads environment variables and centralizes model/endpoints.
- `app/stt/whisper_local.py` wraps local transcription with `faster-whisper`.
- `app/llm/local_llm.py` uses an OpenAI-compatible client pointed at Ollama.
- `app/tts/local_tts.py` wraps local TTS via Piper or XTTS.
- `app/kb/veelead_client.py` keeps the knowledge-base lookup logic in one place.
- `app/pipeline.py` orchestrates STT -> KB -> LLM -> TTS.

## Setup

1. Copy `.env.example` to `.env`.
2. Fill in the keys and local model paths you want to use.
3. Install dependencies:

```bash
pip install -r requirements.txt
```

## Run the Flask demo

```bash
flask --app app.main run
```

Or:

```bash
python -m app.main
```

## Notes

- `models/` is intended for large local weights and stays ignored by git.
- `filler_cache/` is where generated filler audio can be cached.
- The old `v1/` folder is left intact so you can compare or migrate pieces gradually.
