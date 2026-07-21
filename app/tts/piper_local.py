"""
Local text-to-speech using Piper - drop-in replacement for the Sarvam-based
text_to_speech() in voice_helpdesk_pipeline.py.

VERIFIED against the installed piper-tts package (not guessed):
PiperVoice.load() takes model_path + config_path (two separate files you
download once - not a pip-installed model). synthesize_wav() writes into an
already-open wave.Wave_write object, not a plain file path - hence the
wave.open() wrapper below.

MODEL DOWNLOAD (do this once, on your machine - not something I can do in
this sandbox since it needs real internet access to wherever Piper hosts
voice files):
  Piper's voice models are documented at https://github.com/rhasspy/piper
  under "Voices" - download a voice's .onnx model file AND its matching
  .onnx.json config file (they come as a pair, same base filename) to a
  local folder, e.g. a good English starting point is "en_US-lessac-medium".
  I haven't verified the exact current download URL from this sandbox -
  check the GitHub README directly for the current voice list/links.
"""

import os
import wave
from piper import PiperVoice

PIPER_MODEL_PATH = os.environ.get("PIPER_MODEL_PATH", "models/en_US-lessac-medium.onnx")
PIPER_CONFIG_PATH = os.environ.get("PIPER_CONFIG_PATH", "models/en_US-lessac-medium.onnx.json")
PIPER_USE_CUDA = os.environ.get("PIPER_USE_CUDA", "false").lower() == "true"

_voice = None


def _get_voice() -> PiperVoice:
    global _voice
    if _voice is None:
        if not os.path.exists(PIPER_MODEL_PATH):
            raise FileNotFoundError(
                f"Piper model not found at {PIPER_MODEL_PATH} - download the .onnx "
                f"and .onnx.json voice files first (see module docstring)."
            )
        print(f"Loading Piper voice from {PIPER_MODEL_PATH}...")
        _voice = PiperVoice.load(
            PIPER_MODEL_PATH,
            config_path=PIPER_CONFIG_PATH,
            use_cuda=PIPER_USE_CUDA,
        )
    return _voice


def text_to_speech_local(text: str, output_path: str = "response.wav") -> str:
    """Same interface as text_to_speech() in the cloud version: text in, wav path out."""
    voice = _get_voice()
    with wave.open(output_path, "wb") as wav_file:
        voice.synthesize_wav(text, wav_file)
    return output_path


if __name__ == "__main__":
    import sys
    text = " ".join(sys.argv[1:]) or "Hello, this is a test of the local voice."
    path = text_to_speech_local(text)
    print(f"Saved audio to {path}")
