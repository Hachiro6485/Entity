import os
import shutil
import json
import traceback
import sys
import io
from tools.tool_registry import get_tool_function
import re

# ─────────────────────────────────────────────────────────────────────────────
# EXECUTION STATE
# A module-level dict that holds the output of every completed step so that
# subsequent steps can reference prior results via $step_N.output.
# Reset at the start of every new plan via execute_plan().
# ─────────────────────────────────────────────────────────────────────────────
execution_state: dict = {}


# ─────────────────────────────────────────────────────────────────────────────
# FILE SYSTEM TOOL IMPLEMENTATIONS
# These are self-contained so the executor never needs to import coder.py
# or router.py for file operations — keeping the dependency chain clean.
# ─────────────────────────────────────────────────────────────────────────────

def _tool_create_folder(args: dict) -> str:
    """Creates a directory. Expands environment variables like %USERNAME%."""
    path = _normalize_path(os.path.expandvars(args.get("path", "")))
    if not path:
        raise ValueError("create_folder requires a 'path' argument.")
    os.makedirs(path, exist_ok=True)
    return f"Folder created: {path}"


def _tool_find_files(args: dict) -> str:
    """
    Recursively walks a directory and collects all files matching an extension.
    Returns a JSON-encoded list of full absolute paths so move_files can
    consume it directly via $step_N.output resolution.
    """
    extension = args.get("extension", "")
    directory = _normalize_path(os.path.expandvars(args.get("directory", "")))

    if not extension:
        raise ValueError("find_files requires an 'extension' argument (e.g. '.pdf').")
    if not directory:
        raise ValueError("find_files requires a 'directory' argument.")
    if not os.path.exists(directory):
        raise FileNotFoundError(f"Directory not found: {directory}")

    # Normalise extension casing and ensure the dot is present
    if not extension.startswith("."):
        extension = "." + extension

    matches = []
    for root, _, files in os.walk(directory):
        for f in files:
            if f.lower().endswith(extension.lower()):
                matches.append(os.path.join(root, f))

    if not matches:
        return json.dumps([])   # Return empty list — move_files will handle gracefully

    print(f"[EXECUTOR] find_files: found {len(matches)} '{extension}' file(s) in {directory}")
    return json.dumps(matches)


def _tool_move_files(args: dict) -> str:
    """
    Moves one or more files to a destination directory.

    source_paths can be:
      - A JSON-encoded list of paths (output of find_files)
      - A plain single file path string
    """
    raw_sources = args.get("source_paths", "")
    destination = _normalize_path(os.path.expandvars(args.get("destination", "")))

    if not destination:
        raise ValueError("move_files requires a 'destination' argument.")

    # Parse source_paths — accept both JSON list and plain string
    if isinstance(raw_sources, list):
        paths = raw_sources
    else:
        try:
            parsed = json.loads(str(raw_sources))
            paths = parsed if isinstance(parsed, list) else [str(raw_sources)]
        except (json.JSONDecodeError, TypeError):
            paths = [str(raw_sources)]

    if not paths:
        return "No files to move — source list was empty."

    # Ensure destination directory exists
    os.makedirs(destination, exist_ok=True)

    moved, failed = [], []

    for src in paths:
        src = os.path.expandvars(str(src))
        try:
            filename = os.path.basename(src)
            dest_path = os.path.join(destination, filename)
            shutil.move(src, dest_path)
            moved.append(filename)
        except Exception as e:
            failed.append(f"{os.path.basename(src)} ({e})")

    result = f"Moved {len(moved)} file(s) to {destination}."
    if failed:
        result += f" | Failed: {', '.join(failed)}"
    return result


def _tool_list_files(args: dict) -> str:
    """Lists all files (not subdirectories) in a given directory."""
    directory = os.path.expandvars(args.get("directory", ""))
    if not directory:
        raise ValueError("list_files requires a 'directory' argument.")
    if not os.path.exists(directory):
        raise FileNotFoundError(f"Directory not found: {directory}")

    files = [
        f for f in os.listdir(directory)
        if os.path.isfile(os.path.join(directory, f))
    ]
    return json.dumps(files)


