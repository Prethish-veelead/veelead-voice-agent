# # # """Flask entrypoint for the voice help agent scaffold."""

# # # from __future__ import annotations

# # # import os
# # # import tempfile
# # # from urllib.parse import quote

# # # from flask import Flask, Response, jsonify, request, send_file

# # # from app.pipeline import FILLER_PHRASES, get_or_create_filler, process_turn
# # # from app.stt.whisper_local import transcribe_audio_local

# # # app = Flask(__name__)


# # # INDEX_HTML = """<!doctype html>
# # # <html>
# # # <head>
# # # <meta charset="utf-8">
# # # <title>Voice Help Agent</title>
# # # <style>
# # #   body { font-family: system-ui, sans-serif; max-width: 480px; margin: 60px auto; text-align: center; }
# # #   button { font-size: 18px; padding: 16px 32px; border-radius: 8px; border: none;
# # #            color: white; cursor: pointer; margin: 6px; }
# # #   button.start { background: #16a34a; }
# # #   button.end { background: #dc2626; }
# # #   button:disabled { background: #9ca3af; cursor: not-allowed; }
# # #   #stateIndicator { margin-top: 16px; padding: 10px 20px; border-radius: 20px;
# # #            display: inline-block; font-weight: 600; font-size: 14px; }
# # #   .state-idle { background: #dbeafe; color: #1e40af; }
# # #   .state-listening { background: #dcfce7; color: #166534; }
# # #   .state-thinking { background: #fef3c7; color: #92400e; }
# # #   .state-speaking { background: #ede9fe; color: #5b21b6; }
# # #   #status { margin-top: 16px; color: #374151; min-height: 1.5em; }
# # #   #conversationLog { margin-top: 16px; text-align: left; padding: 12px;
# # #            background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px;
# # #            max-height: 320px; overflow-y: auto; display: none; }
# # #   #conversationLog .turn { margin-bottom: 10px; padding-bottom: 10px; border-bottom: 1px solid #e5e7eb; }
# # #   #conversationLog .turn:last-child { border-bottom: none; margin-bottom: 0; }
# # #   #conversationLog .you { color: #1e3a8a; font-weight: 600; }
# # #   #conversationLog .agent { color: #5b21b6; font-weight: 600; }
# # #   #turnCount { font-size: 12px; color: #9ca3af; margin-top: 4px; }
# # # </style>
# # # </head>
# # # <body>
# # #   <h2>Voice Help Agent</h2>
# # #   <div id="callControls">
# # #     <button id="startBtn" class="start">Start Call</button>
# # #   </div>
# # #   <div id="activeControls" style="display:none;">
# # #     <button id="endBtn" class="end">End Call</button>
# # #     <div id="stateIndicator" class="state-idle">Listening...</div>
# # #   </div>
# # #   <div id="status"></div>
# # #   <div id="turnCount"></div>
# # #   <div id="conversationLog"></div>
# # #   <audio id="greeting" src="/filler/greeting.wav" preload="auto"></audio>
# # #   <audio id="filler" src="/filler/checking.wav" preload="auto"></audio>
# # #   <audio id="player" controls style="margin-top:16px; width:100%; display:none;"></audio>

# # # <script>
# # # const startBtn = document.getElementById('startBtn');
# # # const endBtn = document.getElementById('endBtn');
# # # const callControls = document.getElementById('callControls');
# # # const activeControls = document.getElementById('activeControls');
# # # const stateIndicator = document.getElementById('stateIndicator');
# # # const status = document.getElementById('status');
# # # const turnCountEl = document.getElementById('turnCount');
# # # const conversationLog = document.getElementById('conversationLog');
# # # const greeting = document.getElementById('greeting');
# # # const filler = document.getElementById('filler');
# # # const player = document.getElementById('player');

# # # let turnNumber = 0;

# # # function appendLog(who, text) {
# # #   conversationLog.style.display = 'block';
# # #   const turn = document.createElement('div');
# # #   turn.className = 'turn';
# # #   const labelSpan = document.createElement('span');
# # #   labelSpan.className = who;
# # #   labelSpan.textContent = (who === 'you' ? 'You' : 'Agent') + ': ';
# # #   turn.appendChild(labelSpan);
# # #   turn.appendChild(document.createTextNode(text));
# # #   conversationLog.appendChild(turn);
# # #   conversationLog.scrollTop = conversationLog.scrollHeight;
# # # }

# # # // --- Voice activity detection tuning ---
# # # // Lower SPEECH_THRESHOLD if it's not picking up your voice; raise it if
# # # // background noise keeps triggering false starts.
# # # const SPEECH_THRESHOLD = 0.02;   // RMS level that counts as "talking"
# # # const MIN_SPEECH_MS = 300;       // ignore blips shorter than this
# # # const SILENCE_HANG_MS = 1300;    // how long a pause before we consider the turn over

# # # let audioContext, analyser, micStream;
# # # let vadRafId = null;
# # # let mediaRecorder, chunks = [];
# # # let recording = false;
# # # let speechStartedAt = null;
# # # let lastLoudAt = null;
# # # let busy = false;          // true from "sent for processing" until answer finishes playing
# # # let callActive = false;
# # # let callId = 0;            // bumped every startCall - lets us discard stale async results from a previous call
# # # let currentAudioUrl = null; // tracks the last object URL so we can revoke it
# # # let conversationHistory = [];  // questions only - sent to the KB search for disambiguation
# # # let exchangeHistory = [];      // full {question, answer} pairs - sent to the LLM so it stops repeating itself

# # # function setState(mode, text) {
# # #   stateIndicator.className = 'state-' + mode;
# # #   stateIndicator.textContent = text;
# # # }

# # # function resetTurnUI() {
# # #   status.textContent = '';
# # #   player.style.display = 'none';
# # #   player.pause();
# # # }

# # # async function startCall() {
# # #   callActive = true;
# # #   callId += 1;
# # #   busy = true; // stay paused until the greeting finishes
# # #   conversationHistory = [];
# # #   exchangeHistory = [];
# # #   turnNumber = 0;
# # #   conversationLog.innerHTML = '';
# # #   conversationLog.style.display = 'none';
# # #   turnCountEl.textContent = '';
# # #   callControls.style.display = 'none';
# # #   activeControls.style.display = 'block';
# # #   resetTurnUI();
# # #   setState('speaking', 'Connecting...');

# # #   try {
# # #     micStream = await navigator.mediaDevices.getUserMedia({
# # #       audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
# # #     });
# # #   } catch (err) {
# # #     status.textContent = 'Microphone access was denied or unavailable: ' + err.message;
# # #     setState('idle', 'Mic unavailable');
# # #     callActive = false;
# # #     activeControls.style.display = 'none';
# # #     callControls.style.display = 'block';
# # #     return;
# # #   }

# # #   audioContext = new (window.AudioContext || window.webkitAudioContext)();
# # #   const source = audioContext.createMediaStreamSource(micStream);
# # #   analyser = audioContext.createAnalyser();
# # #   analyser.fftSize = 2048;
# # #   source.connect(analyser);

# # #   greeting.currentTime = 0;
# # #   greeting.onended = () => { busy = false; setState('listening', 'Listening...'); };
# # #   greeting.play().catch(() => { busy = false; setState('listening', 'Listening...'); });

# # #   vadLoop();
# # # }

# # # function endCall() {
# # #   callActive = false;
# # #   callId += 1; // invalidate any in-flight turn from this call
# # #   busy = true;
# # #   if (vadRafId) { cancelAnimationFrame(vadRafId); vadRafId = null; }
# # #   if (mediaRecorder && mediaRecorder.state === 'recording') mediaRecorder.stop();
# # #   mediaRecorder = null;
# # #   if (micStream) { micStream.getTracks().forEach(t => t.stop()); micStream = null; }
# # #   if (audioContext) { audioContext.close(); audioContext = null; }
# # #   if (currentAudioUrl) { URL.revokeObjectURL(currentAudioUrl); currentAudioUrl = null; }
# # #   greeting.pause();
# # #   filler.pause();
# # #   conversationHistory = [];
# # #   exchangeHistory = [];
# # #   activeControls.style.display = 'none';
# # #   callControls.style.display = 'block';
# # #   resetTurnUI();
# # #   status.textContent = 'Call ended.';
# # # }

# # # startBtn.addEventListener('click', startCall);
# # # endBtn.addEventListener('click', endCall);

