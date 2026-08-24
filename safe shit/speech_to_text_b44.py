import speech_recognition as sr
import numpy as np
import config

# Initialize the recognizer once
r = sr.Recognizer()

# Seconds of silence after a sentence before it stops listening
r.pause_threshold = 2.0
# Energy level threshold for sounds to be considered speech
r.dynamic_energy_threshold = True 

def record_audio():
    """
    Uses SpeechRecognition to detect when Marcus starts and stops talking 
    dynamically, preventing the assistant from cutting him off.
    """
    try:
        with sr.Microphone(sample_rate=config.SAMPLERATE) as source:
            # Calibrate for 1 second to handle background noise
            print("Calibrating for background noise...")
            r.adjust_for_ambient_noise(source, duration=1)
            
            print("Listening...")
            # phrase_time_limit ensures it doesn't listen forever if there's background noise
            audio_data = r.listen(source, phrase_time_limit=15)
            
            print("Processing speech...")
            
            # Convert the captured audio to the float32 format your system expects
            # This extracts the raw data and converts it to numpy array
            raw_data = audio_data.get_raw_data(convert_rate=config.SAMPLERATE, convert_width=2)
            audio_np = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32) / 32768.0
            
            return audio_np

    except Exception as e:
        print(f"Speech Recognition Error: {e}")
        return None