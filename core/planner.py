import json
import time
from openai import OpenAI

# ─────────────────────────────────────────────────────────────────────────────
# IMPORT SHARED PROVIDER INFRASTRUCTURE
# Previously imported from core.brain, which itself had the keys hardcoded.
# Now both modules (and verifier.py) import from the same core/providers.py,
# which loads keys from the environment and truly shares one cooldown
# registry across brain/planner/verifier instead of each having its own copy.
# ─────────────────────────────────────────────────────────────────────────────
from core.providers import PROVIDERS, COOLDOWN_REGISTRY, COOLDOWN_DURATION_SECONDS

def classify_task(user_goal: str) -> str:
    """
    Returns:
        'execute'
        'plan'
    """

    messages = [
        {
            "role": "system",
            "content": """
You are an intent classifier.

Determine whether the user's request:

1. Can be completed immediately.

OR

2. Requires planning, clarification,
multiple steps, research, comparison,
decision making, or missing information.

Return ONLY valid JSON.

Examples:

User: Open Chrome
{"mode":"execute"}

User: Turn volume up
{"mode":"execute"}

User: What is photosynthesis
{"mode":"execute"}

User: Help me book a flight
{"mode":"plan"}

User: Help me choose a laptop
{"mode":"plan"}

User: Organize my downloads folder
{"mode":"plan"}

Output ONLY JSON.
"""
        },
        {
            "role": "user",
            "content": user_goal
        }
    ]

    for provider in PROVIDERS:

        if time.time() < COOLDOWN_REGISTRY.get(provider["name"], 0):
            continue

        try:

            client = OpenAI(
                base_url=provider["base_url"],
                api_key=provider["api_key"]
            )

            response = client.chat.completions.create(
                model=provider["model"],
                messages=messages,
                temperature=0
            )

            raw = response.choices[0].message.content.strip()

            raw = (
                raw
                .replace("```json", "")
                .replace("```", "")
                .strip()
            )

            data = json.loads(raw)

            return data.get("mode", "execute")

        except Exception as e:

            print(
                f"[CLASSIFIER] {provider['name']} failed: {e}"
            )

            COOLDOWN_REGISTRY[
                provider["name"]
            ] = (
                time.time()
                + COOLDOWN_DURATION_SECONDS
            )

            continue

    return "execute"
# ─────────────────────────────────────────────────────────────────────────────
# PLANNING TRIGGER KEYWORDS
# Before making any LLM call, we scan the user's command for phrases that
# strongly imply a multi-step task. This avoids adding latency to every simple
# request like "open Chrome" or "what is the weather."
# ─────────────────────────────────────────────────────────────────────────────
PLANNING_TRIGGERS = [
    # Sequential intent markers
    "and then", "after that", "and after", "and finally",
    # File-level batch operations (the primary use case for the planner)
    "move all",   "find all",   "copy all",   "rename all",
    "delete all", "sort all",   "list all",   "organize",
    # File-type sweeps
    "all files",  "all pdfs",   "all images", "all documents",
    "all videos", "all folders","all photos",
    # Compound action phrases
    "and put",    "and place",  "and save",   "and copy",
    "and find",   "and move",   "create and", "create a folder and",
    "search and", "download and",
    # Iterative intent
    "for each file", "for every file", "each file",
]


