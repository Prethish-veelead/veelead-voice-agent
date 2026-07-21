# # # # """
# # # # Local LLM via Ollama's OpenAI-compatible API - drop-in replacement for the
# # # # OpenAI/Azure OpenAI client in voice_helpdesk_pipeline.py's ask_gpt().

# # # # Key point: this uses the SAME `openai` Python package and the SAME
# # # # client.chat.completions.create() call as the cloud version - only the
# # # # base_url and model name change. Nothing about how you call it is different.

# # # # SETUP (on your machine, not in this sandbox - see note below):
# # # #   1. Install Ollama: https://ollama.com (not a pip package - separate install)
# # # #   2. ollama pull qwen2.5:7b-instruct
# # # #   3. ollama serve   (runs the API at http://localhost:11434/v1 by default)

# # # # I can't run Ollama or pull model weights myself in this sandbox (no access
# # # # to ollama.com from here) - this code is correct against the OpenAI client's
# # # # documented interface, but the first real test of it talking to a live
# # # # Ollama server needs to happen on your machine.
# # # # """

# # # # import os
# # # # import re
# # # # from openai import OpenAI

# # # # LOCAL_LLM_BASE_URL = os.environ.get("LOCAL_LLM_BASE_URL", "http://localhost:11434/v1")
# # # # LOCAL_LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL", "qwen2.5:7b-instruct")

# # # # # api_key is required by the OpenAI client's constructor but unused by Ollama -
# # # # # any non-empty string works.
# # # # client = OpenAI(base_url=LOCAL_LLM_BASE_URL, api_key="ollama")


# # # # def strip_markdown_for_speech(text: str) -> str:
# # # #     """Same cleanup as the cloud version - strip markdown/emoji before it
# # # #     reaches TTS (or, for now, before it's just read as plain text output)."""
# # # #     text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
# # # #     text = re.sub(r"[#*_`]", "", text)
# # # #     text = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", text)
# # # #     text = re.sub(r"\n{2,}", ". ", text)
# # # #     text = re.sub(r"\n", " ", text)
# # # #     text = re.sub(r"\s{2,}", " ", text)
# # # #     return text.strip()


# # # # def ask_local_llm(question: str, kb_answer: str = "", history: list[dict] | None = None) -> str:
# # # #     """Same behavior as ask_gpt() in voice_helpdesk_pipeline.py: grounds the
# # # #     response in the KB answer, and uses call history to avoid repeating
# # # #     advice the caller already said didn't work.

# # # #     BUG FIX: on the first turn (empty history), the model was hallucinating
# # # #     that the caller had "already tried" the KB's troubleshooting steps -
# # # #     apparently confusing "the KB answer contains a list of steps" with "the
# # # #     caller already performed these steps." Smaller models seem more prone to
# # # #     this than GPT-4o-mini was. Fix: branch the prompt explicitly instead of
# # # #     trusting the model to correctly infer "no history = nothing tried yet."
# # # #     """
# # # #     clean_answer = strip_markdown_for_speech(kb_answer) if kb_answer else ""

# # # #     base_prompt = (
# # # #         "You are a professional voice support agent speaking out loud to a caller "
# # # #         "on a phone call. Keep responses concise - 2 to 4 short sentences, spoken "
# # # #         "style, no lists, no headers, no markdown, no emojis. Do not add information "
# # # #         "that isn't in the source answer."
# # # #     )

# # # #     if history:
# # # #         # Turn 2+: the caller may be reporting that earlier advice didn't work.
# # # #         system_prompt = (
# # # #             f"{base_prompt}\n\n"
# # # #             "Below is what has already been said earlier in this call. Only treat "
# # # #             "something as 'already tried' if the caller's current message actually "
# # # #             "says so (e.g. 'that didn't work', 'I tried that', 'still broken'). "
# # # #             "If they do indicate that, do NOT repeat the same instructions again - "
# # # #             "acknowledge it didn't help, and if the knowledge base answer doesn't "
# # # #             "offer anything new, say you'll connect them with a human teammate. "
# # # #             "If the caller's current message is a NEW question or doesn't clearly "
# # # #             "say the earlier advice failed, just answer it normally using the "
# # # #             "knowledge base answer below - do not assume anything was tried."
# # # #         )
# # # #     else:
# # # #         # Turn 1: nothing has been tried yet, full stop. Say this explicitly
# # # #         # rather than trusting the model to infer it from an empty history.
# # # #         system_prompt = (
# # # #             f"{base_prompt}\n\n"
# # # #             "This is the very first message in the call. The caller has NOT tried "
# # # #             "anything yet - there is no prior history. Present the knowledge base "
# # # #             "answer below as fresh guidance for them to try now. Do NOT say or "
# # # #             "imply they've already attempted these steps, and do NOT suggest "
# # # #             "escalating to a human yet - only do that if the source answer doesn't "
# # # #             "address the question at all."
# # # #         )

# # # #     history_block = ""
# # # #     if history:
# # # #         lines = []
# # # #         for turn in history[-4:]:
# # # #             lines.append(f"Caller: {turn.get('question', '')}")
# # # #             lines.append(f"You already said: {turn.get('answer', '')}")
# # # #         history_block = "Earlier in this call:\n" + "\n".join(lines) + "\n\n"

# # # #     if clean_answer:
# # # #         user_content = f"{history_block}Caller's current question: {question}\n\nKnowledge base answer:\n{clean_answer}"
# # # #     else:
# # # #         user_content = f"{history_block}{question}"

# # # #     completion = client.chat.completions.create(
# # # #         model=LOCAL_LLM_MODEL,
# # # #         messages=[
# # # #             {"role": "system", "content": system_prompt},
# # # #             {"role": "user", "content": user_content},
# # # #         ],
# # # #         temperature=0.4,
# # # #         timeout=30,
# # # #     )
# # # #     return completion.choices[0].message.content.strip()


