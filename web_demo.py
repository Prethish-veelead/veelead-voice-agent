# # """
# # Live browser demo for the voice helpdesk pipeline - "phone call" mode.
# # ------------------------------------------------------------------------
# # Green "Start Call" button -> plays a cached greeting -> caller just talks,
# # no button to hold. The browser watches the mic's volume (Web Audio API) and
# # auto-stops recording after ~1.2s of silence following detected speech, then
# # sends the turn automatically. Listening only resumes after the agent's
# # reply finishes playing, so the mic never picks up the agent's own voice -
# # this is turn-based hands-free, not full interrupt-anytime duplex (that
# # needs a telephony-grade echo-cancellation setup, e.g. via Twilio). Red
# # "End Call" button ends it.

# # Each turn, to feel like talking to a real person instead of silence:
# #   1. POST /transcribe - Deepgram only (~1-2s). As soon as the transcript is
# #      back, the browser instantly plays a pre-cached filler line ("Okay,
# #      let me look into that for you.") with near-zero latency, while...
# #   2. POST /answer - KB lookup + GPT rephrase + Sarvam TTS (~8-15s) - runs
# #      in parallel. Its audio plays right after the filler finishes.

# # The browser keeps the last 5 transcribed questions from the call (oldest
# # first) and sends them as the `previous` param on /answer -> search.json,
# # so follow-ups like "I tried that, still not working" get disambiguated
# # correctly. GPT itself stays stateless per turn (no memory) - only the KB
# # lookup uses call history, per instruction.

# # All of this reuses transcribe_audio / search_knowledge_base / ask_gpt /
# # text_to_speech from voice_helpdesk_pipeline.py unchanged (imported, not
# # duplicated), so the grounding/escalation rules in ask_gpt() stay identical
# # to the CLI version - this file is only a transport layer.

# # This is a local test tool, not a production server: it binds to localhost
# # only and holds no auth. Do not expose it to the public internet as-is.

# # SETUP:
# #   pip install flask
# #   (uses the same .env as voice_helpdesk_pipeline.py)

# # RUN:
# #   python web_demo.py
# #   -> open http://127.0.0.1:5000 in a browser (mic access requires
# #      localhost or https, so 127.0.0.1 works but a LAN IP will not)
# # """

# # import os
# # import tempfile
# # from urllib.parse import quote

# # from flask import Flask, jsonify, request, send_file, Response

# # from voice_helpdesk_pipeline import (
# #     FILLER_DIR,
# #     ask_gpt,
# #     get_or_create_filler,
# #     search_knowledge_base,
# #     text_to_speech,
# #     transcribe_audio,
# # )

# # app = Flask(__name__)

# # INDEX_HTML = """<!doctype html>
# # <html>
# # <head>
# # <meta charset="utf-8">
# # <title>Voice Helpdesk - Live Test</title>
# # <style>
# #   body { font-family: system-ui, sans-serif; max-width: 480px; margin: 60px auto; text-align: center; }
# #   button { font-size: 18px; padding: 16px 32px; border-radius: 8px; border: none;
# #            color: white; cursor: pointer; margin: 6px; }
# #   button.start { background: #16a34a; }
# #   button.end { background: #dc2626; }
# #   button:disabled { background: #9ca3af; cursor: not-allowed; }
# #   #status { margin-top: 16px; color: #374151; min-height: 1.5em; }
# #   #transcript, #answer { margin-top: 16px; text-align: left; padding: 12px;
# #            background: #f3f4f6; border-radius: 8px; display: none; }
# # </style>
# # </head>
# # <body>
# #   <h2>Voice Helpdesk - Live Test</h2>
# #   <div id="callControls">
# #     <button id="startBtn" class="start">Start Call</button>
# #   </div>
# #   <div id="activeControls" style="display:none;">
# #     <button id="endBtn" class="end">End Call</button>
# #   </div>
# #   <div id="status"></div>
# #   <div id="transcript"></div>
# #   <div id="answer"></div>
# #   <audio id="greeting" src="/filler/greeting.wav" preload="auto"></audio>
# #   <audio id="filler" src="/filler/checking.wav" preload="auto"></audio>
# #   <audio id="player" controls style="margin-top:16px; width:100%; display:none;"></audio>

# # <script>
# # const startBtn = document.getElementById('startBtn');
# # const endBtn = document.getElementById('endBtn');
# # const callControls = document.getElementById('callControls');
# # const activeControls = document.getElementById('activeControls');
# # const status = document.getElementById('status');
# # const transcriptEl = document.getElementById('transcript');
# # const answerEl = document.getElementById('answer');
# # const greeting = document.getElementById('greeting');
# # const filler = document.getElementById('filler');
# # const player = document.getElementById('player');

# # const SILENCE_THRESHOLD = 0.02;   // RMS level below which audio counts as silence
# # const SILENCE_DURATION_MS = 1200; // how long silence must last after speech to end the turn

# # let micStream, mediaRecorder, chunks = [];
# # let audioContext, analyser, vadRafId;
# # let conversationHistory = [];
# # let callActive = false;

# # function resetTurnUI() {
# #   transcriptEl.style.display = 'none';
# #   answerEl.style.display = 'none';
# #   player.style.display = 'none';
# #   player.pause();
# # }

# # async function startCall() {
# #   callActive = true;
# #   conversationHistory = [];
# #   callControls.style.display = 'none';
# #   activeControls.style.display = 'block';
# #   resetTurnUI();

# #   try {
# #     micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
# #   } catch (err) {
# #     status.textContent = 'Microphone access failed: ' + err;
# #     endCall();
# #     return;
# #   }

# #   status.textContent = 'Call started.';
# #   greeting.currentTime = 0;
# #   greeting.onended = startListening;
# #   greeting.play().catch(startListening);
# # }

