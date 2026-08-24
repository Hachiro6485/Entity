import subprocess
import pyautogui
import platform
import re
import os
import shutil


# =============================================================================
# APP RESOLUTION
# =============================================================================

# Friendly names -> actual executable names
#
# This is the ONE authoritative app alias map for Entity.
_APP_MAP = {
    "calculator": "calc.exe",
    "calc": "calc.exe",

    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "browser": "chrome.exe",

    "notepad": "notepad.exe",
    "editor": "notepad.exe",

    "spotify": "Spotify.exe",

    "edge": "msedge.exe",
    "microsoft edge": "msedge.exe",

    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",
}


# Only allow normal app names.
#
# This prevents something like:
#
#     notepad & del important_file.txt
#
# from being interpreted as a command.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9 ._-]+$")


def _find_start_menu_shortcut(app_name):
    """
    Searches the Windows Start Menu for an application shortcut.

    This is our fallback for applications that aren't directly
    available through PATH.
    """

    if platform.system() != "Windows":
        return None

    name_lower = app_name.lower().strip()

    start_menu_paths = [
        os.path.join(
            os.environ.get("ProgramData", ""),
            "Microsoft",
            "Windows",
            "Start Menu",
            "Programs"
        ),
        os.path.join(
            os.environ.get("AppData", ""),
            "Microsoft",
            "Windows",
            "Start Menu",
            "Programs"
        )
    ]

    for base_path in start_menu_paths:

        if not base_path or not os.path.exists(base_path):
            continue

        for root, _, files in os.walk(base_path):

            for file in files:

                if not file.lower().endswith(".lnk"):
                    continue

                if name_lower in file.lower():

                    return os.path.join(root, file)

    return None


def open_app(app_name):
    """
    Opens a local desktop application.

    This is the ONE authoritative implementation used by Entity.

    Resolution order:

        1. Validate the app name
        2. Convert friendly name -> executable name
        3. Try the executable directly
        4. Try Windows Start Menu shortcuts
        5. Return a clear failure message
    """

    if app_name is None:
        return "No application was specified."

    original_name = str(app_name).strip()
    name_lower = original_name.lower()

    if not name_lower:
        return "No application was specified."

    # Security check
    if not _SAFE_NAME.match(name_lower):
        return (
            f"Refused to open '{original_name}': "
            "the application name contains unsupported characters."
        )

    # Resolve friendly names through ONE map.
    executable = _APP_MAP.get(name_lower, name_lower)

    print(
        f"DEBUG APP RESOLUTION: "
        f"'{original_name}' -> '{executable}'"
    )

    # -------------------------------------------------------------------------
    # Windows
    # -------------------------------------------------------------------------

    if platform.system() == "Windows":

        # 1. Try to find the executable through PATH.
        executable_path = shutil.which(executable)

        if executable_path:

            try:
                subprocess.Popen([executable_path])

                print(
                    f"DEBUG APP RESOLUTION: "
                    f"Opened executable: {executable_path}"
                )

                return f"Opening {original_name}."

            except Exception as e:

                print(
                    f"DEBUG APP RESOLUTION: "
                    f"Executable launch failed: {e}"
                )

        # 2. Try Windows' normal application launcher.
        #
        # We use cmd /c start as an argument list.
        # shell=False prevents Python from interpreting the input as shell code.
        # 2. Search the Windows Start Menu.
        #
        # This is especially important for Microsoft Store apps such as
        # Spotify, which may not expose a normal Spotify.exe through PATH.
        shortcut = _find_start_menu_shortcut(original_name)

        if shortcut:

            try:

                os.startfile(shortcut)

                print(
                    f"DEBUG APP RESOLUTION: "
                    f"Opened Start Menu shortcut: {shortcut}"
                )

                return f"Opening {original_name}."

            except Exception as e:

                print(
                    f"DEBUG APP RESOLUTION: "
                    f"Start Menu launch failed: {e}"
                )

        # 3. Last-resort Windows launcher.
        #
        # IMPORTANT:
        # We do NOT report success here. Windows' 'start' command can
        # accept a request and then fail asynchronously.
        #
        # We only use this as a final attempt.
        try:

            subprocess.Popen(
                [
                    "cmd",
                    "/c",
                    "start",
                    "",
                    executable
                ],
                shell=False
            )

            print(
                f"DEBUG APP RESOLUTION: "
                f"Attempted Windows launcher: {executable}"
            )

            return (
                f"I attempted to open {original_name}, "
                "but Windows may not have found the application."
            )

        except Exception as e:

            print(
                f"DEBUG APP RESOLUTION: "
                f"Windows launcher failed: {e}"
            )

        # 3. Search the Start Menu.
        shortcut = _find_start_menu_shortcut(original_name)

        if shortcut:

            try:

                os.startfile(shortcut)

                print(
                    f"DEBUG APP RESOLUTION: "
                    f"Opened Start Menu shortcut: {shortcut}"
                )

                return (
                    f"Found and opening "
                    f"{os.path.basename(shortcut)[:-4]}."
                )

            except Exception as e:

                print(
                    f"DEBUG APP RESOLUTION: "
                    f"Start Menu launch failed: {e}"
                )

        return f"I couldn't locate {original_name} on your system."

    # -------------------------------------------------------------------------
    # macOS
    # -------------------------------------------------------------------------

    elif platform.system() == "Darwin":

        try:

            subprocess.Popen(
                ["open", "-a", executable]
            )

            return f"Opening {original_name}."

        except Exception as e:

            return (
                f"I couldn't open {original_name}: "
                f"{e}"
            )

    # -------------------------------------------------------------------------
    # Linux / other Unix-like systems
    # -------------------------------------------------------------------------

    else:

        try:

            subprocess.Popen([executable])

            return f"Opening {original_name}."

        except Exception as e:

            return (
                f"I couldn't open {original_name}: "
                f"{e}"
            )


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