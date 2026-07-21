# # """
# # Voice helpdesk pipeline — pilot version (no telephony yet)
# # ------------------------------------------------------------
# # Flow: caller audio (Deepgram STT) or typed text -> instant cached filler audio
# #       -> veelead-rag KB lookup -> GPT-4o-mini rephrases the answer for speech
# #       -> Sarvam AI TTS -> wav

# # Once Twilio is set up, swap the file-based Deepgram call for their
# # streaming transcript endpoint and this same core logic stays the same —
# # the filler still plays the instant STT detects end-of-speech, while the
# # KB+GPT+TTS chain runs in the background.

# # SETUP:
# #   pip install openai requests python-dotenv sarvamai

# #   Create a .env file (never commit this) with either:
# #     OPENAI_API_KEY=sk-...
# #   or (to use Azure OpenAI instead):
# #     GPT_ENDPOINT=https://<your-resource>.openai.azure.com/
# #     GPT_API_KEY=...
# #     GPT_API_VER=2024-12-01-preview
# #     GPT_MINI_DEPLOY=gpt-4o-mini
# #   plus, either way:
# #     SARVAM_API_KEY=...
# #     SARVAM_SPEAKER=anand                         # see docs.sarvam.ai for the full bulbul:v3 speaker list
# #     SARVAM_TARGET_LANGUAGE=en-IN
# #     VEELEAD_API_KEY=...                          # rotate the one shared in chat before using this
# #     DEEPGRAM_API_KEY=...                         # only needed for audio-file input

# # USAGE:
# #   python voice_helpdesk_pipeline.py question.mp3   # transcribes the file, runs it once, exits
# #   python voice_helpdesk_pipeline.py                # interactive typed-text loop
# # """

# # import base64
# # import os
# # import re
# # import sys
# # import time
# # import requests
# # from openai import OpenAI, AzureOpenAI
# # from sarvamai import SarvamAI
# # from dotenv import load_dotenv

# # load_dotenv()

# # VEELEAD_URL = "https://veelead-rag.southeastasia.cloudapp.azure.com/search.json"
# # VEELEAD_API_KEY = os.environ.get("VEELEAD_API_KEY")
# # OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
# # DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY")
# # SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY")
# # SARVAM_SPEAKER = os.environ.get("SARVAM_SPEAKER", "anand")
# # SARVAM_TARGET_LANGUAGE = os.environ.get("SARVAM_TARGET_LANGUAGE", "en-IN")

# # AZURE_OPENAI_ENDPOINT = os.environ.get("GPT_ENDPOINT")
# # AZURE_OPENAI_API_KEY = os.environ.get("GPT_API_KEY")
# # AZURE_OPENAI_API_VERSION = os.environ.get("GPT_API_VER", "2024-12-01-preview")
# # AZURE_OPENAI_DEPLOYMENT = os.environ.get("GPT_MINI_DEPLOY", "gpt-4o-mini")
# # USE_AZURE_OPENAI = bool(AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY)

# # REQUIRED = {
# #     "VEELEAD_API_KEY": VEELEAD_API_KEY,
# #     "SARVAM_API_KEY": SARVAM_API_KEY,
# # }
# # if not USE_AZURE_OPENAI:
# #     REQUIRED["OPENAI_API_KEY"] = OPENAI_API_KEY
# # missing = [k for k, v in REQUIRED.items() if not v]
# # if missing:
# #     sys.exit(f"Missing required environment variables: {', '.join(missing)}. Set them in your .env file.")

# # if USE_AZURE_OPENAI:
# #     client = AzureOpenAI(
# #         api_key=AZURE_OPENAI_API_KEY,
# #         azure_endpoint=AZURE_OPENAI_ENDPOINT,
# #         api_version=AZURE_OPENAI_API_VERSION,
# #     )
# #     GPT_MODEL = AZURE_OPENAI_DEPLOYMENT
# # else:
# #     client = OpenAI(api_key=OPENAI_API_KEY)
# #     GPT_MODEL = "gpt-4o-mini"

# # sarvam_client = SarvamAI(api_subscription_key=SARVAM_API_KEY)


# # def strip_markdown_for_speech(text: str) -> str:
# #     """Remove markdown/emoji artifacts so TTS doesn't try to speak them literally."""
# #     text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)          # **bold**
# #     text = re.sub(r"[#*_`]", "", text)                     # leftover markdown chars
# #     text = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", text)  # emoji ranges
# #     text = re.sub(r"\n{2,}", ". ", text)
# #     text = re.sub(r"\n", " ", text)
# #     text = re.sub(r"\s{2,}", " ", text)
# #     return text.strip()