# # function endCall() {
# #   callActive = false;
# #   cancelAnimationFrame(vadRafId);
# #   if (mediaRecorder && mediaRecorder.state === 'recording') mediaRecorder.stop();
# #   if (micStream) micStream.getTracks().forEach(t => t.stop());
# #   if (audioContext) { audioContext.close(); audioContext = null; }
# #   greeting.pause();
# #   filler.pause();
# #   conversationHistory = [];
# #   activeControls.style.display = 'none';
# #   callControls.style.display = 'block';
# #   resetTurnUI();
# #   status.textContent = 'Call ended.';
# # }

# # startBtn.addEventListener('click', startCall);
# # endBtn.addEventListener('click', endCall);

# # function startListening() {
# #   if (!callActive) return;
# #   status.textContent = 'Listening...';
# #   resetTurnUI();

# #   chunks = [];
# #   mediaRecorder = new MediaRecorder(micStream);
# #   mediaRecorder.ondataavailable = (ev) => chunks.push(ev.data);
# #   mediaRecorder.onstop = handleRecording;
# #   mediaRecorder.start();

# #   runVoiceActivityDetection();
# # }

# # function runVoiceActivityDetection() {
# #   audioContext = audioContext || new AudioContext();
# #   const source = audioContext.createMediaStreamSource(micStream);
# #   analyser = audioContext.createAnalyser();
# #   analyser.fftSize = 512;
# #   source.connect(analyser);
# #   const data = new Uint8Array(analyser.frequencyBinCount);

# #   let speechDetected = false;
# #   let lastLoudAt = Date.now();

# #   function tick() {
# #     if (!mediaRecorder || mediaRecorder.state !== 'recording') { source.disconnect(); return; }

# #     analyser.getByteTimeDomainData(data);
# #     let sumSquares = 0;
# #     for (let i = 0; i < data.length; i++) {
# #       const v = (data[i] - 128) / 128;
# #       sumSquares += v * v;
# #     }
# #     const rms = Math.sqrt(sumSquares / data.length);

# #     if (rms > SILENCE_THRESHOLD) {
# #       lastLoudAt = Date.now();
# #       if (!speechDetected) {
# #         speechDetected = true;
# #         status.textContent = 'Listening... (hearing you)';
# #       }
# #     } else if (speechDetected && Date.now() - lastLoudAt > SILENCE_DURATION_MS) {
# #       source.disconnect();
# #       mediaRecorder.stop();
# #       return;
# #     }
# #     vadRafId = requestAnimationFrame(tick);
# #   }
# #   vadRafId = requestAnimationFrame(tick);
# # }

# # async function handleRecording() {
# #   if (!callActive) return;
# #   status.textContent = 'Transcribing...';
# #   const blob = new Blob(chunks, { type: 'audio/webm' });
# #   const formData = new FormData();
# #   formData.append('audio', blob, 'question.webm');

# #   let transcript;
# #   try {
# #     const resp = await fetch('/transcribe', { method: 'POST', body: formData });
# #     if (!resp.ok) { status.textContent = 'Error: ' + await resp.text(); startListening(); return; }
# #     ({ transcript } = await resp.json());
# #   } catch (err) {
# #     status.textContent = 'Request failed: ' + err;
# #     startListening();
# #     return;
# #   }

# #   if (!transcript || !transcript.trim()) {
# #     status.textContent = "Didn't catch that - listening again...";
# #     startListening();
# #     return;
# #   }

# #   transcriptEl.textContent = 'You asked: ' + transcript;
# #   transcriptEl.style.display = 'block';
# #   status.textContent = "Ok, let's see...";

# #   // Instant acknowledgment - pre-cached audio, plays with ~0 latency.
# #   filler.currentTime = 0;
# #   filler.play().catch(() => {});

# #   // The real answer (KB + GPT + TTS) runs in parallel while the filler plays.
# #   // conversationHistory carries this call's prior questions so the KB can
# #   // disambiguate follow-ups - GPT itself stays stateless per turn.
# #   const previous = conversationHistory.slice(-5);
# #   let answerResp;
# #   try {
# #     answerResp = await fetch('/answer', {
# #       method: 'POST',
# #       headers: { 'Content-Type': 'application/json' },
# #       body: JSON.stringify({ transcript, previous }),
# #     });
# #   } catch (err) {
# #     status.textContent = 'Request failed: ' + err;
# #     startListening();
# #     return;
# #   }

# #   if (!answerResp.ok) {
# #     status.textContent = 'Error: ' + await answerResp.text();
# #     startListening();
# #     return;
# #   }

# #   conversationHistory.push(transcript);
# #   if (conversationHistory.length > 5) conversationHistory.shift();

# #   const answer = decodeURIComponent(answerResp.headers.get('X-Answer') || '');
# #   answerEl.textContent = 'Agent: ' + answer;
# #   answerEl.style.display = 'block';
# #   const audioUrl = URL.createObjectURL(await answerResp.blob());

# #   const playFinalAnswer = () => {
# #     if (!callActive) return;
# #     player.src = audioUrl;
# #     player.style.display = 'block';
# #     status.textContent = 'Agent speaking...';
# #     // Only resume listening once the agent is done, so the mic never
# #     // picks up its own reply.
# #     player.onended = startListening;
# #     player.play();
# #   };

# #   if (!filler.paused && !filler.ended) {
# #     filler.onended = playFinalAnswer;
# #   } else {
# #     playFinalAnswer();
# #   }
# # }
# # </script>
# # </body>
# # </html>
# # """


# # @app.route("/")
# # def index():
# #     return INDEX_HTML


# # @app.route("/filler/<name>")
# # def filler(name):
# #     safe_name = os.path.basename(name)  # no path traversal
# #     path = os.path.join(FILLER_DIR, safe_name)
# #     if not os.path.exists(path):
# #         return Response("Not found", status=404)
# #     return send_file(path, mimetype="audio/wav")


# # @app.route("/transcribe", methods=["POST"])
# # def transcribe():
# #     if "audio" not in request.files:
# #         return Response("No audio file uploaded.", status=400)