# # # function getRms(dataArray) {
# # #   let sumSquares = 0;
# # #   for (let i = 0; i < dataArray.length; i++) {
# # #     const v = (dataArray[i] - 128) / 128;
# # #     sumSquares += v * v;
# # #   }
# # #   return Math.sqrt(sumSquares / dataArray.length);
# # # }

# # # function vadLoop() {
# # #   if (!callActive) return;
# # #   try {
# # #     const dataArray = new Uint8Array(analyser.fftSize);
# # #     analyser.getByteTimeDomainData(dataArray);
# # #     const rms = getRms(dataArray);
# # #     const now = performance.now();
# # #     const loud = rms > SPEECH_THRESHOLD;

# # #     if (!busy) {
# # #       if (!recording && loud) {
# # #         startSegment();
# # #       } else if (recording) {
# # #         if (loud) lastLoudAt = now;
# # #         if (now - lastLoudAt > SILENCE_HANG_MS) {
# # #           if (now - speechStartedAt - SILENCE_HANG_MS > MIN_SPEECH_MS) {
# # #             stopSegment();
# # #           } else {
# # #             // too short - treat as noise, discard and keep listening
# # #             cancelSegment();
# # #           }
# # #         }
# # #       }
# # #     }
# # #   } catch (err) {
# # #     console.error('vadLoop error (continuing to listen):', err);
# # #     // Reset to a safe state rather than leaving things stuck mid-segment.
# # #     recording = false;
# # #     busy = false;
# # #   }

# # #   vadRafId = requestAnimationFrame(vadLoop);
# # # }

# # # function startSegment() {
# # #   chunks = [];
# # #   mediaRecorder = new MediaRecorder(micStream);
# # #   mediaRecorder.ondataavailable = (ev) => chunks.push(ev.data);
# # #   mediaRecorder.start();
# # #   recording = true;
# # #   speechStartedAt = performance.now();
# # #   lastLoudAt = speechStartedAt;
# # #   setState('listening', 'Hearing you...');
# # # }

# # # function cancelSegment() {
# # #   if (mediaRecorder && mediaRecorder.state === 'recording') mediaRecorder.stop();
# # #   recording = false;
# # #   setState('listening', 'Listening...');
# # # }

# # # function stopSegment() {
# # #   recording = false;
# # #   busy = true; // pause VAD while we process + respond
# # #   setState('thinking', 'Thinking...');
# # #   const myCallId = callId; // pin this turn to the call it belongs to
# # #   mediaRecorder.onstop = () => handleRecording(myCallId);
# # #   mediaRecorder.stop();
# # # }

# # # function waitForFillerEnd() {
# # #   // Resolves once the filler clip finishes (or immediately if it isn't playing).
# # #   return new Promise((resolve) => {
# # #     if (filler.paused || filler.ended) {
# # #       resolve();
# # #     } else {
# # #       filler.onended = resolve;
# # #     }
# # #   });
# # # }

# # # async function handleRecording(myCallId) {
# # #   if (!callActive || myCallId !== callId) return;
# # #   resetTurnUI();
# # #   const blob = new Blob(chunks, { type: 'audio/webm' });
# # #   const formData = new FormData();
# # #   formData.append('audio', blob, 'question.webm');

# # #   let transcript;
# # #   try {
# # #     const resp = await fetch('/transcribe', { method: 'POST', body: formData });
# # #     if (myCallId !== callId) return; // call ended/restarted while this was in flight
# # #     if (!resp.ok) {
# # #       status.textContent = 'Error: ' + await resp.text();
# # #       resumeListening(myCallId);
# # #       return;
# # #     }
# # #     ({ transcript } = await resp.json());
# # #   } catch (err) {
# # #     if (myCallId !== callId) return;
# # #     status.textContent = 'Request failed: ' + err;
# # #     resumeListening(myCallId);
# # #     return;
# # #   }

# # #   if (myCallId !== callId) return;

# # #   if (!transcript || !transcript.trim()) {
# # #     status.textContent = "Didn't catch that - go ahead and try again.";
# # #     resumeListening(myCallId);
# # #     return;
# # #   }

# # #   turnNumber++;
# # #   turnCountEl.textContent = `Turn ${turnNumber}`;
# # #   appendLog('you', transcript);

# # #   setState('speaking', 'Responding...');

# # #   // Only play the "let me check" filler if the answer is actually taking a
# # #   // while. FILLER_DELAY_MS below is the threshold for "taking a while."
# # #   const FILLER_DELAY_MS = 700;
# # #   let fillerTimer = setTimeout(() => {
# # #     filler.currentTime = 0;
# # #     filler.play().catch(() => {});
# # #   }, FILLER_DELAY_MS);

# # #   const previous = conversationHistory.slice(-5);
# # #   const history = exchangeHistory.slice(-4);
# # #   let answerResp;
# # #   try {
# # #     answerResp = await fetch('/answer', {
# # #       method: 'POST',
# # #       headers: { 'Content-Type': 'application/json' },
# # #       body: JSON.stringify({ transcript, previous, history }),
# # #     });
# # #   } catch (err) {
# # #     clearTimeout(fillerTimer);
# # #     if (myCallId !== callId) return;
# # #     status.textContent = 'Request failed: ' + err;
# # #     await waitForFillerEnd(); // don't unmute the mic while the filler is still audible
# # #     resumeListening(myCallId);
# # #     return;
# # #   }

# # #   clearTimeout(fillerTimer); // answer is back - cancel the filler if it hasn't started yet

# # #   if (myCallId !== callId) return;

# # #   if (!answerResp.ok) {
# # #     status.textContent = 'Error: ' + await answerResp.text();
# # #     await waitForFillerEnd();
# # #     resumeListening(myCallId);
# # #     return;
# # #   }

# # #   conversationHistory.push(transcript);
# # #   if (conversationHistory.length > 5) conversationHistory.shift();

# # #   const answer = decodeURIComponent(answerResp.headers.get('X-Answer') || '');
# # #   appendLog('agent', answer);

# # #   exchangeHistory.push({ question: transcript, answer });
# # #   if (exchangeHistory.length > 4) exchangeHistory.shift();

# # #   if (currentAudioUrl) URL.revokeObjectURL(currentAudioUrl);
# # #   currentAudioUrl = URL.createObjectURL(await answerResp.blob());
# # #   const audioUrl = currentAudioUrl;

# # #   const playFinalAnswer = () => {
# # #     if (!callActive || myCallId !== callId) return;
# # #     player.src = audioUrl;
# # #     player.style.display = 'block';
# # #     player.play();
# # #     player.onended = () => resumeListening(myCallId);
# # #   };

# # #   if (!filler.paused && !filler.ended) {
# # #     filler.onended = playFinalAnswer;
# # #   } else {
# # #     playFinalAnswer();
# # #   }
# # # }

# # # function resumeListening(myCallId) {
# # #   if (!callActive || (myCallId !== undefined && myCallId !== callId)) return;
# # #   busy = false;
# # #   setState('listening', 'Listening...');
# # # }
# # # </script>
# # # </body>
# # # </html>
# # # """


# # # @app.get("/")
# # # def index():
# # #     return INDEX_HTML


# # # @app.get("/health")
# # # def health():
# # #     return jsonify({"status": "ok"})


# # # @app.get("/filler/<name>")
# # # def filler(name: str):
# # #     safe_name = os.path.basename(name)
# # #     key = os.path.splitext(safe_name)[0]
# # #     if key not in FILLER_PHRASES:
# # #         return Response("Not found", status=404)
# # #     path = get_or_create_filler(key)
# # #     return send_file(path, mimetype="audio/wav")


# # # @app.post("/transcribe")
# # # def transcribe():
# # #     if "audio" not in request.files:
# # #         return Response("No audio file uploaded.", status=400)

# # #     audio_file = request.files["audio"]
# # #     suffix = os.path.splitext(audio_file.filename or "")[1] or ".webm"

# # #     tmp_in = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
# # #     in_path = tmp_in.name
# # #     tmp_in.close()

# # #     try:
# # #         audio_file.save(in_path)
# # #         transcript = transcribe_audio_local(in_path)
# # #         return jsonify({"transcript": transcript})
# # #     except Exception as exc:
# # #         return Response(f"Transcription error: {exc}", status=500)
# # #     finally:
# # #         if os.path.exists(in_path):
# # #             os.remove(in_path)


# # # @app.post("/answer")
# # # def answer():
# # #     data = request.get_json(silent=True) or {}
# # #     transcript = (data.get("transcript") or "").strip()
# # #     if not transcript:
# # #         return Response("Missing transcript.", status=400)

