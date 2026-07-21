"""
Step 3 test: the complete local pipeline.
audio/text in -> local Whisper -> veelead-rag KB (unchanged) -> local LLM
(grounded + history-aware) -> local Piper TTS -> playback.

This is the local equivalent of your working cloud pipeline
(voice_helpdesk_pipeline.py) - same shape, same KB, only STT/LLM/TTS swapped
for local models.

RUN (single audio file):
  python test_step3.py path/to/question.wav

RUN (interactive text loop - fastest way to test multi-turn behavior):
  python test_step3.py --text
"""

import os
import sys
import time

sys.path.insert(0, ".")

from app.stt.whisper_local import transcribe_audio_local
from app.kb.veelead_client import search_knowledge_base
from app.llm.local_llm import ask_local_llm
from app.tts.piper_local import text_to_speech_local


def play_audio(path: str) -> None:
    """Best-effort local playback, same cross-platform approach as the browser demo."""
    try:
        if sys.platform == "darwin":
            os.system(f"afplay '{path}'")
        elif sys.platform.startswith("linux"):
            os.system(f"mpg123 -q '{path}' 2>/dev/null || ffplay -nodisp -autoexit -loglevel quiet '{path}'")
        elif sys.platform.startswith("win"):
            os.startfile(path)  # noqa: S606
    except Exception as exc:
        print(f"Playback failed ({exc}) - open {path} manually.")


def run_turn(question: str, history: list) -> str:
    t0 = time.time()
    kb_result = search_knowledge_base(question, previous=[h["question"] for h in history])
    print(f"[{time.time() - t0:.2f}s] KB confidence: {kb_result.get('confidence')}")

    answer = ask_local_llm(question, kb_result.get("answer", ""), history=history)
    print(f"[{time.time() - t0:.2f}s] Answer: {answer}")

    audio_path = text_to_speech_local(answer, output_path="response.wav")
    print(f"[{time.time() - t0:.2f}s] Audio saved to {audio_path}")
    play_audio(audio_path)

    return answer


def main():
    history: list = []

    if "--text" in sys.argv:
        print("Type questions, 'quit' to exit.")
        while True:
            question = input("\nYou: ").strip()
            if question.lower() in {"quit", "exit"}:
                break
            if question:
                answer = run_turn(question, history)
                history.append({"question": question, "answer": answer})
                history = history[-5:]
        return

    if len(sys.argv) < 2:
        sys.exit("Usage: python test_step3.py <path-to-audio-file>  OR  python test_step3.py --text")

    audio_path = sys.argv[1]
    print(f"Transcribing {audio_path}...")
    transcript = transcribe_audio_local(audio_path)
    print(f"Transcript: {transcript}")

    if not transcript:
        sys.exit("Got an empty transcript.")

    run_turn(transcript, history)


if __name__ == "__main__":
    main()
