"""
coder.py

CLI entry point for run_python. This used to contain its own exec() call
and a substring-based "safety gate" (`is_dangerous()`, checking for
literal text like "os.remove" in the code string) — that logic now lives
in security/sandbox.py and is shared by every execution path (CLI, GUI,
and the experimental agent) so a fix only has to be made once, and so the
GUI path can't silently ship with zero protection the way it did before.
"""

from security.sandbox import run_sandboxed, cli_confirm_callback


def execute_python(code_string, timeout: int = 20):
    """The main execution node called by router.py / core/executor.py."""
    result = run_sandboxed(code_string, timeout=timeout, confirm_callback=cli_confirm_callback)
    return result.as_message()