# # AUDIO_CONTENT_TYPES = {
# #     ".mp3": "audio/mpeg",
# #     ".wav": "audio/wav",
# #     ".m4a": "audio/mp4",
# #     ".ogg": "audio/ogg",
# #     ".webm": "audio/webm",
# # }


# # def transcribe_audio(file_path: str) -> str:
# #     """Send an audio file to Deepgram and return the transcript text."""
# #     if not DEEPGRAM_API_KEY:
# #         sys.exit("Missing DEEPGRAM_API_KEY in .env — required for audio-file input.")

# #     ext = os.path.splitext(file_path)[1].lower()
# #     content_type = AUDIO_CONTENT_TYPES.get(ext, "audio/mpeg")

# #     with open(file_path, "rb") as audio_file:
# #         resp = requests.post(
# #             "https://api.deepgram.com/v1/listen",
# #             headers={
# #                 "Authorization": f"Token {DEEPGRAM_API_KEY}",
# #                 "Content-Type": content_type,
# #             },
# #             params={"model": "nova-2", "smart_format": "true", "punctuate": "true"},
# #             data=audio_file,
# #             timeout=30,
# #         )
# #     resp.raise_for_status()
# #     return resp.json()["results"]["channels"][0]["alternatives"][0]["transcript"]


# # def search_knowledge_base(query: str, previous: list[str] | None = None) -> dict:
# #     """Query the veelead-rag helpdesk knowledge base for grounding context.

# #     `previous` is up to the last 5 user questions in the call (oldest first) -
# #     the API uses it to disambiguate follow-ups like "I tried that, still broken".
# #     """
# #     headers = {"x-api-key": VEELEAD_API_KEY}
# #     params = {"q": query}
# #     if previous:
# #         params["previous"] = previous[-5:]
# #     resp = requests.get(VEELEAD_URL, headers=headers, params=params, timeout=10)
# #     resp.raise_for_status()
# #     return resp.json()


# # LOW_CONFIDENCE_THRESHOLD = 0.5


# # def ask_gpt(question: str, kb_answer: str, kb_confidence: float | None = None) -> str:
# #     """Rephrase the raw KB answer into a short, natural, professional spoken response."""
# #     clean_answer = strip_markdown_for_speech(kb_answer)
# #     low_confidence = kb_confidence is not None and kb_confidence < LOW_CONFIDENCE_THRESHOLD

# #     system_prompt = (
# #         "You are a professional voice support agent speaking out loud to a caller "
# #         "on a phone call. You are given the correct answer from the knowledge base "
# #         "in written form. Rephrase it as if you were personally explaining it to "
# #         "the caller in a natural, warm, professional tone. Keep it concise — "
# #         "2 to 4 short sentences, spoken style, no lists, no headers, no markdown, "
# #         "no emojis. Do not add information that isn't in the source answer. "
# #         "If the source answer doesn't actually address the question, or you are told "
# #         "the knowledge base confidence is low, do not guess and do not offer to "
# #         "transfer to a human agent — just say something like \"I'm not sure about "
# #         "that, could you rephrase your question?\" so the caller can restate it."
# #     )
# #     user_content = f"Caller's question: {question}\n\nKnowledge base answer:\n{clean_answer}"
# #     if low_confidence:
# #         user_content += "\n\n(Knowledge base confidence is low for this answer.)"

# #     completion = client.chat.completions.create(
# #         model=GPT_MODEL,
# #         messages=[
# #             {"role": "system", "content": system_prompt},
# #             {"role": "user", "content": user_content},
# #         ],
# #         temperature=0.4,
# #     )
# #     return completion.choices[0].message.content.strip()


# # FILLER_PHRASES = {
# #     "greeting": "Hi, this is your support assistant. How may I help you today?",
# #     "checking": "Okay, let me look into that for you.",
# #     "one_moment": "One moment please, I'm looking that up.",
# # }
# # FILLER_DIR = "filler_cache"


# # def get_or_create_filler(phrase_key: str) -> str:
# #     """Generate a filler phrase once and cache it — reused on every call so the
# #     caller hears an instant acknowledgment with zero generation latency."""
# #     os.makedirs(FILLER_DIR, exist_ok=True)
# #     path = os.path.join(FILLER_DIR, f"{phrase_key}.wav")
# #     if not os.path.exists(path):
# #         text_to_speech(FILLER_PHRASES[phrase_key], output_path=path)
# #     return path


# # def text_to_speech(text: str, output_path: str = "response.wav") -> str:
# #     response = sarvam_client.text_to_speech.convert(
# #         model="bulbul:v3",
# #         text=text,
# #         target_language_code=SARVAM_TARGET_LANGUAGE,
# #         speaker=SARVAM_SPEAKER,
# #     )
# #     audio_bytes = base64.b64decode(response.audios[0])
# #     with open(output_path, "wb") as f:
# #         f.write(audio_bytes)
# #     return output_path


