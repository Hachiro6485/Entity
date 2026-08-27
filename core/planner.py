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
  delete_file(path: str)
    — Permanently deletes exactly one specific file.
    — Requires explicit human confirmation and the Entity PIN.
    — Never use run_python for file deletion.
    — Only use when the user explicitly requests deletion.
    — Example: {"path": "C:/Users/%USERNAME%/Desktop/test.txt"}

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
    Determines whether a request genuinely requires the multi-step planner.

    Fast deterministic rules handle obvious simple requests first.
    This prevents the planner from being invoked for things like:
        - counting files
        - listing files
        - checking a folder
        - simple calculations
        - opening an application
        - answering a factual question

    The LLM classifier is only used when the request is genuinely ambiguous.
    """

    command_lower = command.lower().strip()

    # ============================================================
    # OBVIOUS SINGLE-STEP REQUESTS
    # ============================================================

    simple_file_questions = [
        "how many files",
        "how many pdf",
        "how many pdfs",
        "how many images",
        "how many pictures",
        "how many documents",
        "how many videos",
        "how many folders",
        "how many txt",
        "how many text files",
        "how many files are",
        "count the files",
        "count files",
        "count the pdf",
        "count the pdfs",
        "list the files",
        "list files",
        "what files are",
        "which files are",
    ]

    if any(phrase in command_lower for phrase in simple_file_questions):
        print(
            "DEBUG PLANNER AI DECISION: NO "
            "(simple file-information request)"
        )
        return False

    # ============================================================
    # OBVIOUS SINGLE-STEP SYSTEM REQUESTS
    # ============================================================

    simple_commands = [
        "open ",
        "launch ",
        "start ",
        "close ",
        "play ",
        "pause ",
        "mute",
        "unmute",
        "volume up",
        "volume down",
        "turn the volume up",
        "turn the volume down",
    ]

    if any(command_lower.startswith(prefix) for prefix in simple_commands):
        print(
            "DEBUG PLANNER AI DECISION: NO "
            "(simple system request)"
        )
        return False

    # ============================================================
    # OBVIOUS MULTI-STEP REQUESTS
    # ============================================================

    if needs_planning(command):
        print(
            "DEBUG PLANNER AI DECISION: YES "
            "(planning trigger)"
        )
        return True

    # ============================================================
    # LLM CLASSIFIER FOR EVERYTHING ELSE
    # ============================================================

    prompt = f"""
Determine whether this user request genuinely requires a multi-step plan.

A request should be classified as NO if Entity can complete it with one
direct tool call, one calculation, one simple lookup, or one simple action.

A request should be classified as YES only if it requires multiple actions,
missing information, several dependent operations, organization, comparison,
or a sequence of actions.

Examples:

"How many PDFs are on my Desktop?"
NO

"How many files are in my Downloads folder?"
NO

"List the files on my Desktop."
NO

"Open Chrome."
NO

"What is 25 times 25?"
NO

"Create a folder called Test."
NO

"Delete test.txt."
NO

"Find all PDFs on my Desktop and move them into a folder called PDFs."
YES

"Create a folder, put all my PDFs inside it, and then open it."
YES

"Delete these three files."
YES

"Find my photos and organize them into folders by year."
YES

Respond with exactly one word:

YES

or

NO

User request:
{command}
"""

    messages = [
        {
            "role": "system",
            "content": (
                "You are a strict planning classifier. "
                "Respond with exactly YES or NO. "
                "Never call a tool. "
                "Never output JSON."
            )
        },
        {
            "role": "user",
            "content": prompt
        }
    ]

    for provider in PROVIDERS:

        if time.time() < COOLDOWN_REGISTRY.get(
            provider["name"], 0
        ):
            continue

        try:

            client = OpenAI(
                base_url=provider["base_url"],
                api_key=provider["api_key"]
            )

            response = client.chat.completions.create(
                model=provider["model"],
                messages=messages,
                temperature=0,
                max_tokens=3
            )

            answer = (
                response.choices[0]
                .message.content or ""
            ).strip().upper()

            # Only accept an EXACT classifier answer.
            if answer == "YES":
                print(
                    "DEBUG PLANNER AI DECISION: YES"
                )
                return True

            if answer == "NO":
                print(
                    "DEBUG PLANNER AI DECISION: NO"
                )
                return False

            # Anything else is not trustworthy.
            print(
                f"DEBUG PLANNER AI DECISION: "
                f"Invalid classifier response: {answer!r}"
            )

        except Exception as e:

            COOLDOWN_REGISTRY[
                provider["name"]
            ] = (
                time.time()
                + COOLDOWN_DURATION_SECONDS
            )

            print(
                f"[CLASSIFIER] "
                f"{provider['name']} failed: {e}"
            )

            continue

    print(
        "DEBUG PLANNER AI DECISION: "
        "ALL AI NODES BUSY — defaulting to NO."
    )

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