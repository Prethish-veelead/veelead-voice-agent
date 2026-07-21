"""
Local speech-to-text using faster-whisper - drop-in replacement for the
Deepgram-based transcribe_audio() in voice_helpdesk_pipeline.py.

VERIFIED against the installed faster-whisper package (not guessed):
WhisperModel.transcribe() returns a generator of Segment objects plus a
TranscriptionInfo object - not a plain string - hence the join below.

Model download: the first time you run this, faster-whisper downloads the
"small" model weights from Hugging Face automatically (a few hundred MB).
That download needs real internet access on your machine - I can't test
this step myself since this sandbox can't reach Hugging Face's hosting.
"""

import os
from faster_whisper import WhisperModel

WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "small")
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "auto")  # "cuda", "cpu", or "auto"
WHISPER_COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "default")

_model = None


def _get_model() -> WhisperModel:
    """Lazy-load the model once and reuse it - loading is the slow part,
    not the actual transcription of a single short clip."""
    global _model
    if _model is None:
        print(f"Loading Whisper model '{WHISPER_MODEL_SIZE}' on device '{WHISPER_DEVICE}'...")
        _model = WhisperModel(
            WHISPER_MODEL_SIZE,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE_TYPE,
        )
    return _model


def transcribe_audio_local(file_path: str, language: str = None) -> str:
    """Transcribe an audio file and return the full text.

    `language` can be left as None to let Whisper auto-detect it, or set
    explicitly (e.g. "en") to skip detection and slightly reduce latency.
    """
    model = _get_model()
    segments, info = model.transcribe(
        file_path,
        language=language,
        vad_filter=True,  # built into faster-whisper - skips silence, no separate VAD library needed
    )
    print(f"Detected language: {info.language} (confidence {info.language_probability:.2f})")

    full_text = " ".join(segment.text.strip() for segment in segments)
    return full_text.strip()


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        sys.exit("Usage: python whisper_local.py <path-to-audio-file>")
    transcript = transcribe_audio_local(sys.argv[1])
    print(f"\nTranscript: {transcript}")