# # def play_audio(path: str) -> None:
# #     """Best-effort local playback for testing. Falls back to just printing the path."""
# #     try:
# #         if sys.platform == "darwin":
# #             os.system(f"afplay '{path}'")
# #         elif sys.platform.startswith("linux"):
# #             os.system(f"mpg123 -q '{path}' 2>/dev/null || ffplay -nodisp -autoexit -loglevel quiet '{path}'")
# #         elif sys.platform.startswith("win"):
# #             os.startfile(path)  # noqa: S606
# #     except Exception:
# #         pass


# # def run_pipeline(user_question: str) -> None:
# #     print(f"\nCaller asked: {user_question}")

# #     # 1. Instant acknowledgment — pre-cached, so this plays with ~0 latency
# #     t0 = time.time()
# #     filler_path = get_or_create_filler("checking")
# #     print(f"[{time.time() - t0:.2f}s] Playing filler: \"{FILLER_PHRASES['checking']}\"")
# #     play_audio(filler_path)

# #     # 2. KB lookup + reasoning happen while/after the filler plays
# #     kb_result = search_knowledge_base(user_question)
# #     kb_answer = kb_result.get("answer", "")
# #     kb_confidence = kb_result.get("confidence")
# #     print(f"[{time.time() - t0:.2f}s] KB confidence: {kb_confidence}")

# #     spoken_answer = ask_gpt(user_question, kb_answer, kb_confidence)
# #     print(f"[{time.time() - t0:.2f}s] Agent will say: {spoken_answer}")

# #     # 3. Convert final answer to speech and play it
# #     audio_file = text_to_speech(spoken_answer, output_path="response.wav")
# #     print(f"[{time.time() - t0:.2f}s] Response ready: {audio_file}")
# #     play_audio(audio_file)


# # if __name__ == "__main__":
# #     gpt_backend = f"Azure OpenAI ({AZURE_OPENAI_DEPLOYMENT})" if USE_AZURE_OPENAI else "OpenAI (gpt-4o-mini)"
# #     print(f"Using GPT backend: {gpt_backend}")
# #     print(f"Using Sarvam AI voice: speaker='{SARVAM_SPEAKER}', language='{SARVAM_TARGET_LANGUAGE}'")

# #     if len(sys.argv) > 1:
# #         audio_path = sys.argv[1]
# #         print(f"\nTranscribing audio file: {audio_path}")
# #         transcript = transcribe_audio(audio_path)
# #         print(f"Caller said: {transcript}")
# #         run_pipeline(transcript)
# #     else:
# #         print("\nType a question and press Enter (or 'quit' to exit).")
# #         while True:
# #             question = input("\nYou: ").strip()
# #             if question.lower() in {"quit", "exit"}:
# #                 break
# #             if question:
# #                 run_pipeline(question)

# """
# Voice helpdesk pipeline — pilot version (no telephony yet)
# ------------------------------------------------------------
# Flow: caller audio (Deepgram STT) or typed text -> instant cached filler audio
#       -> veelead-rag KB lookup -> GPT-4o-mini rephrases the answer for speech
#       -> Sarvam AI TTS -> wav

# Once Twilio is set up, swap the file-based Deepgram call for their
# streaming transcript endpoint and this same core logic stays the same —
# the filler still plays the instant STT detects end-of-speech, while the
# KB+GPT+TTS chain runs in the background.

# SETUP:
#   pip install openai requests python-dotenv sarvamai

#   Create a .env file (never commit this) with either:
#     OPENAI_API_KEY=sk-...
#   or (to use Azure OpenAI instead):
#     GPT_ENDPOINT=https://<your-resource>.openai.azure.com/
#     GPT_API_KEY=...
#     GPT_API_VER=2024-12-01-preview
#     GPT_MINI_DEPLOY=gpt-4o-mini
#   plus, either way:
#     SARVAM_API_KEY=...
#     SARVAM_SPEAKER=anand                         # see docs.sarvam.ai for the full bulbul:v3 speaker list
#     SARVAM_TARGET_LANGUAGE=en-IN
#     VEELEAD_API_KEY=...                          # rotate the one shared in chat before using this
#     DEEPGRAM_API_KEY=...                         # only needed for audio-file input

# USAGE:
#   python voice_helpdesk_pipeline.py question.mp3   # transcribes the file, runs it once, exits
#   python voice_helpdesk_pipeline.py                # interactive typed-text loop
# """

