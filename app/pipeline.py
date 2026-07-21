# # # """Orchestration layer: STT -> KB -> LLM -> TTS."""

# # # from __future__ import annotations

# # # import os
# # # import tempfile
# # # import time
# # # from pathlib import Path

# # # import requests

# # # from app.config import get_settings
# # # from app.kb.veelead_client import search_knowledge_base
# # # from app.llm.local_llm import ask_local_llm
# # # from app.stt.whisper_local import transcribe_audio_local
# # # from app.tts.local_tts import text_to_speech

# # # FILLER_PHRASES = {
# # #     "greeting": "Hi, this is your support assistant. How may I help you today?",
# # #     "checking": "Okay, let me look into that for you.",
# # #     "one_moment": "One moment please, I'm looking that up.",
# # # }


# # # def get_or_create_filler(phrase_key: str) -> str:
# # #     """Generate a filler phrase once and cache it for reuse."""

# # #     settings = get_settings()
# # #     settings.filler_cache_dir.mkdir(parents=True, exist_ok=True)
# # #     path = settings.filler_cache_dir / f"{phrase_key}.wav"
# # #     if not path.exists():
# # #         text_to_speech(FILLER_PHRASES[phrase_key], output_path=str(path))
# # #     return str(path)


# # # def process_turn(
# # #     user_question: str,
# # #     history: list[dict] | None = None,
# # #     previous: list[str] | None = None,
# # #     output_path: str = "response.wav",
# # # ) -> dict:
# # #     """Run a full question through the local pipeline and return a turn summary."""

# # #     t0 = time.time()
# # #     filler_path = get_or_create_filler("checking")
# # #     kb_previous = previous
# # #     if kb_previous is None and history:
# # #         kb_previous = [str(turn.get("question", "")) for turn in history]

# # #     try:
# # #         kb_result = search_knowledge_base(user_question, previous=kb_previous)
# # #         spoken_answer = ask_local_llm(user_question, kb_result.get("answer", ""), history=history)
# # #     except requests.exceptions.Timeout:
# # #         kb_result = {"answer": "", "confidence": 0}
# # #         spoken_answer = (
# # #             "I'm having trouble reaching the knowledge base right now. "
# # #             "Please try again in a moment."
# # #         )

# # #     audio_path = text_to_speech(spoken_answer, output_path=output_path)
# # #     return {
# # #         "question": user_question,
# # #         "answer": spoken_answer,
# # #         "audio_path": audio_path,
# # #         "filler_path": filler_path,
# # #         "kb_result": kb_result,
# # #         "elapsed_seconds": round(time.time() - t0, 2),
# # #     }


# # # def run_pipeline(
# # #     user_question: str,
# # #     history: list[dict] | None = None,
# # #     previous: list[str] | None = None,
# # #     output_path: str = "response.wav",
# # # ) -> str:
# # #     """Compatibility wrapper that returns just the spoken answer."""

# # #     return process_turn(
# # #         user_question=user_question,
# # #         history=history,
# # #         previous=previous,
# # #         output_path=output_path,
# # #     )["answer"]


# # # def transcribe_and_process(audio_path: str, history: list[dict] | None = None) -> dict:
# # #     """Convenience helper for file-based demos."""

# # #     transcript = transcribe_audio_local(audio_path)
# # #     with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_out:
# # #         out_path = tmp_out.name
# # #     try:
# # #         result = process_turn(transcript, history=history, output_path=out_path)
# # #         result["transcript"] = transcript
# # #         return result
# # #     except Exception:
# # #         if os.path.exists(out_path):
# # #             os.remove(out_path)
# # #         raise
# # """Orchestration layer: STT -> KB -> LLM -> TTS.

# # This is a full rebuild that ports forward everything built and tested in
# # local_web_demo.py (greeting/ack fast-path, confidence-gated KB grounding,
# # streaming LLM+TTS chunking, latency logging, escalation logging) into this
# # project's cleaner module structure. The previous version of this file only
# # had the STT->KB->LLM->TTS wiring with none of those features.
# # """

# # from __future__ import annotations

# # import os
# # import re
# # import tempfile
# # import time
# # import wave
# # from pathlib import Path

# # import requests

# # from app.config import get_settings
# # from app.kb.veelead_client import search_knowledge_base, get_grounded_answer, CONFIDENCE_THRESHOLD
# # from app.llm.local_llm import ask_local_llm_stream
# # from app.stt.whisper_local import transcribe_audio_local
# # from app.tts.local_tts import text_to_speech
# # from app.telemetry.logger import log_turn
# # from app.telemetry.escalations import check_and_log_escalation

# # FILLER_PHRASES = {
# #     "greeting": "Hi, this is your support assistant. How may I help you today?",
# #     "checking": "Okay, let me look into that for you.",
# #     "one_moment": "One moment please, I'm looking that up.",
# #     "ack_response": "Alright, let me know if there's anything else I can help with.",
# # }

