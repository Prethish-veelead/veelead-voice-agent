"""
Step 2 test: audio file -> local Whisper -> veelead-rag KB (unchanged,
same URL/key as the cloud version) -> local LLM, grounded + history-aware.

Still no TTS - proving the KB integration and repetition-avoidance logic
work identically with a local LLM before adding audio output.

RUN (single question):
  python test_step2.py path/to/question.wav

RUN (interactive text loop, to test multi-turn history without needing
multiple audio files):
  python test_step2.py --text
"""

import sys
import time

sys.path.insert(0, ".")

from app.stt.whisper_local import transcribe_audio_local
from app.kb.veelead_client import search_knowledge_base
from app.llm.local_llm import ask_local_llm


def run_turn(question: str, history: list) -> str:
    t0 = time.time()
    kb_result = search_knowledge_base(question, previous=[h["question"] for h in history])
    print(f"[{time.time() - t0:.2f}s] KB confidence: {kb_result.get('confidence')}")

    answer = ask_local_llm(question, kb_result.get("answer", ""), history=history)
    print(f"[{time.time() - t0:.2f}s] Answer: {answer}")
    return answer


def main():
    history: list = []

    if "--text" in sys.argv:
        print("Type questions, 'quit' to exit. Try a follow-up like 'I already tried that' to test the anti-repetition logic.")
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
        sys.exit("Usage: python test_step2.py <path-to-audio-file>  OR  python test_step2.py --text")

    audio_path = sys.argv[1]
    print(f"Transcribing {audio_path}...")
    transcript = transcribe_audio_local(audio_path)
    print(f"Transcript: {transcript}")

    if not transcript:
        sys.exit("Got an empty transcript.")

    run_turn(transcript, history)


if __name__ == "__main__":
    main()