# # # # if __name__ == "__main__":
# # # #     import sys
# # # #     question = " ".join(sys.argv[1:]) or "Hello, can you hear me?"
# # # #     print(f"Asking local LLM: {question}")
# # # #     answer = ask_local_llm(question)
# # # #     print(f"\nAnswer: {answer}")

# # # """
# # # Local LLM via Ollama's OpenAI-compatible API - drop-in replacement for the
# # # OpenAI/Azure OpenAI client in voice_helpdesk_pipeline.py's ask_gpt().

# # # Key point: this uses the SAME `openai` Python package and the SAME
# # # client.chat.completions.create() call as the cloud version - only the
# # # base_url and model name change. Nothing about how you call it is different.

# # # SETUP (on your machine, not in this sandbox - see note below):
# # #   1. Install Ollama: https://ollama.com (not a pip package - separate install)
# # #   2. ollama pull qwen2.5:7b-instruct
# # #   3. ollama serve   (runs the API at http://localhost:11434/v1 by default)

# # # I can't run Ollama or pull model weights myself in this sandbox (no access
# # # to ollama.com from here) - this code is correct against the OpenAI client's
# # # documented interface, but the first real test of it talking to a live
# # # Ollama server needs to happen on your machine.
# # # """

# # # import os
# # # import re
# # # from openai import OpenAI

# # # LOCAL_LLM_BASE_URL = os.environ.get("LOCAL_LLM_BASE_URL", "http://localhost:11434/v1")
# # # LOCAL_LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL", "qwen2.5:7b-instruct")

# # # # api_key is required by the OpenAI client's constructor but unused by Ollama -
# # # # any non-empty string works.
# # # client = OpenAI(base_url=LOCAL_LLM_BASE_URL, api_key="ollama")


# # # def strip_markdown_for_speech(text: str) -> str:
# # #     """Same cleanup as the cloud version - strip markdown/emoji before it
# # #     reaches TTS (or, for now, before it's just read as plain text output)."""
# # #     text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
# # #     text = re.sub(r"[#*_`]", "", text)
# # #     text = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", text)
# # #     text = re.sub(r"\n{2,}", ". ", text)
# # #     text = re.sub(r"\n", " ", text)
# # #     text = re.sub(r"\s{2,}", " ", text)
# # #     return text.strip()


# # # def _build_prompt(question: str, kb_answer: str, history: list[dict] | None) -> tuple[str, str]:
# # #     """Shared between ask_local_llm() and ask_local_llm_stream() - this is
# # #     where the turn-1 hallucination fix and the greeting/smalltalk handling
# # #     live, and both callers need the exact same behavior here."""
# # #     clean_answer = strip_markdown_for_speech(kb_answer) if kb_answer else ""

# # #     base_prompt = (
# # #         "You are a professional voice support agent speaking out loud to a caller "
# # #         "on a phone call. Keep responses concise - 2 to 4 short sentences, spoken "
# # #         "style, no lists, no headers, no markdown, no emojis."
# # #     )

# # #     if clean_answer:
# # #         base_prompt += " Do not add information that isn't in the source answer."
# # #         if history:
# # #             behavior = (
# # #                 "Below is what has already been said earlier in this call. Only treat "
# # #                 "something as 'already tried' if the caller's current message actually "
# # #                 "says so (e.g. 'that didn't work', 'I tried that', 'still broken'). "
# # #                 "If they do indicate that, do NOT repeat the same instructions again - "
# # #                 "acknowledge it didn't help, and if the knowledge base answer doesn't "
# # #                 "offer anything new, say you'll connect them with a human teammate. "
# # #                 "If the caller's current message is a NEW question or doesn't clearly "
# # #                 "say the earlier advice failed, just answer it normally using the "
# # #                 "knowledge base answer below - do not assume anything was tried."
# # #             )
# # #         else:
# # #             behavior = (
# # #                 "This is the very first message in the call. The caller has NOT tried "
# # #                 "anything yet - there is no prior history. Present the knowledge base "
# # #                 "answer below as fresh guidance for them to try now. Do NOT say or "
# # #                 "imply they've already attempted these steps, and do NOT suggest "
# # #                 "escalating to a human yet - only do that if the source answer doesn't "
# # #                 "address the question at all."
# # #             )
# # #     else:
# # #         behavior = (
# # #             "There is no knowledge base match for this message, or the match wasn't "
# # #             "confident enough to use. If the caller's message is just a greeting or "
# # #             "small talk (like 'hi', 'hello', 'thanks', 'ok'), respond warmly and "
# # #             "naturally and ask how you can help - do NOT treat it as a support "
# # #             "question or apologize for lacking information. If it genuinely reads "
# # #             "like a real support question with no matching answer, say you don't "
# # #             "have that information yet and suggest they reach out to the relevant "
# # #             "department directly - do not guess or make up an answer."
# # #         )

# # #     system_prompt = f"{base_prompt}\n\n{behavior}"

# # #     history_block = ""
# # #     if history:
# # #         lines = []
# # #         for turn in history[-4:]:
# # #             lines.append(f"Caller: {turn.get('question', '')}")
# # #             lines.append(f"You already said: {turn.get('answer', '')}")
# # #         history_block = "Earlier in this call:\n" + "\n".join(lines) + "\n\n"

# # #     if clean_answer:
# # #         user_content = f"{history_block}Caller's current question: {question}\n\nKnowledge base answer:\n{clean_answer}"
# # #     else:
# # #         user_content = f"{history_block}Caller's message: {question}"