# #     audio_file = request.files["audio"]
# #     suffix = os.path.splitext(audio_file.filename or "")[1] or ".webm"

# #     with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_in:
# #         audio_file.save(tmp_in.name)
# #         in_path = tmp_in.name

# #     try:
# #         transcript = transcribe_audio(in_path)
# #         return jsonify({"transcript": transcript})
# #     except Exception as exc:
# #         return Response(f"Transcription error: {exc}", status=500)
# #     finally:
# #         os.remove(in_path)


# # @app.route("/answer", methods=["POST"])
# # def answer():
# #     data = request.get_json(silent=True) or {}
# #     transcript = (data.get("transcript") or "").strip()
# #     if not transcript:
# #         return Response("Missing transcript.", status=400)

# #     previous = data.get("previous") or []
# #     if not isinstance(previous, list):
# #         previous = []
# #     previous = [str(p) for p in previous][-5:]

# #     out_path = None
# #     try:
# #         kb_result = search_knowledge_base(transcript, previous=previous)
# #         spoken_answer = ask_gpt(transcript, kb_result.get("answer", ""), kb_result.get("confidence"))

# #         with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_out:
# #             out_path = tmp_out.name
# #         text_to_speech(spoken_answer, output_path=out_path)

# #         response = send_file(out_path, mimetype="audio/wav")
# #         # Header values must be Latin-1; URL-encode so the answer text survives the trip.
# #         response.headers["X-Answer"] = quote(spoken_answer)
# #         response.call_on_close(lambda: os.path.exists(out_path) and os.remove(out_path))
# #         return response
# #     except Exception as exc:
# #         if out_path and os.path.exists(out_path):
# #             os.remove(out_path)
# #         return Response(f"Pipeline error: {exc}", status=500)


# # if __name__ == "__main__":
# #     print("Pre-generating filler audio...")
# #     get_or_create_filler("checking")
# #     get_or_create_filler("greeting")
# #     app.run(host="127.0.0.1", port=5000, debug=False)
# """
# Live browser demo for the voice helpdesk pipeline - "phone call" mode.
# ------------------------------------------------------------------------
# Green "Start Call" button -> plays a cached greeting -> the browser then
# listens continuously and automatically detects when you start and stop
# talking (simple volume-based voice activity detection, no button to hold).
# Red "End Call" button ends it.

# Note: this is client-side VAD on top of file-based Deepgram calls, not
# true streaming transcription. Real Twilio + Deepgram streaming will do
# endpoint detection server-side instead - this gets you the same
# hands-free *feel* for local testing without that infrastructure yet.

# While the assistant is speaking, listening is paused (no barge-in support
# yet) so the mic doesn't pick up its own voice through your speakers.
# Headphones give the cleanest test results since echoCancellation alone
# doesn't fully solve this on laptop speakers.

# Each turn, to feel like talking to a real person instead of silence:
#   1. POST /transcribe - Deepgram only (~1-2s). As soon as the transcript is
#      back, the browser instantly plays a pre-cached filler line ("Okay,
#      let me look into that for you.") with near-zero latency, while...
#   2. POST /answer - KB lookup + GPT rephrase + Sarvam TTS (~8-15s) - runs
#      in parallel. Its audio plays right after the filler finishes.
#      Listening resumes automatically once the answer finishes playing.

# The browser keeps the last 5 transcribed questions from the call (oldest
# first) and sends them as the `previous` param on /answer -> search.json,
# so follow-ups like "I tried that, still not working" get disambiguated
# correctly. GPT itself stays stateless per turn (no memory) - only the KB
# lookup uses call history, per instruction.

# All of this reuses transcribe_audio / search_knowledge_base / ask_gpt /
# text_to_speech from voice_helpdesk_pipeline.py unchanged (imported, not
# duplicated), so the grounding/escalation rules in ask_gpt() stay identical
# to the CLI version - this file is only a transport layer.

# This is a local test tool, not a production server: it binds to localhost
# only and holds no auth. Do not expose it to the public internet as-is.

# SETUP:
#   pip install flask
#   (uses the same .env as voice_helpdesk_pipeline.py)

# RUN:
#   python web_demo.py
#   -> open http://127.0.0.1:5000 in a browser (mic access requires
#      localhost or https, so 127.0.0.1 works but a LAN IP will not)
#   -> use headphones for the cleanest voice-detection results
# """

# import os
# import tempfile
# from urllib.parse import quote

# from flask import Flask, jsonify, request, send_file, Response

# from voice_helpdesk_pipeline import (
#     FILLER_DIR,
#     ask_gpt,
#     get_or_create_filler,
#     search_knowledge_base,
#     text_to_speech,
#     transcribe_audio,
# )

# app = Flask(__name__)

