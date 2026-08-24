import os
import re
import tempfile
import wave

import numpy as np
import speech_recognition as sr
from openai import OpenAI

import config
from core.providers import PROVIDERS


# =============================================================================
# SHARED VOICE SYSTEM
# =============================================================================
#
# Both the GUI and CLI use this file.
#
# The flow is:
#
# Microphone
#     ↓
# SpeechRecognition
#     ↓
# numpy audio
#     ↓
# Groq Whisper
#     ↓
# text
#
# This means we only have ONE transcription system to maintain.
# =============================================================================


# One recognizer shared by the whole application.
recognizer = sr.Recognizer()

# Wait for a little silence before deciding the sentence is finished.
recognizer.pause_threshold = 2.0

# Automatically adapt to changes in background noise.
recognizer.dynamic_energy_threshold = True


# Cache the Groq client so we don't create a new client for every sentence.
_groq_client = None


def _get_groq_client():
    """
    Returns the shared Groq OpenAI-compatible client.
    """

    global _groq_client

    if _groq_client is not None:
        return _groq_client

    groq_provider = next(
        (
            provider
            for provider in PROVIDERS
            if provider.get("name") == "Groq Cloud"
        ),
        None
    )

    if not groq_provider:
        raise RuntimeError(
            "Groq Cloud is not configured. "
            "Set GROQ_API_KEY in your .env file."
        )

    _groq_client = OpenAI(
        base_url=groq_provider["base_url"],
        api_key=groq_provider["api_key"]
    )

    return _groq_client


def record_audio(timeout=15, phrase_time_limit=15):
    """
    Records one sentence from the microphone.

    Returns:
        numpy.float32 audio array
        or None if nothing was captured.
    """

    try:

        with sr.Microphone(
            sample_rate=config.SAMPLERATE
        ) as source:

            print("Calibrating for background noise...")

            recognizer.adjust_for_ambient_noise(
                source,
                duration=0.5
            )

            print("Listening...")

            audio_data = recognizer.listen(
                source,
                timeout=timeout,
                phrase_time_limit=phrase_time_limit
            )

            print("Processing speech...")

            raw_data = audio_data.get_raw_data(
                convert_rate=config.SAMPLERATE,
                convert_width=2
            )

            audio_np = (
                np.frombuffer(
                    raw_data,
                    dtype=np.int16
                )
                .astype(np.float32)
                / 32768.0
            )

            return audio_np

    except sr.WaitTimeoutError:
        return None

    except Exception as e:

        print(
            f"[VOICE] Microphone error: {e}"
        )

        return None


def transcribe_audio_groq(audio_data):
    """
    Sends microphone audio to Groq Whisper and returns text.
    """

    if audio_data is None:
        return ""

    sample_rate = getattr(
        config,
        "SAMPLERATE",
        16000
    )

    # Make sure audio stays within valid PCM range.
    audio_data = np.clip(
        audio_data,
        -1.0,
        1.0
    )

    pcm_data = (
        audio_data * 32767
    ).astype(np.int16)

    tmp_filename = None

    try:

        with tempfile.NamedTemporaryFile(
            suffix=".wav",
            delete=False
        ) as tmp_file:

            tmp_filename = tmp_file.name

        with wave.open(
            tmp_filename,
            "wb"
        ) as wf:

            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(
                pcm_data.tobytes()
            )

        client = _get_groq_client()

        with open(
            tmp_filename,
            "rb"
        ) as audio_file:

            transcription = client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=audio_file
            )

        text = (
            transcription.text
            if transcription
            else ""
        )

        return text.strip()

    except Exception as e:

        print(
            f"[VOICE] Groq transcription error: {e}"
        )

        return ""

    finally:

        if (
            tmp_filename
            and os.path.exists(tmp_filename)
        ):

            try:
                os.remove(tmp_filename)
            except Exception:
                pass


def _normalize_text(text):
    """
    Normalizes speech text so wake-word matching is reliable.
    """

    text = str(text).lower().strip()

    # Turn punctuation into spaces.
    text = re.sub(
        r"[^\w\s]",
        " ",
        text
    )

    # Collapse multiple spaces.
    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def contains_wake_word(text):
    """
    Returns True if the transcript contains one of the configured
    Entity wake words.
    """

    normalized = _normalize_text(text)

    if not normalized:
        return False

    for wake_word in config.WAKE_WORDS:

        wake = _normalize_text(wake_word)

        if not wake:
            continue

        # Use word boundaries so:
        #
        # "entity"       -> YES
        # "entities"     -> NO
        #
        # rather than using a loose substring search.
        pattern = (
            r"(?<!\w)"
            + re.escape(wake)
            + r"(?!\w)"
        )

        if re.search(
            pattern,
            normalized
        ):
            return True

    return False


def remove_wake_words(text):
    """
    Removes configured wake words from a transcript.

    Example:

        "Entity open YouTube"

    becomes:

        "open YouTube"
    """

    result = str(text).strip()

    for wake_word in config.WAKE_WORDS:

        wake = str(wake_word).strip()

        if not wake:
            continue

        pattern = (
            r"(?<!\w)"
            + re.escape(wake)
            + r"(?!\w)"
        )

        result = re.sub(
            pattern,
            "",
            result,
            flags=re.IGNORECASE
        )

    # Clean up leftover punctuation/spaces.
    result = re.sub(
        r"\s+",
        " ",
        result
    )

    return result.strip(
        " \t\n\r.,!?;:-"
    )


def listen_for_wake_word():
    """
    Listens once and checks whether a wake word was spoken.

    Returns:

        (True, transcript)
            if a wake word was detected

        (False, transcript)
            otherwise
    """

    audio = record_audio()

    if audio is None:
        return False, ""

    text = transcribe_audio_groq(
        audio
    )

    if text:
        print(
            f"[VOICE] Heard: {text}"
        )

    detected = contains_wake_word(
        text
    )

    if detected:

        print(
            f"[VOICE] Wake word detected: {text}"
        )

    return detected, text


def listen_for_command():
    """
    Listens for one normal user command.
    """

    audio = record_audio()

    if audio is None:
        return ""

    text = transcribe_audio_groq(
        audio
    )

    if text:
        print(
            f"[VOICE] Command: {text}"
        )

    return text