import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILE = os.path.join(BASE_DIR, "memory_storage", "memory.json")
MAX_HISTORY = 100  # Prevent the file from growing indefinitely

# Ensure directory exists
os.makedirs(os.path.dirname(FILE), exist_ok=True)

def load_memory():
    """Loads memory from the JSON file safely."""
    if not os.path.exists(FILE):
        return []
    try:
        with open(FILE, "r") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, FileNotFoundError):
        return []

def save_memory(data):
    """Saves the conversation list to the JSON file."""
    try:
        # Keep only the last N items to ensure speed over time
        if len(data) > MAX_HISTORY:
            data = data[-MAX_HISTORY:]
            
        with open(FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Failed to save memory: {e}")

def add_memory(text):
    """Appends a new interaction to the history."""
    mem = load_memory()
    mem.append(text)
    save_memory(mem)

def get_context():
    """Returns the last 10 interactions for the AI to understand context."""
    mem = load_memory()
    if not mem:
        return ""
    # Return last 10 messages for immediate conversation context
    return "\n".join(mem[-10:])

def clear_memory():
    """Wipes the memory file - useful for a 'Jarvis, reset' command."""
    save_memory([])
    return "Memory cleared."