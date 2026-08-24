import pyautogui

# =============================================================================
# APP OPENING
# =============================================================================
#
# IMPORTANT:
# The actual app-opening implementation lives in basic_tools.py.
#
# We import it here so older code that still calls:
#
#     system_control.open_app(...)
#
# continues to work.
#
# This prevents duplicate implementations.
# =============================================================================

from tools.basic_tools import open_app


# =============================================================================
# TEXT INPUT
# =============================================================================

def type_text(text):
    """
    Types text into the currently active window.
    """

    if not text:
        return "Nothing to type."

    pyautogui.write(
        text,
        interval=0.01
    )

    return "Text entered."


# =============================================================================
# MEDIA CONTROL
# =============================================================================

def media_control(command):
    """
    Controls basic system media and volume.
    """

    if not command:
        return "No media command was specified."

    cmd = command.lower().strip()

    if "up" in cmd:
        pyautogui.press("volumeup")

    elif "down" in cmd:
        pyautogui.press("volumedown")

    elif "mute" in cmd:
        pyautogui.press("volumemute")

    elif "play" in cmd or "pause" in cmd:
        pyautogui.press("playpause")

    else:
        return f"I don't know how to perform media command: {command}"

    return "Command executed."