# """
# veelead-rag knowledge base client - IDENTICAL to search_knowledge_base() in
# voice_helpdesk_pipeline.py. This is the point of Step 2: the KB call doesn't
# change at all when swapping the LLM - it's a completely separate service.
# """

# import os
# import requests
# from dotenv import load_dotenv

# load_dotenv()

# VEELEAD_URL = "https://veelead-rag.southeastasia.cloudapp.azure.com/search.json"
# VEELEAD_API_KEY = os.environ["VEELEAD_API_KEY"]


# def search_knowledge_base(query: str, previous: list[str] | None = None) -> dict:
#     """Query the veelead-rag helpdesk knowledge base for grounding context.

#     Same 25s timeout + one retry as the cloud version, since the KB does its
#     own LLM generation on non-cached queries and can be genuinely slow.
#     """
#     headers = {"x-api-key": VEELEAD_API_KEY}
#     params = {"q": query}
#     if previous:
#         params["previous"] = previous[-5:]

#     last_error = None
#     for attempt in range(2):
#         try:
#             resp = requests.get(VEELEAD_URL, headers=headers, params=params, timeout=25)
#             resp.raise_for_status()
#             return resp.json()
#         except requests.exceptions.Timeout as exc:
#             last_error = exc
#             print(f"KB request timed out (attempt {attempt + 1}/2): {exc}")

#     raise last_error
"""
veelead-rag knowledge base client - IDENTICAL to search_knowledge_base() in
voice_helpdesk_pipeline.py. This is the point of Step 2: the KB call doesn't
change at all when swapping the LLM - it's a completely separate service.
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

VEELEAD_URL = "https://veelead-rag.southeastasia.cloudapp.azure.com/search.json"
VEELEAD_API_KEY = os.environ["VEELEAD_API_KEY"]

# Below this, treat the KB match as "no relevant answer" rather than grounding
# the response in it. Tune this based on real testing - 0.4 is a starting
# point, not a verified-correct value from the KB's own documentation.
CONFIDENCE_THRESHOLD = 0.4


def get_grounded_answer(kb_result: dict) -> str:
    """Returns the KB's answer text only if confidence clears the threshold,
    otherwise "" - this is what prevents things like a plain "hi" from being
    answered with an unrelated low-confidence KB article."""
    confidence = kb_result.get("confidence") or 0
    if confidence < CONFIDENCE_THRESHOLD:
        return ""
    return kb_result.get("answer", "")


def search_knowledge_base(query: str, previous: list[str] | None = None) -> dict:
    """Query the veelead-rag helpdesk knowledge base for grounding context.

    Same 25s timeout + one retry as the cloud version, since the KB does its
    own LLM generation on non-cached queries and can be genuinely slow.
    """
    headers = {"x-api-key": VEELEAD_API_KEY}
    params = {"q": query}
    if previous:
        params["previous"] = previous[-5:]

    last_error = None
    for attempt in range(2):
        try:
            resp = requests.get(VEELEAD_URL, headers=headers, params=params, timeout=25)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.Timeout as exc:
            last_error = exc
            print(f"KB request timed out (attempt {attempt + 1}/2): {exc}")

    raise last_error