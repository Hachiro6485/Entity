"""
security/sandbox.py

Shared code execution for The Entity's run_python.

WHY THIS EXISTS
----------------
Previously there were THREE separate places that took LLM-generated Python
and handed it straight to exec() with full interpreter access:
  - coder.py                       (CLI path)
  - app.py:run_code_and_capture    (GUI path — had NO safety check at all)
  - experimental/agent_brain.py    (had NO safety check at all)

This module gave all three a shared static-analysis gate instead. That gate
was tightened in an earlier pass (blocking process-spawning, eval/exec,
sandbox-escape tricks, etc.) — it's since been loosened back down on
purpose (see POLICY below): run_python now has full interpreter access
again, EXCEPT for anything that touches the filesystem, which is routed
through the exact same human+PIN confirmation used by delete_file
(security/access_control.py) rather than refused outright.

POLICY
-------
1. Code that fails to parse (a real syntax error) is refused — nothing to
   run.
2. Code containing a file-interfering operation (see FILE_INTERFERING_CALLS
   and the open()-write-mode check below) triggers
   security.access_control.authorize_destructive_action() BEFORE anything
   runs — the same popup/CLI prompt delete_file uses: type DELETE, enter
   the Entity PIN. Declining refuses the whole run, not just that line.
3. Everything else — subprocess, ctypes, sockets, eval/exec, os.system,
   dynamic getattr, all of it — runs with no gate at all. This is a
   deliberate choice, not an oversight: it's a single-user local tool, and
   the useful 95% of run_python is exactly this kind of general-purpose
   scripting.
4. Approved code runs in a **separate subprocess** with a hard timeout, so
   a runaway/hanging script gets killed cleanly rather than hanging the
   assistant.

HONEST LIMIT: the file-interference check is static-analysis over the
Python file-I/O surface (os.*, shutil.*, open()). It can't see through
`os.system("del somefile.txt")` or an obfuscated equivalent — shelling out
is unrestricted by design now (see POLICY #3), so it can also be used to
touch files without tripping this specific gate. If that gap matters to
you, the fix isn't more static analysis — it's not giving run_python full
control back in the first place.
"""

import ast
import os
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass, field

from security.access_control import authorize_destructive_action


# ── The only thing run_python still gates: file-interfering operations ──
# Read-only file access (open in 'r' mode, os.listdir, os.path.exists, ...)
# is NOT included — only operations that delete, overwrite, move, rename,
# or change permissions on something that already exists.
FILE_INTERFERING_CALLS = {
    "os.remove", "os.unlink", "os.rmdir", "os.removedirs",
    "os.rename", "os.renames", "os.replace", "os.truncate",
    "os.chmod", "os.chown",
    "shutil.rmtree", "shutil.move", "shutil.copy", "shutil.copy2", "shutil.copytree",
}


@dataclass
class RiskReport:
    blocked: list = field(default_factory=list)          # unparseable code only
    needs_confirm: list = field(default_factory=list)     # file-interfering ops

    @property
    def is_blocked(self):
        return bool(self.blocked)

    @property
    def needs_confirmation(self):
        return bool(self.needs_confirm)


def _dotted_name(node, import_alias):
    """Resolve an ast.Attribute/ast.Name chain to a dotted string,
    substituting import aliases (e.g. `o` -> `os` for `import os as o`)."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        base = import_alias.get(node.id, node.id)
        parts.append(base)
        parts.reverse()
        return ".".join(parts)
    return None


def analyze_code(code: str) -> RiskReport:
    """Static analysis pass. Returns a RiskReport; does not execute anything."""
    report = RiskReport()

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        report.blocked.append(f"Code has a syntax error and cannot be run: {e}")
        return report

    import_alias = {}     # local name -> real module name (for `import X as Y`)
    from_alias = {}       # local name -> "module.member" (for `from X import Y as Z`)

    for node in ast.walk(tree):

        if isinstance(node, ast.Import):
            for alias in node.names:
                import_alias[alias.asname or alias.name] = alias.name

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                local = alias.asname or alias.name
                from_alias[local] = f"{module}.{alias.name}"

        elif isinstance(node, ast.Call):
            func = node.func
            candidate = None

            if isinstance(func, ast.Name):
                candidate = from_alias.get(func.id, func.id)
            elif isinstance(func, ast.Attribute):
                candidate = _dotted_name(func, import_alias)

            if candidate in FILE_INTERFERING_CALLS:
                report.needs_confirm.append(f"file operation: {candidate}(...)")
            elif candidate == "open":
                mode = ""
                if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                    mode = str(node.args[1].value)
                for kw in node.keywords:
                    if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                        mode = str(kw.value.value)
                if any(m in mode for m in ("w", "a", "x", "+")):
                    report.needs_confirm.append(f"open(..., mode='{mode or 'w'}') — writes to disk")

    return report


@dataclass
class SandboxResult:
    success: bool
    output: str
    blocked: bool = False
    reasons: list = field(default_factory=list)

    def as_message(self) -> str:
        if self.blocked:
            reason_text = "\n".join(f"  - {r}" for r in self.reasons)
            return f"Execution refused:\n{reason_text}"
        if self.success:
            return f"Execution successful. Output:\n{self.output.strip()}" if self.output.strip() else "Execution successful. No output returned."
        return f"Execution FAILED. Error:\n{self.output}"


def run_sandboxed(code: str, timeout: int = 20) -> SandboxResult:
    """
    The single entry point every run_python path calls.

    File-interfering code is gated by security.access_control's
    authorize_destructive_action() — the same popup/CLI prompt delete_file
    uses (typed DELETE + Entity PIN). It already knows how to reach the GUI
    dialog vs. the CLI prompt on its own (via set_gui_authorizer), so this
    function doesn't need its own confirm_callback plumbing anymore.
    """
    report = analyze_code(code)

    if report.is_blocked:
        return SandboxResult(success=False, output="", blocked=True, reasons=report.blocked)

    if report.needs_confirmation:
        preview = code if len(code) <= 800 else code[:800] + "\n... (truncated)"
        details = (
            "Flagged operations:\n"
            + "\n".join(f"- {r}" for r in report.needs_confirm)
            + "\n\nCode:\n" + preview
        )
        approved = authorize_destructive_action("RUN_PYTHON: FILE OPERATION", details)
        if not approved:
            return SandboxResult(
                success=False, output="", blocked=True,
                reasons=report.needs_confirm + ["authorization was not granted"]
            )

    # ── Run in a subprocess so a hang/infinite loop can be killed on timeout
    #    and so the code cannot directly touch the host process's memory. ──
    wrapped = textwrap.dedent(code)
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as tmp:
            tmp.write(wrapped)
            tmp_path = tmp.name

        try:
            proc = subprocess.run(
                [sys.executable, tmp_path],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        if proc.returncode != 0:
            return SandboxResult(success=False, output=proc.stderr or proc.stdout)

        return SandboxResult(success=True, output=proc.stdout)

    except subprocess.TimeoutExpired:
        return SandboxResult(success=False, output=f"Execution timed out after {timeout} seconds and was terminated.")
    except Exception as e:
        return SandboxResult(success=False, output=f"Sandbox execution error: {e}")
