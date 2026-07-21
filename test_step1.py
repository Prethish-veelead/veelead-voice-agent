"""
Step 1 test: audio file -> local Whisper transcription -> local LLM response.

No KB, no TTS yet - this only proves the two new local components work
together. Once this works, Step 2 adds the KB (unchanged, still hits
veelead-rag) and Step 3 adds local TTS.

RUN:
  python test_step1.py path/to/question.wav
"""

import sys
import time

sys.path.insert(0, ".")  # so the app/ package imports work when run from the repo root

from app.stt.whisper_local import transcribe_audio_local
from app.llm.local_llm import ask_local_llm


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python test_step1.py <path-to-audio-file>")

    audio_path = sys.argv[1]

    t0 = time.time()
    print(f"Transcribing {audio_path}...")
    transcript = transcribe_audio_local(audio_path)
    print(f"[{time.time() - t0:.2f}s] Transcript: {transcript}")

    if not transcript:
        sys.exit("Got an empty transcript - check the audio file has clear speech in it.")

    t1 = time.time()
    print("Asking local LLM...")
    answer = ask_local_llm(transcript)
    print(f"[{time.time() - t1:.2f}s] Answer: {answer}")

    print(f"\nTotal round trip: {time.time() - t0:.2f}s")


if __name__ == "__main__":
    main()
