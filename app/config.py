"""Central configuration for the voice help agent scaffold."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from the environment."""

    base_dir: Path = BASE_DIR
    filler_cache_dir: Path = BASE_DIR / "filler_cache"
    models_dir: Path = BASE_DIR / "models"

    veelead_url: str = os.environ.get(
        "VEELEAD_URL",
        "https://veelead-rag.southeastasia.cloudapp.azure.com/search.json",
    )
    veelead_api_key: str | None = os.environ.get("VEELEAD_API_KEY")

    ollama_base_url: str = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    ollama_api_key: str = os.environ.get("OLLAMA_API_KEY", "ollama")
    ollama_model: str = os.environ.get("OLLAMA_MODEL", "llama3.2")

    whisper_model_size: str = os.environ.get("WHISPER_MODEL_SIZE", "small")
    whisper_device: str = os.environ.get("WHISPER_DEVICE", "cpu")
    whisper_compute_type: str = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")
    whisper_language: str | None = os.environ.get("WHISPER_LANGUAGE")

    local_tts_backend: str = os.environ.get("LOCAL_TTS_BACKEND", "piper")
    piper_bin: str = os.environ.get("PIPER_BIN", "piper")
    piper_model_path: str | None = os.environ.get("PIPER_MODEL_PATH")
    piper_config_path: str | None = os.environ.get("PIPER_CONFIG_PATH")

    xtts_model_name: str = os.environ.get("XTTS_MODEL_NAME", "tts_models/multilingual/multi-dataset/xtts_v2")
    xtts_speaker_wav: str | None = os.environ.get("XTTS_SPEAKER_WAV")
    xtts_language: str = os.environ.get("XTTS_LANGUAGE", "en")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