# # # Deliberately simple regex, not a model call - see local_llm.py's history
# # # note for why: this needs to be free/instant, not add a second LLM round trip
# # # just to decide whether the first one is needed.
# # _GREETING_RE = re.compile(
# #     r"\s*(hi+|hello+|hey+|hii+|hai|yo|good\s+(morning|afternoon|evening))[\s,.!]*",
# #     re.IGNORECASE,
# # )
# # _ACK_RE = re.compile(
# #     r"\s*(ok(ay)?|alright|sure|yes|yeah|yep|no|nope|got it|no problem|cool|great|perfect|fine|"
# #     r"thanks?( you)?( so much)?( a lot)?|thank you( very much)?)[\s,.!]*",
# #     re.IGNORECASE,
# # )


# # def classify_intent(text: str) -> str:
# #     """Returns "greeting", "acknowledgment", or "question"."""
# #     stripped = text.strip()
# #     if _GREETING_RE.fullmatch(stripped):
# #         return "greeting"
# #     if _ACK_RE.fullmatch(stripped):
# #         return "acknowledgment"
# #     return "question"


# # def get_or_create_filler(phrase_key: str) -> str:
# #     """Generate a filler phrase once and cache it for reuse."""
# #     settings = get_settings()
# #     settings.filler_cache_dir.mkdir(parents=True, exist_ok=True)
# #     path = settings.filler_cache_dir / f"{phrase_key}.wav"
# #     if not path.exists():
# #         text_to_speech(FILLER_PHRASES[phrase_key], output_path=str(path))
# #     return str(path)


# # def stream_turn(
# #     user_question: str,
# #     turn_id: str = "",
# #     history: list[dict] | None = None,
# #     previous: list[str] | None = None,
# # ):
# #     """Generator yielding one dict per playable chunk, then a final summary dict.

# #     Yields:
# #       {"text": "...", "audio_path": "..."}   - a sentence and its audio file
# #                                                  (caller owns cleanup of the file)
# #       {"done": True, "spoken_answer": "...", "escalated": ...}  - final marker

# #     This is the single source of truth for turn processing - process_turn()
# #     below is a thin non-streaming wrapper built on top of this, not a
# #     separate implementation, so the two can't drift out of sync.
# #     """
# #     t_start = time.time()
# #     intent = classify_intent(user_question)

# #     if intent in ("greeting", "acknowledgment"):
# #         phrase_key = "greeting" if intent == "greeting" else "ack_response"
# #         spoken_answer = FILLER_PHRASES[phrase_key]
# #         audio_path = get_or_create_filler(phrase_key)
# #         yield {"text": spoken_answer, "audio_path": audio_path, "_cached": True}
# #         log_turn(
# #             "answer", turn_id=turn_id, transcript=user_question, intent=intent,
# #             kb_time_s=0, llm_time_s=0, tts_time_s=0,
# #             total_time_s=round(time.time() - t_start, 2), spoken_answer=spoken_answer,
# #         )
# #         yield {"done": True, "spoken_answer": spoken_answer}
# #         return

# #     kb_previous = previous
# #     if kb_previous is None and history:
# #         kb_previous = [str(turn.get("question", "")) for turn in history]

# #     kb_time = 0.0
# #     kb_confidence = None

# #     try:
# #         t_kb = time.time()
# #         kb_result = search_knowledge_base(user_question, previous=kb_previous)
# #         kb_time = time.time() - t_kb
# #         kb_confidence = kb_result.get("confidence")
# #     except requests.exceptions.Timeout:
# #         fallback = (
# #             "I'm having trouble reaching our knowledge base right now. "
# #             "Let me connect you with a human teammate instead."
# #         )
# #         fallback_path = tempfile.mktemp(suffix=".wav")
# #         text_to_speech(fallback, output_path=fallback_path)
# #         yield {"text": fallback, "audio_path": fallback_path}
# #         check_and_log_escalation(
# #             turn_id=turn_id, transcript=user_question, spoken_answer=fallback,
# #             kb_confidence=None, confidence_threshold=CONFIDENCE_THRESHOLD, history=history,
# #         )
# #         log_turn(
# #             "answer", turn_id=turn_id, transcript=user_question, intent=intent,
# #             kb_time_s=round(kb_time, 2), error="kb_timeout",
# #             total_time_s=round(time.time() - t_start, 2),
# #         )
# #         yield {"done": True, "spoken_answer": fallback}
# #         return

# #     sentence_parts: list[str] = []
# #     tts_time_total = 0.0
# #     t_llm_start = time.time()