# # #     return system_prompt, user_content


# # # def ask_local_llm(question: str, kb_answer: str = "", history: list[dict] | None = None) -> str:
# # #     """Non-streaming version - waits for the full response. Kept for the CLI
# # #     test scripts; local_web_demo.py uses ask_local_llm_stream() instead so
# # #     TTS can start on sentence 1 before the LLM finishes generating the rest.
# # #     """
# # #     system_prompt, user_content = _build_prompt(question, kb_answer, history)

# # #     completion = client.chat.completions.create(
# # #         model=LOCAL_LLM_MODEL,
# # #         messages=[
# # #             {"role": "system", "content": system_prompt},
# # #             {"role": "user", "content": user_content},
# # #         ],
# # #         temperature=0.4,
# # #         timeout=30,
# # #     )
# # #     return completion.choices[0].message.content.strip()


# # # # Common abbreviations that end in a period but AREN'T a sentence boundary -
# # # # without this guard, "Mr. Smith" or "e.g." would get cut mid-phrase, exactly
# # # # the failure mode your lead's document warned about for the Response
# # # # Coordinator layer.
# # # _ABBREVIATIONS = {"mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "vs.", "etc.", "e.g.", "i.e.", "no."}
# # # _SENTENCE_END_RE = re.compile(r"[.!?]+(\s+|$)")


# # # class SentenceChunker:
# # #     """Buffers streamed tokens and yields complete sentences as soon as
# # #     they're detected - a simple heuristic version of "linguistic chunking",
# # #     not a full parser. Good enough to avoid the worst failure mode
# # #     (abbreviations), not guaranteed perfect on every edge case.
# # #     """

# # #     def __init__(self, min_chars: int = 15):
# # #         self.buffer = ""
# # #         self.min_chars = min_chars

# # #     def feed(self, token: str) -> list[str]:
# # #         self.buffer += token
# # #         sentences = []
# # #         search_start = 0
# # #         while True:
# # #             match = _SENTENCE_END_RE.search(self.buffer, search_start)
# # #             if not match:
# # #                 break
# # #             end = match.end()
# # #             candidate = self.buffer[:end].strip()
# # #             words = candidate.split()
# # #             last_word = words[-1].lower() if words else ""
# # #             if last_word in _ABBREVIATIONS or len(candidate) < self.min_chars:
# # #                 # Not a real boundary - keep searching FURTHER in the same
# # #                 # buffer instead of giving up entirely (this was the bug:
# # #                 # the first version bailed out of the whole loop here,
# # #                 # meaning a genuine sentence boundary later in the same
# # #                 # buffer never got found either).
# # #                 search_start = end
# # #                 continue
# # #             sentences.append(candidate)
# # #             self.buffer = self.buffer[end:].lstrip()
# # #             search_start = 0
# # #         return sentences

# # #     def flush(self) -> str:
# # #         remaining = self.buffer.strip()
# # #         self.buffer = ""
# # #         return remaining


# # # def ask_local_llm_stream(question: str, kb_answer: str = "", history: list[dict] | None = None):
# # #     """Streams the LLM's response token by token and yields complete
# # #     sentences as soon as they're detected - this is what lets the caller
# # #     start hearing sentence 1 while the LLM is still generating sentence 3.

# # #     NOTE: I can't verify streaming behavior against a live Ollama server from
# # #     this sandbox - the chunk.choices[0].delta.content access pattern below is
# # #     the standard OpenAI-compatible streaming shape, but confirm it works
# # #     against your actual Ollama server as the first real test of this.
# # #     """
# # #     system_prompt, user_content = _build_prompt(question, kb_answer, history)

# # #     stream = client.chat.completions.create(
# # #         model=LOCAL_LLM_MODEL,
# # #         messages=[
# # #             {"role": "system", "content": system_prompt},
# # #             {"role": "user", "content": user_content},
# # #         ],
# # #         temperature=0.4,
# # #         timeout=60,
# # #         stream=True,
# # #     )

# # #     chunker = SentenceChunker()
# # #     for chunk in stream:
# # #         delta = chunk.choices[0].delta.content or ""
# # #         if not delta:
# # #             continue
# # #         for sentence in chunker.feed(delta):
# # #             yield sentence

# # #     remaining = chunker.flush()
# # #     if remaining:
# # #         yield remaining


# # # if __name__ == "__main__":
# # #     import sys
# # #     question = " ".join(sys.argv[1:]) or "Hello, can you hear me?"
# # #     print(f"Asking local LLM (streaming): {question}")
# # #     for sentence in ask_local_llm_stream(question):
# # #         print(f"  chunk: {sentence}")

# # """
# # Local LLM via Ollama's OpenAI-compatible API - drop-in replacement for the
# # OpenAI/Azure OpenAI client in voice_helpdesk_pipeline.py's ask_gpt().

# # Key point: this uses the SAME `openai` Python package and the SAME
# # client.chat.completions.create() call as the cloud version - only the
# # base_url and model name change. Nothing about how you call it is different.

# # SETUP (on your machine, not in this sandbox - see note below):
# #   1. Install Ollama: https://ollama.com (not a pip package - separate install)
# #   2. ollama pull qwen2.5:7b-instruct
# #   3. ollama serve   (runs the API at http://localhost:11434/v1 by default)

# # I can't run Ollama or pull model weights myself in this sandbox (no access
# # to ollama.com from here) - this code is correct against the OpenAI client's
# # documented interface, but the first real test of it talking to a live
# # Ollama server needs to happen on your machine.
# # """

# # import os
# # import re
# # from openai import OpenAI

# # LOCAL_LLM_BASE_URL = os.environ.get("LOCAL_LLM_BASE_URL", "http://localhost:11434/v1")
# # LOCAL_LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL", "qwen2.5:7b-instruct")

