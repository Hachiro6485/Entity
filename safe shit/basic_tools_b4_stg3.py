import subprocess
import pyautogui
import platform
import re

# Map friendly names to the actual system commands
_APP_MAP = {
    "chrome": "chrome",
    "browser": "chrome",
    "notepad": "notepad",
    "editor": "notepad",
    "calculator": "calc",
    "spotify": "Spotify"
}

# Only allow simple app identifiers through to a shell command — anything
# with shell metacharacters gets rejected instead of interpolated.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9 ._-]+$")


def open_app(app_name):
    """
    Dynamically opens applications based on a mapping dictionary.

    SECURITY FIX: this used to build `f"start {cmd}"` and run it with
    `shell=True`, so any shell metacharacter in app_name (e.g. "notepad &
    del important_file") would be interpreted by the shell instead of
    treated as a literal app name. shell=True is no longer used at all —
    Windows apps are launched via `["cmd", "/c", "start", "", cmd]` with a
    real argument list, which the shell cannot reinterpret, and the name is
    additionally validated before use.
    """
    app_name = app_name.lower().strip()

    if not app_name or not _SAFE_NAME.match(app_name):
        return f"Refused to open '{app_name}': contains characters that aren't allowed in an app name."

    cmd = _APP_MAP.get(app_name, app_name)  # Fallback to the raw name if not in dictionary

    try:
        current_os = platform.system()
        if current_os == "Windows":
            # "start" is a cmd.exe builtin, not an executable, so it must be
            # invoked via cmd.exe — but as a real argument list (no
            # shell=True), so `cmd` can never break out into a new command.
            # The empty "" argument after "start" is the (usually blank)
            # window title start.exe expects as its first positional arg.
            subprocess.Popen(["cmd", "/c", "start", "", cmd], shell=False)
        elif current_os == "Darwin":  # macOS
            subprocess.Popen(["open", "-a", cmd])
        else:  # Linux
            subprocess.Popen([cmd])
        return f"Opening {app_name}."
    except Exception as e:
        return f"Failed to open {app_name}: {str(e)}"

def type_text(text):
    """
    Types text with a slight delay to make it look more natural.
    """
    if not text:
        return
    # interval=0.01 adds a tiny delay between keys so it doesn't look instant
    pyautogui.write(text, interval=0.01) 
    return "Text entered."