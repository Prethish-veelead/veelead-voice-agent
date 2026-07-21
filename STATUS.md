# Voice Help Agent — Status

> This file describes what the code currently does and how it's configured.
> Keep it in sync with reality — update it whenever the pipeline, models, or
> file structure change materially. (See `CLAUDE.md` for the standing rule
> that keeps this automatic.)

## What this is

A local voice helpdesk agent: you click **Start Call** in the browser, talk,
and it transcribes your speech, looks up an answer in the Veelead knowledge
base, generates a spoken reply with a local LLM, and speaks it back — fully
on-device (no cloud STT/LLM/TTS).

## Call flow

```
Browser: click "Start Call"
   → mic opens, voice-activity detection listens continuously
   → on speech end, audio chunk POSTed to /transcribe
        → faster-whisper (STT) → transcript
   → transcript POSTed to /answer
        → classify_intent(): greeting / farewell / acknowledgment / question
        → greeting|farewell|ack  → instant cached filler audio (no KB/LLM call)
        → question               → KB search (Veelead) → LLM (Ollama) →
                                    per-sentence TTS (Piper), streamed back
                                    as audio arrives (ndjson stream)
   → browser plays audio sentence-by-sentence, shows timing breakdown,
     resumes listening for the next turn
   → repeats until "End Call"
```

Every turn is logged to `logs/turns.jsonl` (timings, confidence, transcript,
answer) and low-confidence / LLM-flagged turns also go to
`logs/escalations.jsonl`.

## Entry point

```bash
flask --app app.main run
```
Open `http://127.0.0.1:5000`. (`app/main.py` is the only entrypoint that
matters now — see "Known issues" for the older `local_web_demo.py`.)

## Current model configuration (`.env`)

| Setting | Value | Why |
|---|---|---|
| `WHISPER_MODEL_SIZE` | `base` | Was `small`; dropped for lower RAM pressure on this 4GB-RAM machine. |
| `WHISPER_LANGUAGE` | `en` | Pinned to skip language auto-detection (small latency win). |
| `LOCAL_LLM_MODEL` | `llama3.2:3b` (via Ollama) | Was `qwen2.5:7b-instruct` — too large to comfortably fit in 4GB RAM alongside Whisper; 3b tested with comparable answer quality and ~2x faster once warm. |
| `LOCAL_LLM_BASE_URL` | `http://localhost:11434/v1` | Ollama's OpenAI-compatible endpoint. |
| TTS | Piper (`PIPER_MODEL_PATH` / `PIPER_CONFIG_PATH`) | `en_US-lessac-medium` voice. |

## Key files

| File | Role |
|---|---|
| `app/main.py` | Flask entrypoint **and** the entire frontend (HTML/CSS/JS embedded as a string) — Start/End Call button, VAD-based recording, streaming playback, live timing box. |
| `app/pipeline.py` | Orchestration. `stream_turn()` is the single source of truth (intent classification → KB → LLM → TTS, yielded sentence-by-sentence); `process_turn()`/`run_pipeline()` are non-streaming wrappers built on top of it for CLI test scripts. |
| `app/stt/whisper_local.py` | faster-whisper wrapper. |
| `app/llm/local_llm.py` | Ollama-backed LLM calls + prompt construction + sentence-chunking for streaming TTS. |
| `app/tts/local_tts.py` | TTS used by the live pipeline (Piper subprocess or XTTS backend, chosen via `LOCAL_TTS_BACKEND`). |
| `app/kb/veelead_client.py` | Knowledge-base search against the Veelead RAG endpoint. |
| `app/telemetry/logger.py`, `escalations.py` | JSONL logging for turn timings and low-confidence/flagged escalations. |
| `app/config.py` | Central `Settings` dataclass reading `.env`. |

## Known issues / tech debt

- **`app/config.py`'s `ollama_model` / `ollama_base_url` / `ollama_api_key` are dead** — `app/llm/local_llm.py` reads its own `LOCAL_LLM_MODEL` / `LOCAL_LLM_BASE_URL` env vars directly, bypassing `config.py` entirely. Changing the wrong setting silently does nothing.
- **Two TTS modules exist**: `app/tts/piper_local.py` (used only by the older, now-unused `local_web_demo.py`) and `app/tts/local_tts.py` (used by the real pipeline). Not unified.
- **`local_web_demo.py`** (repo root) was the original working prototype before `app/` was rebuilt to match it — no longer the recommended entrypoint, kept for reference.
- **`v1/`** holds the pre-refactor cloud-based implementation (Deepgram/OpenAI) and an Azure Communication Services "Teams call agent" prototype (phone-call style, not a Teams-meeting bot) — kept for reference/migration, not run directly.
- **4GB RAM constraint** — this is the dominant performance bottleneck, more than any single model choice. Running Whisper + Ollama concurrently on 4GB risks swapping; erratic multi-second-to-minutes STT/LLM timing spikes seen in early logs were consistent with this.
- **Not yet real-time-call-ready** — per-turn latency is still multiple seconds even after optimization, and there's no public HTTPS/WSS hosting set up, both required before this could answer real phone/Teams calls (see "Teams integration" below).

## Teams / phone integration (not implemented)

Feasible via Azure Communication Services (ACS) Call Automation — a phone
number rings in, ACS opens a real-time audio WebSocket, this pipeline
processes it. Requires public hosting (not localhost), an ACS resource, and
almost certainly faster hosted STT/LLM/TTS for the real-time path (current
local latency is too slow for a live call). A prior prototype of this exists
in `v1/teams_call_agent_fastapi.py`.

## Recent change log

- Fixed `ImportError` crashes in `app/main.py`/`app/pipeline.py` from a prior
  refactor that renamed functions (`ask_gpt`→`ask_local_llm`,
  `transcribe_audio`→`transcribe_audio_local`) without updating callers.
- Ported the working Start/End Call UI into `app/main.py`'s index route
  (previously a placeholder page with no button — the actual bug behind
  "can't click Start").
- Fixed `/filler/<name>` route extension mismatch (`greeting.wav` vs `greeting`).
- Rebuilt `app/pipeline.py`/`app/main.py` to match `local_web_demo.py`'s full
  feature set: greeting/ack/farewell fast-path, confidence-gated KB
  grounding, streaming sentence-by-sentence TTS, escalation logging.
- Switched `WHISPER_MODEL_SIZE` `small`→`base` and `LOCAL_LLM_MODEL`
  `qwen2.5:7b-instruct`→`llama3.2:3b` for the 4GB-RAM constraint.
- Wired the previously-dead `WHISPER_LANGUAGE` setting into both
  transcription call sites.
- Tightened the LLM system prompt so it stops re-greeting on every turn of a
  continuing call.
- Added a live per-turn timing breakdown box to the UI (STT / KB / LLM / TTS
  / total).