# ─────────────────────────────────────────────────────────────────────────────
# EXECUTION / SYSTEM TOOL IMPLEMENTATIONS
# These delegate to the actual tool modules that already exist in the project.
# ─────────────────────────────────────────────────────────────────────────────

def _tool_run_python(args: dict, python_runner=None) -> str:
    """
    Executes Python code.

    If a python_runner callable is provided (e.g. the GUI's run_code_and_capture),
    it is used instead of coder.execute_python. This is important for the GUI
    path because coder.execute_python's interactive confirmation prompt uses
    input(), which would hang a background thread. Both paths now route
    through the same security/sandbox.py underneath, so the actual safety
    checks are identical either way — only how confirmation is obtained differs.
    """
    code = args.get("code", "")
    if not code:
        return "run_python received empty code string."

    if python_runner is not None:
        return python_runner(code)

    # Fallback: use the project's coder module (CLI-style confirmation)
    from coder import execute_python
    return execute_python(code)


def _tool_search_web(args: dict) -> str:
    from tools.web_tools import search
    return search(args.get("query", ""))


def _tool_open_app(args: dict) -> str:
    from core.router import find_and_open_app
    return find_and_open_app(args.get("app_name", ""))


def _tool_type_text(args: dict) -> str:
    from tools.system_control import type_text
    return type_text(args.get("text", ""))


def _tool_media_control(args: dict) -> str:
    from tools.system_control import media_control
    return media_control(args.get("command", ""))


def _tool_chat(args: dict) -> str:
    """The final reporting step — just returns the response string directly."""
    return args.get("response", "Task completed.")


# ─────────────────────────────────────────────────────────────────────────────
# ARGUMENT RESOLVER
# Walks an args dict/list/string and substitutes any $step_N.output
# placeholder with the actual output stored in execution_state.
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_args(args, state):
    """
    Recursively resolves $step_N.output placeholders.
    """

    if isinstance(args, str):

        pattern = r"\$(step_\d+)\.output"

        def replace(match):
            step_ref = match.group(1)

            return str(
                state.get(step_ref, {}).get(
                    "output",
                    f"[Missing: {step_ref}.output]"
                )
            )

        return re.sub(pattern, replace, args)

    elif isinstance(args, dict):

        return {
            k: _resolve_args(v, state)
            for k, v in args.items()
        }

    elif isinstance(args, list):

        return [
            _resolve_args(v, state)
            for v in args
        ]

    else:

        return args
    
def _normalize_path(path: str) -> str:
    return path.replace("\\", "/")


# ─────────────────────────────────────────────────────────────────────────────
# CENTRAL DISPATCHER
# Single place that maps tool name → implementation. Adding a new tool means
# adding one entry here — nothing else needs to change.
# ─────────────────────────────────────────────────────────────────────────────

# Note: run_python needs python_runner injected, so it is handled separately
# in _dispatch() below rather than in this static registry.



def _dispatch(
    tool: str,
    resolved_args: dict,
    python_runner=None
):
    """
    Dynamic dispatch through Entity's registry.
    """

    # Preserve GUI-safe Python execution.
    if tool == "run_python":
        return _tool_run_python(
            resolved_args,
            python_runner=python_runner
        )

    handler = get_tool_function(tool)

    if handler is None:
        raise ValueError(
            f"Tool not registered: {tool}"
        )

    return handler(resolved_args)