# INDEX_HTML = """<!doctype html>
# <html>
# <head>
# <meta charset="utf-8">
# <title>Voice Helpdesk - Live Test</title>
# <style>
#   body { font-family: system-ui, sans-serif; max-width: 480px; margin: 60px auto; text-align: center; }
#   button { font-size: 18px; padding: 16px 32px; border-radius: 8px; border: none;
#            color: white; cursor: pointer; margin: 6px; }
#   button.start { background: #16a34a; }
#   button.end { background: #dc2626; }
#   button:disabled { background: #9ca3af; cursor: not-allowed; }
#   #stateIndicator { margin-top: 16px; padding: 10px 20px; border-radius: 20px;
#            display: inline-block; font-weight: 600; font-size: 14px; }
#   .state-idle { background: #dbeafe; color: #1e40af; }
#   .state-listening { background: #dcfce7; color: #166534; }
#   .state-thinking { background: #fef3c7; color: #92400e; }
#   .state-speaking { background: #ede9fe; color: #5b21b6; }
#   #status { margin-top: 16px; color: #374151; min-height: 1.5em; }
#   #conversationLog { margin-top: 16px; text-align: left; padding: 12px;
#            background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px;
#            max-height: 320px; overflow-y: auto; display: none; }
#   #conversationLog .turn { margin-bottom: 10px; padding-bottom: 10px; border-bottom: 1px solid #e5e7eb; }
#   #conversationLog .turn:last-child { border-bottom: none; margin-bottom: 0; }
#   #conversationLog .you { color: #1e3a8a; font-weight: 600; }
#   #conversationLog .agent { color: #5b21b6; font-weight: 600; }
#   #turnCount { font-size: 12px; color: #9ca3af; margin-top: 4px; }
# </style>
# </head>
# <body>
#   <h2>Voice Helpdesk - Live Test</h2>
#   <div id="callControls">
#     <button id="startBtn" class="start">Start Call</button>
#   </div>
#   <div id="activeControls" style="display:none;">
#     <button id="endBtn" class="end">End Call</button>
#     <div id="stateIndicator" class="state-idle">Listening...</div>
#   </div>
#   <div id="status"></div>
#   <div id="turnCount"></div>
#   <div id="conversationLog"></div>
#   <audio id="greeting" src="/filler/greeting.wav" preload="auto"></audio>
#   <audio id="filler" src="/filler/checking.wav" preload="auto"></audio>
#   <audio id="player" controls style="margin-top:16px; width:100%; display:none;"></audio>

# <script>
# const startBtn = document.getElementById('startBtn');
# const endBtn = document.getElementById('endBtn');
# const callControls = document.getElementById('callControls');
# const activeControls = document.getElementById('activeControls');
# const stateIndicator = document.getElementById('stateIndicator');
# const status = document.getElementById('status');
# const turnCountEl = document.getElementById('turnCount');
# const conversationLog = document.getElementById('conversationLog');
# const greeting = document.getElementById('greeting');
# const filler = document.getElementById('filler');
# const player = document.getElementById('player');

# let turnNumber = 0;

# function appendLog(who, text) {
#   conversationLog.style.display = 'block';
#   const turn = document.createElement('div');
#   turn.className = 'turn';
#   const label = who === 'you' ? 'You' : 'Agent';
#   turn.innerHTML = `<span class="${who}">${label}:</span> ${text}`;
#   conversationLog.appendChild(turn);
#   conversationLog.scrollTop = conversationLog.scrollHeight;
# }

# // --- Voice activity detection tuning ---
# // Lower SPEECH_THRESHOLD if it's not picking up your voice; raise it if
# // background noise keeps triggering false starts.
# const SPEECH_THRESHOLD = 0.02;   // RMS level that counts as "talking"
# const MIN_SPEECH_MS = 300;       // ignore blips shorter than this
# const SILENCE_HANG_MS = 900;     // how long a pause before we consider the turn over

# let audioContext, analyser, micStream;
# let vadRafId = null;
# let mediaRecorder, chunks = [];
# let recording = false;
# let speechStartedAt = null;
# let lastLoudAt = null;
# let busy = false;          // true from "sent for processing" until answer finishes playing
# let callActive = false;
# let conversationHistory = [];

# function setState(mode, text) {
#   stateIndicator.className = 'state-' + mode;
#   stateIndicator.textContent = text;
# }

# function resetTurnUI() {
#   status.textContent = '';
#   player.style.display = 'none';
#   player.pause();
# }

# async function startCall() {
#   callActive = true;
#   busy = true; // stay paused until the greeting finishes
#   conversationHistory = [];
#   turnNumber = 0;
#   conversationLog.innerHTML = '';
#   conversationLog.style.display = 'none';
#   turnCountEl.textContent = '';
#   callControls.style.display = 'none';
#   activeControls.style.display = 'block';
#   resetTurnUI();
#   setState('speaking', 'Connecting...');

#   micStream = await navigator.mediaDevices.getUserMedia({
#     audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
#   });
#   audioContext = new (window.AudioContext || window.webkitAudioContext)();
#   const source = audioContext.createMediaStreamSource(micStream);
#   analyser = audioContext.createAnalyser();
#   analyser.fftSize = 2048;
#   source.connect(analyser);

#   greeting.currentTime = 0;
#   greeting.onended = () => { busy = false; setState('listening', 'Listening...'); };
#   greeting.play().catch(() => { busy = false; setState('listening', 'Listening...'); });

#   vadLoop();
# }

# function endCall() {
#   callActive = false;
#   busy = true;
#   if (vadRafId) cancelAnimationFrame(vadRafId);
#   if (mediaRecorder && mediaRecorder.state === 'recording') mediaRecorder.stop();
#   if (micStream) micStream.getTracks().forEach(t => t.stop());
#   if (audioContext) audioContext.close();
#   greeting.pause();
#   filler.pause();
#   conversationHistory = [];
#   activeControls.style.display = 'none';
#   callControls.style.display = 'block';
#   resetTurnUI();
#   status.textContent = 'Call ended.';
# }

# startBtn.addEventListener('click', startCall);
# endBtn.addEventListener('click', endCall);

# function getRms(dataArray) {
#   let sumSquares = 0;
#   for (let i = 0; i < dataArray.length; i++) {
#     const v = (dataArray[i] - 128) / 128;
#     sumSquares += v * v;
#   }
#   return Math.sqrt(sumSquares / dataArray.length);
# }

# function vadLoop() {
#   if (!callActive) return;
#   const dataArray = new Uint8Array(analyser.fftSize);
#   analyser.getByteTimeDomainData(dataArray);
#   const rms = getRms(dataArray);
#   const now = performance.now();
#   const loud = rms > SPEECH_THRESHOLD;

#   if (!busy) {
#     if (!recording && loud) {
#       startSegment();
#     } else if (recording) {
#       if (loud) lastLoudAt = now;
#       if (now - lastLoudAt > SILENCE_HANG_MS) {
#         if (now - speechStartedAt - SILENCE_HANG_MS > MIN_SPEECH_MS) {
#           stopSegment();
#         } else {
#           // too short - treat as noise, discard and keep listening
#           cancelSegment();
#         }
#       }
#     }
#   }