# import base64
# import os
# import re
# import sys
# import time
# import requests
# from openai import OpenAI, AzureOpenAI
# from sarvamai import SarvamAI
# from dotenv import load_dotenv

# load_dotenv()

# VEELEAD_URL = "https://veelead-rag.southeastasia.cloudapp.azure.com/search.json"
# VEELEAD_API_KEY = os.environ.get("VEELEAD_API_KEY")
# OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
# DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY")
# SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY")
# SARVAM_SPEAKER = os.environ.get("SARVAM_SPEAKER", "anand")
# SARVAM_TARGET_LANGUAGE = os.environ.get("SARVAM_TARGET_LANGUAGE", "en-IN")

# AZURE_OPENAI_ENDPOINT = os.environ.get("GPT_ENDPOINT")
# AZURE_OPENAI_API_KEY = os.environ.get("GPT_API_KEY")
# AZURE_OPENAI_API_VERSION = os.environ.get("GPT_API_VER", "2024-12-01-preview")
# AZURE_OPENAI_DEPLOYMENT = os.environ.get("GPT_MINI_DEPLOY", "gpt-4o-mini")
# USE_AZURE_OPENAI = bool(AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY)

# REQUIRED = {
#     "VEELEAD_API_KEY": VEELEAD_API_KEY,
#     "SARVAM_API_KEY": SARVAM_API_KEY,
# }
# if not USE_AZURE_OPENAI:
#     REQUIRED["OPENAI_API_KEY"] = OPENAI_API_KEY
# missing = [k for k, v in REQUIRED.items() if not v]
# if missing:
#     sys.exit(f"Missing required environment variables: {', '.join(missing)}. Set them in your .env file.")

# if USE_AZURE_OPENAI:
#     client = AzureOpenAI(
#         api_key=AZURE_OPENAI_API_KEY,
#         azure_endpoint=AZURE_OPENAI_ENDPOINT,
#         api_version=AZURE_OPENAI_API_VERSION,
#     )
#     GPT_MODEL = AZURE_OPENAI_DEPLOYMENT
# else:
#     client = OpenAI(api_key=OPENAI_API_KEY)
#     GPT_MODEL = "gpt-4o-mini"

# sarvam_client = SarvamAI(api_subscription_key=SARVAM_API_KEY, timeout=30)


# def strip_markdown_for_speech(text: str) -> str:
#     """Remove markdown/emoji artifacts so TTS doesn't try to speak them literally."""
#     text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)          # **bold**
#     text = re.sub(r"[#*_`]", "", text)                     # leftover markdown chars
#     text = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", text)  # emoji ranges
#     text = re.sub(r"\n{2,}", ". ", text)
#     text = re.sub(r"\n", " ", text)
#     text = re.sub(r"\s{2,}", " ", text)
#     return text.strip()


# AUDIO_CONTENT_TYPES = {
#     ".mp3": "audio/mpeg",
#     ".wav": "audio/wav",
#     ".m4a": "audio/mp4",
#     ".ogg": "audio/ogg",
#     ".webm": "audio/webm",
# }


# def transcribe_audio(file_path: str) -> str:
#     """Send an audio file to Deepgram and return the transcript text."""
#     if not DEEPGRAM_API_KEY:
#         raise RuntimeError("Missing DEEPGRAM_API_KEY in .env — required for audio-file input.")

#     ext = os.path.splitext(file_path)[1].lower()
#     content_type = AUDIO_CONTENT_TYPES.get(ext, "audio/mpeg")

#     with open(file_path, "rb") as audio_file:
#         resp = requests.post(
#             "https://api.deepgram.com/v1/listen",
#             headers={
#                 "Authorization": f"Token {DEEPGRAM_API_KEY}",
#                 "Content-Type": content_type,
#             },
#             params={"model": "nova-2", "smart_format": "true", "punctuate": "true"},
#             data=audio_file,
#             timeout=30,
#         )
#     resp.raise_for_status()
#     return resp.json()["results"]["channels"][0]["alternatives"][0]["transcript"]


# def search_knowledge_base(query: str, previous: list[str] | None = None) -> dict:
#     """Query the veelead-rag helpdesk knowledge base for grounding context.

#     `previous` is up to the last 5 user questions in the call (oldest first) -
#     the API uses it to disambiguate follow-ups like "I tried that, still broken".

#     The KB has been observed taking ~10s on its own on a normal query, so a
#     10s client timeout was right on the edge and would intermittently trip on
#     nothing but normal variance. Retries once on timeout/connection errors
#     before giving up, since those are usually transient.
#     """
#     headers = {"x-api-key": VEELEAD_API_KEY}
#     params = {"q": query}
#     if previous:
#         params["previous"] = previous[-5:]

