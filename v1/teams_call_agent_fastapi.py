"""
Azure Communication Services (ACS) Call Automation - Teams call agent
FastAPI version, built for Render deployment (needs persistent WebSockets,
which Vercel's serverless model can't hold open).
--------------------------------------------------------------------------------
Reuses search_knowledge_base / ask_gpt / text_to_speech from
voice_helpdesk_pipeline.py completely unchanged - only the transport layer
(answering calls, receiving/sending real-time audio) is new here.

VERIFY BEFORE RELYING ON THIS: the exact JSON message shape ACS sends over
the media WebSocket (the AudioMetadata / AudioData "kind" fields below) is
built from general knowledge of the Call Automation media streaming protocol,
not confirmed against Microsoft's live docs in this environment - cross-check
the field names against https://learn.microsoft.com (Call Automation ->
Media Streaming) before relying on it, ideally by logging the raw messages
from a real test call first. Everything else here (the SDK classes, method
signatures, AudioFormat values, Deepgram streaming params, audioop functions)
was verified directly against the installed packages.

Deepgram's streaming endpoint does end-of-speech detection server-side
(endpointing + utterance_end_ms below) - this replaces any custom VAD/buffer-
size guessing with Deepgram's own silence detection, and is more reliable
than a fixed buffer size threshold.

SETUP:
  pip install -r requirements.txt

  .env additions (same as before, plus Deepgram):
    ACS_CONNECTION_STRING=endpoint=https://<resource>.communication.azure.com/;accesskey=...
    ACS_CALLBACK_BASE_URL=https://<your-render-app>.onrender.com
    ACS_MEDIA_WEBSOCKET_URL=wss://<your-render-app>.onrender.com/media
    DEEPGRAM_API_KEY=...

RENDER DEPLOYMENT:
  Build command: pip install -r requirements.txt
  Start command: uvicorn teams_call_agent_fastapi:app --host 0.0.0.0 --port $PORT
  (Render sets $PORT automatically - don't hardcode 5000/8000 in the start command)

LOCAL TESTING:
  uvicorn teams_call_agent_fastapi:app --reload --port 5000
"""

import asyncio
import base64
import json
import os
import wave
import audioop  # deprecated in 3.13+ - if you're on 3.13, pip install audioop-lts as a drop-in replacement

import websockets
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from azure.communication.callautomation import (
    CallAutomationClient,
    MediaStreamingOptions,
    MediaStreamingContentType,
    MediaStreamingAudioChannelType,
    StreamingTransportType,
    AudioFormat,
)
from dotenv import load_dotenv

# Reuse your existing pipeline, completely unchanged.
from v1.voice_helpdesk_pipeline import search_knowledge_base, ask_gpt, text_to_speech

load_dotenv()

ACS_CONNECTION_STRING = os.environ["ACS_CONNECTION_STRING"]
CALLBACK_BASE_URL = os.environ["ACS_CALLBACK_BASE_URL"]
MEDIA_WEBSOCKET_URL = os.environ["ACS_MEDIA_WEBSOCKET_URL"]
DEEPGRAM_API_KEY = os.environ["DEEPGRAM_API_KEY"]

# Deepgram's streaming endpoint - endpointing/utterance_end_ms below is what lets
# IT detect end-of-speech server-side, replacing our own VAD/buffer-size guess.
DEEPGRAM_STREAMING_URL = (
    "wss://api.deepgram.com/v1/listen"
    "?encoding=linear16&sample_rate=16000&channels=1"
    "&punctuate=true&smart_format=true&interim_results=true"
    "&endpointing=300&utterance_end_ms=1000&vad_events=true"
)

app = FastAPI()
call_automation_client = CallAutomationClient.from_connection_string(ACS_CONNECTION_STRING)


@app.post("/api/incoming_call")
async def incoming_call(request: Request):
    """Event Grid webhook: validation handshake first, then real IncomingCall events."""
    events = await request.json()

    for event in events:
        event_type = event.get("eventType", "")

        if event_type == "Microsoft.EventGrid.SubscriptionValidationEvent":
            validation_code = event["data"]["validationCode"]
            return JSONResponse({"validationResponse": validation_code})

        if event_type == "Microsoft.Communication.IncomingCall":
            incoming_call_context = event["data"]["incomingCallContext"]
            caller_id = event["data"].get("from", {}).get("rawId", "unknown")
            print(f"Incoming call from {caller_id}")

            media_streaming = MediaStreamingOptions(
                transport_url=MEDIA_WEBSOCKET_URL,
                transport_type=StreamingTransportType.WEBSOCKET,
                content_type=MediaStreamingContentType.AUDIO,
                audio_channel_type=MediaStreamingAudioChannelType.MIXED,
                start_media_streaming=True,
                enable_bidirectional=True,
                audio_format=AudioFormat.PCM16_K_MONO,
            )

            call_automation_client.answer_call(
                incoming_call_context=incoming_call_context,
                callback_url=f"{CALLBACK_BASE_URL}/api/call_events",
                media_streaming=media_streaming,
            )

    return JSONResponse({"status": "ok"})