# # # api_key is required by the OpenAI client's constructor but unused by Ollama -
# # # any non-empty string works.
# # client = OpenAI(base_url=LOCAL_LLM_BASE_URL, api_key="ollama")


# # def strip_markdown_for_speech(text: str) -> str:
# #     """Same cleanup as the cloud version - strip markdown/emoji before it
# #     reaches TTS (or, for now, before it's just read as plain text output)."""
# #     text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
# #     text = re.sub(r"[#*_`]", "", text)
# #     text = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", text)
# #     text = re.sub(r"\n{2,}", ". ", text)
# #     text = re.sub(r"\n", " ", text)
# #     text = re.sub(r"\s{2,}", " ", text)
# #     return text.strip()


# # def _build_prompt(question: str, kb_answer: str, history: list[dict] | None) -> tuple[str, str]:
# #     """Shared between ask_local_llm() and ask_local_llm_stream() - this is
# #     where the turn-1 hallucination fix and the greeting/smalltalk handling
# #     live, and both callers need the exact same behavior here."""
# #     clean_answer = strip_markdown_for_speech(kb_answer) if kb_answer else ""

# #     base_prompt = (
# #         "You are a professional voice support agent speaking out loud to a caller "
# #         "on a phone call. Keep responses concise - 2 to 4 short sentences, spoken "
# #         "style, no lists, no headers, no markdown, no emojis."
# #     )

# #     if clean_answer:
# #         base_prompt += " Do not add information that isn't in the source answer."
# #         if history:
# #             behavior = (
# #                 "Below is what has already been said earlier in this call. Only treat "
# #                 "something as 'already tried' if the caller's current message actually "
# #                 "says so (e.g. 'that didn't work', 'I tried that', 'still broken'). "
# #                 "If they do indicate that, do NOT repeat the same instructions again - "
# #                 "acknowledge it didn't help, and if the knowledge base answer doesn't "
# #                 "offer anything new, say you'll connect them with a human teammate. "
# #                 "If the caller's current message is a NEW question or doesn't clearly "
# #                 "say the earlier advice failed, just answer it normally using the "
# #                 "knowledge base answer below - do not assume anything was tried."
# #             )
# #         else:
# #             behavior = (
# #                 "This is the very first message in the call. The caller has NOT tried "
# #                 "anything yet - there is no prior history. Present the knowledge base "
# #                 "answer below as fresh guidance for them to try now. Do NOT say or "
# #                 "imply they've already attempted these steps, and do NOT suggest "
# #                 "escalating to a human yet - only do that if the source answer doesn't "
# #                 "address the question at all."
# #             )
# #     else:
# #         behavior = (
# #             "There is no knowledge base match for this message, or the match wasn't "
# #             "confident enough to use. Figure out which of these three situations "
# #             "applies, based ONLY on the caller's current message - not on anything "
# #             "discussed earlier in this call:\n\n"
# #             "1. Greeting or small talk (like 'hi', 'hello', 'thanks', 'ok') - "
# #             "respond warmly and naturally, ask how you can help.\n\n"
# #             "2. Off-topic or unrelated to workplace IT/HR support (general knowledge, "
# #             "weather, jokes, personal chit-chat) - politely explain you're a "
# #             "workplace support assistant and aren't able to help with that, then ask "
# #             "if there's a work-related issue you can help with instead. A new "
# #             "off-topic question is NOT related to a previous support issue in this "
# #             "call - do not reference or connect it back to anything discussed "
# #             "earlier, even if history is provided below.\n\n"
# #             "3. A genuine support question with no matching KB answer - say you "
# #             "don't have that information yet and suggest reaching out to the "
# #             "relevant department directly. Do not guess or make up an answer."
# #         )

# #     system_prompt = f"{base_prompt}\n\n{behavior}"

# #     history_block = ""
# #     if history:
# #         lines = []
# #         for turn in history[-4:]:
# #             lines.append(f"Caller: {turn.get('question', '')}")
# #             lines.append(f"You already said: {turn.get('answer', '')}")
# #         history_block = "Earlier in this call:\n" + "\n".join(lines) + "\n\n"

# #     if clean_answer:
# #         user_content = f"{history_block}Caller's current question: {question}\n\nKnowledge base answer:\n{clean_answer}"
# #     else:
# #         user_content = f"{history_block}Caller's message: {question}"

# #     return system_prompt, user_content


# # def ask_local_llm(question: str, kb_answer: str = "", history: list[dict] | None = None) -> str:
# #     """Non-streaming version - waits for the full response. Kept for the CLI
# #     test scripts; local_web_demo.py uses ask_local_llm_stream() instead so
# #     TTS can start on sentence 1 before the LLM finishes generating the rest.
# #     """
# #     system_prompt, user_content = _build_prompt(question, kb_answer, history)

# #     completion = client.chat.completions.create(
# #         model=LOCAL_LLM_MODEL,
# #         messages=[
# #             {"role": "system", "content": system_prompt},
# #             {"role": "user", "content": user_content},
# #         ],
# #         temperature=0.4,
# #         timeout=30,
# #     )
# #     return completion.choices[0].message.content.strip()


# # # Common abbreviations that end in a period but AREN'T a sentence boundary -
# # # without this guard, "Mr. Smith" or "e.g." would get cut mid-phrase, exactly
# # # the failure mode your lead's document warned about for the Response
# # # Coordinator layer.
# # _ABBREVIATIONS = {"mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "vs.", "etc.", "e.g.", "i.e.", "no."}
# # _SENTENCE_END_RE = re.compile(r"[.!?]+(\s+|$)")


