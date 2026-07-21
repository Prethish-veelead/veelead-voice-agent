
"""
Live browser demo for the LOCAL voice helpdesk pipeline - "phone call" mode.
------------------------------------------------------------------------
Same frontend as web_demo.py (VAD-based continuous listening, no button
to hold) - only the backend is swapped from cloud APIs to the local stack
built in Steps 1-3: faster-whisper (STT), Ollama/Qwen (LLM), Piper (TTS).
The veelead-rag KB call is unchanged either way - it's a separate service.

IMPORTANT LATENCY NOTE: your Step 1-3 tests showed local round trips in the
15-55+ second range on CPU, vs. ~8-15s for the cloud version. The filler
phrase pattern here was designed around cloud-scale latency - expect a much
longer silence after the filler before the real answer plays. This is
expected given the hardware, not a bug in this file. If it feels broken
rather than just slow, that's the signal to revisit model sizes (a smaller
Whisper model, a smaller/more quantized LLM) before adding more UI polish.

This is a local test tool, not a production server: it binds to localhost
only and holds no auth. Do not expose it to the public internet as-is.

SETUP:
  pip install flask
  (uses the same .env as the rest of the local pipeline)

RUN:
  python local_web_demo.py
  -> open http://127.0.0.1:5000 in a browser
  -> use headphones for the cleanest voice-detection results
"""

import base64
import json
import os
import re
import tempfile
import time
from urllib.parse import quote

import requests
from flask import Flask, jsonify, request, send_file, Response

from app.stt.whisper_local import transcribe_audio_local
from app.kb.veelead_client import search_knowledge_base, get_grounded_answer, CONFIDENCE_THRESHOLD
from app.llm.local_llm import ask_local_llm_stream
from app.tts.piper_local import text_to_speech_local
from app.telemetry.logger import log_turn
from app.telemetry.escalations import check_and_log_escalation

FILLER_DIR = "filler_cache"
FILLER_PHRASES = {
    "greeting": "Hi, this is your support assistant. How may I help you today?",
    "checking": "Okay, let me look into that for you.",
    "ack_response": "Alright, let me know if there's anything else I can help with.",
}

# Deliberately simple and fast (no model call) - this only needs to catch the
# common cases where the whole utterance IS the greeting/ack, not anything
# more nuanced. "Hi, my mic isn't working" should NOT match these, since
# there's real content beyond the greeting - fullmatch below handles that.
_GREETING_RE = re.compile(
    r"\s*(hi+|hello+|hey+|hii+|hai|yo|good\s+(morning|afternoon|evening))[\s,.!]*",
    re.IGNORECASE,
)
_ACK_RE = re.compile(
    r"\s*(ok(ay)?|alright|sure|yes|yeah|yep|no|nope|got it|no problem|cool|great|perfect|fine|"
    r"thanks?( you)?( so much)?( a lot)?|thank you( very much)?)[\s,.!]*",
    re.IGNORECASE,
)


def classify_intent(text: str) -> str:
    """Returns "greeting", "acknowledgment", or "question". Deliberately a
    fast regex check, not an LLM call - the whole point is to avoid the slow
    KB+LLM round trip for things that were never a real question."""
    stripped = text.strip()
    if _GREETING_RE.fullmatch(stripped):
        return "greeting"
    if _ACK_RE.fullmatch(stripped):
        return "acknowledgment"
    return "question"


