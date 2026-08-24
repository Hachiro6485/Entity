import subprocess
import pyautogui
import platform
import os
import shutil

def open_app(name):
    name_lower = name.lower().strip()
    path_check = shutil.which(name_lower) or shutil.which(f"{name_lower}.exe")
    if path_check:
        try:
            subprocess.Popen(path_check)
            return f"Opening {name} for you."
        except Exception as e:
            return f"Found {name}, but failed to launch: {e}"
    start_menu_paths = [os.path.join(os.environ["ProgramData"], "Microsoft", "Windows", "Start Menu", "Programs"), os.path.join(os.environ["AppData"], "Microsoft", "Windows", "Start Menu", "Programs")]
    for path in start_menu_paths:
        if not os.path.exists(path): continue
        for root, dirs, files in os.walk(path):
            for file in files:
                if name_lower in file.lower() and file.endswith(".lnk"):
                    full_path = os.path.join(root, file)
                    try:
                        os.startfile(full_path)
                        return f"Found and opening {file.replace('.lnk', '')}."
                    except Exception as e: return f"Error launching shortcut: {e}"
    return f"I couldn't find '{name}' installed on your system."

def type_text(text):
    if not text: return "Nothing to type."
    pyautogui.write(text, interval=0.01)
    return "Text entered."

def media_control(command):
    cmd = command.lower()
    if "up" in cmd: pyautogui.press("volumeup")
    elif "down" in cmd: pyautogui.press("volumedown")
    elif "mute" in cmd: pyautogui.press("volumemute")
    elif "play" in cmd or "pause" in cmd: pyautogui.press("playpause")
    return "Command executed."