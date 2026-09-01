import pyttsx3
import queue
import threading

from core.humanizer import humanize_for_speech

# Initialize the engine
engine = pyttsx3.init()

# --- VOICE SELECTION ---
voices = engine.getProperty('voices')
# voices[0] is a male voice, voices[1] is female.
engine.setProperty('voice', voices[0].id) 

engine.setProperty("rate", 185)
engine.setProperty("volume", 1.0) # Ensure at full volume

speech_queue = queue.Queue()

def worker():
    while True:
        text = speech_queue.get()
        if text is None:
            break

        # Rewritten for natural spoken delivery here (in the worker thread,
        # not in speak() itself) so the LLM round-trip never blocks
        # whatever thread called speak() — see core/humanizer.py.
        spoken_text = humanize_for_speech(text)
        if spoken_text != text:
            print("[HUMANIZER]:", spoken_text)

        # Check if the engine is already busy
        engine.say(spoken_text)
        engine.runAndWait()
        speech_queue.task_done()

# Start the speech worker
threading.Thread(target=worker, daemon=True).start()

def speak(text):
    """Adds text to the speech queue."""
    print("The Entity:", text)
    speech_queue.put(text)

def stop_speaking():
    """Clears the queue if you want The Entity to shut up immediately."""
    while not speech_queue.empty():
        try:
            speech_queue.get_nowait()
            speech_queue.task_done()
        except queue.Empty:
            break