# # #     previous = data.get("previous") or []
# # #     if not isinstance(previous, list):
# # #         previous = []
# # #     previous = [str(item) for item in previous][-5:]

# # #     raw_history = data.get("history") or []
# # #     history: list[dict] = []
# # #     if isinstance(raw_history, list):
# # #         for turn in raw_history[-4:]:
# # #             if isinstance(turn, dict):
# # #                 history.append(
# # #                     {
# # #                         "question": str(turn.get("question", ""))[:1000],
# # #                         "answer": str(turn.get("answer", ""))[:1000],
# # #                     }
# # #                 )

# # #     out_path = None
# # #     try:
# # #         with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_out:
# # #             out_path = tmp_out.name

# # #         result = process_turn(
# # #             transcript,
# # #             history=history,
# # #             previous=previous,
# # #             output_path=out_path,
# # #         )

# # #         response = send_file(result["audio_path"], mimetype="audio/wav")
# # #         response.headers["X-Answer"] = quote(result["answer"])
# # #         response.call_on_close(lambda: os.path.exists(out_path) and os.remove(out_path))
# # #         return response
# # #     except Exception as exc:
# # #         if out_path and os.path.exists(out_path):
# # #             os.remove(out_path)
# # #         return Response(f"Pipeline error: {exc}", status=500)


# # # if __name__ == "__main__":
# # #     get_or_create_filler("checking")
# # #     get_or_create_filler("greeting")
# # #     app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
# # """Flask entrypoint for the voice help agent."""

# # from __future__ import annotations

# # import base64
# # import json
# # import os
# # import tempfile
# # import time

# # from flask import Flask, Response, jsonify, request, send_file

# # from app.pipeline import FILLER_PHRASES, get_or_create_filler, stream_turn
# # from app.stt.whisper_local import transcribe_audio_local
# # from app.telemetry.logger import log_turn

# # app = Flask(__name__)


# # INDEX_HTML = """<!doctype html>
# # <html>
# # <head>
# # <meta charset="utf-8">
# # <title>Voice Help Agent</title>
# # <style>
# #   body { font-family: system-ui, sans-serif; max-width: 480px; margin: 60px auto; text-align: center; }
# #   button { font-size: 18px; padding: 16px 32px; border-radius: 8px; border: none;
# #            color: white; cursor: pointer; margin: 6px; }
# #   button.start { background: #16a34a; }
# #   button.end { background: #dc2626; }
# #   button:disabled { background: #9ca3af; cursor: not-allowed; }
# #   #stateIndicator { margin-top: 16px; padding: 10px 20px; border-radius: 20px;
# #            display: inline-block; font-weight: 600; font-size: 14px; }
# #   .state-idle { background: #dbeafe; color: #1e40af; }
# #   .state-listening { background: #dcfce7; color: #166534; }
# #   .state-thinking { background: #fef3c7; color: #92400e; }
# #   .state-speaking { background: #ede9fe; color: #5b21b6; }
# #   #status { margin-top: 16px; color: #374151; min-height: 1.5em; }
# #   #conversationLog { margin-top: 16px; text-align: left; padding: 12px;
# #            background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px;
# #            max-height: 320px; overflow-y: auto; display: none; }
# #   #conversationLog .turn { margin-bottom: 10px; padding-bottom: 10px; border-bottom: 1px solid #e5e7eb; }
# #   #conversationLog .turn:last-child { border-bottom: none; margin-bottom: 0; }
# #   #conversationLog .you { color: #1e3a8a; font-weight: 600; }
# #   #conversationLog .agent { color: #5b21b6; font-weight: 600; }
# #   #turnCount { font-size: 12px; color: #9ca3af; margin-top: 4px; }
# # </style>
# # </head>
# # <body>
# #   <h2>Voice Help Agent</h2>
# #   <div id="callControls">
# #     <button id="startBtn" class="start">Start Call</button>
# #   </div>
# #   <div id="activeControls" style="display:none;">
# #     <button id="endBtn" class="end">End Call</button>
# #     <div id="stateIndicator" class="state-idle">Listening...</div>
# #   </div>
# #   <div id="status"></div>
# #   <div id="turnCount"></div>
# #   <div id="conversationLog"></div>
# #   <audio id="greeting" src="/filler/greeting.wav" preload="auto"></audio>
# #   <audio id="filler" src="/filler/checking.wav" preload="auto"></audio>
# #   <audio id="player" controls style="margin-top:16px; width:100%; display:none;"></audio>

# # <script>
# # const startBtn = document.getElementById('startBtn');
# # const endBtn = document.getElementById('endBtn');
# # const callControls = document.getElementById('callControls');
# # const activeControls = document.getElementById('activeControls');
# # const stateIndicator = document.getElementById('stateIndicator');
# # const status = document.getElementById('status');
# # const turnCountEl = document.getElementById('turnCount');
# # const conversationLog = document.getElementById('conversationLog');
# # const greeting = document.getElementById('greeting');
# # const filler = document.getElementById('filler');
# # const player = document.getElementById('player');

# # let turnNumber = 0;

# # function appendLog(who, text) {
# #   conversationLog.style.display = 'block';
# #   const turn = document.createElement('div');
# #   turn.className = 'turn';
# #   const labelSpan = document.createElement('span');
# #   labelSpan.className = who;
# #   labelSpan.textContent = (who === 'you' ? 'You' : 'Agent') + ': ';
# #   turn.appendChild(labelSpan);
# #   turn.appendChild(document.createTextNode(text));
# #   conversationLog.appendChild(turn);
# #   conversationLog.scrollTop = conversationLog.scrollHeight;
# # }

# # const SPEECH_THRESHOLD = 0.02;
# # const MIN_SPEECH_MS = 300;
# # const SILENCE_HANG_MS = 1300;

# # let audioContext, analyser, micStream;
# # let vadRafId = null;
# # let mediaRecorder, chunks = [];
# # let recording = false;
# # let speechStartedAt = null;
# # let lastLoudAt = null;
# # let busy = false;
# # let callActive = false;
# # let callId = 0;
# # let conversationHistory = [];
# # let exchangeHistory = [];

# # function setState(mode, text) {
# #   stateIndicator.className = 'state-' + mode;
# #   stateIndicator.textContent = text;
# # }

# # function resetTurnUI() {
# #   status.textContent = '';
# #   player.style.display = 'none';
# #   player.pause();
# # }

# # async function startCall() {
# #   callActive = true;
# #   callId += 1;
# #   busy = true;
# #   conversationHistory = [];
# #   exchangeHistory = [];
# #   turnNumber = 0;
# #   conversationLog.innerHTML = '';
# #   conversationLog.style.display = 'none';
# #   turnCountEl.textContent = '';
# #   callControls.style.display = 'none';
# #   activeControls.style.display = 'block';
# #   resetTurnUI();
# #   setState('speaking', 'Connecting...');

# #   try {
# #     micStream = await navigator.mediaDevices.getUserMedia({
# #       audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
# #     });
# #   } catch (err) {
# #     status.textContent = 'Microphone access was denied or unavailable: ' + err.message;
# #     setState('idle', 'Mic unavailable');
# #     callActive = false;
# #     activeControls.style.display = 'none';
# #     callControls.style.display = 'block';
# #     return;
# #   }

# #   audioContext = new (window.AudioContext || window.webkitAudioContext)();
# #   const source = audioContext.createMediaStreamSource(micStream);
# #   analyser = audioContext.createAnalyser();
# #   analyser.fftSize = 2048;
# #   source.connect(analyser);

# #   greeting.currentTime = 0;
# #   greeting.onended = () => { busy = false; setState('listening', 'Listening...'); };
# #   greeting.play().catch(() => { busy = false; setState('listening', 'Listening...'); });

# #   vadLoop();
# # }

# # function endCall() {
# #   callActive = false;
# #   callId += 1;
# #   busy = true;
# #   if (vadRafId) { cancelAnimationFrame(vadRafId); vadRafId = null; }
# #   if (mediaRecorder && mediaRecorder.state === 'recording') mediaRecorder.stop();
# #   mediaRecorder = null;
# #   if (micStream) { micStream.getTracks().forEach(t => t.stop()); micStream = null; }
# #   if (audioContext) { audioContext.close(); audioContext = null; }
# #   greeting.pause();
# #   filler.pause();
# #   conversationHistory = [];
# #   exchangeHistory = [];
# #   activeControls.style.display = 'none';
# #   callControls.style.display = 'block';
# #   resetTurnUI();
# #   status.textContent = 'Call ended.';
# # }