#   vadRafId = requestAnimationFrame(vadLoop);
# }

# function startSegment() {
#   chunks = [];
#   mediaRecorder = new MediaRecorder(micStream);
#   mediaRecorder.ondataavailable = (ev) => chunks.push(ev.data);
#   mediaRecorder.start();
#   recording = true;
#   speechStartedAt = performance.now();
#   lastLoudAt = speechStartedAt;
#   setState('listening', 'Hearing you...');
# }

# function cancelSegment() {
#   if (mediaRecorder && mediaRecorder.state === 'recording') mediaRecorder.stop();
#   recording = false;
#   setState('listening', 'Listening...');
# }

# function stopSegment() {
#   recording = false;
#   busy = true; // pause VAD while we process + respond
#   setState('thinking', 'Thinking...');
#   mediaRecorder.onstop = handleRecording;
#   mediaRecorder.stop();
# }

# async function handleRecording() {
#   if (!callActive) return;
#   resetTurnUI();
#   const blob = new Blob(chunks, { type: 'audio/webm' });
#   const formData = new FormData();
#   formData.append('audio', blob, 'question.webm');

#   let transcript;
#   try {
#     const resp = await fetch('/transcribe', { method: 'POST', body: formData });
#     if (!resp.ok) { status.textContent = 'Error: ' + await resp.text(); resumeListening(); return; }
#     ({ transcript } = await resp.json());
#   } catch (err) {
#     status.textContent = 'Request failed: ' + err;
#     resumeListening();
#     return;
#   }

#   if (!transcript || !transcript.trim()) {
#     status.textContent = "Didn't catch that - go ahead and try again.";
#     resumeListening();
#     return;
#   }

#   turnNumber++;
#   turnCountEl.textContent = `Turn ${turnNumber}`;
#   appendLog('you', transcript);

#   // From here on, ANY failure (network, playback, whatever) must still lead
#   // back to resumeListening() - a call that silently stops listening is
#   // worse than a skipped turn.
#   try {
#     // Instant acknowledgment - pre-cached audio, plays with ~0 latency.
#     setState('speaking', 'Responding...');
#     filler.currentTime = 0;
#     const fillerDone = playAndWait(filler);

#     // The real answer (KB + GPT + TTS) runs in parallel while the filler plays.
#     const previous = conversationHistory.slice(-5);
#     const answerResp = await fetch('/answer', {
#       method: 'POST',
#       headers: { 'Content-Type': 'application/json' },
#       body: JSON.stringify({ transcript, previous }),
#     });

#     if (!answerResp.ok) {
#       status.textContent = 'Error: ' + await answerResp.text();
#       resumeListening();
#       return;
#     }

#     conversationHistory.push(transcript);
#     if (conversationHistory.length > 5) conversationHistory.shift();

#     const answer = decodeURIComponent(answerResp.headers.get('X-Answer') || '');
#     appendLog('agent', answer);
#     const audioUrl = URL.createObjectURL(await answerResp.blob());

#     await fillerDone;
#     if (!callActive) return;

#     player.src = audioUrl;
#     player.style.display = 'block';
#     await playAndWait(player);

#     resumeListening();
#   } catch (err) {
#     status.textContent = 'Request failed: ' + err;
#     resumeListening();
#   }
# }

# function playAndWait(audioEl) {
#   // Resolves on 'ended' - and also if play() itself fails (autoplay quirks,
#   // etc.) - so a blocked or broken audio element can never permanently
#   // stall the call.
#   return new Promise((resolve) => {
#     audioEl.onended = resolve;
#     audioEl.play().catch(resolve);
#   });
# }

# function resumeListening() {
#   if (!callActive) return;
#   busy = false;
#   setState('listening', 'Listening...');
# }
# </script>
# </body>
# </html>
# """


# @app.route("/")
# def index():
#     return INDEX_HTML


# @app.route("/filler/<name>")
# def filler(name):
#     safe_name = os.path.basename(name)  # no path traversal
#     path = os.path.join(FILLER_DIR, safe_name)
#     if not os.path.exists(path):
#         return Response("Not found", status=404)
#     return send_file(path, mimetype="audio/wav")


# @app.route("/transcribe", methods=["POST"])
# def transcribe():
#     if "audio" not in request.files:
#         return Response("No audio file uploaded.", status=400)

#     audio_file = request.files["audio"]
#     suffix = os.path.splitext(audio_file.filename or "")[1] or ".webm"

#     with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_in:
#         audio_file.save(tmp_in.name)
#         in_path = tmp_in.name

#     try:
#         transcript = transcribe_audio(in_path)
#         return jsonify({"transcript": transcript})
#     except Exception as exc:
#         return Response(f"Transcription error: {exc}", status=500)
#     finally:
#         os.remove(in_path)


# @app.route("/answer", methods=["POST"])
# def answer():
#     data = request.get_json(silent=True) or {}
#     transcript = (data.get("transcript") or "").strip()
#     if not transcript:
#         return Response("Missing transcript.", status=400)

#     previous = data.get("previous") or []
#     if not isinstance(previous, list):
#         previous = []
#     previous = [str(p) for p in previous][-5:]

#     out_path = None
#     try:
#         kb_result = search_knowledge_base(transcript, previous=previous)
#         spoken_answer = ask_gpt(transcript, kb_result.get("answer", ""), kb_result.get("confidence"))

#         with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_out:
#             out_path = tmp_out.name
#         text_to_speech(spoken_answer, output_path=out_path)

#         response = send_file(out_path, mimetype="audio/wav")
#         # Header values must be Latin-1; URL-encode so the answer text survives the trip.
#         response.headers["X-Answer"] = quote(spoken_answer)
#         response.call_on_close(lambda: os.path.exists(out_path) and os.remove(out_path))
#         return response
#     except Exception as exc:
#         if out_path and os.path.exists(out_path):
#             os.remove(out_path)
#         return Response(f"Pipeline error: {exc}", status=500)