# # class SentenceChunker:
# #     """Buffers streamed tokens and yields complete sentences as soon as
# #     they're detected - a simple heuristic version of "linguistic chunking",
# #     not a full parser. Good enough to avoid the worst failure mode
# #     (abbreviations), not guaranteed perfect on every edge case.
# #     """

# #     def __init__(self, min_chars: int = 15):
# #         self.buffer = ""
# #         self.min_chars = min_chars

# #     def feed(self, token: str) -> list[str]:
# #         self.buffer += token
# #         sentences = []
# #         search_start = 0
# #         while True:
# #             match = _SENTENCE_END_RE.search(self.buffer, search_start)
# #             if not match:
# #                 break
# #             end = match.end()
# #             candidate = self.buffer[:end].strip()
# #             words = candidate.split()
# #             last_word = words[-1].lower() if words else ""
# #             if last_word in _ABBREVIATIONS or len(candidate) < self.min_chars:
# #                 # Not a real boundary - keep searching FURTHER in the same
# #                 # buffer instead of giving up entirely (this was the bug:
# #                 # the first version bailed out of the whole loop here,
# #                 # meaning a genuine sentence boundary later in the same
# #                 # buffer never got found either).
# #                 search_start = end
# #                 continue
# #             sentences.append(candidate)
# #             self.buffer = self.buffer[end:].lstrip()
# #             search_start = 0
# #         return sentences

# #     def flush(self) -> str:
# #         remaining = self.buffer.strip()
# #         self.buffer = ""
# #         return remaining


# # def ask_local_llm_stream(question: str, kb_answer: str = "", history: list[dict] | None = None):
# #     """Streams the LLM's response token by token and yields complete
# #     sentences as soon as they're detected - this is what lets the caller
# #     start hearing sentence 1 while the LLM is still generating sentence 3.

# #     NOTE: I can't verify streaming behavior against a live Ollama server from
# #     this sandbox - the chunk.choices[0].delta.content access pattern below is
# #     the standard OpenAI-compatible streaming shape, but confirm it works
# #     against your actual Ollama server as the first real test of this.
# #     """
# #     system_prompt, user_content = _build_prompt(question, kb_answer, history)

# #     stream = client.chat.completions.create(
# #         model=LOCAL_LLM_MODEL,
# #         messages=[
# #             {"role": "system", "content": system_prompt},
# #             {"role": "user", "content": user_content},
# #         ],
# #         temperature=0.4,
# #         timeout=60,
# #         stream=True,
# #     )

# #     chunker = SentenceChunker()
# #     for chunk in stream:
# #         delta = chunk.choices[0].delta.content or ""
# #         if not delta:
# #             continue
# #         for sentence in chunker.feed(delta):
# #             yield sentence

# #     remaining = chunker.flush()
# #     if remaining:
# #         yield remaining


# # if __name__ == "__main__":
# #     import sys
# #     question = " ".join(sys.argv[1:]) or "Hello, can you hear me?"
# #     print(f"Asking local LLM (streaming): {question}")
# #     for sentence in ask_local_llm_stream(question):
# #         print(f"  chunk: {sentence}")

# """
# Local LLM via Ollama's OpenAI-compatible API - drop-in replacement for the
# OpenAI/Azure OpenAI client in voice_helpdesk_pipeline.py's ask_gpt().

# Key point: this uses the SAME `openai` Python package and the SAME
# client.chat.completions.create() call as the cloud version - only the
# base_url and model name change. Nothing about how you call it is different.

# SETUP (on your machine, not in this sandbox - see note below):
#   1. Install Ollama: https://ollama.com (not a pip package - separate install)
#   2. ollama pull qwen2.5:7b-instruct
#   3. ollama serve   (runs the API at http://localhost:11434/v1 by default)

# I can't run Ollama or pull model weights myself in this sandbox (no access
# to ollama.com from here) - this code is correct against the OpenAI client's
# documented interface, but the first real test of it talking to a live
# Ollama server needs to happen on your machine.
# """

# import os
# import re
# from openai import OpenAI

# LOCAL_LLM_BASE_URL = os.environ.get("LOCAL_LLM_BASE_URL", "http://localhost:11434/v1")
# LOCAL_LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL", "qwen2.5:7b-instruct")

# # api_key is required by the OpenAI client's constructor but unused by Ollama -
# # any non-empty string works.
# client = OpenAI(base_url=LOCAL_LLM_BASE_URL, api_key="ollama")


# def strip_markdown_for_speech(text: str) -> str:
#     """Same cleanup as the cloud version - strip markdown/emoji before it
#     reaches TTS (or, for now, before it's just read as plain text output)."""
#     text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
#     text = re.sub(r"[#*_`]", "", text)
#     text = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", text)
#     text = re.sub(r"\n{2,}", ". ", text)
#     text = re.sub(r"\n", " ", text)
#     text = re.sub(r"\s{2,}", " ", text)
#     return text.strip()


# def _build_prompt(question: str, kb_answer: str, history: list[dict] | None) -> tuple[str, str]:
#     """Shared between ask_local_llm() and ask_local_llm_stream() - this is
#     where the turn-1 hallucination fix and the greeting/smalltalk handling
#     live, and both callers need the exact same behavior here."""
#     clean_answer = strip_markdown_for_speech(kb_answer) if kb_answer else ""

#     base_prompt = (
#         "You are a professional voice support agent speaking out loud to a caller "
#         "on a phone call. Keep responses concise - 2 to 4 short sentences, spoken "
#         "style, no lists, no headers, no markdown, no emojis."
#     )

#     if history:
#         base_prompt += (
#             " This is a continuing call, not the first turn - you already greeted "
#             "the caller earlier. Do NOT open with a greeting or thank-you like "
#             "'Hello, thank you for reaching out' - jump straight into the answer."
#         )