# # startBtn.addEventListener('click', startCall);
# # endBtn.addEventListener('click', endCall);

# # function getRms(dataArray) {
# #   let sumSquares = 0;
# #   for (let i = 0; i < dataArray.length; i++) {
# #     const v = (dataArray[i] - 128) / 128;
# #     sumSquares += v * v;
# #   }
# #   return Math.sqrt(sumSquares / dataArray.length);
# # }

# # function vadLoop() {
# #   if (!callActive) return;
# #   try {
# #     const dataArray = new Uint8Array(analyser.fftSize);
# #     analyser.getByteTimeDomainData(dataArray);
# #     const rms = getRms(dataArray);
# #     const now = performance.now();
# #     const loud = rms > SPEECH_THRESHOLD;

# #     if (!busy) {
# #       if (!recording && loud) {
# #         startSegment();
# #       } else if (recording) {
# #         if (loud) lastLoudAt = now;
# #         if (now - lastLoudAt > SILENCE_HANG_MS) {
# #           if (now - speechStartedAt - SILENCE_HANG_MS > MIN_SPEECH_MS) {
# #             stopSegment();
# #           } else {
# #             cancelSegment();
# #           }
# #         }
# #       }
# #     }
# #   } catch (err) {
# #     console.error('vadLoop error (continuing to listen):', err);
# #     recording = false;
# #     busy = false;
# #   }

# #   vadRafId = requestAnimationFrame(vadLoop);
# # }

# # function startSegment() {
# #   chunks = [];
# #   mediaRecorder = new MediaRecorder(micStream);
# #   mediaRecorder.ondataavailable = (ev) => chunks.push(ev.data);
# #   mediaRecorder.start();
# #   recording = true;
# #   speechStartedAt = performance.now();
# #   lastLoudAt = speechStartedAt;
# #   setState('listening', 'Hearing you...');
# # }

# # function cancelSegment() {
# #   if (mediaRecorder && mediaRecorder.state === 'recording') mediaRecorder.stop();
# #   recording = false;
# #   setState('listening', 'Listening...');
# # }

# # function stopSegment() {
# #   recording = false;
# #   busy = true;
# #   setState('thinking', 'Thinking...');
# #   const myCallId = callId;
# #   mediaRecorder.onstop = () => handleRecording(myCallId);
# #   mediaRecorder.stop();
# # }

# # async function handleRecording(myCallId) {
# #   if (!callActive || myCallId !== callId) return;
# #   resetTurnUI();
# #   const turnId = crypto.randomUUID();
# #   const blob = new Blob(chunks, { type: 'audio/webm' });
# #   const formData = new FormData();
# #   formData.append('audio', blob, 'question.webm');
# #   formData.append('turn_id', turnId);

# #   let transcript;
# #   try {
# #     const resp = await fetch('/transcribe', { method: 'POST', body: formData });
# #     if (myCallId !== callId) return;
# #     if (!resp.ok) {
# #       status.textContent = 'Error: ' + await resp.text();
# #       resumeListening(myCallId);
# #       return;
# #     }
# #     ({ transcript } = await resp.json());
# #   } catch (err) {
# #     if (myCallId !== callId) return;
# #     status.textContent = 'Request failed: ' + err;
# #     resumeListening(myCallId);
# #     return;
# #   }

# #   if (myCallId !== callId) return;

# #   if (!transcript || !transcript.trim()) {
# #     status.textContent = "Didn't catch that - go ahead and try again.";
# #     resumeListening(myCallId);
# #     return;
# #   }

# #   turnNumber++;
# #   turnCountEl.textContent = `Turn ${turnNumber}`;
# #   appendLog('you', transcript);
# #   setState('speaking', 'Responding...');

# #   // Every turn now goes through the same streaming protocol - a greeting
# #   // is just a stream that happens to have exactly one chunk, so there's no
# #   // need for a separate "instant reply" code path anymore.
# #   const FILLER_DELAY_MS = 700;
# #   let fillerTimer = setTimeout(() => {
# #     filler.currentTime = 0;
# #     filler.play().catch(() => {});
# #   }, FILLER_DELAY_MS);

# #   const previous = conversationHistory.slice(-5);
# #   const history = exchangeHistory.slice(-4);
# #   let answerResp;
# #   try {
# #     answerResp = await fetch('/answer', {
# #       method: 'POST',
# #       headers: { 'Content-Type': 'application/json' },
# #       body: JSON.stringify({ transcript, previous, history, turn_id: turnId }),
# #     });
# #   } catch (err) {
# #     clearTimeout(fillerTimer);
# #     if (myCallId !== callId) return;
# #     status.textContent = 'Request failed: ' + err;
# #     await waitForFillerEnd();
# #     resumeListening(myCallId);
# #     return;
# #   }

# #   clearTimeout(fillerTimer);
# #   if (myCallId !== callId) return;

# #   if (!answerResp.ok) {
# #     status.textContent = 'Error: ' + await answerResp.text();
# #     await waitForFillerEnd();
# #     resumeListening(myCallId);
# #     return;
# #   }

# #   conversationHistory.push(transcript);
# #   if (conversationHistory.length > 5) conversationHistory.shift();

# #   await playStreamedAnswer(answerResp, myCallId, transcript);
# # }

# # function waitForFillerEnd() {
# #   return new Promise((resolve) => {
# #     if (filler.paused || filler.ended) {
# #       resolve();
# #     } else {
# #       filler.onended = resolve;
# #     }
# #   });
# # }

# # async function playStreamedAnswer(response, myCallId, questionText) {
# #   const reader = response.body.getReader();
# #   const decoder = new TextDecoder();
# #   let buffer = '';
# #   const audioQueue = [];
# #   let isPlaying = false;
# #   let finalAnswerText = '';
# #   let streamError = null;

# #   function playNext() {
# #     if (!callActive || myCallId !== callId) return;
# #     if (audioQueue.length === 0) { isPlaying = false; return; }
# #     isPlaying = true;
# #     const url = audioQueue.shift();
# #     player.src = url;
# #     player.style.display = 'block';
# #     player.play().catch(() => {});
# #     player.onended = () => {
# #       URL.revokeObjectURL(url);
# #       playNext();
# #     };
# #   }

# #   while (true) {
# #     let readResult;
# #     try {
# #       readResult = await reader.read();
# #     } catch (err) {
# #       streamError = String(err);
# #       break;
# #     }
# #     if (readResult.done) break;
# #     if (myCallId !== callId) return;

# #     buffer += decoder.decode(readResult.value, { stream: true });
# #     let newlineIndex;
# #     while ((newlineIndex = buffer.indexOf('\\n')) !== -1) {
# #       const line = buffer.slice(0, newlineIndex);
# #       buffer = buffer.slice(newlineIndex + 1);
# #       if (!line.trim()) continue;

# #       let msg;
# #       try {
# #         msg = JSON.parse(line);
# #       } catch (err) {
# #         continue;
# #       }

# #       if (msg.done) {
# #         finalAnswerText = msg.spoken_answer || '';
# #         if (msg.error) streamError = msg.error;
# #         continue;
# #       }
# #       if (!msg.audio_b64) continue;

# #       const binary = atob(msg.audio_b64);
# #       const bytes = new Uint8Array(binary.length);
# #       for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
# #       const blob = new Blob([bytes], { type: 'audio/wav' });
# #       const url = URL.createObjectURL(blob);
# #       audioQueue.push(url);
# #       if (!isPlaying) playNext();
# #     }
# #   }

# #   if (myCallId !== callId) return;

# #   if (streamError) {
# #     status.textContent = 'Error: ' + streamError;
# #   }
# #   if (finalAnswerText) {
# #     appendLog('agent', finalAnswerText);
# #     exchangeHistory.push({ question: questionText, answer: finalAnswerText });
# #     if (exchangeHistory.length > 4) exchangeHistory.shift();
# #   }

# #   await new Promise((resolve) => {
# #     const checkDone = () => {
# #       if (!callActive || myCallId !== callId) { resolve(); return; }
# #       if (!isPlaying && audioQueue.length === 0) resolve();
# #       else setTimeout(checkDone, 150);
# #     };
# #     checkDone();
# #   });

# #   resumeListening(myCallId);
# # }

# # function resumeListening(myCallId) {
# #   if (!callActive || (myCallId !== undefined && myCallId !== callId)) return;
# #   busy = false;
# #   setState('listening', 'Listening...');
# # }
# # </script>
# # </body>
# # </html>
# # """