# if __name__ == "__main__":
#     print("Pre-generating filler audio...")
#     get_or_create_filler("checking")
#     get_or_create_filler("greeting")
#     app.run(host="127.0.0.1", port=5000, debug=False)

"""
Live browser demo for the voice helpdesk pipeline - "phone call" mode.
------------------------------------------------------------------------
Green "Start Call" button -> plays a cached greeting -> the browser then
listens continuously and automatically detects when you start and stop
talking (simple volume-based voice activity detection, no button to hold).
Red "End Call" button ends it.

Note: this is client-side VAD on top of file-based Deepgram calls, not
true streaming transcription. Real Twilio + Deepgram streaming will do
endpoint detection server-side instead - this gets you the same
hands-free *feel* for local testing without that infrastructure yet.

While the assistant is speaking, listening is paused (no barge-in support
yet) so the mic doesn't pick up its own voice through your speakers.
Headphones give the cleanest test results since echoCancellation alone
doesn't fully solve this on laptop speakers.

Each turn, to feel like talking to a real person instead of silence:
  1. POST /transcribe - Deepgram only (~1-2s). As soon as the transcript is
     back, the browser instantly plays a pre-cached filler line ("Okay,
     let me look into that for you.") with near-zero latency, while...
  2. POST /answer - KB lookup + GPT rephrase + Sarvam TTS (~8-15s) - runs
     in parallel. Its audio plays right after the filler finishes.
     Listening resumes automatically once the answer finishes playing.

The browser keeps the last 5 transcribed questions from the call (oldest
first) and sends them as the `previous` param on /answer -> search.json,
so follow-ups like "I tried that, still not working" get disambiguated
correctly. GPT itself stays stateless per turn (no memory) - only the KB
lookup uses call history, per instruction.

All of this reuses transcribe_audio / search_knowledge_base / ask_gpt /
text_to_speech from voice_helpdesk_pipeline.py unchanged (imported, not
duplicated), so the grounding/escalation rules in ask_gpt() stay identical
to the CLI version - this file is only a transport layer.

This is a local test tool, not a production server: it binds to localhost
only and holds no auth. Do not expose it to the public internet as-is.

SETUP:
  pip install flask
  (uses the same .env as voice_helpdesk_pipeline.py)

RUN:
  python web_demo.py
  -> open http://127.0.0.1:5000 in a browser (mic access requires
     localhost or https, so 127.0.0.1 works but a LAN IP will not)
  -> use headphones for the cleanest voice-detection results
"""

import os
import tempfile
from urllib.parse import quote

from flask import Flask, jsonify, request, send_file, Response

from voice_helpdesk_pipeline import (
    FILLER_DIR,
    ask_gpt,
    get_or_create_filler,
    search_knowledge_base,
    text_to_speech,
    transcribe_audio,
)

app = Flask(__name__)

