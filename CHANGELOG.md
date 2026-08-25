# CHANGELOG — Security & Correctness Pass

This documents every change made to the original project, why, and what's
still on you to do. Read the **"before you run this"** section first.

## Before you run this

1. **Rotate every key that was in the original zip.** Five live-looking API
   keys (Groq, SambaNova, Cerebras, OpenRouter, Gemini) were hardcoded in
   plaintext across `core/brain.py`, `core/planner.py`, `core/verifier.py`,
   and `experimental/agent_brain.py`. They've been removed from source, but
   the *old* keys should be treated as burned — generate new ones at each
   provider's dashboard and revoke the old ones.
2. `pip install -r requirements.txt`
3. `cp .env.example .env` and fill in your new keys.
4. This is still a Windows-only app (winsound, Start Menu scanning,
   `os.environ["ProgramData"]`, pyautogui). I fixed logic bugs and security
   issues; I could not run the GUI, the mic loop, or TTS here, since none of
   that exists in a Linux sandbox. **Test `main.py` and `app.py` yourself
   before relying on this.**

## Critical fixes

- **Removed all 5 hardcoded API keys** from source. Provider config now
  lives in `core/providers.py`, loaded from environment variables via
  `python-dotenv`. A provider with no key configured is silently skipped
  rather than crashing anything. `brain.py`, `planner.py`, `verifier.py`,
  and `experimental/agent_brain.py` all now import from this single module
  instead of each keeping (and drifting from) their own copy.
- **Replaced the substring-blacklist code "safety gate" with real static
  analysis + a subprocess sandbox** (`security/sandbox.py`), used by every
  `run_python` path:
  - `coder.py` (CLI) — previously checked for literal text like
    `"os.remove"` in the code string, defeated by `getattr(os, "remove")`,
    `os.system("del ...")`, or basically any indirection at all.
  - `app.py`'s `run_code_and_capture` (GUI) — previously had **no check of
    any kind**, a bare `exec()`.
  - `experimental/agent_brain.py` — same, **no check of any kind**.

  The new sandbox: parses code with `ast` (not string matching) and
  resolves import aliases; hard-blocks process spawning, file deletion,
  `eval`/`exec`/`compile`, and the classic `().__class__.__bases__[0].
  __subclasses__()`-style dunder-traversal sandbox escape; requires human
  confirmation for file writes/moves/copies and dynamic `getattr()` calls;
  and runs approved code in a **separate subprocess with a real, enforced
  timeout** instead of `exec()`'ing inside the running assistant process.

  **This raises the bar substantially but is not a hard security
  boundary** — the subprocess still runs as your OS user, so it still has
  your filesystem/network permissions. If you'll ever feed it code derived
  from untrusted sources (e.g. scraped web content), put it inside an
  actual container or VM as well. See the module docstring in
  `security/sandbox.py` for the full threat-model note.

## High-severity fixes

- **Shell injection in `tools/basic_tools.py`'s `open_app`**: previously
  built `f"start {cmd}"` and ran it with `shell=True`, so shell
  metacharacters in an app name were interpreted by the shell rather than
  treated as a literal string. Now uses `subprocess.Popen(["cmd", "/c",
  "start", "", cmd], shell=False)` (a real argument list, not a shell
  string) plus an allowlist regex on the app name before it's used at all.

## Medium-severity fixes

- **Dead memory feature**: `main.py` builds `context = get_context()` and
  passes it to `brain.think(user_input, context)`, but `think()` never
  used the `memory_context` parameter — the assistant had zero real memory
  of prior turns despite the plumbing existing. It's now folded into the
  system prompt as recent conversation history (explicitly labeled as
  context, not instructions, to avoid it being misread as new commands).
- **Overly broad wake word**: `"up"` was in `WAKE_WORDS`, and the wake
  detector does a plain substring match — meaning almost any sentence
  containing the word "up" would activate a system with full computer
  control. Removed from the default list (`config.py`).
- **No access control**: added an opt-in `ENTITY_PIN` (set via `.env`).
  When set, the sandbox's confirmation prompt requires the PIN in addition
  to "y" before running anything flagged as risky. This is intentionally
  lightweight — a full auth layer for a voice assistant is a bigger design
  question than a drop-in patch should try to solve.
- **`get_vision_analysis` used to crash the whole import** if no Gemini key
  was set (`genai.Client(api_key="...")` was called unconditionally at
  module load). Now the client is only created if `GEMINI_API_KEY` is
  present; if missing, the vision tool returns a clear message instead of
  the app failing to start.