#     if clean_answer:
#         base_prompt += " Do not add information that isn't in the source answer."
#         if history:
#             behavior = (
#                 "Below is what has already been said earlier in this call. FIRST, "
#                 "check whether the caller's CURRENT question is about the SAME issue "
#                 "as what's in the history below, or a genuinely DIFFERENT topic. If "
#                 "it's a different topic (e.g. history is about a mic problem and the "
#                 "current question is about leave days), treat it as a completely "
#                 "fresh question - answer it normally using the knowledge base answer "
#                 "below, and do NOT mention connecting to a human or reference the "
#                 "earlier issue at all. Only if the CURRENT question is about the SAME "
#                 "issue as history, AND the caller's current message actually says the "
#                 "earlier advice didn't work (e.g. 'that didn't work', 'I tried that', "
#                 "'still broken'), should you acknowledge it didn't help and consider "
#                 "saying you'll connect them with a human teammate if the knowledge "
#                 "base answer doesn't offer anything new. Never escalate or mention a "
#                 "human teammate just because history contains a different, unrelated "
#                 "issue."
#             )
#         else:
#             behavior = (
#                 "This is the very first message in the call. The caller has NOT tried "
#                 "anything yet - there is no prior history. Present the knowledge base "
#                 "answer below as fresh guidance for them to try now. Do NOT say or "
#                 "imply they've already attempted these steps, and do NOT suggest "
#                 "escalating to a human yet - only do that if the source answer doesn't "
#                 "address the question at all."
#             )
#     else:
#         behavior = (
#             "There is no knowledge base match for this message, or the match wasn't "
#             "confident enough to use. Figure out which of these three situations "
#             "applies, based ONLY on the caller's current message - not on anything "
#             "discussed earlier in this call:\n\n"
#             "1. Greeting or small talk (like 'hi', 'hello', 'thanks', 'ok') - "
#             "respond warmly and naturally, ask how you can help.\n\n"
#             "2. Off-topic or unrelated to workplace IT/HR support (general knowledge, "
#             "weather, jokes, personal chit-chat) - politely explain you're a "
#             "workplace support assistant and aren't able to help with that, then ask "
#             "if there's a work-related issue you can help with instead. A new "
#             "off-topic question is NOT related to a previous support issue in this "
#             "call - do not reference or connect it back to anything discussed "
#             "earlier, even if history is provided below.\n\n"
#             "3. A genuine support question with no matching KB answer - say you "
#             "don't have that information yet and suggest reaching out to the "
#             "relevant department directly. Do not guess or make up an answer."
#         )

#     system_prompt = f"{base_prompt}\n\n{behavior}"

#     history_block = ""
#     if history:
#         lines = []
#         for turn in history[-4:]:
#             lines.append(f"Caller: {turn.get('question', '')}")
#             lines.append(f"You already said: {turn.get('answer', '')}")
#         history_block = "Earlier in this call:\n" + "\n".join(lines) + "\n\n"

#     if clean_answer:
#         user_content = f"{history_block}Caller's current question: {question}\n\nKnowledge base answer:\n{clean_answer}"
#     else:
#         user_content = f"{history_block}Caller's message: {question}"

#     return system_prompt, user_content


# def ask_local_llm(question: str, kb_answer: str = "", history: list[dict] | None = None) -> str:
#     """Non-streaming version - waits for the full response. Kept for the CLI
#     test scripts; local_web_demo.py uses ask_local_llm_stream() instead so
#     TTS can start on sentence 1 before the LLM finishes generating the rest.
#     """
#     system_prompt, user_content = _build_prompt(question, kb_answer, history)

#     completion = client.chat.completions.create(
#         model=LOCAL_LLM_MODEL,
#         messages=[
#             {"role": "system", "content": system_prompt},
#             {"role": "user", "content": user_content},
#         ],
#         temperature=0.4,
#         timeout=30,
#     )
#     return completion.choices[0].message.content.strip()


# # Common abbreviations that end in a period but AREN'T a sentence boundary -
# # without this guard, "Mr. Smith" or "e.g." would get cut mid-phrase, exactly
# # the failure mode your lead's document warned about for the Response
# # Coordinator layer.
# _ABBREVIATIONS = {"mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "vs.", "etc.", "e.g.", "i.e.", "no."}
# _SENTENCE_END_RE = re.compile(r"[.!?]+(\s+|$)")


# class SentenceChunker:
#     """Buffers streamed tokens and yields complete sentences as soon as
#     they're detected - a simple heuristic version of "linguistic chunking",
#     not a full parser. Good enough to avoid the worst failure mode
#     (abbreviations), not guaranteed perfect on every edge case.
#     """

#     def __init__(self, min_chars: int = 15):
#         self.buffer = ""
#         self.min_chars = min_chars

#     def feed(self, token: str) -> list[str]:
#         self.buffer += token
#         sentences = []
#         search_start = 0
#         while True:
#             match = _SENTENCE_END_RE.search(self.buffer, search_start)
#             if not match:
#                 break
#             end = match.end()
#             candidate = self.buffer[:end].strip()
#             words = candidate.split()
#             last_word = words[-1].lower() if words else ""
#             if last_word in _ABBREVIATIONS or len(candidate) < self.min_chars:
#                 # Not a real boundary - keep searching FURTHER in the same
#                 # buffer instead of giving up entirely (this was the bug:
#                 # the first version bailed out of the whole loop here,
#                 # meaning a genuine sentence boundary later in the same
#                 # buffer never got found either).
#                 search_start = end
#                 continue
#             sentences.append(candidate)
#             self.buffer = self.buffer[end:].lstrip()
#             search_start = 0
#         return sentences

