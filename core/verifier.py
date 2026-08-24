import json
import time
from openai import OpenAI

# ─────────────────────────────────────────────────────────────────────────────
# Shared provider stack (see core/providers.py). The verifier uses an LLM
# ONLY as a fallback when the plan's final chat step didn't succeed — in
# most cases no LLM call is needed at all.
# ─────────────────────────────────────────────────────────────────────────────
from core.providers import PROVIDERS, COOLDOWN_REGISTRY, COOLDOWN_DURATION_SECONDS
from core.executor import get_final_chat_output


VERIFIER_PROMPT = """
You are the Verification module for The Entity — an autonomous AI assistant.

You will receive:
1. The user's original goal
2. A summary of every step in the execution plan and its result

Your job is to write ONE concise, natural sentence (or two at most) that
reports what happened back to Marcus. Speak as The Entity — professional,
direct, no markdown, no bullet points, no preamble.

If everything succeeded: confirm what was done and any relevant details
(e.g. how many files were moved, where they went).

If something partially failed: acknowledge what was completed and clearly
state what could not be done in plain language.

If everything failed: apologise briefly and state what went wrong.

NEVER use markdown. NEVER use bullet points. NEVER say "I have" — say
"I've" for natural spoken language since this response will be voiced aloud.
"""


def verify_and_report(plan: list, execution_state: dict, original_goal: str) -> str:
    """
    Produces a natural language completion report for the user.

    Strategy (in priority order):
    1. If the plan's final 'chat' step succeeded, use that as the response
       directly — no extra LLM call needed.
    2. If not, call the LLM verifier with the full execution summary to
       synthesize an appropriate response.
    3. If all LLM providers fail, produce a plain-text fallback.

    Args:
        plan            : The original plan list from planner.generate_plan()
        execution_state : The dict returned by executor.execute_plan()
        original_goal   : The user's original command string

    Returns:
        A string suitable for speaking aloud and displaying in the chat panel.
    """

    # ── STRATEGY 1: Use the plan's own final chat step if it succeeded ──
    chat_output = get_final_chat_output(execution_state)
    if chat_output:
        return chat_output

    # ── Build a concise execution summary for the LLM ──
    step_summaries = []
    all_success    = True
    failed_tools   = []

    for step in plan:
        step_id = step.get("step_id", "?")
        state   = execution_state.get(step_id, {})
        tool    = state.get("tool", step.get("tool", "unknown"))
        status  = state.get("status", "unknown")
        output  = str(state.get("output", "no output"))

        # Trim very long outputs (e.g. full file lists) to keep the prompt small
        if len(output) > 250:
            output = output[:250] + "... [truncated]"

        step_summaries.append({
            "step":   step_id,
            "tool":   tool,
            "status": status,
            "output": output,
        })

        if status == "waiting":
            return output

        if status == "failed":
            all_success = False
            if tool != "chat":
                failed_tools.append(tool)

    # ── STRATEGY 2: LLM-synthesised report ──
    messages = [
        {"role": "system", "content": VERIFIER_PROMPT},
        {
            "role": "user",
            "content": (
                f"ORIGINAL GOAL: {original_goal}\n\n"
                f"EXECUTION RESULTS:\n{json.dumps(step_summaries, indent=2)}"
            )
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
                temperature=0.2,
                max_tokens=120     # Report should be brief — one or two sentences
            )
            report = response.choices[0].message.content.strip()
            print(f"[VERIFIER] ✓ Report synthesised via {provider['name']}")
            return report

        except Exception as e:
            print(f"[VERIFIER] Error with {provider['name']}: {e}")
            COOLDOWN_REGISTRY[provider["name"]] = time.time() + COOLDOWN_DURATION_SECONDS
            continue

    # ── STRATEGY 3: Hard fallback — no LLM available ──
    print("[VERIFIER] All providers unavailable — using fallback report.")
    if all_success:
        return "All steps completed successfully."
    elif failed_tools:
        tool_list = ", ".join(failed_tools)
        return (
            f"The task was partially completed. "
            f"The following steps encountered errors: {tool_list}. "
            "Please check the terminal panel for details."
        )
    else:
        return "The task encountered errors during execution. Please check the terminal panel for details."