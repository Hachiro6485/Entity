import os
import shutil
import subprocess
import webbrowser  
import pyautogui  
import coder
import json
from core import brain
from tools import system_control, web_tools  

def find_and_open_app(app_name):
    name_lower = app_name.lower().strip()
    web_shortcuts = {"youtube": "https://www.youtube.com", "netflix": "https://www.netflix.com", "github": "https://www.github.com", "google": "https://www.google.com"}
    for keyword, url in web_shortcuts.items():
        if keyword in name_lower or name_lower.endswith((".com", ".org", ".net")):
            webbrowser.open(url if keyword in name_lower else (name_lower if name_lower.startswith("http") else f"https://{name_lower}"))
            return f"Opening {keyword if keyword in name_lower else app_name} in your web browser"

    path_check = shutil.which(name_lower) or shutil.which(f"{name_lower}.exe")
    if path_check:
        subprocess.Popen(path_check)
        return f"Opening {app_name}."

    start_menu = [os.path.join(os.environ["ProgramData"], "Microsoft", "Windows", "Start Menu", "Programs"), os.path.join(os.environ["AppData"], "Microsoft", "Windows", "Start Menu", "Programs")]
    for path in start_menu:
        if not os.path.exists(path): continue
        for root, _, files in os.walk(path):
            for file in files:
                if name_lower in file.lower() and file.endswith(".lnk"):
                    os.startfile(os.path.join(root, file))
                    return f"Found and opening {file.replace('.lnk', '')}."
    return f"I couldn't locate {app_name} on your system."

def route(intent):
    if not isinstance(intent, dict): 
        return "Error: Intent format invalid."
        
    action = intent.get("action", "").lower()
    value = intent.get("value", "") 

    if action == "open_app":
        return find_and_open_app(value)

    elif action == "open_website":
        return web_tools.open_website(value)

    elif action == "type_text":
        return system_control.type_text(value)

    elif action == "media_control":
        return system_control.media_control(value)

    elif action == "media":
        return system_control.media_control(value)

    elif action == "search_web" or action == "search":
        return web_tools.search(value)
    elif action == "run_python": return coder.execute_python(value)
    elif action == "vision":
        screenshot_path = "current_screen.png"
        try:
            pyautogui.screenshot().save(screenshot_path)
            return brain.get_vision_analysis(value)
        finally:
            if os.path.exists(screenshot_path): os.remove(screenshot_path)
    # THIS PREVENTS THE PROTOCOL ERROR WHEN THE AI JUST WANTS TO TALK
    elif action == "chat": 
        return value

    return "Command unrecognized."


def process_response(response):
    message = response.choices[0].message
    
    # 1. Handle Tool Calls
    if hasattr(message, 'tool_calls') and message.tool_calls:
        for tool_call in message.tool_calls:
            if tool_call.function.name == "run_python":
                import json
                from coder import execute_python
                
                arguments = json.loads(tool_call.function.arguments)
                code_to_run = arguments.get("code")
                
                # EXECUTE AND ENSURE WE RETURN A STRING
                result = execute_python(code_to_run)
                return str(result) if result else "Tool executed, but no output returned."

    # 2. Handle Normal Chat (Fallback)
    # Ensure this returns an empty string instead of None if content is empty
    return str(message.content or "No response from Entity.")