# #     try:
# #         for sentence in ask_local_llm_stream(user_question, get_grounded_answer(kb_result), history=history):
# #             sentence_parts.append(sentence)
# #             t_tts = time.time()
# #             tts_path = tempfile.mktemp(suffix=".wav")
# #             text_to_speech(sentence, output_path=tts_path)
# #             tts_time_total += time.time() - t_tts
# #             yield {"text": sentence, "audio_path": tts_path}
# #     except Exception as exc:
# #         spoken_answer = " ".join(sentence_parts)
# #         log_turn(
# #             "answer", turn_id=turn_id, transcript=user_question, intent=intent,
# #             kb_time_s=round(kb_time, 2), kb_confidence=kb_confidence,
# #             error=str(exc), total_time_s=round(time.time() - t_start, 2),
# #         )
# #         yield {"done": True, "spoken_answer": spoken_answer, "error": str(exc)}
# #         return

# #     llm_time = max(time.time() - t_llm_start - tts_time_total, 0)
# #     spoken_answer = " ".join(sentence_parts)
# #     total_time = time.time() - t_start

# #     escalation_reason = check_and_log_escalation(
# #         turn_id=turn_id, transcript=user_question, spoken_answer=spoken_answer,
# #         kb_confidence=kb_confidence, confidence_threshold=CONFIDENCE_THRESHOLD, history=history,
# #     )
# #     log_turn(
# #         "answer", turn_id=turn_id, transcript=user_question, intent=intent,
# #         kb_time_s=round(kb_time, 2), kb_confidence=kb_confidence,
# #         llm_time_s=round(llm_time, 2), tts_time_s=round(tts_time_total, 2),
# #         total_time_s=round(total_time, 2), spoken_answer=spoken_answer,
# #         escalated=escalation_reason,
# #     )
# #     yield {"done": True, "spoken_answer": spoken_answer}


# # def _concatenate_wavs(paths: list[str], output_path: str) -> None:
# #     """Merge multiple mono wav segments into one file - used by process_turn()
# #     to present stream_turn()'s chunks as a single file for non-streaming callers."""
# #     if not paths:
# #         raise RuntimeError("No audio segments were generated.")
# #     with wave.open(paths[0], "rb") as first:
# #         params = first.getparams()
# #     Path(output_path).parent.mkdir(parents=True, exist_ok=True)
# #     with wave.open(output_path, "wb") as out:
# #         out.setparams(params)
# #         for p in paths:
# #             with wave.open(p, "rb") as w:
# #                 out.writeframes(w.readframes(w.getnframes()))


# # def process_turn(
# #     user_question: str,
# #     history: list[dict] | None = None,
# #     previous: list[str] | None = None,
# #     output_path: str = "response.wav",
# #     turn_id: str = "",
# # ) -> dict:
# #     """Non-streaming compatibility wrapper for CLI test scripts - built on
# #     top of stream_turn() so behavior can't drift between the two."""
# #     t0 = time.time()
# #     audio_paths: list[str] = []
# #     spoken_answer = ""
# #     is_cached_single_file = False

# #     for chunk in stream_turn(user_question, turn_id=turn_id, history=history, previous=previous):
# #         if chunk.get("done"):
# #             spoken_answer = chunk.get("spoken_answer", "")
# #             break
# #         audio_paths.append(chunk["audio_path"])
# #         is_cached_single_file = chunk.get("_cached", False)

# #     if is_cached_single_file and len(audio_paths) == 1:
# #         # It's the shared filler cache file - copy rather than concatenate,
# #         # and don't delete it (it's reused across turns).
# #         import shutil
# #         Path(output_path).parent.mkdir(parents=True, exist_ok=True)
# #         shutil.copyfile(audio_paths[0], output_path)
# #     else:
# #         _concatenate_wavs(audio_paths, output_path)
# #         for p in audio_paths:
# #             if os.path.exists(p):
# #                 os.remove(p)

# #     return {
# #         "question": user_question,
# #         "answer": spoken_answer,
# #         "audio_path": output_path,
# #         "elapsed_seconds": round(time.time() - t0, 2),
# #     }


# # def run_pipeline(
# #     user_question: str,
# #     history: list[dict] | None = None,
# #     previous: list[str] | None = None,
# #     output_path: str = "response.wav",
# # ) -> str:
# #     """Compatibility wrapper that returns just the spoken answer."""
# #     return process_turn(
# #         user_question=user_question,
# #         history=history,
# #         previous=previous,
# #         output_path=output_path,
# #     )["answer"]


# # def transcribe_and_process(audio_path: str, history: list[dict] | None = None) -> dict:
# #     """Convenience helper for file-based demos."""
# #     transcript = transcribe_audio_local(audio_path)
# #     with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_out:
# #         out_path = tmp_out.name
# #     try:
# #         result = process_turn(transcript, history=history, output_path=out_path)
# #         result["transcript"] = transcript
# #         return result
# #     except Exception:
# #         if os.path.exists(out_path):
# #             os.remove(out_path)
# #         raise