def get_or_create_filler(phrase_key: str) -> str:
    """Same idea as the cloud version - generate once, cache, reuse for
    instant playback on every turn."""
    os.makedirs(FILLER_DIR, exist_ok=True)
    path = os.path.join(FILLER_DIR, f"{phrase_key}.wav")
    if not os.path.exists(path):
        text_to_speech_local(FILLER_PHRASES[phrase_key], output_path=path)
    return path

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
  const turnId = crypto.randomUUID();
  const blob = new Blob(chunks, { type: 'audio/webm' });
  const formData = new FormData();
  formData.append('audio', blob, 'question.webm');
  formData.append('turn_id', turnId);

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

  setState('speaking', 'Responding...');

  // Only play the "let me check" filler if the answer is actually taking a
  // while - a greeting or quick acknowledgment now resolves near-instantly
  // (no KB/LLM call on the backend), so there's nothing to bridge the gap
  // for. FILLER_DELAY_MS below is the threshold for "taking a while."
  const FILLER_DELAY_MS = 700;
  let fillerTimer = setTimeout(() => {
    filler.currentTime = 0;
    filler.play().catch(() => {});
  }, FILLER_DELAY_MS);

  // The real answer (KB + LLM + TTS) runs in parallel while the filler plays.
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
    clearTimeout(fillerTimer);
    if (myCallId !== callId) return;
    status.textContent = 'Request failed: ' + err;
    await waitForFillerEnd(); // don't unmute the mic while the filler is still audible
    resumeListening(myCallId);
    return;
  }

  clearTimeout(fillerTimer); // answer is back - cancel the filler if it hasn't started yet

  if (myCallId !== callId) return;

  if (!answerResp.ok) {
    status.textContent = 'Error: ' + await answerResp.text();
    await waitForFillerEnd();
    resumeListening(myCallId);
    return;
  }

  conversationHistory.push(transcript);
  if (conversationHistory.length > 5) conversationHistory.shift();

  const contentType = answerResp.headers.get('Content-Type') || '';

  if (contentType.includes('application/x-ndjson')) {
    // Real question - streamed sentence-by-sentence, TTS starts on sentence 1
    // while the LLM is still generating the rest.
    await playStreamedAnswer(answerResp, myCallId, transcript);
    return;
  }

  // Greeting/acknowledgment fast path - single cached audio file, unchanged.
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