#     def flush(self) -> str:
#         remaining = self.buffer.strip()
#         self.buffer = ""
#         return remaining


# def ask_local_llm_stream(question: str, kb_answer: str = "", history: list[dict] | None = None):
#     """Streams the LLM's response token by token and yields complete
#     sentences as soon as they're detected - this is what lets the caller
#     start hearing sentence 1 while the LLM is still generating sentence 3.

#     NOTE: I can't verify streaming behavior against a live Ollama server from
#     this sandbox - the chunk.choices[0].delta.content access pattern below is
#     the standard OpenAI-compatible streaming shape, but confirm it works
#     against your actual Ollama server as the first real test of this.
#     """
#     system_prompt, user_content = _build_prompt(question, kb_answer, history)

#     stream = client.chat.completions.create(
#         model=LOCAL_LLM_MODEL,
#         messages=[
#             {"role": "system", "content": system_prompt},
#             {"role": "user", "content": user_content},
#         ],
#         temperature=0.4,
#         timeout=60,
#         stream=True,
#     )

#     chunker = SentenceChunker()
#     for chunk in stream:
#         delta = chunk.choices[0].delta.content or ""
#         if not delta:
#             continue
#         for sentence in chunker.feed(delta):
#             yield sentence

#     remaining = chunker.flush()
#     if remaining:
#         yield remaining


# if __name__ == "__main__":
#     import sys
#     question = " ".join(sys.argv[1:]) or "Hello, can you hear me?"
#     print(f"Asking local LLM (streaming): {question}")
#     for sentence in ask_local_llm_stream(question):
#         print(f"  chunk: {sentence}")

"""
Local LLM via Ollama's OpenAI-compatible API - drop-in replacement for the
OpenAI/Azure OpenAI client in voice_helpdesk_pipeline.py's ask_gpt().

Key point: this uses the SAME `openai` Python package and the SAME
client.chat.completions.create() call as the cloud version - only the
base_url and model name change. Nothing about how you call it is different.

SETUP (on your machine, not in this sandbox - see note below):
  1. Install Ollama: https://ollama.com (not a pip package - separate install)
  2. ollama pull qwen2.5:7b-instruct
  3. ollama serve   (runs the API at http://localhost:11434/v1 by default)

I can't run Ollama or pull model weights myself in this sandbox (no access
to ollama.com from here) - this code is correct against the OpenAI client's
documented interface, but the first real test of it talking to a live
Ollama server needs to happen on your machine.
"""

import os
import re
from openai import OpenAI

LOCAL_LLM_BASE_URL = os.environ.get("LOCAL_LLM_BASE_URL", "http://localhost:11434/v1")
LOCAL_LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL", "qwen2.5:7b-instruct")

# api_key is required by the OpenAI client's constructor but unused by Ollama -
# any non-empty string works.
client = OpenAI(base_url=LOCAL_LLM_BASE_URL, api_key="ollama")


def strip_markdown_for_speech(text: str) -> str:
    """Same cleanup as the cloud version - strip markdown/emoji before it
    reaches TTS (or, for now, before it's just read as plain text output)."""
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"[#*_`]", "", text)
    text = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", text)
    text = re.sub(r"\n{2,}", ". ", text)
    text = re.sub(r"\n", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def _build_prompt(question: str, kb_answer: str, history: list[dict] | None) -> tuple[str, str]:
    """Shared between ask_local_llm() and ask_local_llm_stream() - this is
    where the turn-1 hallucination fix and the greeting/smalltalk handling
    live, and both callers need the exact same behavior here."""
    clean_answer = strip_markdown_for_speech(kb_answer) if kb_answer else ""

    base_prompt = (
        "You are a professional voice support agent speaking out loud to a caller "
        "on a phone call. Keep responses concise - 2 to 4 short sentences, spoken "
        "style, no lists, no headers, no markdown, no emojis."
    )

    if clean_answer:
        base_prompt += " Do not add information that isn't in the source answer."
        if history:
            behavior = (
                "Below is what has already been said earlier in this call. FIRST, "
                "check whether the caller's CURRENT question is about the SAME issue "
                "as what's in the history below, or a genuinely DIFFERENT topic. If "
                "it's a different topic (e.g. history is about a mic problem and the "
                "current question is about leave days), treat it as a completely "
                "fresh question - answer it normally using the knowledge base answer "
                "below, and do NOT mention connecting to a human or reference the "
                "earlier issue at all. Only if the CURRENT question is about the SAME "
                "issue as history, AND the caller's current message actually says the "
                "earlier advice didn't work (e.g. 'that didn't work', 'I tried that', "
                "'still broken'), should you acknowledge it didn't help and consider "
                "saying you'll connect them with a human teammate if the knowledge "
                "base answer doesn't offer anything new. Never escalate or mention a "
                "human teammate just because history contains a different, unrelated "
                "issue."
            )
        else:
            behavior = (
                "This is the very first message in the call. The caller has NOT tried "
                "anything yet - there is no prior history. Present the knowledge base "
                "answer below as fresh guidance for them to try now. Do NOT say or "
                "imply they've already attempted these steps, and do NOT suggest "
                "escalating to a human yet - only do that if the source answer doesn't "
                "address the question at all."
            )
    else:
        behavior = (
            "There is no knowledge base match for this message, or the match wasn't "
            "confident enough to use. Figure out which of these three situations "
            "applies, based ONLY on the caller's current message - not on anything "
            "discussed earlier in this call:\n\n"
            "1. Greeting or small talk (like 'hi', 'hello', 'thanks', 'ok') - "
            "respond warmly and naturally, ask how you can help.\n\n"
            "2. Off-topic or unrelated to workplace IT/HR support (general knowledge, "
            "weather, jokes, personal chit-chat) - politely explain you're a "
            "workplace support assistant and aren't able to help with that, then ask "
            "if there's a work-related issue you can help with instead. A new "
            "off-topic question is NOT related to a previous support issue in this "
            "call - do not reference or connect it back to anything discussed "
            "earlier, even if history is provided below.\n\n"
            "3. A genuine support question with no matching KB answer - say you "
            "don't have that information yet and suggest reaching out to the "
            "relevant department directly. Do not guess or make up an answer."
        )

    system_prompt = f"{base_prompt}\n\n{behavior}"

    history_block = ""
    if history:
        lines = []
        for turn in history[-4:]:
            lines.append(f"Caller: {turn.get('question', '')}")
            lines.append(f"You already said: {turn.get('answer', '')}")
        history_block = "Earlier in this call:\n" + "\n".join(lines) + "\n\n"

    if clean_answer:
        user_content = f"{history_block}Caller's current question: {question}\n\nKnowledge base answer:\n{clean_answer}"
    else:
        user_content = f"{history_block}Caller's message: {question}"

    return system_prompt, user_content


def generate_quick_ack(question: str) -> str:
    """Generates a short, question-specific acknowledgment to speak before
    the real answer is ready - e.g. "Let me find the process for applying
    for two days of sick leave," instead of a generic "let me check that."

    Deliberately capped at a small max_tokens regardless of model speed -
    the whole point of this call is to bridge the wait, so it needs to stay
    fast on its own, not become a second slow call stacked in front of the
    first one.
    """
    system_prompt = (
        "You are a voice support agent. The caller just asked a question. "
        "Respond with exactly ONE short spoken sentence acknowledging their "
        "SPECIFIC question - start with 'Let me' or 'One moment, let me'. "
        "Do NOT answer the question itself, just acknowledge what they're "
        "asking about, specifically, in under 15 words. No markdown, no lists."
    )
    completion = client.chat.completions.create(
        model=LOCAL_LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ],
        temperature=0.4,
        max_tokens=40,
        timeout=15,
    )
    return completion.choices[0].message.content.strip()