# """Orchestration layer: STT -> KB -> LLM -> TTS.

# This is a full rebuild that ports forward everything built and tested in
# local_web_demo.py (greeting/ack fast-path, confidence-gated KB grounding,
# streaming LLM+TTS chunking, latency logging, escalation logging) into this
# project's cleaner module structure. The previous version of this file only
# had the STT->KB->LLM->TTS wiring with none of those features.
# """

# from __future__ import annotations

# import os
# import re
# import tempfile
# import time
# import wave
# from pathlib import Path

# import requests

# from app.config import get_settings
# from app.kb.veelead_client import search_knowledge_base, get_grounded_answer, CONFIDENCE_THRESHOLD
# from app.llm.local_llm import ask_local_llm_stream
# from app.stt.whisper_local import transcribe_audio_local
# from app.tts.local_tts import text_to_speech
# from app.telemetry.logger import log_turn
# from app.telemetry.escalations import check_and_log_escalation

# FILLER_PHRASES = {
#     "greeting": "Hi, this is your support assistant. How may I help you today?",
#     "checking": "Okay, let me look into that for you.",
#     "one_moment": "One moment please, I'm looking that up.",
#     "ack_response": "Alright, let me know if there's anything else I can help with.",
#     "farewell_response": "Thanks for calling! Take care, and reach out anytime you need help.",
# }

# # Deliberately simple regex, not a model call - see local_llm.py's history
# # note for why: this needs to be free/instant, not add a second LLM round trip
# # just to decide whether the first one is needed.
# #
# # The outer (...)+ wraps each pattern so REPEATED words match too - e.g.
# # "Hello. Hello." or "Thanks Thanks" - a real gap found from live test data
# # where these fell through to the full (30+ second) pipeline for no reason.
# _GREETING_RE = re.compile(
#     r"(\s*(hi+|hello+|hey+|hii+|hai|yo|good\s+(morning|afternoon|evening))[\s,.!]*)+",
#     re.IGNORECASE,
# )
# _ACK_RE = re.compile(
#     r"(\s*(ok(ay)?|alright|sure|yes|yeah|yep|no|nope|got it|no problem|cool|great|perfect|fine|"
#     r"thanks?( you)?( so much)?( a lot)?|thank you( very much)?)[\s,.!]*)+",
#     re.IGNORECASE,
# )
# # Added based on real log evidence - "Bye." had no fast-path at all before this.
# _FAREWELL_RE = re.compile(
#     r"(\s*(bye+|goodbye|good\s*bye|see\s*you( later)?|take\s*care)[\s,.!]*)+",
#     re.IGNORECASE,
# )


# def classify_intent(text: str) -> str:
#     """Returns "greeting", "acknowledgment", "farewell", or "question"."""
#     stripped = text.strip()
#     if _GREETING_RE.fullmatch(stripped):
#         return "greeting"
#     if _FAREWELL_RE.fullmatch(stripped):
#         return "farewell"
#     if _ACK_RE.fullmatch(stripped):
#         return "acknowledgment"
#     return "question"


# def get_or_create_filler(phrase_key: str) -> str:
#     """Generate a filler phrase once and cache it for reuse."""
#     settings = get_settings()
#     settings.filler_cache_dir.mkdir(parents=True, exist_ok=True)
#     path = settings.filler_cache_dir / f"{phrase_key}.wav"
#     if not path.exists():
#         text_to_speech(FILLER_PHRASES[phrase_key], output_path=str(path))
#     return str(path)


# def stream_turn(
#     user_question: str,
#     turn_id: str = "",
#     history: list[dict] | None = None,
#     previous: list[str] | None = None,
# ):
#     """Generator yielding one dict per playable chunk, then a final summary dict.

#     Yields:
#       {"text": "...", "audio_path": "..."}   - a sentence and its audio file
#                                                  (caller owns cleanup of the file)
#       {"done": True, "spoken_answer": "...", "escalated": ...}  - final marker

#     This is the single source of truth for turn processing - process_turn()
#     below is a thin non-streaming wrapper built on top of this, not a
#     separate implementation, so the two can't drift out of sync.
#     """
#     t_start = time.time()
#     intent = classify_intent(user_question)

#     if intent in ("greeting", "acknowledgment", "farewell"):
#         phrase_key = {"greeting": "greeting", "acknowledgment": "ack_response", "farewell": "farewell_response"}[intent]
#         spoken_answer = FILLER_PHRASES[phrase_key]
#         audio_path = get_or_create_filler(phrase_key)
#         yield {"text": spoken_answer, "audio_path": audio_path, "_cached": True}
#         total_time = round(time.time() - t_start, 2)
#         log_turn(
#             "answer", turn_id=turn_id, transcript=user_question, intent=intent,
#             kb_time_s=0, llm_time_s=0, tts_time_s=0,
#             total_time_s=total_time, spoken_answer=spoken_answer,
#         )
#         yield {
#             "done": True, "spoken_answer": spoken_answer,
#             "kb_time_s": 0, "llm_time_s": 0, "tts_time_s": 0, "total_time_s": total_time,
#         }
#         return

