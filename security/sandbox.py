"""
security/sandbox.py

Shared, meaningfully-restricted code execution for The Entity.

WHY THIS EXISTS
----------------
Previously there were THREE separate places that took LLM-generated Python
and handed it straight to exec() with full interpreter access:
  - coder.py                       (CLI path)
  - app.py:run_code_and_capture    (GUI path — had NO safety check at all)
  - experimental/agent_brain.py    (had NO safety check at all)

coder.py's only guard was a substring blacklist (`if "os.remove" in
code_string`), which is trivially defeated by anything that doesn't spell
the string out literally: getattr(os, "remove"), os.system("del ..."),
string concatenation, base64-encoded payloads, etc. The other two paths
had nothing at all.

WHAT THIS MODULE DOES
----------------------
1. Parses the code with `ast` (not string matching) and resolves import
   aliases, so `import os as o; o.system(...)` is caught the same as
   `os.system(...)`.
2. Hard-BLOCKS an import allowlist violation and a call blocklist of
   destructive/escape-prone operations (process spawning, file deletion,
   eval/exec/compile, dunder traversal used for sandbox-escape tricks like
   `().__class__.__bases__[0].__subclasses__()`).
3. Requires explicit human CONFIRMATION for a middle tier of "risky but
   sometimes legitimate" operations (writing files, moving/copying files,
   dynamic getattr-based calls).
4. Runs the (approved) code in a **separate subprocess** with a hard
   timeout, rather than exec()'ing it inside the running assistant process.
   This means a runaway or hanging script gets killed cleanly and can't
   directly corrupt the host process's memory/state.

HONEST LIMITS
--------------
This is a real improvement over a keyword blacklist, but it is a
*mitigation*, not a hard security boundary. The subprocess still runs as
your OS user account, so it still has your filesystem/network permissions
— static analysis reduces the attack surface but cannot catch every
possible bypass of a sufficiently adversarial payload. If you want an
actual security boundary (e.g. because this will run code sourced from
places you don't fully trust, like scraped web content), run it inside a
container, VM, or a restricted OS-level sandbox (Docker, firejail,
Windows Sandbox) instead of / in addition to this.
"""

import ast
import os
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass, field


# ── Modules with no legitimate use inside an LLM-authored run_python task ──
# (Dedicated tools already exist for opening apps, moving files, etc. —
# run_python is only meant to be used when no dedicated tool exists.)
MODULE_BLOCKLIST = {
    "subprocess", "ctypes", "winreg", "socket", "multiprocessing",
    "importlib", "pty", "pdb", "code", "mmap", "resource", "signal",
    "sysconfig",
}

# ── Specific calls that are always destructive / an escape vector ──
CALL_BLOCKLIST = {
    "os.system", "os.popen", "os.popen2", "os.popen3", "os.popen4",
    "os.execv", "os.execve", "os.execl", "os.execle", "os.execlp",
    "os.execlpe", "os.execvp", "os.execvpe",
    "os.spawnl", "os.spawnle", "os.spawnlp", "os.spawnv", "os.spawnve", "os.spawnvp",
    "os.remove", "os.unlink", "os.rmdir", "os.removedirs",
    "os.rename", "os.renames", "os.replace", "os.truncate",
    "os.chmod", "os.chown", "os.kill", "os.killpg", "os.fork", "os.startfile",
    "shutil.rmtree",
    "eval", "exec", "compile", "__import__", "globals", "locals", "vars",
}

# ── Calls that are sometimes legitimate but need a human to say yes ──
CALL_CONFIRM = {"shutil.move", "shutil.copy", "shutil.copy2", "shutil.copytree"}

# Dunder attributes used in the classic "walk back to __builtins__" escape.
DANGEROUS_DUNDERS = {
    "__subclasses__", "__bases__", "__mro__", "__globals__", "__builtins__",
    "__base__", "__code__", "__closure__", "__getattribute__",
    "__reduce__", "__reduce_ex__", "__class__",
}