def ask_local_llm(question: str, kb_answer: str = "", history: list[dict] | None = None) -> str:
    """Non-streaming version - waits for the full response. Kept for the CLI
    test scripts; local_web_demo.py uses ask_local_llm_stream() instead so
    TTS can start on sentence 1 before the LLM finishes generating the rest.
    """
    system_prompt, user_content = _build_prompt(question, kb_answer, history)

    completion = client.chat.completions.create(
        model=LOCAL_LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.4,
        timeout=30,
    )
    return completion.choices[0].message.content.strip()


# Common abbreviations that end in a period but AREN'T a sentence boundary -
# without this guard, "Mr. Smith" or "e.g." would get cut mid-phrase, exactly
# the failure mode your lead's document warned about for the Response
# Coordinator layer.
_ABBREVIATIONS = {"mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "vs.", "etc.", "e.g.", "i.e.", "no."}
_SENTENCE_END_RE = re.compile(r"[.!?]+(\s+|$)")


class SentenceChunker:
    """Buffers streamed tokens and yields complete sentences as soon as
    they're detected - a simple heuristic version of "linguistic chunking",
    not a full parser. Good enough to avoid the worst failure mode
    (abbreviations), not guaranteed perfect on every edge case.
    """

    def __init__(self, min_chars: int = 15):
        self.buffer = ""
        self.min_chars = min_chars

    def feed(self, token: str) -> list[str]:
        self.buffer += token
        sentences = []
        search_start = 0
        while True:
            match = _SENTENCE_END_RE.search(self.buffer, search_start)
            if not match:
                break
            end = match.end()
            candidate = self.buffer[:end].strip()
            words = candidate.split()
            last_word = words[-1].lower() if words else ""
            if last_word in _ABBREVIATIONS or len(candidate) < self.min_chars:
                # Not a real boundary - keep searching FURTHER in the same
                # buffer instead of giving up entirely (this was the bug:
                # the first version bailed out of the whole loop here,
                # meaning a genuine sentence boundary later in the same
                # buffer never got found either).
                search_start = end
                continue
            sentences.append(candidate)
            self.buffer = self.buffer[end:].lstrip()
            search_start = 0
        return sentences

    def flush(self) -> str:
        remaining = self.buffer.strip()
        self.buffer = ""
        return remaining


def ask_local_llm_stream(question: str, kb_answer: str = "", history: list[dict] | None = None):
    """Streams the LLM's response token by token and yields complete
    sentences as soon as they're detected - this is what lets the caller
    start hearing sentence 1 while the LLM is still generating sentence 3.

    NOTE: I can't verify streaming behavior against a live Ollama server from
    this sandbox - the chunk.choices[0].delta.content access pattern below is
    the standard OpenAI-compatible streaming shape, but confirm it works
    against your actual Ollama server as the first real test of this.
    """
    system_prompt, user_content = _build_prompt(question, kb_answer, history)

    stream = client.chat.completions.create(
        model=LOCAL_LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.4,
        timeout=60,
        stream=True,
    )

    chunker = SentenceChunker()
    for chunk in stream:
        delta = chunk.choices[0].delta.content or ""
        if not delta:
            continue
        for sentence in chunker.feed(delta):
            yield sentence

    remaining = chunker.flush()
    if remaining:
        yield remaining


if __name__ == "__main__":
    import sys
    question = " ".join(sys.argv[1:]) or "Hello, can you hear me?"
    print(f"Asking local LLM (streaming): {question}")
    for sentence in ask_local_llm_stream(question):
        print(f"  chunk: {sentence}")