# # @app.get("/")
# # def index():
# #     return INDEX_HTML


# # @app.get("/health")
# # def health():
# #     return jsonify({"status": "ok"})


# # @app.get("/filler/<name>")
# # def filler(name: str):
# #     safe_name = os.path.basename(name)
# #     key = os.path.splitext(safe_name)[0]
# #     if key not in FILLER_PHRASES:
# #         return Response("Not found", status=404)
# #     path = get_or_create_filler(key)
# #     return send_file(path, mimetype="audio/wav")


# # @app.post("/transcribe")
# # def transcribe():
# #     if "audio" not in request.files:
# #         return Response("No audio file uploaded.", status=400)

# #     turn_id = request.form.get("turn_id", "")
# #     audio_file = request.files["audio"]
# #     suffix = os.path.splitext(audio_file.filename or "")[1] or ".webm"

# #     tmp_in = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
# #     in_path = tmp_in.name
# #     tmp_in.close()

# #     t0 = time.time()
# #     try:
# #         audio_file.save(in_path)
# #         transcript = transcribe_audio_local(in_path)
# #         log_turn("transcribe", turn_id=turn_id, stt_time_s=round(time.time() - t0, 2), transcript=transcript)
# #         return jsonify({"transcript": transcript})
# #     except Exception as exc:
# #         log_turn("transcribe", turn_id=turn_id, stt_time_s=round(time.time() - t0, 2), error=str(exc))
# #         return Response(f"Transcription error: {exc}", status=500)
# #     finally:
# #         if os.path.exists(in_path):
# #             os.remove(in_path)


# # @app.post("/answer")
# # def answer():
# #     data = request.get_json(silent=True) or {}
# #     transcript = (data.get("transcript") or "").strip()
# #     turn_id = data.get("turn_id", "")
# #     if not transcript:
# #         return Response("Missing transcript.", status=400)

# #     previous = data.get("previous") or []
# #     if not isinstance(previous, list):
# #         previous = []
# #     previous = [str(item) for item in previous][-5:]

# #     raw_history = data.get("history") or []
# #     history: list[dict] = []
# #     if isinstance(raw_history, list):
# #         for turn in raw_history[-4:]:
# #             if isinstance(turn, dict):
# #                 history.append({
# #                     "question": str(turn.get("question", ""))[:1000],
# #                     "answer": str(turn.get("answer", ""))[:1000],
# #                 })

# #     def generate():
# #         try:
# #             for chunk in stream_turn(transcript, turn_id=turn_id, history=history, previous=previous):
# #                 if chunk.get("done"):
# #                     payload = {"done": True, "spoken_answer": chunk.get("spoken_answer", "")}
# #                     if chunk.get("error"):
# #                         payload["error"] = chunk["error"]
# #                     yield json.dumps(payload) + "\n"
# #                     continue

# #                 audio_path = chunk["audio_path"]
# #                 is_cached = chunk.get("_cached", False)
# #                 try:
# #                     with open(audio_path, "rb") as f:
# #                         audio_bytes = f.read()
# #                 finally:
# #                     # Don't delete the shared filler cache file - only
# #                     # per-sentence temp files get cleaned up here.
# #                     if not is_cached and os.path.exists(audio_path):
# #                         os.remove(audio_path)

# #                 yield json.dumps({
# #                     "text": chunk["text"],
# #                     "audio_b64": base64.b64encode(audio_bytes).decode("utf-8"),
# #                 }) + "\n"
# #         except Exception as exc:
# #             yield json.dumps({"done": True, "error": str(exc), "spoken_answer": ""}) + "\n"

# #     return Response(generate(), mimetype="application/x-ndjson")


# # if __name__ == "__main__":
# #     get_or_create_filler("checking")
# #     get_or_create_filler("greeting")
# #     app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)

# """Flask entrypoint for the voice help agent."""

# from __future__ import annotations

# import base64
# import json
# import os
# import re
# import tempfile
# import time

# from flask import Flask, Response, jsonify, request, send_file

# from app.config import get_settings
# from app.pipeline import FILLER_PHRASES, get_or_create_filler, stream_turn
# from app.stt.whisper_local import transcribe_audio_local
# from app.telemetry.logger import log_turn

# app = Flask(__name__)

# # Whisper occasionally transcribes background noise/silence as a stray
# # punctuation mark (a lone "," showed up in real test logs, wasting a full
# # KB+LLM+TTS round trip on nothing). Require at least 2 real alphanumeric
# # characters before treating a transcript as real speech.
# _MEANINGFUL_TRANSCRIPT_RE = re.compile(r"[a-zA-Z0-9]{2,}")


# def _is_meaningful(text: str) -> bool:
#     return bool(_MEANINGFUL_TRANSCRIPT_RE.search(text))


# INDEX_HTML = """<!doctype html>
# <html>
# <head>
# <meta charset="utf-8">
# <title>Voice Help Agent</title>
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
#   #timingBox { margin-top: 12px; padding: 10px 14px; text-align: left; font-size: 12px;
#            font-family: ui-monospace, monospace; color: #374151; background: #f9fafb;
#            border: 1px solid #e5e7eb; border-radius: 8px; display: none; }
#   #timingBox .row { display: flex; justify-content: space-between; margin-bottom: 4px; }
#   #timingBox .row:last-child { margin-bottom: 0; padding-top: 6px; border-top: 1px solid #e5e7eb; font-weight: 600; }
#   #timingBox .label { color: #6b7280; }
# </style>
# </head>
# <body>
#   <h2>Voice Help Agent</h2>
#   <div id="callControls">
#     <button id="startBtn" class="start">Start Call</button>
#   </div>
#   <div id="activeControls" style="display:none;">
#     <button id="endBtn" class="end">End Call</button>
#     <div id="stateIndicator" class="state-idle">Listening...</div>
#   </div>
#   <div id="status"></div>
#   <div id="turnCount"></div>
#   <div id="timingBox"></div>
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
# const timingBox = document.getElementById('timingBox');
# const greeting = document.getElementById('greeting');
# const filler = document.getElementById('filler');
# const player = document.getElementById('player');

# let turnNumber = 0;
# let lastSttTime = null;

# function fmtTime(v) {
#   return (typeof v === 'number') ? v.toFixed(2) + 's' : '—';
# }

# function updateTimingBox({ stt, kb, llm, tts, total }) {
#   timingBox.style.display = 'block';
#   timingBox.innerHTML = `
#     <div class="row"><span class="label">Transcribing (speech-to-text)</span><span>${fmtTime(stt)}</span></div>
#     <div class="row"><span class="label">Knowledge base lookup</span><span>${fmtTime(kb)}</span></div>
#     <div class="row"><span class="label">LLM response generation</span><span>${fmtTime(llm)}</span></div>
#     <div class="row"><span class="label">Text-to-speech (audio generation)</span><span>${fmtTime(tts)}</span></div>
#     <div class="row"><span class="label">Total turn time</span><span>${fmtTime(total)}</span></div>
#   `;
# }

# function appendLog(who, text) {
#   conversationLog.style.display = 'block';
#   const turn = document.createElement('div');
#   turn.className = 'turn';
#   const labelSpan = document.createElement('span');
#   labelSpan.className = who;
#   labelSpan.textContent = (who === 'you' ? 'You' : 'Agent') + ': ';
#   turn.appendChild(labelSpan);
#   turn.appendChild(document.createTextNode(text));
#   conversationLog.appendChild(turn);
#   conversationLog.scrollTop = conversationLog.scrollHeight;
# }

# const SPEECH_THRESHOLD = 0.02;
# const MIN_SPEECH_MS = 300;
# const SILENCE_HANG_MS = 1300;

# let audioContext, analyser, micStream;
# let vadRafId = null;
# let mediaRecorder, chunks = [];
# let recording = false;
# let speechStartedAt = null;
# let lastLoudAt = null;
# let busy = false;
# let callActive = false;
# let callId = 0;
# let conversationHistory = [];
# let exchangeHistory = [];

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
#   callId += 1;
#   busy = true;
#   conversationHistory = [];
#   exchangeHistory = [];
#   turnNumber = 0;
#   conversationLog.innerHTML = '';
#   conversationLog.style.display = 'none';
#   turnCountEl.textContent = '';
#   callControls.style.display = 'none';
#   activeControls.style.display = 'block';
#   resetTurnUI();
#   setState('speaking', 'Connecting...');

