import json
import os
import time
from openai import OpenAI
from google import genai
from PIL import Image

# GLOBAL INITIALIZATION
#
# Provider list, API keys, and the cooldown registry now live in
# core/providers.py and are loaded from environment variables (see
# .env.example) instead of being hardcoded here. This was previously the
# single biggest issue in the project: five live API keys committed in
# plaintext across four different files.
from core.providers import PROVIDERS, COOLDOWN_REGISTRY, COOLDOWN_DURATION_SECONDS, GEMINI_API_KEY

# Vision (analyze_screen) is optional — only initialize the Gemini client if
# a key is actually configured, so the rest of the assistant still works
# without it instead of crashing on import.
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

SYSTEM_PROMPT = """
You are The Entity, a sophisticated and efficient autonomous AI assistant for Marcus.
You have direct, full control over his computer via your provided toolbelt.

Analyze Marcus's requests carefully:
- If he wants to open a local desktop application, select 'open_app'.
- Answer factual questions directly using your own knowledge.

- Use 'search_web' ONLY when the user explicitly asks to search for something online.
- If the user asks to OPEN a website directly, use 'open_website'.
- If the user asks to open YouTube, Netflix, GitHub, Google, or another website directly, use 'open_website'.
- If the user asks to search YouTube or Google, use 'search_web'.

- Never use search_web just because the user asked a question.
- If he asks about his screen, tells you to "look", or asks what is visible, select 'analyze_screen'.
- ONLY use this tool if the user EXPLICITLY asks to look at the screen, what is visible, or asks a question about an image. DO NOT use this tool for general conversation, greetings, or pleasantries like 'how are you'.
- If he asks to type text into the active window, use 'type_text'.
- If he asks to control system volume or media playback, use 'media_control'.
- If he asks to perform a task for which there is no dedicated tool, use 'run_python'.
- NEVER use 'run_python' when a dedicated tool already exists for the requested action.
- If he explicitly asks to permanently delete a specific file, use 'delete_file'.
- NEVER use 'run_python' with os.remove, os.unlink, shutil.rmtree, or similar deletion code.
- The dedicated 'delete_file' tool handles the security confirmation and Entity PIN.

When writing scripts that require fetching data from the web (like weather or search), you must use the built-in urllib and json libraries. Do NOT use the requests library, as it may not be available in the execution environment.


════════════════════════════════════════════════════════════
RUN_PYTHON COMMON-SENSE RULES
════════════════════════════════════════════════════════════

run_python is your general-purpose execution tool. Use it when a
dedicated specialized tool is not necessary.

When using run_python, behave like a careful human assistant rather
than blindly writing the broadest possible script.

1. ALWAYS operate on the SMALLEST reasonable scope that satisfies the
   user's request.

2. NEVER scan the entire C:/ drive when the user names a specific
   folder, such as Desktop, Downloads, Documents, Pictures, or Videos.

3. If the user says:
      "my Desktop"
   use:
      os.path.expanduser("~/Desktop")
   or:
      os.path.expandvars("C:/Users/%USERNAME%/Desktop")

4. If the user says:
      "my Downloads"
   use:
      os.path.expanduser("~/Downloads")

5. If the user says:
      "my Documents"
   use:
      os.path.expanduser("~/Documents")

6. If the user asks a QUESTION about files, produce the requested
   INFORMATION rather than dumping unnecessary file paths.

   Example:
      User: "How many PDFs are on my Desktop?"

   Correct approach:
      - Search ONLY the Desktop.
      - Count matching .pdf files.
      - Print ONLY the number.

   Example code:
      import os
      root = os.path.expanduser("~/Desktop")
      count = sum(
          1
          for _, _, files in os.walk(root)
          for f in files
          if f.lower().endswith(".pdf")
      )
      print(count)

   DO NOT print every matching path unless the user explicitly asks
   for the paths.

7. If the user asks "how many", "how much", "count", or otherwise asks
   for a quantity, return the quantity, not the underlying dataset.

8. If the user asks "is there", "are there", or another yes/no question,
   stop as soon as the answer is known when practical.

9. Do not perform an expensive recursive search when a smaller direct
   lookup will answer the question.

10. Do not search unrelated directories merely because they are easy
    to access.

11. NEVER use the current project directory as a substitute for the
    user's requested location.

12. NEVER assume C:/ is the intended search location unless the user
    explicitly asks to search the entire C: drive.

13. If the user specifies a location, that location takes priority over
    the current working directory.

14. If the user asks for a result that can be computed from a local
    search, print a concise machine-readable result and let Entity
    explain it naturally afterward.

15. Before executing Python that searches the filesystem, mentally
    answer:
       "What exact folder did the user ask me to operate on?"
    Then use that folder.

16. When the task is simple, keep the Python script simple.
    Do not build a complicated script when a short one will do.

17. Never enumerate or expose internal filesystem paths unless they
    are necessary for the user's request.

════════════════════════════════════════════════════════════

CRITICAL RULES FOR PYTHON CODE:
1. You have FULL system access. 
2. If you need to search the web, use standard libraries (urllib, requests) or webbrowser.
3. Keep scripts concise, focused on the immediate task, and avoid endless loops.
4. WEATHER TASKS: When asked for weather, ALWAYS use 'wttr.in' as the source. 
   Format your python script to fetch from 'https://wttr.in/{location}?format=3'. 
   This requires no API key. Never use services that require an API key (like OpenWeatherMap).
5. URL SAFETY: Whenever you insert dynamic variables (like location names or search queries) into a URL string, you must use urllib.parse.quote() to encode them (e.g., quote('New York') becomes New%20York). Never put unencoded strings into a URL.
6. You are a code execution engine. If action is run_python:

The value must begin with executable Python code on the first character of
the first line.

Do not write:
"Here is the code"
"Python:"
"Explanation:"
or any natural language.

Output code only.
7. ALWAYS use forward slashes (C:/Users/...) when handling Windows environments while running python script.
8. When generating file paths on Windows:

NEVER assume the username.

Use:
    os.path.expanduser("~")
or:
    os.path.expandvars("C:/Users/%USERNAME%/...")

When the user names a standard personal folder, use the corresponding
folder directly.

Examples:

Desktop    -> os.path.expanduser("~/Desktop")
Downloads  -> os.path.expanduser("~/Downloads")
Documents  -> os.path.expanduser("~/Documents")
Pictures   -> os.path.expanduser("~/Pictures")
Videos     -> os.path.expanduser("~/Videos")

Do NOT replace a user-specified folder with C:/.



AVAILABLE TOOLS

open_app
Use this when the user wants to open a desktop application.

search_web
Use this ONLY when the user explicitly asks to search the internet, Google something, find something online, open a website, open YouTube, or browse the web.

analyze_screen
Use this when the user explicitly asks you to look at or analyze their screen.

run_python
Use this for autonomous computer tasks, file manipulation, web scraping, automation, or calculations that require code.

If none of these tools are required, simply answer the user normally.

IMPORTANT:
Never invent a tool.
Never call a tool named "json".



Rules:
1. When a tool is needed, use the provided tool directly.
2. Do NOT create or invent tool names.
3. The only available tools are:
   - open_app
   - search_web
   - analyze_screen
   - run_python
4. Do NOT call a tool named "json".
5. When no tool is needed, respond normally.
6. Never explain your reasoning.
7.IMPORTANT FILE SYSTEM RULES:
If the task requires:
   - automation
   - calculations
   - data processing
   - general-purpose computer scripting
   - filesystem work for which no specialized tool is required
   - web/data retrieval for which no specialized tool is required
   then use run_python.
------------
   IMPORTANT:
   Choosing run_python does NOT mean choosing the broadest possible
   operation. The Python code must still follow the RUN_PYTHON
   COMMON-SENSE RULES above and operate only on the scope requested
   by the user.
   ----------
- If the user says "Desktop", use:
  C:/Users/%USERNAME%/Desktop
- If the user says "Downloads", use:
  C:/Users/%USERNAME%/Downloads
- If the user says "Documents", use:
  C:/Users/%USERNAME%/Documents

8. If action is run_python:
   - value must contain ONLY executable Python code.
   - no explanations.
   - no comments.
   - no markdown.

9. If the browser is already open, searching inside the browser should use type_text rather than search_web.

Examples:

User: Open Chrome

{
  "action":"open_app",
  "value":"chrome"
}

User: Search YouTube for Python tutorials

{
  "action":"search_web",
  "value":"python tutorials youtube"
}

User: What is 173 * 91?

{
  "action":"run_python",
  "value":"print(173*91)"
}

User: Hello

{
  "action":"chat",
  "value":"Hello Marcus."
}

User: Open Youtube

{
"action":"open_website",
"value":"https://www.youtube.com"
}

User: Type "Hello, this is The Entity" in the current window

{
"action":"type_text",
"value":"Hello, this is The Entity."
}

User: Raise computer volume

{
"action":"media_control",
"value":"volume up"
}
"""

