"""Local text-to-speech wrapper for Piper or XTTS."""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

from app.config import get_settings

try:
    from TTS.api import TTS
except Exception:  # pragma: no cover - optional dependency
    TTS = None  # type: ignore[assignment]


def _run_piper(text: str, output_path: str) -> str:
    settings = get_settings()
    if not settings.piper_model_path:
        raise RuntimeError("Set PIPER_MODEL_PATH to use the Piper backend.")

    command = [
        settings.piper_bin,
        "--model",
        settings.piper_model_path,
        "--output_file",
        output_path,
    ]
    if settings.piper_config_path:
        command.extend(["--config", settings.piper_config_path])

    subprocess.run(
        command,
        input=text.encode("utf-8"),
        check=True,
    )
    return output_path


@lru_cache(maxsize=1)
def _load_xtts_model() -> TTS:
    if TTS is None:  # pragma: no cover - handled by runtime error below
        raise RuntimeError("TTS is not installed. Install the optional dependency to use XTTS.")
    settings = get_settings()
    return TTS(settings.xtts_model_name)


def _run_xtts(text: str, output_path: str) -> str:
    settings = get_settings()
    if TTS is None:
        raise RuntimeError("TTS is not installed. Install the optional dependency to use XTTS.")
    if not settings.xtts_speaker_wav:
        raise RuntimeError("Set XTTS_SPEAKER_WAV to use the XTTS backend.")

    _load_xtts_model().tts_to_file(
        text=text,
        file_path=output_path,
        speaker_wav=settings.xtts_speaker_wav,
        language=settings.xtts_language,
    )
    return output_path


def text_to_speech(text: str, output_path: str = "response.wav") -> str:
    """Render speech with the configured local backend."""

    settings = get_settings()
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    backend = settings.local_tts_backend.lower().strip()
    if backend == "piper":
        return _run_piper(text, output_path)
    if backend == "xtts":
        return _run_xtts(text, output_path)

    raise RuntimeError(f"Unknown LOCAL_TTS_BACKEND: {settings.local_tts_backend!r}")
