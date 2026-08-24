import numpy as np
import sounddevice as sd
import sys
import os
import winsound  
import tempfile
import wave

# Ensure local modules can be found
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from utils.tts import speak
from memory.memory import get_context, add_memory
from core.brain import think, client  # Pulls the Groq client from your cloud brain script
from core.router import route
from perception.speech_to_text import record_audio
import config

print("Initializing Systems...")
print(f"System Online. Wake words: {config.WAKE_WORDS}")

def transcribe_audio_groq(audio_data):
    """
    Converts live numpy audio arrays into a temporary WAV file and
    transcribes it using Groq's lightning-fast cloud Whisper API.
    """
    # Safely look for a sample rate in your config, or default to standard 16000Hz
    sample_rate = getattr(config, "SAMPLE_RATE", 16000)
    
    # Clip and convert float32 audio to 16-bit PCM for WAV compilation
    audio_data = np.clip(audio_data, -1.0, 1.0)
    pcm_data = (audio_data * 32767).astype(np.int16)
    
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
        tmp_filename = tmp_file.name
        
    try:
        # Write temporary WAV file structure
        with wave.open(tmp_filename, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_data.tobytes())
            
        # Ship to Groq cloud for processing
        with open(tmp_filename, "rb") as af:
            transcription = client.audio.transcriptions.create(
                model="whisper-large-v3", 
                file=af
            )
        return transcription.text
    except Exception as e:
        print(f" [Cloud Audio Error]: {e}")
        return ""
    finally:
        # Always clean up the temporary file from your storage
        if os.path.exists(tmp_filename):
            os.remove(tmp_filename)

def listen_for_wake_word():
    audio = record_audio() 
    if audio is None:
        return False

    try:
        audio_data = np.array(audio, dtype=np.float32)
        text = transcribe_audio_groq(audio_data).lower().strip()
        
        if any(word in text for word in config.WAKE_WORDS):
            return True
    except Exception:
        pass
    return False

def listen_for_command():
    audio = record_audio()
    if audio is None:
        return ""

    try:
        audio_data = np.array(audio, dtype=np.float32)
        text = transcribe_audio_groq(audio_data).strip()
        
        if text:
            print(f"You: {text}")
        return text
    except Exception as e:
        print(f"Transcription Error: {e}")
        return ""

def main():
    speak("The Entity online and standing by.")

    # Phrases that should trigger an exit from active mode back to idle mode
    CLOSING_PHRASES = ["no", "nothing else", "that is all", "thank you", "thanks", "i'm good", "no thanks"]

    while True:
        # 1. Idle Mode 
        if listen_for_wake_word():
            print("\n[Wake Word Detected]")
            winsound.Beep(1000, 200) 
            speak("Yes?") 
            
            # --- SESSION START ---
            while True:
                user_input = listen_for_command()

                if not user_input:
                    break

                clean_input = user_input.lower().strip().replace(".", "").replace("!", "")
                
                if clean_input in CLOSING_PHRASES:
                    speak("Understood. I'll be here if you need anything else.")
                    winsound.Beep(600, 150)
                    break # Breaks the active loop and goes back to Idle

                # Emergency Shutdown
                if any(x in clean_input for x in ["shutdown", "exit", "shut up", "down"]):
                    speak("Systems offline.")
                    return 

                # --- SILENT PROCESSING ---
                winsound.Beep(600, 150)

                # 2. Process through Brain and Router
                context = get_context()
                intent = think(user_input, context)
                
                add_memory(f"User: {user_input}")
                
                result = route(intent)
                if result:
                    speak(result)
                    add_memory(f"The Entity: {result}")
                    
                    # 3. Follow-up
                    speak("Is there anything else I can help you with?")
                else:
                    break 
        else:
            continue

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nManual Exit.")