# ─────────────────────────────────────────────────────────────────────────────
# PLAN EXECUTOR — PUBLIC ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def execute_plan(plan: list, log_callback=None, python_runner=None) -> dict:
    """
    Executes a plan generated by planner.generate_plan() step by step.

    Args:
        plan          : List of step dicts from the planner.
        log_callback  : Optional callable(str) that receives log lines in real
                        time. Used by the GUI to stream progress to the terminal
                        panel as the plan executes.
        python_runner : Optional callable(code_str) → str. If provided, used
                        for 'run_python' steps instead of coder.execute_python.
                        Pass app's run_code_and_capture for GUI safety.

    Returns:
        execution_state : Dict keyed by step_id, each value being:
                          {"tool": str, "args": dict, "status": str, "output": str}
    """
    global execution_state
    execution_state = {}   # Reset for this new plan run

    def log(msg: str):
        """Sends a log line to both the console and the GUI terminal panel."""
        print(msg)
        if log_callback:
            log_callback(msg)

    log("═" * 52)
    log("⚡  THE ENTITY  —  EXECUTION PROTOCOL INITIATED")
    log("═" * 52)

    for step in plan:
        step_id  = step.get("step_id", f"step_{len(execution_state) + 1}")
        tool     = step.get("tool", "")
        raw_args = step.get("args", {})

        log(f"\n▸ [{step_id.upper()}]  Dispatching  '{tool}'...")

        # 1. Substitute $step_N.output placeholders with real prior outputs
        resolved_args = _resolve_args(raw_args, execution_state)

        if resolved_args is None:
            resolved_args = {}

                # REQUEST INFORMATION STEP
        if tool == "request_information":

            execution_state[step_id] = {
                "tool": tool,
                "args": resolved_args,
                "status": "waiting",
                "output": resolved_args.get("question", "")
            }

            log(
                f"  ? Waiting for user input: "
                f"{resolved_args.get('question', '')}"
            )

            break

        # 2. Dispatch to the real tool
        try:
            result = _dispatch(tool, resolved_args, python_runner=python_runner)
            status = "success"
            log(f"  ✓  {result}")
        except Exception:
            result = traceback.format_exc()
            status = "failed"
            log(f"  ✗  STEP FAILED:\n{result}")

        # 3. Store result so subsequent steps can reference it
        execution_state[step_id] = {
            "tool":   tool,
            "args":   resolved_args,
            "status": status,
            "output": result,
        }

        # 4. Halt the chain on critical failure
        #    (The final 'chat' step is not critical — we try it regardless)
        if status == "failed" and tool != "chat":
            log(f"\n⛔  EXECUTION HALTED AT [{step_id.upper()}] — CRITICAL STEP FAILED")
            break

    log("\n" + "═" * 52)
    log("🏁  EXECUTION PROTOCOL COMPLETE")
    log("═" * 52 + "\n")

    return execution_state

def resume_plan(
    plan,
    execution_state,
    log_callback=None,
    python_runner=None
):
    """
    Continues a paused plan from the first unfinished step.
    """

    def log(msg):
        print(msg)

        if log_callback:
            log_callback(msg)

    found_resume_point = False

    for step in plan:

        step_id = step.get("step_id")

        if step_id not in execution_state:
            found_resume_point = True

        if not found_resume_point:
            continue

        tool = step.get("tool")
        raw_args = step.get("args", {})

        resolved_args = _resolve_args(
            raw_args,
            execution_state
        )

        resolved_args = _resolve_args(
            raw_args,
            execution_state
        )

        log(
            f"\n▸ [{step_id.upper()}] Resuming '{tool}'..."
        )

        if tool == "request_information":

            execution_state[step_id] = {
                "tool": tool,
                "args": resolved_args,
                "status": "waiting",
                "output": resolved_args.get(
                    "question",
                    ""
                )
            }

            log(
                f"  ? Waiting for user input: "
                f"{resolved_args.get('question')}"
            )

            break

        try:

            result = _dispatch(
                tool,
                resolved_args,
                python_runner=python_runner
            )

            execution_state[step_id] = {
                "tool": tool,
                "args": resolved_args,
                "status": "success",
                "output": result
            }

            log(f"  ✓ {result}")

        except Exception as e:

            execution_state[step_id] = {
                "tool": tool,
                "args": resolved_args,
                "status": "failed",
                "output": str(e)
            }

            log(f"  ✗ {e}")

            break

    return execution_state

def get_final_chat_output(execution_state: dict) -> str | None:
    """
    Helper used by verifier.py — searches execution_state for the last
    successful 'chat' step and returns its output string, or None.
    """
    # Walk in reverse order so we get the last chat step first
    for step_id in reversed(list(execution_state.keys())):
        state = execution_state[step_id]
        if state.get("tool") == "chat" and state.get("status") == "success":
            return state.get("output")
    return None