#   try {
#     micStream = await navigator.mediaDevices.getUserMedia({
#       audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
#     });
#   } catch (err) {
#     status.textContent = 'Microphone access was denied or unavailable: ' + err.message;
#     setState('idle', 'Mic unavailable');
#     callActive = false;
#     activeControls.style.display = 'none';
#     callControls.style.display = 'block';
#     return;
#   }

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
#   callId += 1;
#   busy = true;
#   if (vadRafId) { cancelAnimationFrame(vadRafId); vadRafId = null; }
#   if (mediaRecorder && mediaRecorder.state === 'recording') mediaRecorder.stop();
#   mediaRecorder = null;
#   if (micStream) { micStream.getTracks().forEach(t => t.stop()); micStream = null; }
#   if (audioContext) { audioContext.close(); audioContext = null; }
#   greeting.pause();
#   filler.pause();
#   conversationHistory = [];
#   exchangeHistory = [];
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
#   try {
#     const dataArray = new Uint8Array(analyser.fftSize);
#     analyser.getByteTimeDomainData(dataArray);
#     const rms = getRms(dataArray);
#     const now = performance.now();
#     const loud = rms > SPEECH_THRESHOLD;

#     if (!busy) {
#       if (!recording && loud) {
#         startSegment();
#       } else if (recording) {
#         if (loud) lastLoudAt = now;
#         if (now - lastLoudAt > SILENCE_HANG_MS) {
#           if (now - speechStartedAt - SILENCE_HANG_MS > MIN_SPEECH_MS) {
#             stopSegment();
#           } else {
#             cancelSegment();
#           }
#         }
#       }
#     }
#   } catch (err) {
#     console.error('vadLoop error (continuing to listen):', err);
#     recording = false;
#     busy = false;
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
#   busy = true;
#   setState('thinking', 'Thinking...');
#   const myCallId = callId;
#   mediaRecorder.onstop = () => handleRecording(myCallId);
#   mediaRecorder.stop();
# }

# async function handleRecording(myCallId) {
#   if (!callActive || myCallId !== callId) return;
#   resetTurnUI();
#   const turnId = crypto.randomUUID();
#   const blob = new Blob(chunks, { type: 'audio/webm' });
#   const formData = new FormData();
#   formData.append('audio', blob, 'question.webm');
#   formData.append('turn_id', turnId);

#   let transcript;
#   try {
#     const resp = await fetch('/transcribe', { method: 'POST', body: formData });
#     if (myCallId !== callId) return;
#     if (!resp.ok) {
#       status.textContent = 'Error: ' + await resp.text();
#       resumeListening(myCallId);
#       return;
#     }
#     ({ transcript, stt_time_s: lastSttTime } = await resp.json());
#   } catch (err) {
#     if (myCallId !== callId) return;
#     status.textContent = 'Request failed: ' + err;
#     resumeListening(myCallId);
#     return;
#   }

#   if (myCallId !== callId) return;

#   if (!transcript || !transcript.trim()) {
#     status.textContent = "Didn't catch that - go ahead and try again.";
#     resumeListening(myCallId);
#     return;
#   }

#   turnNumber++;
#   turnCountEl.textContent = `Turn ${turnNumber}`;
#   appendLog('you', transcript);
#   setState('speaking', 'Responding...');

#   // Every turn now goes through the same streaming protocol - a greeting
#   // is just a stream that happens to have exactly one chunk, so there's no
#   // need for a separate "instant reply" code path anymore.
#   const FILLER_DELAY_MS = 700;
#   let fillerTimer = setTimeout(() => {
#     filler.currentTime = 0;
#     filler.play().catch(() => {});
#   }, FILLER_DELAY_MS);

#   const previous = conversationHistory.slice(-5);
#   const history = exchangeHistory.slice(-4);
#   let answerResp;
#   try {
#     answerResp = await fetch('/answer', {
#       method: 'POST',
#       headers: { 'Content-Type': 'application/json' },
#       body: JSON.stringify({ transcript, previous, history, turn_id: turnId }),
#     });
#   } catch (err) {
#     clearTimeout(fillerTimer);
#     if (myCallId !== callId) return;
#     status.textContent = 'Request failed: ' + err;
#     await waitForFillerEnd();
#     resumeListening(myCallId);
#     return;
#   }

#   clearTimeout(fillerTimer);
#   if (myCallId !== callId) return;

#   if (!answerResp.ok) {
#     status.textContent = 'Error: ' + await answerResp.text();
#     await waitForFillerEnd();
#     resumeListening(myCallId);
#     return;
#   }

#   conversationHistory.push(transcript);
#   if (conversationHistory.length > 5) conversationHistory.shift();

#   await playStreamedAnswer(answerResp, myCallId, transcript);
# }

# function waitForFillerEnd() {
#   return new Promise((resolve) => {
#     if (filler.paused || filler.ended) {
#       resolve();
#     } else {
#       filler.onended = resolve;
#     }
#   });
# }

# async function playStreamedAnswer(response, myCallId, questionText) {
#   const reader = response.body.getReader();
#   const decoder = new TextDecoder();
#   let buffer = '';
#   const audioQueue = [];
#   let isPlaying = false;
#   let finalAnswerText = '';
#   let streamError = null;
#   let turnTimings = null;

#   function playNext() {
#     if (!callActive || myCallId !== callId) return;
#     if (audioQueue.length === 0) { isPlaying = false; return; }
#     isPlaying = true;
#     const url = audioQueue.shift();
#     player.src = url;
#     player.style.display = 'block';
#     player.play().catch(() => {});
#     player.onended = () => {
#       URL.revokeObjectURL(url);
#       playNext();
#     };
#   }

#   while (true) {
#     let readResult;
#     try {
#       readResult = await reader.read();
#     } catch (err) {
#       streamError = String(err);
#       break;
#     }
#     if (readResult.done) break;
#     if (myCallId !== callId) return;

#     buffer += decoder.decode(readResult.value, { stream: true });
#     let newlineIndex;
#     while ((newlineIndex = buffer.indexOf('\\n')) !== -1) {
#       const line = buffer.slice(0, newlineIndex);
#       buffer = buffer.slice(newlineIndex + 1);
#       if (!line.trim()) continue;

#       let msg;
#       try {
#         msg = JSON.parse(line);
#       } catch (err) {
#         continue;
#       }

#       if (msg.done) {
#         finalAnswerText = msg.spoken_answer || '';
#         if (msg.error) streamError = msg.error;
#         turnTimings = {
#           stt: lastSttTime, kb: msg.kb_time_s, llm: msg.llm_time_s,
#           tts: msg.tts_time_s, total: msg.total_time_s,
#         };
#         continue;
#       }
#       if (!msg.audio_b64) continue;

#       const binary = atob(msg.audio_b64);
#       const bytes = new Uint8Array(binary.length);
#       for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
#       const blob = new Blob([bytes], { type: 'audio/wav' });
#       const url = URL.createObjectURL(blob);
#       audioQueue.push(url);
#       if (!isPlaying) playNext();
#     }
#   }

#   if (myCallId !== callId) return;

#   if (streamError) {
#     status.textContent = 'Error: ' + streamError;
#   }
#   if (finalAnswerText) {
#     appendLog('agent', finalAnswerText);
#     exchangeHistory.push({ question: questionText, answer: finalAnswerText });
#     if (exchangeHistory.length > 4) exchangeHistory.shift();
#   }
#   if (turnTimings) updateTimingBox(turnTimings);

#   await new Promise((resolve) => {
#     const checkDone = () => {
#       if (!callActive || myCallId !== callId) { resolve(); return; }
#       if (!isPlaying && audioQueue.length === 0) resolve();
#       else setTimeout(checkDone, 150);
#     };
#     checkDone();
#   });

#   resumeListening(myCallId);
# }

# function resumeListening(myCallId) {
#   if (!callActive || (myCallId !== undefined && myCallId !== callId)) return;
#   busy = false;
#   setState('listening', 'Listening...');
# }
# </script>
# </body>
# </html>
# """


# @app.get("/")
# def index():
#     return INDEX_HTML


# @app.get("/health")
# def health():
#     return jsonify({"status": "ok"})


# @app.get("/filler/<name>")
# def filler(name: str):
#     safe_name = os.path.basename(name)
#     key = os.path.splitext(safe_name)[0]
#     if key not in FILLER_PHRASES:
#         return Response("Not found", status=404)
#     path = get_or_create_filler(key)
#     return send_file(path, mimetype="audio/wav")


