import customtkinter as ctk
import threading
import time
import queue
import sys
import os
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
import config
from security.access_control import set_gui_authorizer

# Align static paths
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path: sys.path.insert(0, project_root)

from core import brain
from core import router
from core import planner
from core import executor
from core import verifier
from core.humanizer import humanize_for_speech
import tools.entity_tools
from tools.tool_registry import print_registry
from memory.memory import get_context, add_memory
from perception.speech_to_text import (
    listen_for_wake_word,
    listen_for_command,
    remove_wake_words,
    set_muted,
    is_muted
)

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

MUTED_GREY = "#555555"

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
        
        # --- INTERACTIVE 2D PARTICLE NETWORK CONFIGURATION ---
        # Replaced the static 3D orbital cloud with a drifting network that
        # actually reacts to you: particles wander slowly, link to nearby
        # particles, and link to the cursor when it's in range — the "call
        # mute button" style effect, applied to the visualizer.
        self.current_scale = 1.0
        self.target_scale = 1.0
        self.speech_tick = 0

        self.mouse_x = None
        self.mouse_y = None

        # Bumped from 90 for a denser, livelier network. Benchmarked
        # headlessly first (O(n^2) pairwise distance checks run every frame
        # for particle-to-particle links): 160 sits comfortably under the
        # 25ms/frame budget this loop targets (~19ms/frame in a pessimistic
        # software-rendered test — real GPU-accelerated Tk on your machine
        # should do better). Push higher if your machine handles it fine;
        # drop back toward 90 if it visibly chugs.
        self.particles = []
        num_particles = 160
        for i in range(num_particles):
            self.particles.append({
                "x": random.uniform(0, 900),
                "y": random.uniform(0, 500),
                "vx": random.uniform(-0.25, 0.25),
                "vy": random.uniform(-0.25, 0.25),
            })
        
        self._build_interface()
        set_gui_authorizer(
            self._authorize_destructive_action
        )
        self.show_view("dashboard") 
        self.refresh_clock()
        self.after(500, self._start_background_tasks)
        self.gui_heartbeat_ticker()
        self.animate_core_visualizer()
        self.bind("<Control-m>", lambda event: self.toggle_mute())

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

        # --- MUTE TOGGLE (call-style hard mute) ---
        # Ctrl+M also toggles this — see the bind() call at the end of __init__.
        self.btn_mute = ctk.CTkButton(
            self.top_frame, text="🎤  MUTE", font=FONT_BOLD,
            fg_color="transparent", text_color=TEXT_COLOR,
            hover_color=SB_BTN_HOVER, border_width=1, border_color=PRIMARY_GREEN,
            width=120, height=32, corner_radius=8,
            command=self.toggle_mute
        )
        self.btn_mute.pack(side="right", padx=(0, 10))

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
        self.canvas.bind("<Motion>", self._on_canvas_motion)
        self.canvas.bind("<Leave>", self._on_canvas_leave)

        # --- BOTTOM BAR ---
        self.bottom_frame = ctk.CTkFrame(self, fg_color="transparent", height=40)
        self.bottom_frame.grid(row=2, column=1, sticky="ew", padx=(6, 12), pady=(6, 12))
        self.entry_cmd = ctk.CTkEntry(self.bottom_frame, placeholder_text="Manual command override...", fg_color=CARD_COLOR, text_color=TEXT_COLOR, font=FONT_MAIN, height=40, corner_radius=12, border_width=0)
        self.entry_cmd.pack(side="left", fill="x", expand=True)
        self.entry_cmd.bind("<Return>", lambda event: self._manual_override())

    def toggle_mute(self):
        """
        Hard mute toggle — enforced in perception/speech_to_text.py's
        record_audio(), so this isn't just a UI state flip that the voice
        loop might ignore: while muted, the microphone is never opened.

        Caveat worth knowing: if you hit mute mid-listen (the loop is
        already inside a blocking recognizer.listen() call), it takes
        effect at the start of the *next* listen cycle rather than
        instantly — bounded to a few seconds by the short wake-word poll
        timeout, not mid-sentence. Typed commands in the box below still
        work while muted; this only affects the microphone.
        """
        muted = not is_muted()
        set_muted(muted)

        if muted:
            self.btn_mute.configure(text="🔇  MUTED", fg_color=ACTIVE_ORANGE, text_color="#050508", border_color=ACTIVE_ORANGE)
            self.lbl_listener.configure(text="● DAEMON: MUTED", text_color=MUTED_GREY)
            self._write_to_box(self.txt_terminal, "[VOICE] Microphone muted by user.\n")
        else:
            self.btn_mute.configure(text="🎤  MUTE", fg_color="transparent", text_color=TEXT_COLOR, border_color=PRIMARY_GREEN)
            self._write_to_box(self.txt_terminal, "[VOICE] Microphone unmuted.\n")

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

    def _on_canvas_motion(self, event):
        self.mouse_x = event.x
        self.mouse_y = event.y

    def _on_canvas_leave(self, event):
        self.mouse_x = None
        self.mouse_y = None

    def _blend_color(self, hex_color, bg_hex, fraction):
        """Fakes per-line alpha (tkinter Canvas lines don't support real
        transparency) by blending toward the canvas background color —
        fraction=0 is full hex_color, fraction=1 is fully invisible."""
        fraction = max(0.0, min(1.0, fraction))
        c1 = tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
        c2 = tuple(int(bg_hex[i:i + 2], 16) for i in (1, 3, 5))
        blended = tuple(int(c1[k] + (c2[k] - c1[k]) * fraction) for k in range(3))
        return "#%02x%02x%02x" % blended

    def animate_core_visualizer(self):
        """
        Interactive 2D particle network.

        Replaces the old static 3D orbital cloud: particles drift slowly
        and wrap at the edges, link to nearby particles (line brightness
        fades with distance), and link to the cursor when it's within
        range — same effect as a "particles.js"-style background, just
        drawn on a tkinter Canvas instead of a web canvas.

        Speaking gives the whole network a brief "excited" pulse (faster
        drift + longer cursor reach + brighter dots), echoing what the old
        scale-pulse effect was going for.
        """
        self.canvas.delete("all")
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()

        if width > 10 and height > 10:
            LINK_DIST = 110
            MOUSE_DIST = 150

            speed_mult = 1.0
            mouse_reach = MOUSE_DIST
            if self.is_speaking:
                self.speech_tick += 1
                speed_mult = 2.2
                mouse_reach = MOUSE_DIST * 1.3

            for p in self.particles:
                p["x"] = (p["x"] + p["vx"] * speed_mult) % width
                p["y"] = (p["y"] + p["vy"] * speed_mult) % height

            n = len(self.particles)

            # Particle-to-particle links
            for i in range(n):
                pi = self.particles[i]
                for j in range(i + 1, n):
                    pj = self.particles[j]
                    d = math.hypot(pi["x"] - pj["x"], pi["y"] - pj["y"])
                    if d < LINK_DIST:
                        fraction = 0.15 + (d / LINK_DIST) * 0.75
                        color = self._blend_color(PRIMARY_GREEN, CARD_COLOR, fraction)
                        self.canvas.create_line(pi["x"], pi["y"], pj["x"], pj["y"], fill=color)

            # Cursor links
            if self.mouse_x is not None:
                for p in self.particles:
                    d = math.hypot(p["x"] - self.mouse_x, p["y"] - self.mouse_y)
                    if d < mouse_reach:
                        fraction = (d / mouse_reach) * 0.75
                        color = self._blend_color(ACTIVE_ORANGE, CARD_COLOR, fraction)
                        self.canvas.create_line(p["x"], p["y"], self.mouse_x, self.mouse_y, fill=color, width=1.4)

            dot_color = ACTIVE_ORANGE if self.is_speaking else PRIMARY_GREEN
            for p in self.particles:
                self.canvas.create_oval(p["x"] - 1.6, p["y"] - 1.6, p["x"] + 1.6, p["y"] + 1.6, fill=dot_color, outline="")

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
        GUI-safe Python executor. run_python has full interpreter access —
        the only gate is file-interfering operations (delete/move/rename/
        overwrite/chmod), which trigger the exact same PIN-gated popup as
        delete_file (self._authorize_destructive_action, wired in __init__
        via set_gui_authorizer). security/sandbox.py's
        authorize_destructive_action() call already resolves to that GUI
        dialog on its own, so no extra plumbing is needed here — this
        method still runs on a background thread, and the dialog-scheduling
        is handled inside _authorize_destructive_action itself.
        """
        # Remove markdown code blocks if the LLM includes them
        code = re.sub(r'^```python\s*', '', code, flags=re.IGNORECASE | re.MULTILINE)
        code = re.sub(r'^```\s*', '', code, flags=re.MULTILINE)
        code = re.sub(r'\s*```$', '', code, flags=re.MULTILINE)
        code = code.strip()

        from security.sandbox import run_sandboxed

        result = run_sandboxed(code, timeout=20)

# ---------------------------------------------------------
# HARD FAILURE PROPAGATION
#
# The sandbox distinguishes between:
#
#   success=True
#       Python actually ran successfully.
#
#   success=False
#       Python crashed, timed out, or otherwise failed.
#
# The executor relies on exceptions to mark a step as
# "failed" and stop the plan.
#
# Do NOT return a failed Python result as a normal string,
# because the planner could mistake the traceback for valid
# output and pass it into a later tool.
# ---------------------------------------------------------

        if result.blocked:
            raise RuntimeError(
                result.as_message()
            )

        if not result.success:
            raise RuntimeError(
                result.as_message()
            )

        return result.output

    def _authorize_destructive_action(
        self,
        action_name,
        details
    ):
        """
        Secure GUI authorization for destructive actions.

        The actual dialog is created on the Tkinter main thread.
        The worker thread waits for the user's decision.

        IMPORTANT:
        The PIN is checked locally against config.ENTITY_PIN.
        It is never sent to the AI.
        """

        result = {
            "approved": False
        }

        finished = threading.Event()

        def show_dialog():

            dialog = ctk.CTkToplevel(self)

            dialog.title("ENTITY SECURITY")
            dialog.geometry("520x360")
            dialog.resizable(False, False)
            dialog.configure(fg_color=BG_COLOR)

            dialog.transient(self)
            dialog.grab_set()

            # ---------------------------------------------------------
            # TITLE
            # ---------------------------------------------------------

            title_label = ctk.CTkLabel(
                dialog,
                text="⚠  SECURITY AUTHORIZATION REQUIRED",
                text_color=ACTIVE_ORANGE,
                font=FONT_TITLE
            )

            title_label.pack(
                pady=(25, 15)
            )

            # ---------------------------------------------------------
            # ACTION
            # ---------------------------------------------------------

            action_label = ctk.CTkLabel(
                dialog,
                text=f"Action: {action_name}",
                text_color=TEXT_COLOR,
                font=FONT_BOLD
            )

            action_label.pack(
                pady=(0, 10)
            )

            # ---------------------------------------------------------
            # TARGET / DETAILS
            # ---------------------------------------------------------
            # Use a scrollable textbox instead of a label so long AI-generated
            # code or other destructive-action details remain fully visible.
            # CTkTextbox provides its own vertical scrollbar and mouse-wheel
            # scrolling, while keeping the popup at a fixed size.

            target_box = ctk.CTkTextbox(
                dialog,
                width=460,
                height=115,
                text_color=TEXT_COLOR,
                font=(FONT_FAMILY, 11),
                wrap="none",
                corner_radius=8
            )

            target_box.pack(
                pady=(0, 15),
                padx=20,
                fill="x"
            )

            target_box.insert(
                "1.0",
                f"Target:\n{details}"
            )

            target_box.configure(
                state="disabled"
            )

            # Make sure the mouse wheel scrolls the details/code box when the
            # cursor is over it. This is especially useful for long Python code.
            target_box.bind(
                "<MouseWheel>",
                lambda event: target_box.yview_scroll(
                    int(-1 * (event.delta / 120)),
                    "units"
                )
            )

            # ---------------------------------------------------------
            # WARNING
            # ---------------------------------------------------------

            warning_label = ctk.CTkLabel(
                dialog,
                text=(
                    "This action may permanently change data.\n"
                    "Type YES and enter your Entity PIN to continue."
                ),
                text_color=TERMINAL_BLUE,
                font=FONT_MAIN,
                wraplength=450
            )

            warning_label.pack(
                pady=(0, 12)
            )

            # ---------------------------------------------------------
            # DELETE CONFIRMATION
            # ---------------------------------------------------------

            confirmation_entry = ctk.CTkEntry(
                dialog,
                placeholder_text="Type YES",
                width=360,
                height=40
            )

            confirmation_entry.pack(
                pady=5
            )

            # ---------------------------------------------------------
            # PIN
            # ---------------------------------------------------------

            pin_entry = ctk.CTkEntry(
                dialog,
                placeholder_text="Entity PIN",
                width=360,
                height=40,
                show="*"
            )

            pin_entry.pack(
                pady=5
            )

            # ---------------------------------------------------------
            # STATUS
            # ---------------------------------------------------------

            status_label = ctk.CTkLabel(
                dialog,
                text="",
                text_color=ACTIVE_ORANGE,
                font=FONT_MAIN
            )

            status_label.pack(
                pady=5
            )

            # ---------------------------------------------------------
            # FINISH FUNCTION
            # ---------------------------------------------------------

            def finish(approved):

                result["approved"] = approved

                try:
                    dialog.grab_release()
                except Exception:
                    pass

                try:
                    dialog.destroy()
                except Exception:
                    pass

                finished.set()

            # ---------------------------------------------------------
            # CANCEL
            # ---------------------------------------------------------

            def cancel():

                finish(False)

            # ---------------------------------------------------------
            # AUTHORIZE
            # ---------------------------------------------------------

            def approve():

                confirmation = (
                    confirmation_entry
                    .get()
                    .strip()
                )

                entered_pin = (
                    pin_entry
                    .get()
                    .strip()
                )

                configured_pin = getattr(
                    config,
                    "ENTITY_PIN",
                    None
                )

                # -----------------------------------------------------
                # Check DELETE
                # -----------------------------------------------------

                if confirmation != "YES":

                    status_label.configure(
                        text="You must type YES exactly."
                    )

                    confirmation_entry.focus_set()

                    return

                # -----------------------------------------------------
                # Check PIN exists
                # -----------------------------------------------------

                if not configured_pin:

                    status_label.configure(
                        text="ENTITY_PIN is not configured."
                    )

                    return

                # -----------------------------------------------------
                # Check PIN
                # -----------------------------------------------------

                if entered_pin != configured_pin:

                    status_label.configure(
                        text="Incorrect Entity PIN."
                    )

                    pin_entry.delete(
                        0,
                        "end"
                    )

                    pin_entry.focus_set()

                    return

                # -----------------------------------------------------
                # EVERYTHING IS CORRECT
                # -----------------------------------------------------

                print(
                    "[SECURITY] GUI authorization accepted."
                )

                finish(True)

            # ---------------------------------------------------------
            # BUTTONS
            # ---------------------------------------------------------

            button_frame = ctk.CTkFrame(
                dialog,
                fg_color="transparent"
            )

            button_frame.pack(
                pady=15
            )

            cancel_button = ctk.CTkButton(
                button_frame,
                text="CANCEL",
                fg_color="#333333",
                hover_color="#444444",
                width=140,
                height=40,
                command=cancel
            )

            cancel_button.pack(
                side="left",
                padx=10
            )

            approve_button = ctk.CTkButton(
                button_frame,
                text="AUTHORIZE DELETE",
                fg_color=ACTIVE_ORANGE,
                hover_color="#ff7733",
                width=180,
                height=40,
                command=approve
            )

            approve_button.pack(
                side="left",
                padx=10
            )

            # ---------------------------------------------------------
            # WINDOW CLOSE BUTTON
            # ---------------------------------------------------------

            dialog.protocol(
                "WM_DELETE_WINDOW",
                cancel
            )

            # ---------------------------------------------------------
            # ENTER KEY
            # ---------------------------------------------------------

            pin_entry.bind(
                "<Return>",
                lambda event: approve()
            )

            confirmation_entry.bind(
                "<Return>",
                lambda event: pin_entry.focus_set()
            )

            confirmation_entry.focus_set()

        # -------------------------------------------------------------
        # Schedule dialog creation on Tkinter's main thread.
        # -------------------------------------------------------------

        self.after(
            0,
            show_dialog
        )

        # -------------------------------------------------------------
        # Worker thread waits here.
        # Tkinter itself remains free to process the dialog.
        # -------------------------------------------------------------

        finished.wait()

        return result["approved"]

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

        # This gives the AI the conversation that happened BEFORE this request.
        memory_context = get_context()

        # Save the user's new message so future requests can remember it.
        add_memory(f"User: {command}")

        waiting_step = None
        
        if self.waiting_for_plan_input:

            print(
                "DEBUG APP: received answer for pending plan"
            )


            for step_id, data in self.pending_state.items():

                if data.get("status") == "waiting":
                    waiting_step = step_id
                    break

        if waiting_step:

            print(
                "DEBUG APP: received answer for pending plan"
            )

            print(
                f"DEBUG APP: received information: '{command}'"
            )

    # ---------------------------------------------------------
    # The old plan has now reached the point where information
    # was missing.
    #
    # DO NOT blindly resume the old plan.
    #
    # The old plan was generated before the user's answer was
    # known, so its remaining steps may contain assumptions
    # based on missing information.
    #
    # Instead, rebuild the plan using:
    #
    #   1. The original user goal
    #   2. The user's newly supplied information
    #
    # This lets the planner create the correct tool calls.
    # ---------------------------------------------------------

            original_goal = "\n".join(
                self.active_plan_context
            )

            replanning_context = (
                f"Original user request:\n"
                f"{original_goal}\n\n"
                f"Additional information supplied by the user:\n"
                f"{command}\n\n"
                f"Use the new information to continue the original request. "
                f"Do not ask for information that has already been provided."
            )

            print(
                "DEBUG APP: Replanning with supplied information..."
            )

            new_plan = planner.generate_plan(
                replanning_context
            )

            if not new_plan:

                result_text = (
                    "I couldn't continue the task because "
                    "I was unable to generate the next steps."
                )

                self.pending_plan = None
                self.pending_state = None
                self.waiting_for_plan_input = False
                self.planning_mode = False
                self.active_plan_context.clear()

                self.ui_queue.put({
                    "type": "chat",
                    "sender": "ENTITY",
                    "text": result_text
                })

                add_memory(
                    f"The Entity: {result_text}"
                )

                self.vocalize_response(
                    result_text
                )

                return

    # ---------------------------------------------------------
    # Replace the old waiting plan with the newly generated
    # plan.
    # ---------------------------------------------------------

            self.pending_plan = None
            self.pending_state = None
            self.waiting_for_plan_input = False

            self.ui_queue.put({
                "type": "state",
                "text": "● DAEMON: EXECUTING PLAN...",
                "color": ACTIVE_ORANGE
            })

            self.ui_queue.put({
                "type": "log",
                "text": "[PLANNER] Rebuilt plan using the information supplied by the user."
            })

            def log_to_terminal(text: str):
                self.ui_queue.put({
                    "type": "log",
                    "text": text
                })

            state = executor.execute_plan(
                new_plan,
                log_callback=log_to_terminal,
                python_runner=self.run_code_and_capture
            )

    # ---------------------------------------------------------
    # Check whether the new plan needs another question.
    # ---------------------------------------------------------

            waiting_again = False

            for step_id, data in state.items():

                if data.get("status") == "waiting":

                    waiting_again = True
                    break

            if waiting_again:

                self.pending_plan = new_plan
                self.pending_state = state
                self.waiting_for_plan_input = True

            else:

                self.pending_plan = None
                self.pending_state = None

            result_text = verifier.verify_and_report(
                new_plan,
                state,
                original_goal
            )

            self.ui_queue.put({
                "type": "chat",
                "sender": "ENTITY",
                "text": result_text
            })

            add_memory(
                    f"The Entity: {result_text}"
            )

            self.vocalize_response(
                result_text
            )

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

                add_memory(f"The Entity: {result_text}")

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

        intent = brain.think(command, memory_context)

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
        self.is_speaking = True

        def async_speak():
            self.ui_queue.put({"type": "state", "text": "● DAEMON: TRANSMITTING...", "color": ACTIVE_ORANGE})
            # Rewritten for natural spoken delivery here, inside the already-
            # spawned background thread — not before it, so the LLM
            # round-trip never risks blocking the Tkinter main thread
            # regardless of which thread called vocalize_response().
            # Supersedes the old symbol-stripping regex (core/humanizer.py's
            # fallback path covers that same ground if every provider is down).
            clean_speech_text = humanize_for_speech(text)
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
        """
        Starts the Entity's background voice daemon.

        State machine:

            IDLE
              ↓
            LISTEN FOR WAKE WORD
              ↓
            WAKE DETECTED
              ↓
            AWAITING COMMAND
              ↓
            PROCESSING
              ↓
            TRANSMITTING
              ↓
            IDLE
        """

        def loop():

            while True:

                try:

                    # ============================================================
                    # WAIT UNTIL ENTITY FINISHES SPEAKING
                    # ============================================================

                    if self.is_speaking:

                        self.ui_queue.put({
                            "type": "state",
                            "text": "● DAEMON: TRANSMITTING...",
                            "color": ACTIVE_ORANGE
                        })

                        while self.is_speaking:
                            time.sleep(0.1)

                    # ============================================================
                    # MUTED — skip listening entirely, don't open the mic
                    # ============================================================

                    if is_muted():

                        self.ui_queue.put({
                            "type": "state",
                            "text": "● DAEMON: MUTED",
                            "color": MUTED_GREY
                        })

                        time.sleep(0.2)
                        continue

                    # ============================================================
                    # FOLLOW-UP MODE
                    # ============================================================

                    if self.expecting_followup:

                        self.ui_queue.put({
                            "type": "state",
                            "text": "● DAEMON: AWAITING REPLY...",
                            "color": ACTIVE_ORANGE
                        })

                        command = listen_for_command()

                        if command:

                            self.expecting_followup = False

                            self.compile_pipeline_request(
                                command
                            )

                        else:

                            self.expecting_followup = False

                        continue

                    # ============================================================
                    # IDLE MODE
                    # ============================================================

                    self.listening_enabled = False

                    self.ui_queue.put({
                        "type": "state",
                        "text": "● DAEMON: LISTENING FOR WAKE WORD...",
                        "color": PRIMARY_GREEN
                    })

                    detected, transcript = listen_for_wake_word()

                    if not detected:
                        continue

                    # ============================================================
                    # WAKE WORD DETECTED
                    # ============================================================

                    self.listening_enabled = True

                    print(
                        f"DEBUG VOICE: Wake detected: "
                        f"{transcript}"
                    )

                    self.ui_queue.put({
                        "type": "log",
                        "text": f"[VOICE] Wake word detected: {transcript}"
                    })

                    self.ui_queue.put({
                        "type": "state",
                        "text": "● DAEMON: AWAITING COMMAND...",
                        "color": PRIMARY_GREEN
                    })

                    command = remove_wake_words(transcript)

                    # ============================================================
                    # WAKE WORD ONLY
                    # ============================================================

                    if not command:

                        wake_response = "Yes?"

                        self.ui_queue.put({
                            "type": "chat",
                            "sender": "ENTITY",
                            "text": wake_response
                        })

                        self.vocalize_response(wake_response)

                        command = listen_for_command()

                        if not command:

                            self.listening_enabled = False

                            continue

                    # ============================================================
                    # COMMAND RECEIVED
                    # ============================================================

                    self.listening_enabled = True

                    self.ui_queue.put({
                        "type": "state",
                        "text": "● DAEMON: PROCESSING...",
                        "color": TERMINAL_BLUE
                    })

                    print(
                        f"DEBUG VOICE: Command received: "
                        f"{command}"
                    )

                    self.compile_pipeline_request(command)

                    self.listening_enabled = False

                except Exception as e:

                    print(
                        f"DEBUG VOICE ERROR: {e}"
                    )

                    self.ui_queue.put({
                        "type": "log",
                        "text": f"[VOICE ERROR] {e}"
                    })

                    self.listening_enabled = False

                    time.sleep(0.5)

        threading.Thread(
            target=loop,
            daemon=True
        ).start()

    def gui_heartbeat_ticker(self):
        try:
            while True:
                packet = self.ui_queue.get_nowait()

                if packet["type"] == "state":
                    self.lbl_listener.configure(
                        text=packet["text"],
                        text_color=packet["color"]
                    )

                elif packet["type"] == "log":
                    self._write_to_box(
                        self.txt_terminal,
                        packet["text"]
                    )

                elif packet["type"] == "chat":
                    self._write_to_box(
                        self.chat_history,
                        f"{packet['sender']}: {packet['text']}\n"
                    )

        except queue.Empty:
            pass

        finally:
            self.after(100, self.gui_heartbeat_ticker)


if __name__ == "__main__":
    app = CyberHUD()
    app.mainloop()