INDEX_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Voice Helpdesk - Live Test</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 480px; margin: 60px auto; text-align: center; }
  button { font-size: 18px; padding: 16px 32px; border-radius: 8px; border: none;
           color: white; cursor: pointer; margin: 6px; }
  button.start { background: #16a34a; }
  button.end { background: #dc2626; }
  button:disabled { background: #9ca3af; cursor: not-allowed; }
  #stateIndicator { margin-top: 16px; padding: 10px 20px; border-radius: 20px;
           display: inline-block; font-weight: 600; font-size: 14px; }
  .state-idle { background: #dbeafe; color: #1e40af; }
  .state-listening { background: #dcfce7; color: #166534; }
  .state-thinking { background: #fef3c7; color: #92400e; }
  .state-speaking { background: #ede9fe; color: #5b21b6; }
  #status { margin-top: 16px; color: #374151; min-height: 1.5em; }
  #conversationLog { margin-top: 16px; text-align: left; padding: 12px;
           background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px;
           max-height: 320px; overflow-y: auto; display: none; }
  #conversationLog .turn { margin-bottom: 10px; padding-bottom: 10px; border-bottom: 1px solid #e5e7eb; }
  #conversationLog .turn:last-child { border-bottom: none; margin-bottom: 0; }
  #conversationLog .you { color: #1e3a8a; font-weight: 600; }
  #conversationLog .agent { color: #5b21b6; font-weight: 600; }
  #turnCount { font-size: 12px; color: #9ca3af; margin-top: 4px; }
</style>
</head>
<body>
  <h2>Voice Helpdesk - Live Test</h2>
  <div id="callControls">
    <button id="startBtn" class="start">Start Call</button>
  </div>
  <div id="activeControls" style="display:none;">
    <button id="endBtn" class="end">End Call</button>
    <div id="stateIndicator" class="state-idle">Listening...</div>
  </div>
  <div id="status"></div>
  <div id="turnCount"></div>
  <div id="conversationLog"></div>
  <audio id="greeting" src="/filler/greeting.wav" preload="auto"></audio>
  <audio id="filler" src="/filler/checking.wav" preload="auto"></audio>
  <audio id="player" controls style="margin-top:16px; width:100%; display:none;"></audio>

<script>
const startBtn = document.getElementById('startBtn');
const endBtn = document.getElementById('endBtn');
const callControls = document.getElementById('callControls');
const activeControls = document.getElementById('activeControls');
const stateIndicator = document.getElementById('stateIndicator');
const status = document.getElementById('status');
const turnCountEl = document.getElementById('turnCount');
const conversationLog = document.getElementById('conversationLog');
const greeting = document.getElementById('greeting');
const filler = document.getElementById('filler');
const player = document.getElementById('player');

let turnNumber = 0;

function appendLog(who, text) {
  conversationLog.style.display = 'block';
  const turn = document.createElement('div');
  turn.className = 'turn';
  const labelSpan = document.createElement('span');
  labelSpan.className = who;
  labelSpan.textContent = (who === 'you' ? 'You' : 'Agent') + ': ';
  turn.appendChild(labelSpan);
  turn.appendChild(document.createTextNode(text));
  conversationLog.appendChild(turn);
  conversationLog.scrollTop = conversationLog.scrollHeight;
}

// --- Voice activity detection tuning ---
// Lower SPEECH_THRESHOLD if it's not picking up your voice; raise it if
// background noise keeps triggering false starts.
const SPEECH_THRESHOLD = 0.02;   // RMS level that counts as "talking"
const MIN_SPEECH_MS = 300;       // ignore blips shorter than this
const SILENCE_HANG_MS = 1300;    // how long a pause before we consider the turn over

let audioContext, analyser, micStream;
let vadRafId = null;
let mediaRecorder, chunks = [];
let recording = false;
let speechStartedAt = null;
let lastLoudAt = null;
let busy = false;          // true from "sent for processing" until answer finishes playing
let callActive = false;
let callId = 0;            // bumped every startCall - lets us discard stale async results from a previous call
let currentAudioUrl = null; // tracks the last object URL so we can revoke it
let conversationHistory = [];  // questions only - sent to the KB search for disambiguation
let exchangeHistory = [];      // full {question, answer} pairs - sent to GPT so it stops repeating itself

function setState(mode, text) {
  stateIndicator.className = 'state-' + mode;
  stateIndicator.textContent = text;
}

function resetTurnUI() {
  status.textContent = '';
  player.style.display = 'none';
  player.pause();
}

async function startCall() {
  callActive = true;
  callId += 1;
  busy = true; // stay paused until the greeting finishes
  conversationHistory = [];
  exchangeHistory = [];
  turnNumber = 0;
  conversationLog.innerHTML = '';
  conversationLog.style.display = 'none';
  turnCountEl.textContent = '';
  callControls.style.display = 'none';
  activeControls.style.display = 'block';
  resetTurnUI();
  setState('speaking', 'Connecting...');

  try {
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
  } catch (err) {
    status.textContent = 'Microphone access was denied or unavailable: ' + err.message;
    setState('idle', 'Mic unavailable');
    callActive = false;
    activeControls.style.display = 'none';
    callControls.style.display = 'block';
    return;
  }

  audioContext = new (window.AudioContext || window.webkitAudioContext)();
  const source = audioContext.createMediaStreamSource(micStream);
  analyser = audioContext.createAnalyser();
  analyser.fftSize = 2048;
  source.connect(analyser);

  greeting.currentTime = 0;
  greeting.onended = () => { busy = false; setState('listening', 'Listening...'); };
  greeting.play().catch(() => { busy = false; setState('listening', 'Listening...'); });

  vadLoop();
}

function endCall() {
  callActive = false;
  callId += 1; // invalidate any in-flight turn from this call
  busy = true;
  if (vadRafId) { cancelAnimationFrame(vadRafId); vadRafId = null; }
  if (mediaRecorder && mediaRecorder.state === 'recording') mediaRecorder.stop();
  mediaRecorder = null;
  if (micStream) { micStream.getTracks().forEach(t => t.stop()); micStream = null; }
  if (audioContext) { audioContext.close(); audioContext = null; }
  if (currentAudioUrl) { URL.revokeObjectURL(currentAudioUrl); currentAudioUrl = null; }
  greeting.pause();
  filler.pause();
  conversationHistory = [];
  exchangeHistory = [];
  activeControls.style.display = 'none';
  callControls.style.display = 'block';
  resetTurnUI();
  status.textContent = 'Call ended.';
}

startBtn.addEventListener('click', startCall);
endBtn.addEventListener('click', endCall);

function getRms(dataArray) {
  let sumSquares = 0;
  for (let i = 0; i < dataArray.length; i++) {
    const v = (dataArray[i] - 128) / 128;
    sumSquares += v * v;
  }
  return Math.sqrt(sumSquares / dataArray.length);
}

function vadLoop() {
  if (!callActive) return;
  try {
    const dataArray = new Uint8Array(analyser.fftSize);
    analyser.getByteTimeDomainData(dataArray);
    const rms = getRms(dataArray);
    const now = performance.now();
    const loud = rms > SPEECH_THRESHOLD;

    if (!busy) {
      if (!recording && loud) {
        startSegment();
      } else if (recording) {
        if (loud) lastLoudAt = now;
        if (now - lastLoudAt > SILENCE_HANG_MS) {
          if (now - speechStartedAt - SILENCE_HANG_MS > MIN_SPEECH_MS) {
            stopSegment();
          } else {
            // too short - treat as noise, discard and keep listening
            cancelSegment();
          }
        }
      }
    }
  } catch (err) {
    console.error('vadLoop error (continuing to listen):', err);
    // Reset to a safe state rather than leaving things stuck mid-segment.
    recording = false;
    busy = false;
  }

  vadRafId = requestAnimationFrame(vadLoop);
}

function startSegment() {
  chunks = [];
  mediaRecorder = new MediaRecorder(micStream);
  mediaRecorder.ondataavailable = (ev) => chunks.push(ev.data);
  mediaRecorder.start();
  recording = true;
  speechStartedAt = performance.now();
  lastLoudAt = speechStartedAt;
  setState('listening', 'Hearing you...');
}

function cancelSegment() {
  if (mediaRecorder && mediaRecorder.state === 'recording') mediaRecorder.stop();
  recording = false;
  setState('listening', 'Listening...');
}

function stopSegment() {
  recording = false;
  busy = true; // pause VAD while we process + respond
  setState('thinking', 'Thinking...');
  const myCallId = callId; // pin this turn to the call it belongs to
  mediaRecorder.onstop = () => handleRecording(myCallId);
  mediaRecorder.stop();
}

function waitForFillerEnd() {
  // Resolves once the filler clip finishes (or immediately if it isn't playing).
  return new Promise((resolve) => {
    if (filler.paused || filler.ended) {
      resolve();
    } else {
      filler.onended = resolve;
    }
  });
}

async function handleRecording(myCallId) {
  if (!callActive || myCallId !== callId) return;
  resetTurnUI();
  const blob = new Blob(chunks, { type: 'audio/webm' });
  const formData = new FormData();
  formData.append('audio', blob, 'question.webm');

  let transcript;
  try {
    const resp = await fetch('/transcribe', { method: 'POST', body: formData });
    if (myCallId !== callId) return; // call ended/restarted while this was in flight
    if (!resp.ok) {
      status.textContent = 'Error: ' + await resp.text();
      resumeListening(myCallId);
      return;
    }
    ({ transcript } = await resp.json());
  } catch (err) {
    if (myCallId !== callId) return;
    status.textContent = 'Request failed: ' + err;
    resumeListening(myCallId);
    return;
  }

  if (myCallId !== callId) return;

  if (!transcript || !transcript.trim()) {
    status.textContent = "Didn't catch that - go ahead and try again.";
    resumeListening(myCallId);
    return;
  }

  turnNumber++;
  turnCountEl.textContent = `Turn ${turnNumber}`;
  appendLog('you', transcript);

  // Instant acknowledgment - pre-cached audio, plays with ~0 latency.
  setState('speaking', 'Responding...');
  filler.currentTime = 0;
  filler.play().catch(() => {});

  // The real answer (KB + GPT + TTS) runs in parallel while the filler plays.
  const previous = conversationHistory.slice(-5);
  const history = exchangeHistory.slice(-4);
  let answerResp;
  try {
    answerResp = await fetch('/answer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ transcript, previous, history }),
    });
  } catch (err) {
    if (myCallId !== callId) return;
    status.textContent = 'Request failed: ' + err;
    await waitForFillerEnd(); // don't unmute the mic while the filler is still audible
    resumeListening(myCallId);
    return;
  }

  if (myCallId !== callId) return;

  if (!answerResp.ok) {
    status.textContent = 'Error: ' + await answerResp.text();
    await waitForFillerEnd();
    resumeListening(myCallId);
    return;
  }

  conversationHistory.push(transcript);
  if (conversationHistory.length > 5) conversationHistory.shift();

  const answer = decodeURIComponent(answerResp.headers.get('X-Answer') || '');
  appendLog('agent', answer);

  exchangeHistory.push({ question: transcript, answer });
  if (exchangeHistory.length > 4) exchangeHistory.shift();

  if (currentAudioUrl) URL.revokeObjectURL(currentAudioUrl);
  currentAudioUrl = URL.createObjectURL(await answerResp.blob());
  const audioUrl = currentAudioUrl;

  const playFinalAnswer = () => {
    if (!callActive || myCallId !== callId) return;
    player.src = audioUrl;
    player.style.display = 'block';
    player.play();
    player.onended = () => resumeListening(myCallId);
  };

  if (!filler.paused && !filler.ended) {
    filler.onended = playFinalAnswer;
  } else {
    playFinalAnswer();
  }
}

function resumeListening(myCallId) {
  if (!callActive || (myCallId !== undefined && myCallId !== callId)) return;
  busy = false;
  setState('listening', 'Listening...');
}
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return INDEX_HTML


@app.route("/filler/<name>")
def filler(name):
    safe_name = os.path.basename(name)  # no path traversal
    path = os.path.join(FILLER_DIR, safe_name)
    if not os.path.exists(path):
        return Response("Not found", status=404)
    return send_file(path, mimetype="audio/wav")


@app.route("/transcribe", methods=["POST"])
def transcribe():
    if "audio" not in request.files:
        return Response("No audio file uploaded.", status=400)

    audio_file = request.files["audio"]
    suffix = os.path.splitext(audio_file.filename or "")[1] or ".webm"

    tmp_in = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    in_path = tmp_in.name
    tmp_in.close()

    try:
        audio_file.save(in_path)
        transcript = transcribe_audio(in_path)
        return jsonify({"transcript": transcript})
    except Exception as exc:
        return Response(f"Transcription error: {exc}", status=500)
    finally:
        if os.path.exists(in_path):
            os.remove(in_path)


@app.route("/answer", methods=["POST"])
def answer():
    data = request.get_json(silent=True) or {}
    transcript = (data.get("transcript") or "").strip()
    if not transcript:
        return Response("Missing transcript.", status=400)

    previous = data.get("previous") or []
    if not isinstance(previous, list):
        previous = []
    previous = [str(p) for p in previous][-5:]

    # Full (question, answer) pairs from earlier in this call - this is what lets
    # GPT recognize "I already tried that" instead of repeating the same advice.
    raw_history = data.get("history") or []
    history = []
    if isinstance(raw_history, list):
        for turn in raw_history[-4:]:
            if isinstance(turn, dict):
                history.append({
                    "question": str(turn.get("question", ""))[:1000],
                    "answer": str(turn.get("answer", ""))[:1000],
                })

    out_path = None
    try:
        kb_result = search_knowledge_base(transcript, previous=previous)
        spoken_answer = ask_gpt(transcript, kb_result.get("answer", ""), history=history)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_out:
            out_path = tmp_out.name
        text_to_speech(spoken_answer, output_path=out_path)

        response = send_file(out_path, mimetype="audio/wav")
        # Header values must be Latin-1; URL-encode so the answer text survives the trip.
        response.headers["X-Answer"] = quote(spoken_answer)
        response.call_on_close(lambda: os.path.exists(out_path) and os.remove(out_path))
        return response
    except Exception as exc:
        if out_path and os.path.exists(out_path):
            os.remove(out_path)
        return Response(f"Pipeline error: {exc}", status=500)


if __name__ == "__main__":
    print("Pre-generating filler audio...")
    get_or_create_filler("checking")
    get_or_create_filler("greeting")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)