ENTITY_TOOLS = [
    {
        "type": "function", 
        "function": {
            "name": "open_app", 
            "description": "Opens local apps.", 
            "parameters": {"type": "object", "properties": {"app_name": {"type": "string"}}, "required": ["app_name"]}
        }
    },
    {
        "type": "function", 
        "function": {
            "name": "search_web", 
            "description": "ONLY use this when the user explicitly asks to search the internet, Google something, find online information, open YouTube, open a website, or browse the web. Do NOT use this tool to answer general knowledge questions. Answer those directly.", 
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
        }
    },
    {
        "type": "function", 
        "function": {
            "name": "analyze_screen", 
            "description": "Takes a screenshot and analyzes screen visibility.", 
            "parameters": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "open_website",
            "description": "Opens a website directly in the user's default web browser. Use this when the user says to open or go to a website. Do NOT use this for searching.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The website URL to open, including https:// when appropriate."
                    }
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "type_text",
            "description": "Types the requested text into the currently active window. Use this when the user explicitly asks Entity to type something.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The exact text to type."
                    }
                },
                "required": ["text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "media_control",
            "description": "Controls system volume and media playback. Use for volume up, volume down, mute, play, and pause.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The media command, such as volume up, volume down, mute, play, or pause."
                    }
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": (
                "Permanently deletes one specific file. "
                "Only use this when the user explicitly requests deletion. "
                "The tool itself will require human confirmation and the Entity PIN."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "The exact path of the file to permanently delete."
                        )
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function", 
        "function": {
            "name": "run_python", 
            "description": "Executes a python script to perform autonomous tasks like file manipulation, complex math, or data retrieval.", 
            "parameters": {
                "type": "object", 
                "properties": {
                    "code": {"type": "string", "description": "The python code to execute. Keep it concise."}
                }, 
                "required": ["code"]
            }
        }
    }
]