async function playStreamedAnswer(response, myCallId, questionText) {
  // Consumes the newline-delimited JSON stream from /answer, plays each
  // sentence's audio back-to-back as chunks arrive (not waiting for the
  // full response), and updates history/log once the final marker lands.
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  const audioQueue = [];
  let isPlaying = false;
  let finalAnswerText = '';
  let streamError = null;

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
    if (myCallId !== callId) return; // stale call - stop processing entirely

    buffer += decoder.decode(readResult.value, { stream: true });
    let newlineIndex;
    while ((newlineIndex = buffer.indexOf('\n')) !== -1) {
      const line = buffer.slice(0, newlineIndex);
      buffer = buffer.slice(newlineIndex + 1);
      if (!line.trim()) continue;

      let msg;
      try {
        msg = JSON.parse(line);
      } catch (err) {
        continue; // skip a malformed line rather than crashing the whole turn
      }

      if (msg.done) {
        finalAnswerText = msg.spoken_answer || '';
        if (msg.error) streamError = msg.error;
        continue;
      }
      if (!msg.audio_b64) continue;

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

  // Wait for all queued audio to actually finish playing before resuming
  // listening - otherwise the mic could reopen mid-sentence.
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
        stt_time = time.time() - t0
        log_turn("transcribe", turn_id=turn_id, stt_time_s=round(stt_time, 2), transcript=transcript)
        return jsonify({"transcript": transcript})
    except Exception as exc:
        log_turn("transcribe", turn_id=turn_id, stt_time_s=round(time.time() - t0, 2), error=str(exc))
        return Response(f"Transcription error: {exc}", status=500)
    finally:
        if os.path.exists(in_path):
            os.remove(in_path)


@app.route("/answer", methods=["POST"])
def answer():
    t_start = time.time()
    data = request.get_json(silent=True) or {}
    transcript = (data.get("transcript") or "").strip()
    turn_id = data.get("turn_id", "")
    if not transcript:
        return Response("Missing transcript.", status=400)

    intent = classify_intent(transcript)
    if intent in ("greeting", "acknowledgment"):
        phrase_key = "greeting" if intent == "greeting" else "ack_response"
        spoken_answer = FILLER_PHRASES[phrase_key]
        cached_path = get_or_create_filler(phrase_key)
        with open(cached_path, "rb") as f:
            audio_bytes = f.read()
        response = Response(audio_bytes, mimetype="audio/wav")
        response.headers["X-Answer"] = quote(spoken_answer)
        log_turn(
            "answer", turn_id=turn_id, transcript=transcript, intent=intent,
            kb_time_s=0, llm_time_s=0, tts_time_s=0,
            total_time_s=round(time.time() - t_start, 2),
            spoken_answer=spoken_answer,
        )
        return response

    previous = data.get("previous") or []
    if not isinstance(previous, list):
        previous = []
    previous = [str(p) for p in previous][-5:]

    # Full (question, answer) pairs from earlier in this call - this is what lets
    # the LLM recognize "I already tried that" instead of repeating the same advice.
    raw_history = data.get("history") or []
    history = []
    if isinstance(raw_history, list):
        for turn in raw_history[-4:]:
            if isinstance(turn, dict):
                history.append({
                    "question": str(turn.get("question", ""))[:1000],
                    "answer": str(turn.get("answer", ""))[:1000],
                })

    def generate():
        """Streaming response: KB lookup happens once up front, then each
        LLM-generated sentence gets its own TTS call and is yielded to the
        browser immediately - the browser can start playing sentence 1
        while sentence 2 is still being generated/synthesized.

        Protocol: newline-delimited JSON. Each line is either
          {"text": "...", "audio_b64": "..."}   - one playable sentence
          {"done": true, "spoken_answer": "...", ...timings}  - final marker
        """
        kb_time = 0.0
        llm_time = 0.0
        tts_time_total = 0.0
        kb_confidence = None
        sentence_parts = []

        try:
            t_kb = time.time()
            kb_result = search_knowledge_base(transcript, previous=previous)
            kb_time = time.time() - t_kb
            kb_confidence = kb_result.get("confidence")
        except requests.exceptions.Timeout:
            print(f"KB timed out for query: {transcript!r}")
            fallback = (
                "I'm having trouble reaching our knowledge base right now. "
                "Let me connect you with a human teammate instead."
            )
            fallback_path = tempfile.mktemp(suffix=".wav")
            text_to_speech_local(fallback, output_path=fallback_path)
            with open(fallback_path, "rb") as f:
                audio_bytes = f.read()
            os.remove(fallback_path)
            yield json.dumps({"text": fallback, "audio_b64": base64.b64encode(audio_bytes).decode()}) + "\n"
            yield json.dumps({"done": True, "spoken_answer": fallback}) + "\n"
            check_and_log_escalation(
                turn_id=turn_id, transcript=transcript, spoken_answer=fallback,
                kb_confidence=None, confidence_threshold=CONFIDENCE_THRESHOLD,
                history=history,
            )
            log_turn(
                "answer", turn_id=turn_id, transcript=transcript, intent=intent,
                kb_time_s=round(kb_time, 2), error="kb_timeout",
                total_time_s=round(time.time() - t_start, 2),
            )
            return
        except Exception as exc:
            yield json.dumps({"done": True, "error": str(exc)}) + "\n"
            log_turn(
                "answer", turn_id=turn_id, transcript=transcript, intent=intent,
                error=str(exc), total_time_s=round(time.time() - t_start, 2),
            )
            return

        try:
            t_llm_start = time.time()
            for sentence in ask_local_llm_stream(transcript, get_grounded_answer(kb_result), history=history):
                sentence_parts.append(sentence)

                t_tts = time.time()
                tts_path = tempfile.mktemp(suffix=".wav")
                text_to_speech_local(sentence, output_path=tts_path)
                with open(tts_path, "rb") as f:
                    audio_bytes = f.read()
                os.remove(tts_path)
                tts_time_total += time.time() - t_tts

                yield json.dumps({"text": sentence, "audio_b64": base64.b64encode(audio_bytes).decode()}) + "\n"

            llm_time = max(time.time() - t_llm_start - tts_time_total, 0)
        except Exception as exc:
            yield json.dumps({"done": True, "error": str(exc), "spoken_answer": " ".join(sentence_parts)}) + "\n"
            log_turn(
                "answer", turn_id=turn_id, transcript=transcript, intent=intent,
                kb_time_s=round(kb_time, 2), kb_confidence=kb_confidence,
                error=str(exc), total_time_s=round(time.time() - t_start, 2),
            )
            return

        spoken_answer = " ".join(sentence_parts)
        total_time = time.time() - t_start
        yield json.dumps({"done": True, "spoken_answer": spoken_answer}) + "\n"

        escalation_reason = check_and_log_escalation(
            turn_id=turn_id, transcript=transcript, spoken_answer=spoken_answer,
            kb_confidence=kb_confidence, confidence_threshold=CONFIDENCE_THRESHOLD,
            history=history,
        )

        log_turn(
            "answer", turn_id=turn_id, transcript=transcript, intent=intent,
            kb_time_s=round(kb_time, 2), kb_confidence=kb_confidence,
            llm_time_s=round(llm_time, 2), tts_time_s=round(tts_time_total, 2),
            total_time_s=round(total_time, 2), spoken_answer=spoken_answer,
            escalated=escalation_reason,
        )

    return Response(generate(), mimetype="application/x-ndjson")


if __name__ == "__main__":
    print("Pre-generating filler audio...")
    get_or_create_filler("checking")
    get_or_create_filler("greeting")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)