@dataclass
class RiskReport:
    blocked: list = field(default_factory=list)
    needs_confirm: list = field(default_factory=list)

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
        report.blocked.append(f"Code has a syntax error and cannot be analyzed safely: {e}")
        return report

    import_alias = {}     # local name -> real module name (for `import X as Y`)
    from_alias = {}       # local name -> "module.member" (for `from X import Y as Z`)

    for node in ast.walk(tree):

        if isinstance(node, ast.Import):
            for alias in node.names:
                real = alias.name
                local = alias.asname or alias.name
                import_alias[local] = real
                top_level = real.split(".")[0]
                if top_level in MODULE_BLOCKLIST:
                    report.blocked.append(f"import of blocked module: {real}")

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            top_level = module.split(".")[0]
            if top_level in MODULE_BLOCKLIST:
                report.blocked.append(f"import from blocked module: {module}")
            for alias in node.names:
                local = alias.asname or alias.name
                from_alias[local] = f"{module}.{alias.name}"

        elif isinstance(node, ast.Attribute):
            if node.attr in DANGEROUS_DUNDERS:
                report.blocked.append(f"access to dangerous dunder attribute: .{node.attr}")

        elif isinstance(node, ast.Call):
            func = node.func
            candidate = None

            if isinstance(func, ast.Name):
                name = func.id
                candidate = from_alias.get(name, name)
                if name == "getattr":
                    report.needs_confirm.append(
                        "dynamic getattr(...) call — cannot be statically verified as safe"
                    )
            elif isinstance(func, ast.Attribute):
                candidate = _dotted_name(func, import_alias)
                if candidate is None:
                    report.needs_confirm.append(
                        "call on a dynamically-computed object — cannot be statically verified"
                    )

            if candidate:
                if candidate in CALL_BLOCKLIST or candidate.split(".")[-1] in {"eval", "exec", "compile", "__import__"}:
                    report.blocked.append(f"blocked call: {candidate}(...)")
                elif candidate in CALL_CONFIRM:
                    report.needs_confirm.append(f"requires confirmation: {candidate}(...)")
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
            return f"Execution refused by the safety sandbox:\n{reason_text}"
        if self.success:
            return f"Execution successful. Output:\n{self.output.strip()}" if self.output.strip() else "Execution successful. No output returned."
        return f"Execution FAILED. Error:\n{self.output}"


def run_sandboxed(code: str, timeout: int = 20, confirm_callback=None) -> SandboxResult:
    """
    The single entry point every run_python path should call.

    confirm_callback: optional callable(code: str, reasons: list[str]) -> bool
        Called only if the static analysis found CONFIRM-tier risks.
        Return True to proceed, False to refuse. If None, any CONFIRM-tier
        code is refused automatically (safe default for unattended/GUI use).
    """
    report = analyze_code(code)

    if report.is_blocked:
        return SandboxResult(success=False, output="", blocked=True, reasons=report.blocked)

    if report.needs_confirmation:
        approved = confirm_callback(code, report.needs_confirm) if confirm_callback else False
        if not approved:
            reasons = report.needs_confirm + (
                [] if confirm_callback else ["no confirmation channel available in this context — refused by default"]
            )
            return SandboxResult(success=False, output="", blocked=True, reasons=reasons)

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


def cli_confirm_callback(code: str, reasons: list) -> bool:
    """Interactive confirmation for the console (main.py / coder.py) path.

    If config.ENTITY_PIN is set (via the ENTITY_PIN env var), a plain "y"
    isn't enough — the PIN must be entered too. This is the one lightweight
    piece of access control in the project: previously anyone with mic or
    terminal access could authorize any action just by saying/typing "yes".
    """
    print("\n==================================================")
    print("SYSTEM ALERT: CONFIRMATION REQUIRED")
    print("==================================================")
    print("The Entity wants to run code that triggered these checks:")
    for r in reasons:
        print(f"  - {r}")
    print("---------------------------------")
    print(code)
    print("---------------------------------")
    answer = input("Do you authorize this execution? [y/n]: ")
    if answer.strip().lower() != "y":
        return False

    try:
        import config
        pin = getattr(config, "ENTITY_PIN", None)
    except Exception:
        pin = None

    if pin:
        entered = input("Enter PIN to confirm: ").strip()
        if entered != pin:
            print("[Execution Aborted] Incorrect PIN.")
            return False

    return True
