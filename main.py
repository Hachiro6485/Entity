import sys
import os
import winsound

# Ensure local modules can be found
sys.path.append(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

from utils.tts import speak
from memory.memory import get_context, add_memory
from core.brain import think
from core.router import route

from perception.speech_to_text import (
    listen_for_wake_word,
    listen_for_command,
    remove_wake_words
)

import config

print("Initializing Systems...")
print(f"System Online. Wake words: {config.WAKE_WORDS}")

def main():
    speak("The Entity online and standing by.")

    # Phrases that should trigger an exit from active mode back to idle mode
    CLOSING_PHRASES = ["no", "nothing else", "that is all", "thank you", "thanks", "i'm good", "no thanks"]

    while True:

    # ================================================================
    # IDLE MODE
    # ================================================================

        detected, wake_transcript = listen_for_wake_word()

        if not detected:
            continue

        print(
            "\n[Wake Word Detected]"
        )

        winsound.Beep(
            1000,
            200
        )

    # Check whether the user said:
    #
    #     "Entity"
    #
    # or:
    #
    #     "Entity open YouTube"
    #
        wake_command = remove_wake_words(
            wake_transcript
        )

    # ------------------------------------------------
    # WAKE WORD ONLY
    # ------------------------------------------------

        if not wake_command:

            speak("Yes?")

        # --- SESSION START ---
            while True:

                user_input = listen_for_command()

                if not user_input:
                    break

                clean_input = (
                    user_input
                    .lower()
                    .strip()
                    .replace(".", "")
                    .replace("!", "")
                )

                if clean_input in CLOSING_PHRASES:

                    speak(
                        "Understood. I'll be here "
                        "if you need anything else."
                    )

                    winsound.Beep(
                        600,
                        150
                    )

                    break

                if any(
                    x in clean_input
                    for x in [
                        "shutdown",
                        "exit",
                        "shut up",
                        "system down"
                    ]
                ):

                    speak(
                        "Systems offline."
                    )

                    return

                winsound.Beep(
                    600,
                    150
                )

                context = get_context()

                intent = think(
                    user_input,
                    context
                )

                add_memory(
                    f"User: {user_input}"
                )

                result = route(
                    intent
                )

                if result:

                    speak(result)

                    add_memory(
                        f"The Entity: {result}"
                    )

                else:
                    break

    # ------------------------------------------------
    # WAKE WORD + COMMAND IN ONE SENTENCE
    # ------------------------------------------------

        else:

            user_input = wake_command

            print(
                f"[Wake + Command] {user_input}"
            )

            winsound.Beep(
                600,
                150
            )

            context = get_context()

            intent = think(
                user_input,
                context
            )

            add_memory(
                f"User: {user_input}"
            )

            result = route(
                intent
            )

            if result:

                speak(result)

                add_memory(
                    f"The Entity: {result}"
                )

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nManual Exit.")