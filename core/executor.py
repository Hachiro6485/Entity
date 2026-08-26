import os
import shutil
import json
import traceback
import sys
import io
from tools.tool_registry import get_tool_function
import tools.entity_tools  # noqa: F401 — import side effect: this module's
# @entity_tool decorators are what populate TOOL_REGISTRY. Previously only
# app.py imported this, so get_tool_function() below only worked when the
# GUI happened to run first — importing it directly here means the plan
# executor's tool registry is populated regardless of which entry point
# (main.py, app.py, a test script) calls execute_plan() first.
import re

# ─────────────────────────────────────────────────────────────────────────────
# EXECUTION STATE
# A module-level dict that holds the output of every completed step so that
# subsequent steps can reference prior results via $step_N.output.
# Reset at the start of every new plan via execute_plan().
# ─────────────────────────────────────────────────────────────────────────────
execution_state: dict = {}


# ─────────────────────────────────────────────────────────────────────────────
# EXECUTION / SYSTEM TOOL IMPLEMENTATIONS
# run_python is handled here directly (not via the registry) because it
# needs the python_runner injection described below. Every other tool
# (create_folder, find_files, move_files, list_files, open_app, type_text,
# media_control, search_web, chat, delete_file, analyze_screen, ...) is
# implemented once in tools/entity_tools.py and reached through the
# registry in _dispatch() — this file used to carry a second, unused copy
# of each of those (_tool_create_folder, _tool_find_files, _tool_move_files,
# _tool_list_files, _tool_search_web, _tool_open_app, _tool_type_text,
# _tool_media_control, _tool_chat) that _dispatch() never actually called;
# removed as dead code so a future fix doesn't get applied to the wrong copy.
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