# ─────────────────────────────────────────────────────────────────────────────
# PLANNER SYSTEM PROMPT
# The LLM's ONLY job here is to decompose a goal into a JSON plan.
# Every available tool is documented so the LLM knows what it can use.
# The "chat" tool is always the final step — it's how Entity reports back.
# ─────────────────────────────────────────────────────────────────────────────
PLANNER_PROMPT = """
You are the Strategic Planner module for The Entity — an autonomous AI system
running on a Windows machine owned by Marcus.

Your ONLY job is to decompose a user's goal into a precise, ordered sequence of
tool calls that will achieve it. You do NOT execute anything — you only plan.

═══════════════════════════════════════════════════════
AVAILABLE TOOLS (use EXACTLY these names)
═══════════════════════════════════════════════════════

FILE SYSTEM TOOLS:
  create_folder(path: str)
    — Creates a new directory. Expands %USERNAME% and other env vars.
    — Example: {"path": "C:/Users/%USERNAME%/Desktop/PDFs"}

  find_files(extension: str, directory: str)
    — Recursively finds all files with the given extension in a directory.
    — extension must include the dot, e.g. ".pdf", ".jpg", ".txt"
    — Returns a JSON list of full file paths.
    — Example: {"extension": ".pdf", "directory": "C:/Users/%USERNAME%/Desktop"}

  move_files(source_paths: str, destination: str)
    — Moves a file or list of files to the destination directory.
    — source_paths accepts either a single path string OR a JSON list of paths.
    — Example: {"source_paths": "$step_2.output", "destination": "C:/Users/%USERNAME%/Desktop/PDFs"}

  delete_file(path: str)
    — Permanently deletes exactly one specific file.
    — Requires explicit human confirmation and the Entity PIN.
    — Never use run_python for file deletion.
    — Only use when the user explicitly requests deletion.
    — Example: {"path": "C:/Users/%USERNAME%/Desktop/test.txt"}

  list_files(directory: str)
    — Lists all files in a given directory.
    — Returns a JSON list of file names.
    — Example: {"directory": "C:/Users/%USERNAME%/Documents"}

EXECUTION TOOLS:
  run_python(code: str)
    — Executes a Python script on Marcus's machine.
    — Use for: math, data processing, web fetching, anything programmatic.
    — Use this ONLY when no dedicated tool exists for the task.

  search_web(query: str)
    — Opens a Google or YouTube search in the default browser.
    — Example: {"query": "weather in Trinidad today"}

  open_app(app_name: str)
    — Opens a local application by name.
    — Example: {"app_name": "notepad"}

  type_text(text: str)
    — Types text into the currently active window.

  media_control(command: str)
    — Controls media: "volume up", "volume down", "mute", "play", "pause".

    
INFORMATION GATHERING TOOL:
  request_information(question: str)

Use this when information is missing.

Examples:

- What city are you departing from?
- What date would you like to leave?
- What is your budget?

Do not execute further steps until the user answers.

IMPORTANT:
- If information required to complete the goal is missing: Use request_information.
- Ask for the information in normal human language.
- NEVER require the user to respond in JSON unless the user specifically asks to use JSON.
- NEVER ask the user to provide information in a programming-language format when normal human language is sufficient.
- When the user provides missing information, interpret their answer and use it to continue the task.
- Do not treat the user's natural-language answer as JSON, Python code, or another structured format unless it actually is that format.
- Do not guess missing information.


RESPONSE TOOL (ALWAYS USE AS FINAL STEP):
  chat(response: str)
    — Sends a spoken/displayed response to Marcus.
    — This MUST be the last step in every plan.
    — Write the response as The Entity would say it: concise, professional.

═══════════════════════════════════════════════════════
STRICT OUTPUT RULES
═══════════════════════════════════════════════════════
1. Output ONLY a valid JSON array. Zero markdown, zero explanation, zero preamble.
2. Every step MUST have: "step_id" (e.g. "step_1"), "tool", and "args".
3. To pass the OUTPUT of a previous step into a later step, use the placeholder
   "$step_N.output" as the argument value. This is resolved automatically at
   runtime before the tool executes.
4. chat may appear at any point in a plan. Use chat whenever information is missing. If information is missing, ask the user for it. The final step should normally be chat, but intermediate chat steps are allowed.
5. Keep plans minimal — use the fewest steps that correctly achieve the goal.
6. For Windows file paths, use the pattern C:/Users/%USERNAME%/... with
   forward slashes. %USERNAME% is expanded automatically at runtime.
7. Every plan must end with a chat step unless waiting for request_information. Search tools are never terminal. If information is retrieved, add a final chat step that summarizes or reports the findings to the user.
8. Never assume file locations. If a task lacks required parameters such as a path, filename, source directory, or destination, ask the user using request_information instead of guessing.
9. NEVER report a destructive action as completed unless the corresponding destructive tool returned a successful result.
10. If a tool fails, do not use its error message, traceback, or failure output as an argument to another tool.
11. If a destructive operation fails or is cancelled, stop the destructive chain and report the failure.


═══════════════════════════════════════════════════════
EXAMPLES
═══════════════════════════════════════════════════════

GOAL: "Create a folder called Projects on my Desktop"
[
    {
        "step_id": "step_1",
        "tool": "create_folder",
        "args": {"path": "C:/Users/%USERNAME%/Desktop/Projects"}
    },
    {
        "step_id": "step_2",
        "tool": "chat",
        "args": {"response": "I've created the Projects folder on your Desktop."}
    }
]

GOAL: "Find all PDFs on my Desktop and move them into a folder called Documents"
[
    {
        "step_id": "step_1",
        "tool": "create_folder",
        "args": {"path": "C:/Users/%USERNAME%/Desktop/Documents"}
    },
    {
        "step_id": "step_2",
        "tool": "find_files",
        "args": {"extension": ".pdf", "directory": "C:/Users/%USERNAME%/Desktop"}
    },
    {
        "step_id": "step_3",
        "tool": "move_files",
        "args": {"source_paths": "$step_2.output", "destination": "C:/Users/%USERNAME%/Desktop/Documents"}
    },
    {
        "step_id": "step_4",
        "tool": "chat",
        "args": {"response": "Done. All PDF files from your Desktop have been moved into the Documents folder."}
    }
]

GOAL: "Search YouTube for lo-fi music and then open Spotify"
[
    {
        "step_id": "step_1",
        "tool": "search_web",
        "args": {"query": "lo-fi music youtube"}
    },
    {
        "step_id": "step_2",
        "tool": "open_app",
        "args": {"app_name": "Spotify"}
    },
    {
        "step_id": "step_3",
        "tool": "chat",
        "args": {"response": "Done. I've opened the YouTube search for lo-fi music and launched Spotify for you."}
    }
]
"""


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC INTERFACE
# ─────────────────────────────────────────────────────────────────────────────

