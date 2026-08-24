import os

WHISPER_MODEL_SIZE = "base"
DEVICE = "cpu"
COMPUTE_TYPE = "float32"
SAMPLERATE = 16000

# NOTE: "up" was removed from the default wake words. main.py matches wake
# words with a plain substring check (`word in text`), so "up" as a wake
# word meant almost any sentence containing the word "up" ("what's up",
# "hold up", "up next"...) would trigger active listening. That's both
# annoying and a mild security issue for a system with full computer
# control — pick wake phrases that are unlikely to occur by accident.
WAKE_WORDS = ["hello world", "entity"]

# --- VAD Settings ---
VAD_ENABLED = True
VAD_THRESHOLD = 0.5            # Sensitivity (0.1 to 1.0)
MIN_SILENCE_MS = 750           # How long to wait before processing speech

# --- ACCESS CONTROL ---
# The Entity has full control of this computer (file moves, code execution,
# app launching) and previously had zero access control — anyone within
# earshot of the mic could issue commands. This is a lightweight opt-in gate:
# if ENTITY_PIN is set (in your .env, not here), destructive confirmations
# (see security/sandbox.py's cli_confirm_callback) will also require typing
# this PIN, not just "y". Leave it unset to keep the original y/n-only
# behavior.
ENTITY_PIN = os.environ.get("ENTITY_PIN", "").strip() or None