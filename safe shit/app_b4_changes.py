import customtkinter as ctk
import threading
import time
import queue
import sys
import os
import speech_recognition as sr
import asyncio
import edge_tts
import pygame
import tempfile
import uuid
import io
import contextlib
import re
import math
import random
import json

# Align static paths
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path: sys.path.insert(0, project_root)

from core import brain
from core import router
from core import planner
from core import executor
from core import verifier
import tools.entity_tools
from tools.tool_registry import print_registry

print_registry()

# --- UI STYLE & COLOR CONFIGURATION ---
ctk.set_appearance_mode("dark")
BG_COLOR = "#050508"          # Deepest black/blue
CARD_COLOR = "#0f111a"        # Dark UI panels
PRIMARY_GREEN = "#ffbf00"     # Changed to Cyber Gold to match the image
ACTIVE_ORANGE = "#ff5500"     # Deep transmission orange
TERMINAL_BLUE = "#ffd452"     # Light yellow/gold accents
TEXT_COLOR = "#e2e8f0"        
SB_BTN_HOVER = "#1a1d2e"      

FONT_FAMILY = "Segoe UI" if os.name == "nt" else "Helvetica Neue"
FONT_MAIN = (FONT_FAMILY, 13)
FONT_BOLD = (FONT_FAMILY, 14, "bold")
FONT_TITLE = (FONT_FAMILY, 16, "bold")

