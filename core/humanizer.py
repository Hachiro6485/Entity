"""
core/humanizer.py

Rewrites AI-generated text into natural spoken language before it's handed
to text-to-speech.

Raw LLM output is written for reading, not speaking: markdown bullets,
**bold**, numbered lists, headers, arrows, and similar visual formatting
either gets read aloud literally by a TTS engine ("asterisk asterisk...")
or silently mangled into something that doesn't sound like a sentence.
Written responses also tend to be more thorough/hedged than how a person
actually talks in a live conversation.

This makes one extra LLM call — using the same provider failover stack as
everything else (core/providers.py) — to rewrite the response the way a
person would actually SAY it out loud, and to trim anything that's only
useful in writing (redundant caveats, repeated detail) in the same pass.

Deliberately skipped for short strings (tool confirmations like "Opening
chrome." or "Yes?") — those are already spoken-friendly, and paying for an
extra LLM round-trip on them would only add latency for no benefit.
"""

import re
import time
from openai import OpenAI
from core.providers import PROVIDERS, COOLDOWN_REGISTRY, COOLDOWN_DURATION_SECONDS

# Below this length, text is assumed to already be TTS-friendly. Skipping
# the LLM call here saves a full round-trip of latency in the voice loop
# for strings like "Opening chrome." or "Folder created." that don't need
# rewriting.
MIN_LENGTH_TO_HUMANIZE = 60

SYSTEM_PROMPT = """You are a text-to-speech formatter for a voice assistant called The Entity.
You will be given a written response that is about to be SPOKEN out loud, not read on a screen.

Rewrite it so it sounds like natural spoken conversation — the way a person
would actually say it out loud, not like a piece of written text.

Rules:
- Remove ALL markdown and symbols that only make sense visually: no
  asterisks, pound signs, dash-bullets, numbered lists, code fences,
  arrows, or stray punctuation.
- Turn lists into natural spoken sentences ("First... then... and
  finally...") instead of reading bullet points aloud.
- Replace or drop symbols that don't translate to speech (e.g. "%" ->
  "percent", "&" -> "and", em dashes used as punctuation -> a comma or a
  new sentence).
- Cut anything that's only useful in writing: redundant caveats, repeated
  information, or long technical detail a person wouldn't actually say in
  a quick spoken reply.
- Keep every fact, number, name, and piece of meaning EXACTLY correct.
  Never invent, exaggerate, or drop anything factually important.
- Keep the same first-person voice and tone as the original.
- Output ONLY the rewritten spoken version — no preamble, no quotation
  marks, no explanation of what you changed.
"""


def humanize_for_speech(text: str) -> str:
    """
    Rewrites `text` for natural spoken delivery.

    Falls back to a plain regex cleanup (still strips the most common
    offenders — markdown bold/italic markers, bullet dashes, headers, code
    fences) if every provider is unavailable, rather than speaking raw
    unformatted text or raising.
    """

    if not text or len(text.strip()) < MIN_LENGTH_TO_HUMANIZE:
        return text

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": text}
    ]

    for provider in PROVIDERS:

        if time.time() < COOLDOWN_REGISTRY.get(provider["name"], 0):
            continue

        try:
            client = OpenAI(base_url=provider["base_url"], api_key=provider["api_key"])
            response = client.chat.completions.create(
                model=provider["model"],
                messages=messages,
                temperature=0.4
            )
            result = (response.choices[0].message.content or "").strip()
            if result:
                return result

        except Exception as e:
            COOLDOWN_REGISTRY[provider["name"]] = time.time() + COOLDOWN_DURATION_SECONDS
            print(f"[HUMANIZER] {provider['name']} failed: {e}")
            continue

    print("[HUMANIZER] All providers unavailable — falling back to regex cleanup.")
    return _regex_fallback_cleanup(text)


def _regex_fallback_cleanup(text: str) -> str:
    """
    Cheap, no-API-call cleanup used only if every provider is down.
    Doesn't paraphrase or trim length — just strips the most obviously
    broken-when-spoken markdown symbols, so the assistant never reads
    raw asterisks/pound-signs aloud even in a total-outage worst case.
    """
    cleaned = text
    cleaned = re.sub(r'\*\*(.*?)\*\*', r'\1', cleaned)             # **bold**
    cleaned = re.sub(r'\*(.*?)\*', r'\1', cleaned)                 # *italic*
    cleaned = re.sub(r'`([^`]*)`', r'\1', cleaned)                 # `code`
    cleaned = re.sub(r'^#+\s*', '', cleaned, flags=re.MULTILINE)   # # headers
    cleaned = re.sub(r'^[-*]\s+', '', cleaned, flags=re.MULTILINE)  # - bullets
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned
