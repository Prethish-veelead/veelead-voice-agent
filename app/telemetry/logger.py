"""
Lightweight per-turn latency/quality logging - the Tier 1 observability step.

Deliberately NOT Langfuse/OpenTelemetry - this is meant to be the cheapest
possible thing that gives you real numbers to make decisions from (e.g.
"is streaming LLM/TTS actually worth building", "is the local stack fast
enough to ship"). One JSON object per line, easy to inspect by eye or load
into pandas later: pd.read_json("logs/turns.jsonl", lines=True)

Thread-safe append (Flask's dev server with threaded=True can log from
multiple requests concurrently).
"""

import json
import os
import threading
from datetime import datetime, timezone

LOG_PATH = os.environ.get("TELEMETRY_LOG_PATH", "logs/turns.jsonl")
_lock = threading.Lock()


def log_turn(event_type: str, **fields) -> None:
    """event_type is e.g. "transcribe" or "answer" - lets you distinguish
    STT-stage log lines from KB/LLM/TTS-stage log lines that share the same
    turn_id, without needing separate log files."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        **fields,
    }
    os.makedirs(os.path.dirname(LOG_PATH) or ".", exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False)

    with _lock:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