class CyberHUD(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("THE ENTITY DASHBOARD")
        self.geometry("1150x680")
        self.configure(fg_color=BG_COLOR)
        self.listening_enabled = False
        self.wake_detected = False
        
        pygame.mixer.init()
        # Planner persistence
        self.expecting_followup = False

        self.active_plan_context = []
        self.planning_mode = False

# Planner persistence
        self.pending_plan = None
        self.pending_state = None
        self.waiting_for_plan_input = False

        self.is_speaking = False

        self.ui_queue = queue.Queue()
        self.voice_model = "en-GB-SoniaNeural"
        
        # --- NATIVE 3D JARVIS VISUALIZER CONFIGURATION ---
        self.current_scale = 1.0
        self.target_scale = 1.0
        self.speech_tick = 0
        
        # Initialize 3D particle cloud points (X, Y, Z coordinates + point configurations)
        self.particles = []
        num_particles = 500
        for i in range(num_particles):
            # Assign particles across 4 distinct orbital rings with varying inclinations
            ring_id = i % 4
            angle = random.uniform(0, math.pi * 2)
            radius = 120 + random.uniform(-10, 10) + (ring_id * 25)
            
            # Mathematical inclination vectors to achieve multi-directional 3D orbits
            if ring_id == 0:
                tilt_x, tilt_y = 0.5, 0.8
                speed = 0.03
                color = "#ff7700"
            elif ring_id == 1:
                tilt_x, tilt_y = -0.6, 0.4
                speed = -0.02
                color = "#ffaa00"
            elif ring_id == 2:
                tilt_x, tilt_y = 0.8, -0.3
                speed = 0.04
                color = "#ffd452"
            else:
                tilt_x, tilt_y = -0.2, -0.7
                speed = -0.025
                color = "#cc5500"

            self.particles.append({
                "radius": radius,
                "angle": angle,
                "tilt_x": tilt_x,
                "tilt_y": tilt_y,
                "speed": speed,
                "base_color": color
            })
        
        self._build_interface()
        self.show_view("dashboard") 
        self.refresh_clock()
        self.after(500, self._start_background_tasks)
        self.gui_heartbeat_ticker()
        self.animate_core_visualizer() 

    def _build_interface(self):
        # Configured layout tags to expand components fluidly across the screen space
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1) 
        self.grid_rowconfigure(0, weight=0) 
        self.grid_rowconfigure(1, weight=1) 
        self.grid_rowconfigure(2, weight=0) 

        # --- SIDEBAR ---
        self.sidebar = ctk.CTkFrame(self, fg_color=CARD_COLOR, width=200, corner_radius=16)
        self.sidebar.grid(row=0, column=0, rowspan=3, sticky="nsew", padx=(12, 6), pady=12)
        self.sidebar.grid_propagate(False)
        
        lbl_brand = ctk.CTkLabel(self.sidebar, text="ENTITY OS", text_color=PRIMARY_GREEN, font=FONT_TITLE)
        lbl_brand.pack(pady=(20, 30))
        
        self.btn_dash = ctk.CTkButton(self.sidebar, text="DASHBOARD", font=FONT_BOLD, fg_color="transparent", 
                                      text_color=TEXT_COLOR, hover_color=SB_BTN_HOVER, height=40, corner_radius=8,
                                      command=lambda: self.show_view("dashboard"))
        self.btn_dash.pack(fill="x", padx=10, pady=5)
        
        self.btn_vis = ctk.CTkButton(self.sidebar, text="VISUALIZER", font=FONT_BOLD, fg_color="transparent", 
                                     text_color=TEXT_COLOR, hover_color=SB_BTN_HOVER, height=40, corner_radius=8,
                                     command=lambda: self.show_view("visualizer"))
        self.btn_vis.pack(fill="x", padx=10, pady=5)

        # --- TOP BAR ---
        self.top_frame = ctk.CTkFrame(self, fg_color=CARD_COLOR, height=50, corner_radius=16)
        self.top_frame.grid(row=0, column=1, sticky="ew", padx=(6, 12), pady=(12, 6))
        self.top_frame.grid_propagate(False)
        
        self.lbl_listener = ctk.CTkLabel(self.top_frame, text="● DAEMON: STANDBY", text_color=PRIMARY_GREEN, font=FONT_BOLD)
        self.lbl_listener.pack(side="left", padx=20)
        self.lbl_time = ctk.CTkLabel(self.top_frame, text="SYS_TIME: 00:00:00", text_color=TERMINAL_BLUE, font=FONT_MAIN)
        self.lbl_time.pack(side="right", padx=20)

        # --- DYNAMIC VIEWPORTS ---
        self.viewport_container = ctk.CTkFrame(self, fg_color="transparent")
        self.viewport_container.grid(row=1, column=1, sticky="nsew", padx=(6, 12), pady=6)
        
        # Added cell expand weight options to correct the screen maximization geometry issues
        self.viewport_container.grid_columnconfigure(0, weight=1)
        self.viewport_container.grid_rowconfigure(0, weight=1)
        
        self.dashboard_view = ctk.CTkFrame(self.viewport_container, fg_color="transparent")
        self.dashboard_view.grid_columnconfigure(0, weight=6)
        self.dashboard_view.grid_columnconfigure(1, weight=4)
        self.dashboard_view.grid_rowconfigure(0, weight=1)
        
        self.chat_history = ctk.CTkTextbox(self.dashboard_view, fg_color=CARD_COLOR, text_color=TEXT_COLOR, font=FONT_MAIN, wrap="word", state="disabled", corner_radius=16)
        self.chat_history.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        
        self.txt_terminal = ctk.CTkTextbox(self.dashboard_view, fg_color=CARD_COLOR, text_color=TERMINAL_BLUE, font=FONT_MAIN, wrap="word", state="disabled", corner_radius=16)
        self.txt_terminal.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        self.visualizer_view = ctk.CTkFrame(self.viewport_container, fg_color=CARD_COLOR, corner_radius=16)
        self.canvas = ctk.CTkCanvas(self.visualizer_view, bg=CARD_COLOR, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True, padx=20, pady=20)

        # --- BOTTOM BAR ---
        self.bottom_frame = ctk.CTkFrame(self, fg_color="transparent", height=40)
        self.bottom_frame.grid(row=2, column=1, sticky="ew", padx=(6, 12), pady=(6, 12))
        self.entry_cmd = ctk.CTkEntry(self.bottom_frame, placeholder_text="Manual command override...", fg_color=CARD_COLOR, text_color=TEXT_COLOR, font=FONT_MAIN, height=40, corner_radius=12, border_width=0)
        self.entry_cmd.pack(side="left", fill="x", expand=True)
        self.entry_cmd.bind("<Return>", lambda event: self._manual_override())

    def show_view(self, target_view):
        self.dashboard_view.grid_remove()
        self.visualizer_view.grid_remove()
        self.btn_dash.configure(fg_color="transparent")
        self.btn_vis.configure(fg_color="transparent")
        
        if target_view == "dashboard":
            self.dashboard_view.grid(row=0, column=0, sticky="nsew")
            self.btn_dash.configure(fg_color=SB_BTN_HOVER)
        elif target_view == "visualizer":
            self.visualizer_view.grid(row=0, column=0, sticky="nsew")
            self.btn_vis.configure(fg_color=SB_BTN_HOVER)

    def animate_core_visualizer(self):
        """Renders the true 3D multidirectional orbiting particles with deep depth of field."""
        self.canvas.delete("all")
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        
        if width > 10 and height > 10:
            cx, cy = width / 2, height / 2
            
            # Handle audio sync scale changes smoothly
            if self.is_speaking:
                self.speech_tick += 1
                if self.speech_tick % 3 == 0:
                    self.target_scale = random.uniform(1.3, 1.9)
            else:
                self.target_scale = 1.0 + (0.06 * math.sin(time.time() * 2.5))
                
            self.current_scale += (self.target_scale - self.current_scale) * 0.15
            
            # Perspective focal constant for depth mapping calculations
            focal_length = 300
            rendered_particles = []

            for p in self.particles:
                # Progress individual orbital path positions
                p["angle"] = (p["angle"] + p["speed"]) % (math.pi * 2)
                
                # Base ring spatial mapping calculation
                x_raw = math.cos(p["angle"]) * p["radius"] * self.current_scale
                y_raw = math.sin(p["angle"]) * p["radius"] * self.current_scale
                z_raw = math.sin(p["angle"] + 1.5) * p["radius"] * self.current_scale
                
                # Perform 3D orientation transformation using inclination variables
                x3d = x_raw
                y3d = y_raw * math.cos(p["tilt_x"]) - z_raw * math.sin(p["tilt_x"])
                z3d = y_raw * math.sin(p["tilt_y"]) + z_raw * math.cos(p["tilt_y"])
                
                # Shift structural axis back out into coordinate space depth
                z_depth = z3d + 400 
                
                if z_depth > 50:
                    # Apply classic perspective depth scaling factor calculation
                    scale_factor = focal_length / z_depth
                    screen_x = cx + (x3d * scale_factor)
                    screen_y = cy + (y3d * scale_factor)
                    
                    # Compute particle sizing variables using distance metrics
                    point_size = max(1, min(7, 3.5 * scale_factor))
                    
                    rendered_particles.append((z_depth, screen_x, screen_y, point_size, p["base_color"]))

            # Sort items to implement proper rendering layering based on distance values
            rendered_particles.sort(key=lambda item: item[0], reverse=True)

            # Draw points sequentially onto interface window layer stack
            for _, sx, sy, p_size, p_color in rendered_particles:
                self.canvas.create_oval(
                    sx - p_size, sy - p_size, 
                    sx + p_size, sy + p_size, 
                    fill=p_color, outline=""
                )

        self.after(25, self.animate_core_visualizer)

    def _write_to_box(self, box, text):
        box.configure(state="normal")
        box.insert("end", text + "\n")
        box.see("end")
        box.configure(state="disabled")

    def _manual_override(self):
        cmd = self.entry_cmd.get().strip()
        if cmd:
            self.entry_cmd.delete(0, 'end')
            threading.Thread(target=self.compile_pipeline_request, args=(cmd,), daemon=True).start()

    def refresh_clock(self):
        self.lbl_time.configure(text=f"SYS_TIME: {time.strftime('%H:%M:%S')}")
        self.after(1000, self.refresh_clock)

    def run_code_and_capture(self, code):
        """
        GUI-safe Python executor.

        This used to be a bare exec(code, {'__builtins__': __builtins__})
        with NO safety checks whatsoever — not even the substring blacklist
        that coder.py had. It's now routed through the same shared sandbox
        (security/sandbox.py) that the CLI path uses, so both surfaces get
        identical static-analysis checks, a real subprocess-level timeout,
        and file writes are actually risk-flagged.

        Because this runs on a background thread with no way to safely pop
        up a blocking confirmation dialog yet, any code that trips a
        CONFIRM-tier check (e.g. writing a file) is refused automatically
        rather than silently executed — safer default for hands-free/voice
        use. Run it from the console (main.py) instead if you need the
        interactive y/n prompt, or extend confirm_callback here with a
        proper CTk dialog if you want in-GUI confirmation.
        """
        # Remove markdown code blocks if the LLM includes them
        code = re.sub(r'^```python\s*', '', code, flags=re.IGNORECASE | re.MULTILINE)
        code = re.sub(r'^```\s*', '', code, flags=re.MULTILINE)
        code = re.sub(r'\s*```$', '', code, flags=re.MULTILINE)
        code = code.strip()

        from security.sandbox import run_sandboxed
        result = run_sandboxed(code, timeout=20, confirm_callback=None)
        if result.blocked:
            return f"Code Error: {result.as_message()}"
        return result.output

    def check_termination_gate(self, command):
        if "system down" in command.lower() or "shut down" in command.lower():
            self.ui_queue.put({"type": "chat", "sender": "ENTITY", "text": "Shutting down systems. Goodbye."})
            self.vocalize_response("Shutting down systems. Goodbye.")
            def kill_switch():
                time.sleep(0.5)
                while self.is_speaking: time.sleep(0.1)
                os._exit(0)
            threading.Thread(target=kill_switch, daemon=True).start()
            return True
        return False

    # ─────────────────────────────────────────────────────────────────────────
    # MAIN PIPELINE — PHASE 1 INTEGRATED
    # ─────────────────────────────────────────────────────────────────────────

    def compile_pipeline_request(self, command):
        """
        Central request handler. Routes commands through one of two pathways:

        PATH A — MULTI-STEP PLANNER (Phase 1)
            Triggered when planner.needs_planning() detects a multi-step intent.
            Flow: generate_plan → execute_plan → verify_and_report
            Streams each step's log output to the terminal panel in real time.

        PATH B — SINGLE-STEP (existing behaviour)
            Triggered for all simple, single-intent commands.
            Flow: brain.think → router.route  (or run_python directly)
            Preserves all original logic exactly as it was.
        """
        if self.check_termination_gate(command):
            return
        
        if self.waiting_for_plan_input:

            print(
                "DEBUG APP: received answer for pending plan"
            )

            waiting_step = None

            for step_id, data in self.pending_state.items():

                if data.get("status") == "waiting":
                    waiting_step = step_id
                    break

            if waiting_step:

                self.pending_state[waiting_step]["status"] = "success"
                self.pending_state[waiting_step]["output"] = command

                print(
                    f"DEBUG APP: stored answer '{command}' in {waiting_step}"
                )

                self.waiting_for_plan_input = False

                state = executor.resume_plan(
                    self.pending_plan,
                    self.pending_state,
                    python_runner=self.run_code_and_capture
                )

                print("\nDEBUG RESUME STATE:")
                print(json.dumps(state, indent=2))
                print()

                waiting_again = False

                for _, data in state.items():

                    if data.get("status") == "waiting":
                        waiting_again = True
                        break

                if waiting_again:

                    self.pending_state = state
                    self.waiting_for_plan_input = True

                    result_text = verifier.verify_and_report(
                    self.pending_plan,
                    state,
                        command
                    )

                else:

                    result_text = verifier.verify_and_report(
                        self.pending_plan,
                        state,
                        command
                    )

                    self.pending_plan = None
                    self.pending_state = None

                self.ui_queue.put({
                    "type": "chat",
                    "sender": "ENTITY",
                    "text": result_text
                })

                self.vocalize_response(result_text)

                return

        self.ui_queue.put({"type": "chat", "sender": "USER", "text": command})
        
        if self.planning_mode:
            self.active_plan_context.append(command)
        
        decision = planner.ai_needs_planning(command)

        print(
            f"DEBUG APP: planning decision = {decision}"
        )

        if decision:
            self.planning_mode = True
        else:
            self.planning_mode = False

        # ── PATH A: MULTI-STEP PLANNING PIPELINE ──────────────────────────────
        if not self.planning_mode:

            if planner.ai_needs_planning(command):
                self.planning_mode = True

        if self.planning_mode:

            if not self.active_plan_context:
                self.active_plan_context.append(command)

            self.ui_queue.put({
                "type": "state",
                "text": "● DAEMON: PLANNING...",
                "color": TERMINAL_BLUE
            })
            self.ui_queue.put({
                "type": "log",
                "text": f"[PLANNER] Analysing goal: {command}"
            })

            full_context = "\n".join(self.active_plan_context)
            plan = planner.generate_plan(full_context)

            # If the planner fails or returns something unusable, fall through
            # to the single-step path rather than returning an empty response.
            if not plan or len(plan) < 2:
                self.ui_queue.put({
                    "type": "log",
                    "text": "[PLANNER] Plan generation failed or returned a trivial result. Falling back to single-step."
                })
            else:
                # ── Display the plan in the terminal panel ──
                plan_lines = ["[PLANNER] Plan generated:"]
                for i, step in enumerate(plan):
                    tool = step.get("tool", "?")
                    args = step.get("args", {})
                    safe_args = json.dumps(args, ensure_ascii=False).replace("\\", "/")
                    plan_lines.append(f"  Step {i + 1}: {tool}({safe_args})")
                self.ui_queue.put({
                    "type": "log",
                    "text": "\n".join(plan_lines)
                })

                self.ui_queue.put({
                    "type": "state",
                    "text": "● DAEMON: EXECUTING PLAN...",
                    "color": ACTIVE_ORANGE
                })

                # ── Stream executor logs to the terminal panel ──
                def log_to_terminal(text: str):
                    self.ui_queue.put({"type": "log", "text": text})

                # ── Execute all plan steps using real tools ──
                # We pass self.run_code_and_capture as the python_runner so that
                # any run_python steps use the GUI-safe executor (no input() prompts
                # that would hang the background thread).
                state = executor.execute_plan(
                    plan,
                    log_callback=log_to_terminal,
                    python_runner=self.run_code_and_capture
                )

                waiting_step = None

                for step_id, data in state.items():
                    if data.get("status") == "waiting":
                        waiting_step = step_id
                        break

                if waiting_step:
                    self.pending_plan = plan
                    self.pending_state = state
                    self.waiting_for_plan_input = True

                    print(
                        f"DEBUG APP: Stored waiting plan at {waiting_step}"
                    )

                # ── Verify results and produce the spoken/chat response ──
                result_text = verifier.verify_and_report(plan, state, command)
                
                if result_text.strip().endswith("?"):
                    self.expecting_followup = True
                else:
                    self.expecting_followup = False

                if not self.expecting_followup:
                    self.planning_mode = False
                    self.active_plan_context.clear()

                self.ui_queue.put({"type": "chat", "sender": "ENTITY", "text": result_text})
                self.vocalize_response(result_text)
                self.expecting_followup = result_text.strip().endswith("?")
                # Return here — do NOT fall through to single-step path
                return

        # ── PATH B: SINGLE-STEP PIPELINE (original logic, fully preserved) ────
        self.ui_queue.put({
            "type": "state",
            "text": "● DAEMON: PROCESSING...",
            "color": TERMINAL_BLUE
        })

        intent = brain.think(command)

        if (
            isinstance(intent, dict)
            and intent.get("action") == "chat"
        ):

            value = intent.get("value", "")

            if isinstance(value, str):

                try:
                    parsed = json.loads(value)

                    if (
                        isinstance(parsed, dict)
                        and "value" in parsed
                    ):
                        intent["value"] = parsed["value"]

                except Exception:
                    pass

        if intent.get("action") == "run_python":

            code = intent.get("value", "")

            if not isinstance(code, str):
             code = str(code)

            code = code.strip()

            if code.startswith("```python"):
             code = code.replace("```python", "", 1)
            
            if code.startswith("```"):
             code = code.replace("```", "", 1)

            if code.endswith("```"):
                code = code[:-3]

            intent["value"] = code.strip()


            code_result = self.run_code_and_capture(intent.get("value"))

            
            # 1. Log the raw terminal output to the right-hand panel
            display_result = code_result if code_result else "Code executed successfully, no terminal output."
            self.ui_queue.put({"type": "log", "text": f"--- EXECUTION START ---\n{display_result}\n--- EXECUTION END ---"})
            
            # 2. Determine what Entity should say aloud
            if code_result and code_result.strip():
                # If your code printed something specific, speak it
                result_text = code_result.strip()
            else:
                # If code executed silently, ask the brain to confirm completion
                confirmation_intent = brain.think(
                    f"The user requested: '{command}'. The background script executed "
                    "successfully with no errors. Confirm completion to the user in one short sentence."
                )
                result_text = confirmation_intent.get("value") if isinstance(confirmation_intent, dict) else str(confirmation_intent)
                if not result_text or "run_python" in result_text: 
                    result_text = "Action completed successfully."

            self.ui_queue.put({"type": "chat", "sender": "ENTITY", "text": result_text})
        else:
            result_text = router.route(intent)

            if isinstance(result_text, dict):

                if "value" in result_text:
                    result_text = result_text["value"]
                else:
                    result_text = str(result_text)

            if result_text is None: result_text = ""

            self.ui_queue.put({"type": "chat", "sender": "ENTITY", "text": result_text})
        
        self.vocalize_response(result_text)
        self.expecting_followup = result_text.strip().endswith("?")
        #  Return system to idle after completing a command
        self.listening_enabled = False

    # ─────────────────────────────────────────────────────────────────────────
    # VOICE & UI SUPPORT (unchanged)
    # ─────────────────────────────────────────────────────────────────────────

    def vocalize_response(self, text):
        if not text.strip(): return
        clean_speech_text = re.sub(r'[*_~#`]', '', text) 
        self.is_speaking = True  
        
        def async_speak():
            self.ui_queue.put({"type": "state", "text": "● DAEMON: TRANSMITTING...", "color": ACTIVE_ORANGE})
            temp_file = os.path.join(tempfile.gettempdir(), f"entity_{uuid.uuid4()}.mp3")
            try:
                communicate = edge_tts.Communicate(clean_speech_text, voice=self.voice_model)
                asyncio.run(communicate.save(temp_file))
                pygame.mixer.music.load(temp_file)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy(): time.sleep(0.1)
                pygame.mixer.music.unload()
            except: pass
            finally:
                if os.path.exists(temp_file):
                    try: os.remove(temp_file)
                    except: pass
                self.is_speaking = False  
        threading.Thread(target=async_speak, daemon=True).start()

    def _start_background_tasks(self):
        def loop():
            recognizer = sr.Recognizer()
            recognizer.pause_threshold = 1.2  
            while True:
                if not self.listening_enabled and not self.expecting_followup:
                    self.ui_queue.put({
                        "type": "state",
                        "text": "● DAEMON: STANDBY",
                        "color": PRIMARY_GREEN
                    })
                    time.sleep(0.2)
                    continue
                if self.is_speaking:
                    self.ui_queue.put({"type": "state", "text": "● DAEMON: TRANSMITTING...", "color": ACTIVE_ORANGE})
                    while self.is_speaking: time.sleep(0.1)

                try:
                    with sr.Microphone() as mic:
                        if self.expecting_followup:
                            self.ui_queue.put({"type": "state", "text": "● DAEMON: AWAITING REPLY...", "color": ACTIVE_ORANGE})
                            audio = recognizer.listen(mic, timeout=15, phrase_time_limit=None)
                            self.ui_queue.put({"type": "state", "text": "● DAEMON: PROCESSING...", "color": TERMINAL_BLUE})
                            text = recognizer.recognize_google(audio)
                            self.expecting_followup = False
                            self.compile_pipeline_request(text)
                        else:
                            self.ui_queue.put({"type": "state", "text": "● DAEMON: STANDBY", "color": PRIMARY_GREEN})
                            recognizer.adjust_for_ambient_noise(mic, duration=0.3)
                            if not self.listening_enabled:
                                continue  # CRITICAL: do NOT listen yet
                            audio = recognizer.listen(mic, timeout=15, phrase_time_limit=None)
                            text = recognizer.recognize_google(audio).lower().strip()
                            
                            if "entity" in text or "jarvis" in text:
                                self.listening_enabled = True
                                self.ui_queue.put({
                                    "type": "state",
                                    "text": "● DAEMON: AWAITING COMMAND...",
                                    "color": PRIMARY_GREEN
                                })
                                continue

                            cmd = text.replace("entity", "").replace("jarvis", "").strip()

                            if cmd:
                                self.compile_pipeline_request(cmd)
                            
                            else:
                                wake_response = "Hello, how can I help you?"

                                self.ui_queue.put({
                                    "type": "chat",
                                    "sender": "The Entity",
                                    "text": wake_response
                                })

                                self.vocalize_response(wake_response)

                                self.expecting_followup = True

                except sr.WaitTimeoutError:
                    if self.expecting_followup:
                        self.expecting_followup = False
                        self.ui_queue.put({"type": "state", "text": "● DAEMON: STANDBY", "color": PRIMARY_GREEN})
                except sr.UnknownValueError: continue
                except Exception: continue
        threading.Thread(target=loop, daemon=True).start()

    def gui_heartbeat_ticker(self):
        try:
            while True:
                packet = self.ui_queue.get_nowait()
                if packet["type"] == "state": 
                    self.lbl_listener.configure(text=packet["text"], text_color=packet["color"])
                elif packet["type"] == "log":
                    self._write_to_box(self.txt_terminal, packet["text"])
                elif packet["type"] == "chat":
                    self._write_to_box(self.chat_history, f"{packet['sender']}: {packet['text']}\n")
        except queue.Empty: pass
        finally: self.after(100, self.gui_heartbeat_ticker)

if __name__ == "__main__":
    app = CyberHUD()
    app.mainloop()