#     kb_previous = previous
#     if kb_previous is None and history:
#         kb_previous = [str(turn.get("question", "")) for turn in history]

#     kb_time = 0.0
#     kb_confidence = None

#     try:
#         t_kb = time.time()
#         kb_result = search_knowledge_base(user_question, previous=kb_previous)
#         kb_time = time.time() - t_kb
#         kb_confidence = kb_result.get("confidence")
#     except requests.exceptions.Timeout:
#         fallback = (
#             "I'm having trouble reaching our knowledge base right now. "
#             "Let me connect you with a human teammate instead."
#         )
#         fallback_path = tempfile.mktemp(suffix=".wav")
#         text_to_speech(fallback, output_path=fallback_path)
#         yield {"text": fallback, "audio_path": fallback_path}
#         check_and_log_escalation(
#             turn_id=turn_id, transcript=user_question, spoken_answer=fallback,
#             kb_confidence=None, confidence_threshold=CONFIDENCE_THRESHOLD, history=history,
#         )
#         total_time = round(time.time() - t_start, 2)
#         log_turn(
#             "answer", turn_id=turn_id, transcript=user_question, intent=intent,
#             kb_time_s=round(kb_time, 2), error="kb_timeout",
#             total_time_s=total_time,
#         )
#         yield {
#             "done": True, "spoken_answer": fallback,
#             "kb_time_s": round(kb_time, 2), "llm_time_s": 0, "tts_time_s": 0, "total_time_s": total_time,
#         }
#         return

#     sentence_parts: list[str] = []
#     tts_time_total = 0.0
#     t_llm_start = time.time()

#     try:
#         for sentence in ask_local_llm_stream(user_question, get_grounded_answer(kb_result), history=history):
#             sentence_parts.append(sentence)
#             t_tts = time.time()
#             tts_path = tempfile.mktemp(suffix=".wav")
#             text_to_speech(sentence, output_path=tts_path)
#             tts_time_total += time.time() - t_tts
#             yield {"text": sentence, "audio_path": tts_path}
#     except Exception as exc:
#         spoken_answer = " ".join(sentence_parts)
#         total_time = round(time.time() - t_start, 2)
#         log_turn(
#             "answer", turn_id=turn_id, transcript=user_question, intent=intent,
#             kb_time_s=round(kb_time, 2), kb_confidence=kb_confidence,
#             error=str(exc), total_time_s=total_time,
#         )
#         yield {
#             "done": True, "spoken_answer": spoken_answer, "error": str(exc),
#             "kb_time_s": round(kb_time, 2), "tts_time_s": round(tts_time_total, 2), "total_time_s": total_time,
#         }
#         return

#     llm_time = max(time.time() - t_llm_start - tts_time_total, 0)
#     spoken_answer = " ".join(sentence_parts)
#     total_time = time.time() - t_start

#     escalation_reason = check_and_log_escalation(
#         turn_id=turn_id, transcript=user_question, spoken_answer=spoken_answer,
#         kb_confidence=kb_confidence, confidence_threshold=CONFIDENCE_THRESHOLD, history=history,
#     )
#     log_turn(
#         "answer", turn_id=turn_id, transcript=user_question, intent=intent,
#         kb_time_s=round(kb_time, 2), kb_confidence=kb_confidence,
#         llm_time_s=round(llm_time, 2), tts_time_s=round(tts_time_total, 2),
#         total_time_s=round(total_time, 2), spoken_answer=spoken_answer,
#         escalated=escalation_reason,
#     )
#     yield {
#         "done": True, "spoken_answer": spoken_answer,
#         "kb_time_s": round(kb_time, 2), "llm_time_s": round(llm_time, 2),
#         "tts_time_s": round(tts_time_total, 2), "total_time_s": round(total_time, 2),
#     }


# def _concatenate_wavs(paths: list[str], output_path: str) -> None:
#     """Merge multiple mono wav segments into one file - used by process_turn()
#     to present stream_turn()'s chunks as a single file for non-streaming callers."""
#     if not paths:
#         raise RuntimeError("No audio segments were generated.")
#     with wave.open(paths[0], "rb") as first:
#         params = first.getparams()
#     Path(output_path).parent.mkdir(parents=True, exist_ok=True)
#     with wave.open(output_path, "wb") as out:
#         out.setparams(params)
#         for p in paths:
#             with wave.open(p, "rb") as w:
#                 out.writeframes(w.readframes(w.getnframes()))


