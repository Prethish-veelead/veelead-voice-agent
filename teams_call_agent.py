"""
Azure Communication Services (ACS) Call Automation - Teams call agent skeleton
--------------------------------------------------------------------------------
This replaces Twilio/the browser demo as the "telephony adapter" for a real
Teams-reachable phone number. It reuses the same AI pipeline functions from
voice_helpdesk_pipeline.py unchanged - only the transport layer is new here.

WHAT THIS DOES:
  1. Receives an Event Grid webhook when a call comes in to your ACS number.
  2. Answers the call and starts bidirectional media streaming over a
     WebSocket - audio comes IN from the caller and goes OUT to the caller
     over that same connection.
  3. (You fill in) feed incoming audio chunks to Deepgram, run the KB+GPT
     pipeline, and send the TTS audio back over the same WebSocket.

This is a skeleton, not a finished pipeline - the WebSocket audio handling
(#5 below) needs real implementation before this can hold a full conversation.
Treat this as the scaffold to build that into, not a drop-in finished agent.

SETUP:
  pip install azure-communication-callautomation azure-eventgrid flask

  .env additions:
    ACS_CONNECTION_STRING=endpoint=https://<resource>.communication.azure.com/;accesskey=...
    ACS_CALLBACK_BASE_URL=https://<your-public-url>            # e.g. your ngrok URL during testing
    ACS_MEDIA_WEBSOCKET_URL=wss://<your-public-url>/media       # same host, WebSocket path

RUN:
  python teams_call_agent.py
  Point your ACS resource's Event Grid subscription (or Direct Line webhook)
  at https://<your-public-url>/api/incoming_call
"""

import os
from flask import Flask, request, jsonify
from azure.communication.callautomation import (
    CallAutomationClient,
    MediaStreamingOptions,
    MediaStreamingContentType,
    MediaStreamingAudioChannelType,
    StreamingTransportType,
)
from dotenv import load_dotenv

load_dotenv()

ACS_CONNECTION_STRING = os.environ["ACS_CONNECTION_STRING"]
CALLBACK_BASE_URL = os.environ["ACS_CALLBACK_BASE_URL"]
MEDIA_WEBSOCKET_URL = os.environ["ACS_MEDIA_WEBSOCKET_URL"]

app = Flask(__name__)
call_automation_client = CallAutomationClient.from_connection_string(ACS_CONNECTION_STRING)


@app.route("/api/incoming_call", methods=["POST"])
def incoming_call():
    """Event Grid sends a subscription-validation event first, then an
    IncomingCall event for every real call. Handle both."""
    events = request.get_json()

    for event in events:
        event_type = event.get("eventType", "")

        # Event Grid handshake - must echo this back once, or ACS never
        # delivers real events to this endpoint.
        if event_type == "Microsoft.EventGrid.SubscriptionValidationEvent":
            validation_code = event["data"]["validationCode"]
            return jsonify({"validationResponse": validation_code})

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
                enable_bidirectional=True,  # lets us send TTS audio back over the same socket
            )

            call_automation_client.answer_call(
                incoming_call_context=incoming_call_context,
                callback_url=f"{CALLBACK_BASE_URL}/api/call_events",
                media_streaming=media_streaming,
            )

    return jsonify({"status": "ok"})


@app.route("/api/call_events", methods=["POST"])
def call_events():
    """Mid-call events: CallConnected, CallDisconnected, MediaStreamingStarted, etc."""
    events = request.get_json()
    for event in events:
        print(f"Call event: {event.get('type')}")
        # TODO: on CallDisconnected, clean up any per-call state (history, buffers).
    return jsonify({"status": "ok"})


# TODO #5 - the actual audio handling:
# ACS streams raw PCM audio over the WebSocket at MEDIA_WEBSOCKET_URL. You'll
# need a WebSocket server (Flask-Sock, or a separate asyncio/FastAPI service)
# that:
#   - buffers incoming audio and detects end-of-speech (like the browser VAD,
#     or Deepgram's own streaming endpoint which does this server-side)
#   - calls search_knowledge_base() -> ask_gpt() -> text_to_speech()
#     from voice_helpdesk_pipeline.py, completely unchanged
#   - sends the resulting audio back over the same WebSocket as outbound
#     PCM frames
# This is the one genuinely new piece of engineering in this whole project -
# everything else here is configuration, not new AI logic.


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