# @app.post("/transcribe")
# def transcribe():
#     if "audio" not in request.files:
#         return Response("No audio file uploaded.", status=400)

#     turn_id = request.form.get("turn_id", "")
#     audio_file = request.files["audio"]
#     suffix = os.path.splitext(audio_file.filename or "")[1] or ".webm"

#     tmp_in = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
#     in_path = tmp_in.name
#     tmp_in.close()

#     t0 = time.time()
#     try:
#         audio_file.save(in_path)
#         transcript = transcribe_audio_local(in_path, language=get_settings().whisper_language)
#         stt_time = round(time.time() - t0, 2)
#         if not _is_meaningful(transcript):
#             # Reuse the frontend's existing empty-transcript handling ("Didn't
#             # catch that - go ahead and try again") instead of sending noise
#             # through the full KB+LLM+TTS pipeline.
#             log_turn(
#                 "transcribe", turn_id=turn_id, stt_time_s=stt_time,
#                 transcript=transcript, filtered_as_noise=True,
#             )
#             return jsonify({"transcript": "", "stt_time_s": stt_time})
#         log_turn("transcribe", turn_id=turn_id, stt_time_s=stt_time, transcript=transcript)
#         return jsonify({"transcript": transcript, "stt_time_s": stt_time})
#     except Exception as exc:
#         log_turn("transcribe", turn_id=turn_id, stt_time_s=round(time.time() - t0, 2), error=str(exc))
#         return Response(f"Transcription error: {exc}", status=500)
#     finally:
#         if os.path.exists(in_path):
#             os.remove(in_path)


# @app.post("/answer")
# def answer():
#     data = request.get_json(silent=True) or {}
#     transcript = (data.get("transcript") or "").strip()
#     turn_id = data.get("turn_id", "")
#     if not transcript:
#         return Response("Missing transcript.", status=400)

#     previous = data.get("previous") or []
#     if not isinstance(previous, list):
#         previous = []
#     previous = [str(item) for item in previous][-5:]

#     raw_history = data.get("history") or []
#     history: list[dict] = []
#     if isinstance(raw_history, list):
#         for turn in raw_history[-4:]:
#             if isinstance(turn, dict):
#                 history.append({
#                     "question": str(turn.get("question", ""))[:1000],
#                     "answer": str(turn.get("answer", ""))[:1000],
#                 })

#     def generate():
#         try:
#             for chunk in stream_turn(transcript, turn_id=turn_id, history=history, previous=previous):
#                 if chunk.get("done"):
#                     payload = {
#                         "done": True,
#                         "spoken_answer": chunk.get("spoken_answer", ""),
#                         "kb_time_s": chunk.get("kb_time_s"),
#                         "llm_time_s": chunk.get("llm_time_s"),
#                         "tts_time_s": chunk.get("tts_time_s"),
#                         "total_time_s": chunk.get("total_time_s"),
#                     }
#                     if chunk.get("error"):
#                         payload["error"] = chunk["error"]
#                     yield json.dumps(payload) + "\n"
#                     continue

#                 audio_path = chunk["audio_path"]
#                 is_cached = chunk.get("_cached", False)
#                 try:
#                     with open(audio_path, "rb") as f:
#                         audio_bytes = f.read()
#                 finally:
#                     # Don't delete the shared filler cache file - only
#                     # per-sentence temp files get cleaned up here.
#                     if not is_cached and os.path.exists(audio_path):
#                         os.remove(audio_path)

#                 yield json.dumps({
#                     "text": chunk["text"],
#                     "audio_b64": base64.b64encode(audio_bytes).decode("utf-8"),
#                 }) + "\n"
#         except Exception as exc:
#             yield json.dumps({"done": True, "error": str(exc), "spoken_answer": ""}) + "\n"

#     return Response(generate(), mimetype="application/x-ndjson")


# if __name__ == "__main__":
#     get_or_create_filler("checking")
#     get_or_create_filler("greeting")
#     app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)

"""Flask entrypoint for the voice help agent."""

from __future__ import annotations

import base64
import json
import os
import re
import tempfile
import time

from flask import Flask, Response, jsonify, request, send_file

from app.pipeline import FILLER_PHRASES, get_or_create_filler, stream_turn
from app.stt.whisper_local import transcribe_audio_local
from app.telemetry.logger import log_turn

app = Flask(__name__)

# Whisper occasionally transcribes background noise/silence as a stray
# punctuation mark (a lone "," showed up in real test logs, wasting a full
# KB+LLM+TTS round trip on nothing). Require at least 2 real alphanumeric
# characters before treating a transcript as real speech.
_MEANINGFUL_TRANSCRIPT_RE = re.compile(r"[a-zA-Z0-9]{2,}")


def _is_meaningful(text: str) -> bool:
    return bool(_MEANINGFUL_TRANSCRIPT_RE.search(text))


INDEX_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Voice Help Agent</title>
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
  #timingBox { margin-top: 12px; padding: 10px 14px; text-align: left; font-size: 12px;
           font-family: ui-monospace, monospace; color: #374151; background: #f9fafb;
           border: 1px solid #e5e7eb; border-radius: 8px; display: none; }
  #timingBox .row { display: flex; justify-content: space-between; margin-bottom: 4px; }
  #timingBox .row:last-child { margin-bottom: 0; padding-top: 6px; border-top: 1px solid #e5e7eb; font-weight: 600; }
  #timingBox .label { color: #6b7280; }
</style>
</head>
<body>
  <h2>Voice Help Agent</h2>
  <div id="callControls">
    <button id="startBtn" class="start">Start Call</button>
  </div>
  <div id="activeControls" style="display:none;">
    <button id="endBtn" class="end">End Call</button>
    <div id="stateIndicator" class="state-idle">Listening...</div>
  </div>
  <div id="status"></div>
  <div id="turnCount"></div>
  <div id="timingBox"></div>
  <div id="conversationLog"></div>
  <audio id="greeting" src="/filler/greeting.wav" preload="auto"></audio>
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
const timingBox = document.getElementById('timingBox');
const greeting = document.getElementById('greeting');
const player = document.getElementById('player');

let turnNumber = 0;
let lastSttTime = null;

function fmtTime(v) {
  return (typeof v === 'number') ? v.toFixed(2) + 's' : '—';
}

function updateTimingBox({ stt, kb, llm, tts, total }) {
  timingBox.style.display = 'block';
  timingBox.innerHTML = `
    <div class="row"><span class="label">Transcribing (speech-to-text)</span><span>${fmtTime(stt)}</span></div>
    <div class="row"><span class="label">Knowledge base lookup</span><span>${fmtTime(kb)}</span></div>
    <div class="row"><span class="label">LLM response generation</span><span>${fmtTime(llm)}</span></div>
    <div class="row"><span class="label">Text-to-speech (audio generation)</span><span>${fmtTime(tts)}</span></div>
    <div class="row"><span class="label">Total turn time</span><span>${fmtTime(total)}</span></div>
  `;
}

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

const SPEECH_THRESHOLD = 0.02;
const MIN_SPEECH_MS = 300;
const SILENCE_HANG_MS = 1300;

let audioContext, analyser, micStream;
let vadRafId = null;
let mediaRecorder, chunks = [];
let recording = false;
let speechStartedAt = null;
let lastLoudAt = null;
let busy = false;
let callActive = false;
let callId = 0;
let conversationHistory = [];
let exchangeHistory = [];

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
  busy = true;
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
  callId += 1;
  busy = true;
  if (vadRafId) { cancelAnimationFrame(vadRafId); vadRafId = null; }
  if (mediaRecorder && mediaRecorder.state === 'recording') mediaRecorder.stop();
  mediaRecorder = null;
  if (micStream) { micStream.getTracks().forEach(t => t.stop()); micStream = null; }
  if (audioContext) { audioContext.close(); audioContext = null; }
  greeting.pause();
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
            cancelSegment();
          }
        }
      }
    }
  } catch (err) {
    console.error('vadLoop error (continuing to listen):', err);
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
  busy = true;
  setState('thinking', 'Thinking...');
  const myCallId = callId;
  mediaRecorder.onstop = () => handleRecording(myCallId);
  mediaRecorder.stop();
}