# def process_turn(
#     user_question: str,
#     history: list[dict] | None = None,
#     previous: list[str] | None = None,
#     output_path: str = "response.wav",
#     turn_id: str = "",
# ) -> dict:
#     """Non-streaming compatibility wrapper for CLI test scripts - built on
#     top of stream_turn() so behavior can't drift between the two."""
#     t0 = time.time()
#     audio_paths: list[str] = []
#     spoken_answer = ""
#     is_cached_single_file = False

#     for chunk in stream_turn(user_question, turn_id=turn_id, history=history, previous=previous):
#         if chunk.get("done"):
#             spoken_answer = chunk.get("spoken_answer", "")
#             break
#         audio_paths.append(chunk["audio_path"])
#         is_cached_single_file = chunk.get("_cached", False)

#     if is_cached_single_file and len(audio_paths) == 1:
#         # It's the shared filler cache file - copy rather than concatenate,
#         # and don't delete it (it's reused across turns).
#         import shutil
#         Path(output_path).parent.mkdir(parents=True, exist_ok=True)
#         shutil.copyfile(audio_paths[0], output_path)
#     else:
#         _concatenate_wavs(audio_paths, output_path)
#         for p in audio_paths:
#             if os.path.exists(p):
#                 os.remove(p)

#     return {
#         "question": user_question,
#         "answer": spoken_answer,
#         "audio_path": output_path,
#         "elapsed_seconds": round(time.time() - t0, 2),
#     }


# def run_pipeline(
#     user_question: str,
#     history: list[dict] | None = None,
#     previous: list[str] | None = None,
#     output_path: str = "response.wav",
# ) -> str:
#     """Compatibility wrapper that returns just the spoken answer."""
#     return process_turn(
#         user_question=user_question,
#         history=history,
#         previous=previous,
#         output_path=output_path,
#     )["answer"]


# def transcribe_and_process(audio_path: str, history: list[dict] | None = None) -> dict:
#     """Convenience helper for file-based demos."""
#     transcript = transcribe_audio_local(audio_path, language=get_settings().whisper_language)
#     with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_out:
#         out_path = tmp_out.name
#     try:
#         result = process_turn(transcript, history=history, output_path=out_path)
#         result["transcript"] = transcript
#         return result
#     except Exception:
#         if os.path.exists(out_path):
#             os.remove(out_path)
#         raise

"""Orchestration layer: STT -> KB -> LLM -> TTS.

This is a full rebuild that ports forward everything built and tested in
local_web_demo.py (greeting/ack fast-path, confidence-gated KB grounding,
streaming LLM+TTS chunking, latency logging, escalation logging) into this
project's cleaner module structure. The previous version of this file only
had the STT->KB->LLM->TTS wiring with none of those features.
"""

from __future__ import annotations

import os
import re
import tempfile
import time
import wave
from pathlib import Path

import requests

from app.config import get_settings
from app.kb.veelead_client import search_knowledge_base, get_grounded_answer, CONFIDENCE_THRESHOLD
from app.llm.local_llm import ask_local_llm_stream, generate_quick_ack
from app.stt.whisper_local import transcribe_audio_local
from app.tts.local_tts import text_to_speech
from app.telemetry.logger import log_turn
from app.telemetry.escalations import check_and_log_escalation

FILLER_PHRASES = {
    "greeting": "Hi, this is your support assistant. How may I help you today?",
    "checking": "Okay, let me look into that for you.",
    "one_moment": "One moment please, I'm looking that up.",
    "ack_response": "Alright, let me know if there's anything else I can help with.",
    "farewell_response": "Thanks for calling! Take care, and reach out anytime you need help.",
}

# Deliberately simple regex, not a model call - see local_llm.py's history
# note for why: this needs to be free/instant, not add a second LLM round trip
# just to decide whether the first one is needed.
#
# The outer (...)+ wraps each pattern so REPEATED words match too - e.g.
# "Hello. Hello." or "Thanks Thanks" - a real gap found from live test data
# where these fell through to the full (30+ second) pipeline for no reason.
_GREETING_RE = re.compile(
    r"(\s*(hi+|hello+|hey+|hii+|hai|yo|good\s+(morning|afternoon|evening))[\s,.!]*)+",
    re.IGNORECASE,
)
_ACK_RE = re.compile(
    r"(\s*(ok(ay)?|alright|sure|yes|yeah|yep|no|nope|got it|no problem|cool|great|perfect|fine|"
    r"thanks?( you)?( so much)?( a lot)?|thank you( very much)?)[\s,.!]*)+",
    re.IGNORECASE,
)
# Added based on real log evidence - "Bye." had no fast-path at all before this.
_FAREWELL_RE = re.compile(
    r"(\s*(bye+|goodbye|good\s*bye|see\s*you( later)?|take\s*care)[\s,.!]*)+",
    re.IGNORECASE,
)