@app.post("/api/call_events")
async def call_events(request: Request):
    """Mid-call events: CallConnected, CallDisconnected, MediaStreamingStarted, etc."""
    events = await request.json()
    for event in events:
        print(f"Call event: {event.get('type')}")
        # TODO: on CallDisconnected, clean up any per-call state (history, buffers).
    return JSONResponse({"status": "ok"})


class CallSession:
    """Tracks one call's state across the lifetime of a single WebSocket connection."""

    def __init__(self):
        self.history: list[dict] = []
        self.speaking = False  # true while sending TTS audio back - ignore transcripts during this
        self.current_utterance = ""  # accumulates interim transcript pieces until Deepgram signals end-of-speech


@app.websocket("/media")
async def media_stream(websocket: WebSocket):
    await websocket.accept()
    session = CallSession()

    # One Deepgram streaming connection per call, held open for the call's duration.
    async with websockets.connect(
        DEEPGRAM_STREAMING_URL,
        additional_headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"},
    ) as deepgram_ws:

        async def forward_acs_audio_to_deepgram():
            """Read audio frames from ACS and forward the raw PCM straight to Deepgram."""
            try:
                while True:
                    raw_message = await websocket.receive_text()
                    message = json.loads(raw_message)
                    kind = message.get("kind")

                    # VERIFY: confirm these "kind" values and nested field paths
                    # against current Microsoft docs / your own Step D logging
                    # before relying on this in production.
                    if kind == "AudioMetadata":
                        print("Stream started:", message.get("audioMetadata"))

                    elif kind == "AudioData":
                        audio_data = message.get("audioData", {})
                        if audio_data.get("silent"):
                            continue
                        if session.speaking:
                            continue  # don't feed our own TTS output back into STT

                        chunk = base64.b64decode(audio_data.get("data", ""))
                        await deepgram_ws.send(chunk)  # Deepgram wants raw binary frames, not JSON-wrapped
            except WebSocketDisconnect:
                print("Call media stream disconnected")

        async def handle_deepgram_results():
            """Read transcripts back from Deepgram and act once a full utterance is ready."""
            async for raw_result in deepgram_ws:
                result = json.loads(raw_result)
                result_type = result.get("type")

                if result_type == "Results":
                    alt = result.get("channel", {}).get("alternatives", [{}])[0]
                    text = alt.get("transcript", "")
                    if text and result.get("is_final"):
                        session.current_utterance = (session.current_utterance + " " + text).strip()

                elif result_type == "UtteranceEnd":
                    if session.current_utterance:
                        transcript = session.current_utterance
                        session.current_utterance = ""
                        await handle_utterance(websocket, session, transcript)

        # Run both directions concurrently for the life of the call.
        await asyncio.gather(
            forward_acs_audio_to_deepgram(),
            handle_deepgram_results(),
        )


def wav_to_pcm_frames(wav_path: str, frame_ms: int = 20) -> list[bytes]:
    """Convert a wav file (whatever sample rate/channels it was recorded at)
    into a list of raw PCM16 mono 16kHz frames, matching AudioFormat.PCM16_K_MONO.
    Sending audio back in small frames rather than one giant blob is standard
    practice for real-time streaming protocols - VERIFY the expected frame size
    against current Microsoft docs, 20ms (640 bytes) is a common default."""
    with wave.open(wav_path, "rb") as wf:
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        frame_rate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())

    if channels == 2:
        raw = audioop.tomono(raw, sample_width, 0.5, 0.5)
    if frame_rate != 16000:
        raw, _ = audioop.ratecv(raw, sample_width, 1, frame_rate, 16000, None)
    if sample_width != 2:
        raw = audioop.lin2lin(raw, sample_width, 2)

    frame_bytes = int(16000 * (frame_ms / 1000) * 2)  # 2 bytes/sample at 16-bit
    return [raw[i:i + frame_bytes] for i in range(0, len(raw), frame_bytes)]


async def handle_utterance(websocket: WebSocket, session: CallSession, transcript: str):
    """Runs one turn: transcript -> KB -> GPT -> TTS -> back to the caller, framed correctly."""
    session.speaking = True
    print(f"Caller said: {transcript}")

    try:
        kb_result = search_knowledge_base(
            transcript, previous=[h["question"] for h in session.history[-5:]]
        )
        spoken_answer = ask_gpt(transcript, kb_result.get("answer", ""), history=session.history[-4:])
        session.history.append({"question": transcript, "answer": spoken_answer})
        session.history = session.history[-5:]

        wav_path = "/tmp/turn_response.wav"
        text_to_speech(spoken_answer, output_path=wav_path)

        for frame in wav_to_pcm_frames(wav_path):
            outbound_message = {
                "kind": "AudioData",
                "audioData": {"data": base64.b64encode(frame).decode("utf-8")},
            }
            await websocket.send_text(json.dumps(outbound_message))

        os.remove(wav_path)

    finally:
        session.speaking = False


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
