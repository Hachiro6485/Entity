"""
core/providers.py

Single source of truth for LLM provider configuration.

Previously, the same four API keys (Groq, SambaNova, Cerebras, OpenRouter)
plus a Gemini key were hardcoded, in plaintext, in THREE different files
(brain.py, planner.py, verifier.py) and a fourth copy of the Groq key lived
in experimental/agent_brain.py. That meant:
  - the keys were committed to source and shipped in every zip/export
  - rotating a key meant hunting through multiple files
  - brain.py, planner.py and verifier.py each kept their OWN cooldown
    registry, so a rate-limited provider in one module wasn't skipped by
    the others

This module fixes all three problems: one place to configure providers,
keys loaded from environment variables (never committed), and a single
shared cooldown registry imported everywhere.

SETUP:
  1. Copy .env.example to .env
  2. Fill in your real API keys in .env
  3. Never commit .env (it's already in .gitignore)

If a key is missing, that provider is silently skipped rather than
crashing the app — this keeps failover working even if you've only
set up one or two providers.
"""

import os
import time

# config.py resolves and loads .env explicitly (relative to the project
# root via os.path.abspath(__file__), not the process's current working
# directory), so importing it here — even though nothing below reads from
# it directly — guarantees .env is loaded correctly regardless of which
# module happens to get imported first or what directory Entity was
# launched from. This replaces a previous bare load_dotenv() call here,
# which only searched upward from the current working directory and could
# silently miss .env if Entity were ever launched from a shortcut or
# scheduled task with a different working directory.
import config  # noqa: F401


def _provider(name, base_url, env_var, default_model, model_env_var=None):
    key = os.environ.get(env_var, "").strip()
    if not key:
        return None
    model = os.environ.get(model_env_var, "").strip() if model_env_var else ""
    return {"name": name, "base_url": base_url, "api_key": key, "model": model or default_model}


# Default model per provider. These get renamed/deprecated by providers
# periodically (e.g. Groq retired llama-3.3-70b-versatile in favor of
# openai/gpt-oss-120b) — if you start seeing 404 "model_not_found" errors,
# check the provider's current model list and override via the matching
# _MODEL env var below rather than editing this file.
_ALL_PROVIDERS = [
    _provider("Groq Cloud", "https://api.groq.com/openai/v1", "GROQ_API_KEY", "openai/gpt-oss-120b", "GROQ_MODEL"),
    _provider("OpenRouter Free", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "openrouter/free", "OPENROUTER_MODEL"),
    _provider("Mistral AI", "https://api.mistral.ai/v1", "MISTRAL_API_KEY", "mistral-small-latest", "MISTRAL_MODEL"),
    _provider("DeepSeek", "https://api.deepseek.com", "DEEPSEEK_APEY", "deepseek-v4-flash", "DEEPSEEK_MODEL"),
]

# Only providers that actually have a key configured are usable.
PROVIDERS = [p for p in _ALL_PROVIDERS if p is not None]

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# Shared across brain.py / planner.py / verifier.py so a provider that gets
# rate-limited by one module is correctly skipped by the others too.
COOLDOWN_REGISTRY: dict = {}
COOLDOWN_DURATION_SECONDS = 60


def require_providers():
    """Call this at startup so a misconfigured .env fails loudly and early,
    instead of failing silently deep inside brain.think()."""
    if not PROVIDERS:
        raise RuntimeError(
            "No LLM providers configured. Set "
            "at least one of GROQ_API_KEY, DEEPSEEK_API_KEY, MISTRAL_API_KEY, "
            "or OPENROUTER_API_KEY."
        )