def classify_intent(text: str) -> str:
    """Returns "greeting", "acknowledgment", "farewell", or "question"."""
    stripped = text.strip()
    if _GREETING_RE.fullmatch(stripped):
        return "greeting"
    if _FAREWELL_RE.fullmatch(stripped):
        return "farewell"
    if _ACK_RE.fullmatch(stripped):
        return "acknowledgment"
    return "question"


def get_or_create_filler(phrase_key: str) -> str:
    """Generate a filler phrase once and cache it for reuse."""
    settings = get_settings()
    settings.filler_cache_dir.mkdir(parents=True, exist_ok=True)
    path = settings.filler_cache_dir / f"{phrase_key}.wav"
    if not path.exists():
        text_to_speech(FILLER_PHRASES[phrase_key], output_path=str(path))
    return str(path)


def stream_turn(
    user_question: str,
    turn_id: str = "",
    history: list[dict] | None = None,
    previous: list[str] | None = None,
):
    """Generator yielding one dict per playable chunk, then a final summary dict.

    Yields:
      {"text": "...", "audio_path": "..."}   - a sentence and its audio file
                                                 (caller owns cleanup of the file)
      {"done": True, "spoken_answer": "...", "escalated": ...}  - final marker

    This is the single source of truth for turn processing - process_turn()
    below is a thin non-streaming wrapper built on top of this, not a
    separate implementation, so the two can't drift out of sync.
    """
    t_start = time.time()
    intent = classify_intent(user_question)

    if intent in ("greeting", "acknowledgment", "farewell"):
        phrase_key = {"greeting": "greeting", "acknowledgment": "ack_response", "farewell": "farewell_response"}[intent]
        spoken_answer = FILLER_PHRASES[phrase_key]
        audio_path = get_or_create_filler(phrase_key)
        yield {"text": spoken_answer, "audio_path": audio_path, "_cached": True, "kind": "answer"}
        total_time = round(time.time() - t_start, 2)
        log_turn(
            "answer", turn_id=turn_id, transcript=user_question, intent=intent,
            kb_time_s=0, llm_time_s=0, tts_time_s=0,
            total_time_s=total_time, spoken_answer=spoken_answer,
        )
        yield {
            "done": True, "spoken_answer": spoken_answer,
            "ack_time_s": 0, "kb_time_s": 0, "llm_time_s": 0, "tts_time_s": 0, "total_time_s": total_time,
        }
        return

    kb_previous = previous
    if kb_previous is None and history:
        kb_previous = [str(turn.get("question", "")) for turn in history]

    # Quick, question-specific acknowledgment before the real answer - e.g.
    # "Let me find the process for applying for two days of sick leave."
    # Deliberately non-fatal: if this fails or is slow, we just skip it and
    # go straight to the real answer rather than failing the whole turn over
    # what's meant to be a small nicety.
    ack_time = 0.0
    try:
        t_ack = time.time()
        quick_ack = generate_quick_ack(user_question)
        ack_time = time.time() - t_ack
        ack_path = tempfile.mktemp(suffix=".wav")
        text_to_speech(quick_ack, output_path=ack_path)
        yield {"text": quick_ack, "audio_path": ack_path, "kind": "filler"}
    except Exception as exc:
        print(f"Quick-ack generation failed (continuing without it): {exc}")

    kb_time = 0.0
    kb_confidence = None

    try:
        t_kb = time.time()
        kb_result = search_knowledge_base(user_question, previous=kb_previous)
        kb_time = time.time() - t_kb
        kb_confidence = kb_result.get("confidence")
    except requests.exceptions.Timeout:
        fallback = (
            "I'm having trouble reaching our knowledge base right now. "
            "Let me connect you with a human teammate instead."
        )
        fallback_path = tempfile.mktemp(suffix=".wav")
        text_to_speech(fallback, output_path=fallback_path)
        yield {"text": fallback, "audio_path": fallback_path, "kind": "answer"}
        check_and_log_escalation(
            turn_id=turn_id, transcript=user_question, spoken_answer=fallback,
            kb_confidence=None, confidence_threshold=CONFIDENCE_THRESHOLD, history=history,
        )
        total_time = round(time.time() - t_start, 2)
        log_turn(
            "answer", turn_id=turn_id, transcript=user_question, intent=intent,
            kb_time_s=round(kb_time, 2), ack_time_s=round(ack_time, 2), error="kb_timeout",
            total_time_s=total_time,
        )
        yield {
            "done": True, "spoken_answer": fallback,
            "ack_time_s": round(ack_time, 2), "kb_time_s": round(kb_time, 2),
            "llm_time_s": 0, "tts_time_s": 0, "total_time_s": total_time,
        }
        return

    sentence_parts: list[str] = []
    tts_time_total = 0.0
    t_llm_start = time.time()

    try:
        for sentence in ask_local_llm_stream(user_question, get_grounded_answer(kb_result), history=history):
            sentence_parts.append(sentence)
            t_tts = time.time()
            tts_path = tempfile.mktemp(suffix=".wav")
            text_to_speech(sentence, output_path=tts_path)
            tts_time_total += time.time() - t_tts
            yield {"text": sentence, "audio_path": tts_path, "kind": "answer"}
    except Exception as exc:
        spoken_answer = " ".join(sentence_parts)
        total_time = round(time.time() - t_start, 2)
        log_turn(
            "answer", turn_id=turn_id, transcript=user_question, intent=intent,
            kb_time_s=round(kb_time, 2), kb_confidence=kb_confidence, ack_time_s=round(ack_time, 2),
            error=str(exc), total_time_s=total_time,
        )
        yield {
            "done": True, "spoken_answer": spoken_answer, "error": str(exc),
            "ack_time_s": round(ack_time, 2), "kb_time_s": round(kb_time, 2),
            "tts_time_s": round(tts_time_total, 2), "total_time_s": total_time,
        }
        return

    llm_time = max(time.time() - t_llm_start - tts_time_total, 0)
    spoken_answer = " ".join(sentence_parts)
    total_time = time.time() - t_start

    escalation_reason = check_and_log_escalation(
        turn_id=turn_id, transcript=user_question, spoken_answer=spoken_answer,
        kb_confidence=kb_confidence, confidence_threshold=CONFIDENCE_THRESHOLD, history=history,
    )
    log_turn(
        "answer", turn_id=turn_id, transcript=user_question, intent=intent,
        kb_time_s=round(kb_time, 2), kb_confidence=kb_confidence, ack_time_s=round(ack_time, 2),
        llm_time_s=round(llm_time, 2), tts_time_s=round(tts_time_total, 2),
        total_time_s=round(total_time, 2), spoken_answer=spoken_answer,
        escalated=escalation_reason,
    )
    yield {
        "done": True, "spoken_answer": spoken_answer,
        "ack_time_s": round(ack_time, 2), "kb_time_s": round(kb_time, 2),
        "llm_time_s": round(llm_time, 2), "tts_time_s": round(tts_time_total, 2),
        "total_time_s": round(total_time, 2),
    }


