"""
experimental/agent_brain.py

Experimental standalone agent branch. Previously had its own hardcoded
Groq API key (a duplicate of the one in core/brain.py) and its own
completely unguarded exec() with zero safety checks at all — the GUI and
CLI paths at least had *some* protection; this one had none.

Both issues are fixed the same way as the rest of the project: shared
provider config (core/providers.py) and the shared sandbox
(security/sandbox.py).
"""

import re
from openai import OpenAI

from core.providers import PROVIDERS, COOLDOWN_REGISTRY, COOLDOWN_DURATION_SECONDS
from security.sandbox import run_sandboxed
import time

# Prefer Groq for speed since this experimental branch is meant to think
# quickly, but fall back through the rest of the shared provider list if
# Groq isn't configured or is rate-limited.
_PREFERRED = [p for p in PROVIDERS if p["name"] == "Groq Cloud"]
_PROVIDER_ORDER = _PREFERRED + [p for p in PROVIDERS if p not in _PREFERRED]

AGENT_PROMPT = """
You are The Entity (Experimental Branch). You are an autonomous Python agent.
You have the ability to execute Python code directly on Marcus's machine to fulfill his requests.

When Marcus asks you to do something, write the python script necessary to do it.
Wrap your code in standard python markdown blocks.

CRITICAL RULES:
1. If you need to search the web, write a script to use standard libraries or webbrowser.
2. If you need to open an app, write a script using subprocess or os.startfile.
3. Keep scripts concise and focused on the immediate task. Do not write endless loops.
4. Your code will be run through a sandbox that blocks destructive operations
   (deleting files, spawning processes, running shell commands) and asks for
   human confirmation before writing files. Write code accordingly.
"""


def think_and_code(user_input):
    if not _PROVIDER_ORDER:
        return "Error connecting to neural net: no LLM providers configured (see .env.example)."

    messages = [
        {"role": "system", "content": AGENT_PROMPT},
        {"role": "user", "content": user_input}
    ]

    for provider in _PROVIDER_ORDER:
        if time.time() < COOLDOWN_REGISTRY.get(provider["name"], 0):
            continue
        try:
            client = OpenAI(base_url=provider["base_url"], api_key=provider["api_key"])
            response = client.chat.completions.create(
                model=provider["model"],
                messages=messages,
                temperature=0.2
            )
            return response.choices[0].message.content
        except Exception as e:
            COOLDOWN_REGISTRY[provider["name"]] = time.time() + COOLDOWN_DURATION_SECONDS
            continue

    return "Error connecting to neural net: all providers unavailable."


def extract_code(text):
    """Extracts python code from markdown blocks."""
    pattern = r"```python\n(.*?)\n```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1)
    return None


def execute_sandbox_code(code_string, timeout: int = 20):
    """Executes code through the shared sandbox. File-interfering code
    triggers the same PIN-gated popup as delete_file; everything else
    runs unrestricted."""
    result = run_sandboxed(code_string, timeout=timeout)
    return result.as_message()