#     last_exc = None
#     for _ in range(2):
#         try:
#             resp = requests.get(VEELEAD_URL, headers=headers, params=params, timeout=20)
#             resp.raise_for_status()
#             return resp.json()
#         except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
#             last_exc = exc
#     raise last_exc


# def ask_gpt(question: str, kb_answer: str, history: list[dict] | None = None) -> str:
#     """Rephrase the raw KB answer into a short, natural, professional spoken response.

#     `history` is up to the last few (question, answer) exchanges *from this call*
#     (oldest first). Without this, GPT has no idea it already gave this same
#     advice and will repeat it verbatim when the caller says "I tried that."
#     """
#     clean_answer = strip_markdown_for_speech(kb_answer)

#     system_prompt = (
#         "You are a professional voice support agent speaking out loud to a caller "
#         "on a phone call. You are given the correct answer from the knowledge base "
#         "in written form, plus what has already been said earlier in this same call. "
#         "Rephrase the knowledge base answer as if you were personally explaining it, "
#         "in a natural, warm, professional tone. Keep it concise — 2 to 4 short "
#         "sentences, spoken style, no lists, no headers, no markdown, no emojis. "
#         "Do not add information that isn't in the source answer.\n\n"
#         "If the caller indicates they already tried what was suggested earlier in "
#         "this call and it didn't work, do NOT repeat the same instructions again. "
#         "Acknowledge that it didn't help. If the knowledge base answer doesn't offer "
#         "anything new beyond what's already been said, say you'll connect them with "
#         "a human teammate instead of repeating yourself or guessing.\n\n"
#         "If the source answer doesn't actually address the question at all, say you "
#         "don't have that information yet and suggest they reach out to the relevant "
#         "department directly, instead of guessing."
#     )

#     history_block = ""
#     if history:
#         lines = []
#         for turn in history[-4:]:
#             lines.append(f"Caller: {turn.get('question', '')}")
#             lines.append(f"You already said: {turn.get('answer', '')}")
#         history_block = "Earlier in this call:\n" + "\n".join(lines) + "\n\n"

#     user_content = (
#         f"{history_block}"
#         f"Caller's current question: {question}\n\n"
#         f"Knowledge base answer:\n{clean_answer}"
#     )

#     completion = client.chat.completions.create(
#         model=GPT_MODEL,
#         messages=[
#             {"role": "system", "content": system_prompt},
#             {"role": "user", "content": user_content},
#         ],
#         temperature=0.4,
#         timeout=20,
#     )
#     return completion.choices[0].message.content.strip()


# FILLER_PHRASES = {
#     "greeting": "Hi, this is your support assistant. How may I help you today?",
#     "checking": "Okay, let me look into that for you.",
#     "one_moment": "One moment please, I'm looking that up.",
# }
# FILLER_DIR = "filler_cache"


# def get_or_create_filler(phrase_key: str) -> str:
#     """Generate a filler phrase once and cache it — reused on every call so the
#     caller hears an instant acknowledgment with zero generation latency."""
#     os.makedirs(FILLER_DIR, exist_ok=True)
#     path = os.path.join(FILLER_DIR, f"{phrase_key}.wav")
#     if not os.path.exists(path):
#         text_to_speech(FILLER_PHRASES[phrase_key], output_path=path)
#     return path


# def text_to_speech(text: str, output_path: str = "response.wav") -> str:
#     response = sarvam_client.text_to_speech.convert(
#         model="bulbul:v3",
#         text=text,
#         target_language_code=SARVAM_TARGET_LANGUAGE,
#         speaker=SARVAM_SPEAKER,
#     )
#     audio_bytes = base64.b64decode(response.audios[0])
#     with open(output_path, "wb") as f:
#         f.write(audio_bytes)
#     return output_path


# def play_audio(path: str) -> None:
#     """Best-effort local playback for testing. Falls back to just printing the path."""
#     try:
#         if sys.platform == "darwin":
#             os.system(f"afplay '{path}'")
#         elif sys.platform.startswith("linux"):
#             os.system(f"mpg123 -q '{path}' 2>/dev/null || ffplay -nodisp -autoexit -loglevel quiet '{path}'")
#         elif sys.platform.startswith("win"):
#             os.startfile(path)  # noqa: S606
#     except Exception:
#         pass


# def run_pipeline(user_question: str, history: list[dict] | None = None) -> str:
#     print(f"\nCaller asked: {user_question}")

#     # 1. Instant acknowledgment — pre-cached, so this plays with ~0 latency
#     t0 = time.time()
#     filler_path = get_or_create_filler("checking")
#     print(f"[{time.time() - t0:.2f}s] Playing filler: \"{FILLER_PHRASES['checking']}\"")
#     play_audio(filler_path)

#     # 2. KB lookup + reasoning happen while/after the filler plays
#     kb_result = search_knowledge_base(user_question, previous=[h["question"] for h in (history or [])])
#     kb_answer = kb_result.get("answer", "")
#     print(f"[{time.time() - t0:.2f}s] KB confidence: {kb_result.get('confidence')}")

#     spoken_answer = ask_gpt(user_question, kb_answer, history=history)
#     print(f"[{time.time() - t0:.2f}s] Agent will say: {spoken_answer}")

#     # 3. Convert final answer to speech and play it
#     audio_file = text_to_speech(spoken_answer, output_path="response.wav")
#     print(f"[{time.time() - t0:.2f}s] Response ready: {audio_file}")
#     play_audio(audio_file)
#     return spoken_answer


# if __name__ == "__main__":
#     gpt_backend = f"Azure OpenAI ({AZURE_OPENAI_DEPLOYMENT})" if USE_AZURE_OPENAI else "OpenAI (gpt-4o-mini)"
#     print(f"Using GPT backend: {gpt_backend}")
#     print(f"Using Sarvam AI voice: speaker='{SARVAM_SPEAKER}', language='{SARVAM_TARGET_LANGUAGE}'")

#     if len(sys.argv) > 1:
#         audio_path = sys.argv[1]
#         print(f"\nTranscribing audio file: {audio_path}")
#         transcript = transcribe_audio(audio_path)
#         print(f"Caller said: {transcript}")
#         run_pipeline(transcript)
#     else:
#         print("\nType a question and press Enter (or 'quit' to exit).")
#         call_history: list[dict] = []
#         while True:
#             question = input("\nYou: ").strip()
#             if question.lower() in {"quit", "exit"}:
#                 break
#             if question:
#                 answer = run_pipeline(question, history=call_history)
#                 call_history.append({"question": question, "answer": answer})
#                 call_history = call_history[-5:]

"""
Voice helpdesk pipeline — pilot version (no telephony yet)
------------------------------------------------------------
Flow: caller audio (Deepgram STT) or typed text -> instant cached filler audio
      -> veelead-rag KB lookup -> GPT-4o-mini rephrases the answer for speech
      -> Sarvam AI TTS -> wav

Once Twilio is set up, swap the file-based Deepgram call for their
streaming transcript endpoint and this same core logic stays the same —
the filler still plays the instant STT detects end-of-speech, while the
KB+GPT+TTS chain runs in the background.

SETUP:
  pip install openai requests python-dotenv sarvamai

  Create a .env file (never commit this) with either:
    OPENAI_API_KEY=sk-...
  or (to use Azure OpenAI instead):
    GPT_ENDPOINT=https://<your-resource>.openai.azure.com/
    GPT_API_KEY=...
    GPT_API_VER=2024-12-01-preview
    GPT_MINI_DEPLOY=gpt-4o-mini
  plus, either way:
    SARVAM_API_KEY=...
    SARVAM_SPEAKER=anand                         # see docs.sarvam.ai for the full bulbul:v3 speaker list
    SARVAM_TARGET_LANGUAGE=en-IN
    VEELEAD_API_KEY=...                          # rotate the one shared in chat before using this
    DEEPGRAM_API_KEY=...                         # only needed for audio-file input

USAGE:
  python voice_helpdesk_pipeline.py question.mp3   # transcribes the file, runs it once, exits
  python voice_helpdesk_pipeline.py                # interactive typed-text loop
"""

import base64
import os
import re
import sys
import time
import requests
from openai import OpenAI, AzureOpenAI
from sarvamai import SarvamAI
from dotenv import load_dotenv

load_dotenv()

VEELEAD_URL = "https://veelead-rag.southeastasia.cloudapp.azure.com/search.json"
VEELEAD_API_KEY = os.environ.get("VEELEAD_API_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY")
SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY")
SARVAM_SPEAKER = os.environ.get("SARVAM_SPEAKER", "anand")
SARVAM_TARGET_LANGUAGE = os.environ.get("SARVAM_TARGET_LANGUAGE", "en-IN")

AZURE_OPENAI_ENDPOINT = os.environ.get("GPT_ENDPOINT")
AZURE_OPENAI_API_KEY = os.environ.get("GPT_API_KEY")
AZURE_OPENAI_API_VERSION = os.environ.get("GPT_API_VER", "2024-12-01-preview")
AZURE_OPENAI_DEPLOYMENT = os.environ.get("GPT_MINI_DEPLOY", "gpt-4o-mini")
USE_AZURE_OPENAI = bool(AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY)