def _concatenate_wavs(paths: list[str], output_path: str) -> None:
    """Merge multiple mono wav segments into one file - used by process_turn()
    to present stream_turn()'s chunks as a single file for non-streaming callers."""
    if not paths:
        raise RuntimeError("No audio segments were generated.")
    with wave.open(paths[0], "rb") as first:
        params = first.getparams()
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(output_path, "wb") as out:
        out.setparams(params)
        for p in paths:
            with wave.open(p, "rb") as w:
                out.writeframes(w.readframes(w.getnframes()))


def process_turn(
    user_question: str,
    history: list[dict] | None = None,
    previous: list[str] | None = None,
    output_path: str = "response.wav",
    turn_id: str = "",
) -> dict:
    """Non-streaming compatibility wrapper for CLI test scripts - built on
    top of stream_turn() so behavior can't drift between the two."""
    t0 = time.time()
    audio_paths: list[str] = []
    spoken_answer = ""
    is_cached_single_file = False

    for chunk in stream_turn(user_question, turn_id=turn_id, history=history, previous=previous):
        if chunk.get("done"):
            spoken_answer = chunk.get("spoken_answer", "")
            break
        audio_paths.append(chunk["audio_path"])
        is_cached_single_file = chunk.get("_cached", False)

    if is_cached_single_file and len(audio_paths) == 1:
        # It's the shared filler cache file - copy rather than concatenate,
        # and don't delete it (it's reused across turns).
        import shutil
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(audio_paths[0], output_path)
    else:
        _concatenate_wavs(audio_paths, output_path)
        for p in audio_paths:
            if os.path.exists(p):
                os.remove(p)

    return {
        "question": user_question,
        "answer": spoken_answer,
        "audio_path": output_path,
        "elapsed_seconds": round(time.time() - t0, 2),
    }


def run_pipeline(
    user_question: str,
    history: list[dict] | None = None,
    previous: list[str] | None = None,
    output_path: str = "response.wav",
) -> str:
    """Compatibility wrapper that returns just the spoken answer."""
    return process_turn(
        user_question=user_question,
        history=history,
        previous=previous,
        output_path=output_path,
    )["answer"]


def transcribe_and_process(audio_path: str, history: list[dict] | None = None) -> dict:
    """Convenience helper for file-based demos."""
    transcript = transcribe_audio_local(audio_path)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_out:
        out_path = tmp_out.name
    try:
        result = process_turn(transcript, history=history, output_path=out_path)
        result["transcript"] = transcript
        return result
    except Exception:
        if os.path.exists(out_path):
            os.remove(out_path)
        raise