async function handleRecording(myCallId) {
  if (!callActive || myCallId !== callId) return;
  resetTurnUI();
  const turnId = crypto.randomUUID();
  const blob = new Blob(chunks, { type: 'audio/webm' });
  const formData = new FormData();
  formData.append('audio', blob, 'question.webm');
  formData.append('turn_id', turnId);

  let transcript;
  try {
    const resp = await fetch('/transcribe', { method: 'POST', body: formData });
    if (myCallId !== callId) return;
    if (!resp.ok) {
      status.textContent = 'Error: ' + await resp.text();
      resumeListening(myCallId);
      return;
    }
    ({ transcript, stt_time_s: lastSttTime } = await resp.json());
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
  setState('speaking', 'Responding...');

  // No more client-side filler timer - the backend now streams a
  // question-specific acknowledgment as the first chunk (see stream_turn's
  // "kind": "filler" chunks), which plays through the same audio queue as
  // everything else. See playStreamedAnswer for how "filler" vs "answer"
  // chunks are logged differently.
  const previous = conversationHistory.slice(-5);
  const history = exchangeHistory.slice(-4);
  let answerResp;
  try {
    answerResp = await fetch('/answer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ transcript, previous, history, turn_id: turnId }),
    });
  } catch (err) {
    if (myCallId !== callId) return;
    status.textContent = 'Request failed: ' + err;
    resumeListening(myCallId);
    return;
  }

  if (myCallId !== callId) return;

  if (!answerResp.ok) {
    status.textContent = 'Error: ' + await answerResp.text();
    resumeListening(myCallId);
    return;
  }

  conversationHistory.push(transcript);
  if (conversationHistory.length > 5) conversationHistory.shift();

  await playStreamedAnswer(answerResp, myCallId, transcript);
}

async function playStreamedAnswer(response, myCallId, questionText) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  const audioQueue = [];
  let isPlaying = false;
  let finalAnswerText = '';
  let streamError = null;
  let turnTimings = null;

  function playNext() {
    if (!callActive || myCallId !== callId) return;
    if (audioQueue.length === 0) { isPlaying = false; return; }
    isPlaying = true;
    const url = audioQueue.shift();
    player.src = url;
    player.style.display = 'block';
    player.play().catch(() => {});
    player.onended = () => {
      URL.revokeObjectURL(url);
      playNext();
    };
  }

  while (true) {
    let readResult;
    try {
      readResult = await reader.read();
    } catch (err) {
      streamError = String(err);
      break;
    }
    if (readResult.done) break;
    if (myCallId !== callId) return;

    buffer += decoder.decode(readResult.value, { stream: true });
    let newlineIndex;
    while ((newlineIndex = buffer.indexOf('\\n')) !== -1) {
      const line = buffer.slice(0, newlineIndex);
      buffer = buffer.slice(newlineIndex + 1);
      if (!line.trim()) continue;

      let msg;
      try {
        msg = JSON.parse(line);
      } catch (err) {
        continue;
      }

      if (msg.done) {
        finalAnswerText = msg.spoken_answer || '';
        if (msg.error) streamError = msg.error;
        turnTimings = {
          stt: lastSttTime, kb: msg.kb_time_s, llm: msg.llm_time_s,
          tts: msg.tts_time_s, total: msg.total_time_s,
        };
        continue;
      }
      if (!msg.audio_b64) continue;

      // The quick acknowledgment ("Let me find the process for...") logs as
      // its own message the moment it arrives - the real answer's sentences
      // accumulate silently and get logged as a second message once the
      // "done" marker arrives (see below), matching a two-turn chat layout
      // rather than one combined block of text.
      if (msg.kind === 'filler' && msg.text) {
        appendLog('agent', msg.text);
      }

      const binary = atob(msg.audio_b64);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
      const blob = new Blob([bytes], { type: 'audio/wav' });
      const url = URL.createObjectURL(blob);
      audioQueue.push(url);
      if (!isPlaying) playNext();
    }
  }

  if (myCallId !== callId) return;

  if (streamError) {
    status.textContent = 'Error: ' + streamError;
  }
  if (finalAnswerText) {
    appendLog('agent', finalAnswerText);
    exchangeHistory.push({ question: questionText, answer: finalAnswerText });
    if (exchangeHistory.length > 4) exchangeHistory.shift();
  }
  if (turnTimings) updateTimingBox(turnTimings);

  await new Promise((resolve) => {
    const checkDone = () => {
      if (!callActive || myCallId !== callId) { resolve(); return; }
      if (!isPlaying && audioQueue.length === 0) resolve();
      else setTimeout(checkDone, 150);
    };
    checkDone();
  });

  resumeListening(myCallId);
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


@app.get("/")
def index():
    return INDEX_HTML


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/filler/<name>")
def filler(name: str):
    safe_name = os.path.basename(name)
    key = os.path.splitext(safe_name)[0]
    if key not in FILLER_PHRASES:
        return Response("Not found", status=404)
    path = get_or_create_filler(key)
    return send_file(path, mimetype="audio/wav")


@app.post("/transcribe")
def transcribe():
    if "audio" not in request.files:
        return Response("No audio file uploaded.", status=400)

    turn_id = request.form.get("turn_id", "")
    audio_file = request.files["audio"]
    suffix = os.path.splitext(audio_file.filename or "")[1] or ".webm"

    tmp_in = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    in_path = tmp_in.name
    tmp_in.close()

    t0 = time.time()
    try:
        audio_file.save(in_path)
        transcript = transcribe_audio_local(in_path)
        stt_time = round(time.time() - t0, 2)
        if not _is_meaningful(transcript):
            # Reuse the frontend's existing empty-transcript handling ("Didn't
            # catch that - go ahead and try again") instead of sending noise
            # through the full KB+LLM+TTS pipeline.
            log_turn(
                "transcribe", turn_id=turn_id, stt_time_s=stt_time,
                transcript=transcript, filtered_as_noise=True,
            )
            return jsonify({"transcript": "", "stt_time_s": stt_time})
        log_turn("transcribe", turn_id=turn_id, stt_time_s=stt_time, transcript=transcript)
        return jsonify({"transcript": transcript, "stt_time_s": stt_time})
    except Exception as exc:
        log_turn("transcribe", turn_id=turn_id, stt_time_s=round(time.time() - t0, 2), error=str(exc))
        return Response(f"Transcription error: {exc}", status=500)
    finally:
        if os.path.exists(in_path):
            os.remove(in_path)


@app.post("/answer")
def answer():
    data = request.get_json(silent=True) or {}
    transcript = (data.get("transcript") or "").strip()
    turn_id = data.get("turn_id", "")
    if not transcript:
        return Response("Missing transcript.", status=400)

    previous = data.get("previous") or []
    if not isinstance(previous, list):
        previous = []
    previous = [str(item) for item in previous][-5:]

    raw_history = data.get("history") or []
    history: list[dict] = []
    if isinstance(raw_history, list):
        for turn in raw_history[-4:]:
            if isinstance(turn, dict):
                history.append({
                    "question": str(turn.get("question", ""))[:1000],
                    "answer": str(turn.get("answer", ""))[:1000],
                })

    def generate():
        try:
            for chunk in stream_turn(transcript, turn_id=turn_id, history=history, previous=previous):
                if chunk.get("done"):
                    payload = {
                        "done": True,
                        "spoken_answer": chunk.get("spoken_answer", ""),
                        "ack_time_s": chunk.get("ack_time_s"),
                        "kb_time_s": chunk.get("kb_time_s"),
                        "llm_time_s": chunk.get("llm_time_s"),
                        "tts_time_s": chunk.get("tts_time_s"),
                        "total_time_s": chunk.get("total_time_s"),
                    }
                    if chunk.get("error"):
                        payload["error"] = chunk["error"]
                    yield json.dumps(payload) + "\n"
                    continue

                audio_path = chunk["audio_path"]
                is_cached = chunk.get("_cached", False)
                try:
                    with open(audio_path, "rb") as f:
                        audio_bytes = f.read()
                finally:
                    # Don't delete the shared filler cache file - only
                    # per-sentence temp files get cleaned up here.
                    if not is_cached and os.path.exists(audio_path):
                        os.remove(audio_path)

                yield json.dumps({
                    "text": chunk["text"],
                    "audio_b64": base64.b64encode(audio_bytes).decode("utf-8"),
                    "kind": chunk.get("kind", "answer"),
                }) + "\n"
        except Exception as exc:
            yield json.dumps({"done": True, "error": str(exc), "spoken_answer": ""}) + "\n"

    return Response(generate(), mimetype="application/x-ndjson")


if __name__ == "__main__":
    get_or_create_filler("checking")
    get_or_create_filler("greeting")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)