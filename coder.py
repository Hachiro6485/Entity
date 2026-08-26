"""
coder.py

CLI entry point for run_python. Execution logic lives in
security/sandbox.py and is shared by every execution path (CLI, GUI, and
the experimental agent) so a fix only has to be made once. File-interfering
code triggers the same PIN-gated confirmation as delete_file
(security/access_control.py) — everything else runs unrestricted.
"""

from security.sandbox import run_sandboxed


def execute_python(code_string, timeout: int = 20):
    """The main execution node called by router.py / core/executor.py."""
    result = run_sandboxed(code_string, timeout=timeout)
    return result.as_message()