def needs_planning(command: str) -> bool:
    """
    Fast keyword scan to determine whether a command likely requires a
    multi-step plan rather than a single-shot brain.think() call.

    Uses heuristics only — no LLM call — to keep latency near zero for
    simple commands like "open Chrome" or "what's the weather."
    """
    command_lower = command.lower()
    return any(trigger in command_lower for trigger in PLANNING_TRIGGERS)

def ai_needs_planning(command):
    """
    Uses a direct LLM call to decide whether a request requires multi-step
    planning.

    This used to call brain.think(prompt), which drags in Entity's full
    tool-calling system prompt and tool definitions for what's really just
    a YES/NO classification — that's what caused the "attempted to call
    tool 'json' which was not in request.tools" 400 errors: the model got
    confused between "answer YES/NO" and "call a tool." classify_task()
    just above already does this the right way (direct completion, no
    tools attached); this follows the same pattern instead of going
    through brain.
    """

    prompt = f"""
Determine whether the following user request requires:

- multiple steps
- asking follow-up questions
- gathering missing information
- making decisions with the user
- executing a plan

Respond ONLY with:

YES

or

NO

Request:
{command}
"""

    messages = [
        {"role": "system", "content": "You are a classifier. Respond with exactly one word: YES or NO. Nothing else."},
        {"role": "user", "content": prompt}
    ]

    for provider in PROVIDERS:

        if time.time() < COOLDOWN_REGISTRY.get(provider["name"], 0):
            continue

        try:
            client = OpenAI(base_url=provider["base_url"], api_key=provider["api_key"])
            response = client.chat.completions.create(
                model=provider["model"],
                messages=messages,
                temperature=0
            )
            answer = (response.choices[0].message.content or "").strip().upper()

            print(
                f"DEBUG PLANNER AI DECISION: {answer}"
            )

            return "YES" in answer

        except Exception as e:
            COOLDOWN_REGISTRY[provider["name"]] = time.time() + COOLDOWN_DURATION_SECONDS
            continue

    print("DEBUG PLANNER AI DECISION: ALL AI NODES BUSY.")
    return False


def generate_plan(user_goal: str) -> list | None:
    """
    Calls the LLM planner with the full provider failover stack from brain.py.
    Returns a validated list of step dicts, or None if all providers fail.

    The returned structure is:
    [
        {"step_id": "step_1", "tool": "...", "args": {...}},
        ...
    ]
    """
    messages = [
        {"role": "system", "content": PLANNER_PROMPT},
        {"role": "user",   "content": f"GOAL: {user_goal}"}
    ]

    for provider in PROVIDERS:
        # Skip providers that are still in their cooldown window
        if time.time() < COOLDOWN_REGISTRY.get(provider["name"], 0):
            continue

        try:
            client = OpenAI(
                base_url=provider["base_url"],
                api_key=provider["api_key"]
            )
            response = client.chat.completions.create(
                model=provider["model"],
                messages=messages,
                temperature=0.1       # Low temp → deterministic, structured JSON
            )
            raw_output = response.choices[0].message.content.strip()

            # Strip any accidental markdown fences the model might hallucinate
            raw_output = (
                raw_output
                .replace("```json", "")
                .replace("```", "")
                .strip()
            )

            plan = json.loads(raw_output)

            # Sanity check — must be a non-empty list of dicts
            if not isinstance(plan, list) or not plan:
                print(f"[PLANNER] {provider['name']} returned an invalid plan structure.")
                continue

            print(f"[PLANNER] ✓ {len(plan)}-step plan generated via {provider['name']}")
            return plan

        except json.JSONDecodeError as e:
            print(f"[PLANNER] JSON parse error from {provider['name']}: {e}")
            # Don't put this provider on cooldown for a JSON error — try the next one
            continue

        except Exception as e:
            print(f"[PLANNER] Error with {provider['name']}: {e}")
            # Rate limit / network error → put provider on cooldown
            COOLDOWN_REGISTRY[provider["name"]] = time.time() + COOLDOWN_DURATION_SECONDS
            continue

    print("[PLANNER] ✗ All providers failed to generate a plan.")
    return None