REQUIRED = {
    "VEELEAD_API_KEY": VEELEAD_API_KEY,
    "SARVAM_API_KEY": SARVAM_API_KEY,
}
if not USE_AZURE_OPENAI:
    REQUIRED["OPENAI_API_KEY"] = OPENAI_API_KEY
missing = [k for k, v in REQUIRED.items() if not v]
if missing:
    sys.exit(f"Missing required environment variables: {', '.join(missing)}. Set them in your .env file.")

if USE_AZURE_OPENAI:
    client = AzureOpenAI(
        api_key=AZURE_OPENAI_API_KEY,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_version=AZURE_OPENAI_API_VERSION,
    )
    GPT_MODEL = AZURE_OPENAI_DEPLOYMENT
else:
    client = OpenAI(api_key=OPENAI_API_KEY)
    GPT_MODEL = "gpt-4o-mini"

sarvam_client = SarvamAI(api_subscription_key=SARVAM_API_KEY, timeout=30)


def strip_markdown_for_speech(text: str) -> str:
    """Remove markdown/emoji artifacts so TTS doesn't try to speak them literally."""
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)          # **bold**
    text = re.sub(r"[#*_`]", "", text)                     # leftover markdown chars
    text = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", text)  # emoji ranges
    text = re.sub(r"\n{2,}", ". ", text)
    text = re.sub(r"\n", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


AUDIO_CONTENT_TYPES = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".webm": "audio/webm",
}


def transcribe_audio(file_path: str) -> str:
    """Send an audio file to Deepgram and return the transcript text."""
    if not DEEPGRAM_API_KEY:
        raise RuntimeError("Missing DEEPGRAM_API_KEY in .env — required for audio-file input.")

    ext = os.path.splitext(file_path)[1].lower()
    content_type = AUDIO_CONTENT_TYPES.get(ext, "audio/mpeg")

    with open(file_path, "rb") as audio_file:
        resp = requests.post(
            "https://api.deepgram.com/v1/listen",
            headers={
                "Authorization": f"Token {DEEPGRAM_API_KEY}",
                "Content-Type": content_type,
            },
            params={"model": "nova-2", "smart_format": "true", "punctuate": "true"},
            data=audio_file,
            timeout=30,
        )
    resp.raise_for_status()
    return resp.json()["results"]["channels"][0]["alternatives"][0]["transcript"]


def search_knowledge_base(query: str, previous: list[str] | None = None) -> dict:
    """Query the veelead-rag helpdesk knowledge base for grounding context.

    `previous` is up to the last 5 user questions in the call (oldest first) -
    the API uses it to disambiguate follow-ups like "I tried that, still broken".

    The KB appears to run its own LLM generation on non-cached queries
    (its responses include "model_used"/"cached" fields), so a cold query can
    genuinely take longer than a simple lookup - hence the longer timeout and
    one retry here rather than failing immediately on the first slow response.
    """
    headers = {"x-api-key": VEELEAD_API_KEY}
    params = {"q": query}
    if previous:
        params["previous"] = previous[-5:]

    last_error = None
    for attempt in range(2):  # one retry - covers transient slowness, not a real outage
        try:
            resp = requests.get(VEELEAD_URL, headers=headers, params=params, timeout=25)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.Timeout as exc:
            last_error = exc
            print(f"KB request timed out (attempt {attempt + 1}/2): {exc}")

    raise last_error


def ask_gpt(question: str, kb_answer: str, history: list[dict] | None = None) -> str:
    """Rephrase the raw KB answer into a short, natural, professional spoken response.

    `history` is up to the last few (question, answer) exchanges *from this call*
    (oldest first). Without this, GPT has no idea it already gave this same
    advice and will repeat it verbatim when the caller says "I tried that."
    """
    clean_answer = strip_markdown_for_speech(kb_answer)

    system_prompt = (
        "You are a professional voice support agent speaking out loud to a caller "
        "on a phone call. You are given the correct answer from the knowledge base "
        "in written form, plus what has already been said earlier in this same call. "
        "Rephrase the knowledge base answer as if you were personally explaining it, "
        "in a natural, warm, professional tone. Keep it concise — 2 to 4 short "
        "sentences, spoken style, no lists, no headers, no markdown, no emojis. "
        "Do not add information that isn't in the source answer.\n\n"
        "If the caller indicates they already tried what was suggested earlier in "
        "this call and it didn't work, do NOT repeat the same instructions again. "
        "Acknowledge that it didn't help. If the knowledge base answer doesn't offer "
        "anything new beyond what's already been said, say you'll connect them with "
        "a human teammate instead of repeating yourself or guessing.\n\n"
        "If the source answer doesn't actually address the question at all, say you "
        "don't have that information yet and suggest they reach out to the relevant "
        "department directly, instead of guessing."
    )

    history_block = ""
    if history:
        lines = []
        for turn in history[-4:]:
            lines.append(f"Caller: {turn.get('question', '')}")
            lines.append(f"You already said: {turn.get('answer', '')}")
        history_block = "Earlier in this call:\n" + "\n".join(lines) + "\n\n"

    user_content = (
        f"{history_block}"
        f"Caller's current question: {question}\n\n"
        f"Knowledge base answer:\n{clean_answer}"
    )

    completion = client.chat.completions.create(
        model=GPT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.4,
        timeout=20,
    )
    return completion.choices[0].message.content.strip()


