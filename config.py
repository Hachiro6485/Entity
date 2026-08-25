import os

# ============================================================
# ENVIRONMENT CONFIGURATION
# ============================================================
#
# Load .env HERE, before reading any configuration values.
# This prevents configuration from depending on which Python
# module happens to get imported first.
# ============================================================

try:
    from dotenv import load_dotenv

    project_root = os.path.dirname(
        os.path.abspath(__file__)
    )

    env_file = os.path.join(
        project_root,
        ".env"
    )

    load_dotenv(env_file)

except ImportError:
    pass


# ============================================================
# SPEECH / AUDIO
# ============================================================

WHISPER_MODEL_SIZE = "base"
DEVICE = "cpu"
COMPUTE_TYPE = "float32"
SAMPLERATE = 16000


# ============================================================
# WAKE WORDS
# ============================================================

WAKE_WORDS = [
    "hello world",
    "entity"
]


# ============================================================
# VAD SETTINGS
# ============================================================

VAD_ENABLED = True
VAD_THRESHOLD = 0.5
MIN_SILENCE_MS = 750


# ============================================================
# ACCESS CONTROL
# ============================================================

ENTITY_PIN = (
    os.environ
    .get("ENTITY_PIN", "")
    .strip()
    or None
)