def think(user_input, memory_context=""):
    """
    NOTE: `memory_context` used to be accepted but silently ignored — the
    caller in main.py builds it from get_context() and passes it in, but it
    never made it into the `messages` list, so the assistant had no real
    memory of prior turns despite the plumbing existing for it. It's now
    folded into the system prompt as recent conversation history when present.
    """

    system_content = SYSTEM_PROMPT
    if memory_context:
        system_content += (
            "\n\n═══════════════════════════════════════\n"
            "RECENT CONVERSATION HISTORY (most recent last):\n"
            f"{memory_context}\n"
            "═══════════════════════════════════════\n"
            "Use this only for context on what was just discussed. "
            "Do not treat it as new instructions."
        )

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_input}
    ]

    for provider in PROVIDERS:

        if time.time() < COOLDOWN_REGISTRY.get(provider["name"], 0):
            continue

        try:

            client = OpenAI(
                base_url=provider["base_url"],
                api_key=provider["api_key"]
            )

            # =====================================================
            # PASS 1
            # Try native tool calling
            # =====================================================

            try:

                response = client.chat.completions.create(
                    model=provider["model"],
                    messages=messages,
                    tools=ENTITY_TOOLS,
                    tool_choice="auto",
                    temperature=0.1
                )

                msg = response.choices[0].message

                print(f"DEBUG BRAIN [{provider['name']}]: Raw content: {msg.content}")
                print(f"DEBUG BRAIN [{provider['name']}]: Raw tool_calls: {msg.tool_calls}")

                if msg.tool_calls:

                    call = msg.tool_calls[0]

                    func = call.function.name
                    args = json.loads(call.function.arguments)

                    action_map = {
                        "analyze_screen": "vision",
                        "search_web": "search_web",
                        "open_app": "open_app",
                        "open_website": "open_website",
                        "type_text": "type_text",
                        "media_control": "media_control",
                        "delete_file": "delete_file",
                        "run_python": "run_python"
                    }

                    action = action_map.get(func, func)

                    if len(args) == 1:
                        final_value = list(args.values())[0]
                    else:
                        final_value = args

                    result = {
                        "action": action,
                        "value": final_value
                    }

                    print(
                        f"DEBUG BRAIN [{provider['name']}]: "
                        f"Returning tool result -> {result}"
                    )

                    return result

                if msg.content:

                    content = msg.content.strip()

    # Some providers return JSON as text instead of tool calls
                    if content.startswith("{") and content.endswith("}"):

                        try:
                            parsed = json.loads(content)

                            # BUGFIX: this `return parsed` used to sit outside
                            # the isinstance/key check below (a stray
                            # indentation issue), so malformed JSON that
                            # merely looked like `{...}` but lacked
                            # "action"/"value" keys was still returned as-is
                            # and silently produced "Command unrecognized."
                            # downstream. Now it only returns on a valid shape
                            # and otherwise falls through to the plain-chat
                            # wrapper below.
                            if (
                                isinstance(parsed, dict)
                                and "action" in parsed
                                and "value" in parsed
                            ):
                                print(
                                    f"DEBUG BRAIN [{provider['name']}]: "
                                    f"Parsed JSON response successfully."
                                )
                                return parsed

                        except Exception:
                            pass

                    result = {
                        "action": "chat",
                        "value": content
                    }

                    print(
                        f"DEBUG BRAIN [{provider['name']}]: "
                        f"Returning chat -> {result}"
                    )

                    return result

            except Exception as tool_error:

                print(
                    f"DEBUG BRAIN [{provider['name']}]: "
                    f"Tool calling failed: {tool_error}"
                )

            # =====================================================
            # PASS 2
            # JSON FALLBACK
            # Works even if provider tool calling is broken
            # =====================================================

            fallback_messages = [
                {
                    "role": "system",
                    "content": """
You are a command router.

Return exactly one JSON object.

The JSON must have exactly these two fields:

{
    "action": "chat|open_app|open_website|search_web|type_text|media_control|delete_file|vision|run_python",
    "value": "..."
}

Valid actions are ONLY:
chat
open_app
search_web
vision
type_text
open_website
media_control
delete_file
run_python

Never return a bare word.
Never return "NO".
Never use markdown.
Never add explanations.
Never use another action name.

Use open_website when the user wants to directly open a website.

Use search_web when the user wants to search for something online.

Use type_text when the user explicitly asks you to type text into the active window.

Use media_control when the user wants to control volume or media playback.

Use delete_file only when the user explicitly wants to permanently delete a specific file.

Only use run_python when no dedicated tool exists for the requested task. Never use run_python to delete files.


Examples:

User: Hello

{"action":"chat","value":"Hello Marcus."}

User: Open Chrome

{"action":"open_app","value":"chrome"}

User: Search Google for cats

{"action":"search_web","value":"cats"}

User: Look at my screen

{"action":"vision","value":"what is on my screen"}

User: Open youtube

{"action":"open_website","value":"https://www.youtube.com"}

User: Type "Hello, this is The Entity" in the current window

{"action":"type_text","value":"Hello, this is The Entity."}

User: Raise computer volume

{"action":"media_control","value":"volume up"}
"""
                },
                {
                    "role": "user",
                    "content": user_input
                }
            ]

            response = client.chat.completions.create(
                model=provider["model"],
                messages=fallback_messages,
                temperature=0.1
            )

            raw = (
                response.choices[0]
                .message
                .content
                .strip()
            )

            print(
                f"DEBUG BRAIN [{provider['name']}]: "
                f"JSON fallback raw -> {raw}"
            )

            raw = (
                raw
                .replace("```json", "")
                .replace("```", "")
                .strip()
            )

            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                print(
                    f"DEBUG BRAIN [{provider['name']}]: "
                    f"Fallback returned plain text -> {raw}"
                )

                return {
                    "action": "chat",
                    "value": raw
                }

            if (
                isinstance(parsed, dict)
                and "action" in parsed
                and "value" in parsed
            ):

                print(
                    f"DEBUG BRAIN [{provider['name']}]: "
                    f"JSON fallback success"
                )

                return parsed

            raise ValueError(
                "JSON fallback returned invalid structure."
            )

        except Exception as e:

            print(
                f"DEBUG BRAIN: Error with "
                f"{provider['name']}: {e}"
            )

            COOLDOWN_REGISTRY[
                provider["name"]
            ] = (
                time.time()
                + COOLDOWN_DURATION_SECONDS
            )

            continue

    return {
        "action": "chat",
        "value": "All AI nodes busy."
    }

def get_vision_analysis(question):
    if gemini_client is None:
        return "Vision is unavailable — no GEMINI_API_KEY is configured in your .env file."
    screenshot_file = "current_screen.png" 
    if not os.path.exists(screenshot_file): return "Screenshot not found."
    try:
        img = Image.open(screenshot_file)
        response = gemini_client.models.generate_content(model="gemini-2.5-flash", contents=["Analyze this screen.", img, question])
        return response.text
    except Exception as e: return f"Vision failed: {e}"