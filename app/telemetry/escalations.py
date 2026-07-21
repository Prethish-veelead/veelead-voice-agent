"""
Escalation logging - closes the gap between "the agent SAYS it'll connect
you with a human" and something actually happening. This doesn't build a
real ticketing/notification system (that's a bigger integration decision -
Zendesk? Slack webhook? Teams channel?) - it's the minimum viable version:
every escalation gets written to a real, reviewable record with full
context, instead of just being spoken words that vanish into the call.

Two independent triggers, since they catch different failure modes:
  - low_confidence: the KB itself didn't have a good match for this question
  - llm_flagged: the LLM decided (based on repeated "that didn't work"
    signals) that it should hand off, even if the KB confidence was fine
"""

import os
import re
from datetime import datetime, timezone

from app.telemetry.logger import log_turn  # reuse the same thread-safe append pattern

ESCALATION_LOG_PATH = os.environ.get("ESCALATION_LOG_PATH", "logs/escalations.jsonl")

# These are the exact phrases our own system prompts instruct the LLM to use
# when it decides to hand off - detecting our own fixed wording is much more
# reliable than trying to infer intent from arbitrary free-form text.
_ESCALATION_PHRASES = re.compile(
    r"connect (you|them) with a human|human teammate|connect (you|them) to a human|"
    r"reach out to the relevant department|human agent",
    re.IGNORECASE,
)


def check_and_log_escalation(
    turn_id: str,
    transcript: str,
    spoken_answer: str,
    kb_confidence: float | None,
    confidence_threshold: float,
    history: list[dict] | None = None,
) -> str | None:
    """Call this once per turn, after the full spoken_answer is known.
    Returns the escalation reason if one was logged, else None."""
    reason = None

    if kb_confidence is not None and kb_confidence < confidence_threshold:
        reason = "low_confidence"
    elif _ESCALATION_PHRASES.search(spoken_answer or ""):
        reason = "llm_flagged"

    if reason is None:
        return None

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "turn_id": turn_id,
        "reason": reason,
        "transcript": transcript,
        "spoken_answer": spoken_answer,
        "kb_confidence": kb_confidence,
        "recent_history": history or [],
    }
    os.makedirs(os.path.dirname(ESCALATION_LOG_PATH) or ".", exist_ok=True)

    import json
    import threading
    if not hasattr(check_and_log_escalation, "_lock"):
        check_and_log_escalation._lock = threading.Lock()
    with check_and_log_escalation._lock:
        with open(ESCALATION_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"ESCALATION LOGGED ({reason}): {transcript!r}")
    return reason
