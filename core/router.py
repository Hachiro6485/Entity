import os
import shutil
import subprocess
import webbrowser  
import pyautogui  
import coder
import json
from core import brain
from tools import system_control, web_tools
from tools.basic_tools import (
    open_app,
    delete_file
    )

def find_and_open_app(app_name):
    """
    Compatibility wrapper.

    Older parts of Entity, including the planner/executor,
    still call router.find_and_open_app().

    The actual implementation now lives ONLY in:
        tools.basic_tools.open_app()
    """

    return open_app(app_name)

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

    elif action == "delete_file":
        return delete_file(value)

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