FILLER_PHRASES = {
    "greeting": "Hi, this is your support assistant. How may I help you today?",
    "checking": "Okay, let me look into that for you.",
    "one_moment": "One moment please, I'm looking that up.",
}
FILLER_DIR = "filler_cache"


def get_or_create_filler(phrase_key: str) -> str:
    """Generate a filler phrase once and cache it — reused on every call so the
    caller hears an instant acknowledgment with zero generation latency."""
    os.makedirs(FILLER_DIR, exist_ok=True)
    path = os.path.join(FILLER_DIR, f"{phrase_key}.wav")
    if not os.path.exists(path):
        text_to_speech(FILLER_PHRASES[phrase_key], output_path=path)
    return path


def text_to_speech(text: str, output_path: str = "response.wav") -> str:
    response = sarvam_client.text_to_speech.convert(
        model="bulbul:v3",
        text=text,
        target_language_code=SARVAM_TARGET_LANGUAGE,
        speaker=SARVAM_SPEAKER,
    )
    audio_bytes = base64.b64decode(response.audios[0])
    with open(output_path, "wb") as f:
        f.write(audio_bytes)
    return output_path


def play_audio(path: str) -> None:
    """Best-effort local playback for testing. Falls back to just printing the path."""
    try:
        if sys.platform == "darwin":
            os.system(f"afplay '{path}'")
        elif sys.platform.startswith("linux"):
            os.system(f"mpg123 -q '{path}' 2>/dev/null || ffplay -nodisp -autoexit -loglevel quiet '{path}'")
        elif sys.platform.startswith("win"):
            os.startfile(path)  # noqa: S606
    except Exception:
        pass


def run_pipeline(user_question: str, history: list[dict] | None = None) -> str:
    print(f"\nCaller asked: {user_question}")

    # 1. Instant acknowledgment — pre-cached, so this plays with ~0 latency
    t0 = time.time()
    filler_path = get_or_create_filler("checking")
    print(f"[{time.time() - t0:.2f}s] Playing filler: \"{FILLER_PHRASES['checking']}\"")
    play_audio(filler_path)

    # 2. KB lookup + reasoning happen while/after the filler plays
    kb_result = search_knowledge_base(user_question, previous=[h["question"] for h in (history or [])])
    kb_answer = kb_result.get("answer", "")
    print(f"[{time.time() - t0:.2f}s] KB confidence: {kb_result.get('confidence')}")

    spoken_answer = ask_gpt(user_question, kb_answer, history=history)
    print(f"[{time.time() - t0:.2f}s] Agent will say: {spoken_answer}")

    # 3. Convert final answer to speech and play it
    audio_file = text_to_speech(spoken_answer, output_path="response.wav")
    print(f"[{time.time() - t0:.2f}s] Response ready: {audio_file}")
    play_audio(audio_file)
    return spoken_answer


if __name__ == "__main__":
    gpt_backend = f"Azure OpenAI ({AZURE_OPENAI_DEPLOYMENT})" if USE_AZURE_OPENAI else "OpenAI (gpt-4o-mini)"
    print(f"Using GPT backend: {gpt_backend}")
    print(f"Using Sarvam AI voice: speaker='{SARVAM_SPEAKER}', language='{SARVAM_TARGET_LANGUAGE}'")

    if len(sys.argv) > 1:
        audio_path = sys.argv[1]
        print(f"\nTranscribing audio file: {audio_path}")
        transcript = transcribe_audio(audio_path)
        print(f"Caller said: {transcript}")
        run_pipeline(transcript)
    else:
        print("\nType a question and press Enter (or 'quit' to exit).")
        call_history: list[dict] = []
        while True:
            question = input("\nYou: ").strip()
            if question.lower() in {"quit", "exit"}:
                break
            if question:
                answer = run_pipeline(question, history=call_history)
                call_history.append({"question": question, "answer": answer})
                call_history = call_history[-5:]