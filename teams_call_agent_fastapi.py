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
Media Streaming) before wiring in real audio handling. Everything else here
(the SDK classes, method signatures, AudioFormat values) was verified
directly against the installed azure-communication-callautomation package.

SETUP:
  pip install fastapi "uvicorn[standard]" azure-communication-callautomation python-dotenv

  .env additions (same as before):
    ACS_CONNECTION_STRING=endpoint=https://<resource>.communication.azure.com/;accesskey=...
    ACS_CALLBACK_BASE_URL=https://<your-render-app>.onrender.com
    ACS_MEDIA_WEBSOCKET_URL=wss://<your-render-app>.onrender.com/media

RENDER DEPLOYMENT:
  Build command: pip install -r requirements.txt
  Start command: uvicorn teams_call_agent_fastapi:app --host 0.0.0.0 --port $PORT
  (Render sets $PORT automatically - don't hardcode 5000/8000 in the start command)

LOCAL TESTING:
  uvicorn teams_call_agent_fastapi:app --reload --port 5000
"""

import base64
import json
import os

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
from voice_helpdesk_pipeline import search_knowledge_base, ask_gpt, text_to_speech

load_dotenv()

ACS_CONNECTION_STRING = os.environ["ACS_CONNECTION_STRING"]
CALLBACK_BASE_URL = os.environ["ACS_CALLBACK_BASE_URL"]
MEDIA_WEBSOCKET_URL = os.environ["ACS_MEDIA_WEBSOCKET_URL"]

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
    """Tracks one call's audio buffer and conversation history across the
    lifetime of a single WebSocket connection."""

    def __init__(self):
        self.audio_buffer = bytearray()
        self.history: list[dict] = []
        self.speaking = False  # true while we're sending TTS audio back - pause ingestion during this


@app.websocket("/media")
async def media_stream(websocket: WebSocket):
    await websocket.accept()
    session = CallSession()

    try:
        while True:
            raw_message = await websocket.receive_text()
            message = json.loads(raw_message)
            kind = message.get("kind")

            # VERIFY: confirm these "kind" values and nested field paths against
            # current Microsoft docs before relying on this in production.
            if kind == "AudioMetadata":
                print("Stream started:", message.get("audioMetadata"))

            elif kind == "AudioData":
                audio_data = message.get("audioData", {})
                if audio_data.get("silent"):
                    continue

                chunk = base64.b64decode(audio_data.get("data", ""))
                if not session.speaking:
                    session.audio_buffer.extend(chunk)

                # TODO: replace this placeholder with real end-of-speech detection
                # (equivalent to the browser's VAD, or Deepgram's own streaming
                # endpoint which does this server-side and is the better fit here).
                if len(session.audio_buffer) > 320_000:  # ~10s of 16kHz mono PCM16
                    await handle_utterance(websocket, session)

    except WebSocketDisconnect:
        print("Call media stream disconnected")


async def handle_utterance(websocket: WebSocket, session: CallSession):
    """Runs one turn: whatever's in the buffer -> KB -> GPT -> TTS -> back to the caller."""
    session.speaking = True
    pcm_audio = bytes(session.audio_buffer)
    session.audio_buffer = bytearray()

    try:
        # TODO: STT here. Deepgram's streaming endpoint accepts raw PCM directly -
        # this is actually a better fit than the file-based transcribe_audio()
        # used in the browser demo, since we already have a raw audio buffer.
        transcript = "PLACEHOLDER - wire up Deepgram streaming STT on pcm_audio"

        kb_result = search_knowledge_base(
            transcript, previous=[h["question"] for h in session.history[-5:]]
        )
        spoken_answer = ask_gpt(transcript, kb_result.get("answer", ""), history=session.history[-4:])
        session.history.append({"question": transcript, "answer": spoken_answer})
        session.history = session.history[-5:]

        wav_path = "/tmp/turn_response.wav"
        text_to_speech(spoken_answer, output_path=wav_path)

        # TODO: convert the wav to raw PCM16 frames matching AudioFormat.PCM16_K_MONO
        # and stream them back as outbound "AudioData" messages - VERIFY the exact
        # outbound message shape against current Microsoft docs.
        with open(wav_path, "rb") as f:
            pcm_bytes = f.read()

        outbound_message = {
            "kind": "AudioData",
            "audioData": {"data": base64.b64encode(pcm_bytes).decode("utf-8")},
        }
        await websocket.send_text(json.dumps(outbound_message))

    finally:
        session.speaking = False


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