## Low-severity / correctness fixes

- **Logic bug in `brain.py`'s JSON-fallback parsing**: an indentation issue
  meant `return parsed` ran unconditionally instead of only when the parsed
  JSON actually had `"action"`/`"value"` keys, so malformed responses that
  merely looked like `{...}` were passed downstream as if valid (silently
  producing "Command unrecognized."). Fixed the indentation so it only
  returns on a genuinely valid shape.
- Removed stray empty duplicate folder (`the pictures fold`, likely an
  accidental rename artifact) and all `__pycache__`/`*.pyc` files from the
  archive.
- Added `.gitignore` (excludes `.env`, `__pycache__`, and
  `memory_storage/memory.json`) and `requirements.txt`.

## Follow-up fix (post-delivery)

- **Groq retired `llama-3.3-70b-versatile`** sometime after this project was
  originally written (and after my own training cutoff, so the original
  hardcoded model name was already stale by the time I reviewed the code).
  Default Groq model updated to `openai/gpt-oss-120b`, which is Groq's
  current general-purpose recommendation. More importantly: **every
  provider's model is now overridable via an env var**
  (`GROQ_MODEL`, `SAMBANOVA_MODEL`, `CEREBRAS_MODEL`, `OPENROUTER_MODEL` in
  `.env`) instead of hardcoded, so the next time a provider renames or
  retires a model, it's a one-line `.env` edit instead of a code change.
  If you hit a `model_not_found` 404 again, check the provider's current
  model list and set the matching env var.

## Feature addition (post-delivery)

- **Added a hard mute toggle to the GUI** (`app.py`), styled like a
  call-mute button, plus a `Ctrl+M` shortcut. This is enforced in
  `perception/speech_to_text.py`'s `record_audio()` — the one place both
  the GUI and CLI actually open the microphone — so muting genuinely means
  the mic is never opened while muted, not a UI flag the voice loop could
  ignore. One honest caveat: if you hit mute while already inside a
  blocking `recognizer.listen()` call, it takes effect at the start of the
  next listen cycle rather than instantly mid-capture; the wake-word poll's
  timeout was shortened from 15s to 4s specifically to bound that window.
  Typed commands in the manual-override box are unaffected by mute.

## Visualizer redesign (post-delivery)

- **Replaced the static 3D orbital particle cloud with an interactive 2D
  particle network** (`app.py`'s `animate_core_visualizer`), based on a
  reference video of the "particles.js"-style effect (drifting dots,
  lines connecting nearby particles, lines connecting to the cursor when
  it's close). Two variants were prototyped first — a flat 2D network and
  a hybrid that kept the 3D orbit and added cursor links — the 2D network
  was chosen.
  - Particle count dropped from 500 to 90: the network draws a line for
    every nearby *pair* of particles (O(n^2)), so 500 would mean up to
    ~125,000 distance checks per frame: 90 keeps it comfortably fast at
    ~40fps while still looking dense.
  - tkinter Canvas lines don't support real alpha transparency, so line
    "fade by distance" is faked by blending the line color toward the
    canvas's actual background color (`_blend_color()`) — this only looks
    right if the blend target matches the canvas's real bg color
    (`CARD_COLOR`), not the outer window background.
  - Mouse position is tracked via `<Motion>`/`<Leave>` bindings on the
    canvas itself (`self.mouse_x`/`self.mouse_y`), so links to the cursor
    only draw while the mouse is actually over the visualizer.
  - The old speech-reactive pulse (scale animation) is now a speed +
    reach + brightness boost on the network instead, to keep some visual
    "is it talking" feedback.
  - Verified with a real headless tkinter render (Xvfb) exercising the
    exact drawing calls used in `app.py`, not just a mockup — confirmed
    the cursor-starburst pattern renders correctly.

## Deliberately left unchanged

- The `open_app` logic duplication between `core/router.py` and
  `tools/system_control.py` (the router version adds web-shortcut
  handling on top). Both are now free of the shell-injection issue where
  applicable, but I didn't merge them — doing so risked changing behavior
  in ways I couldn't test without a Windows machine in front of me.
- `memory_storage/memory.json` conversation history — left as-is (it's your
  existing data), just added to `.gitignore` going forward so it doesn't
  get committed if you put this in git.
