"""ActionExecutionAgent — HITL-gated agent for all 6 state-mutating and destructive tools.

Each tool validates arguments and financial-readiness gates first, then invokes
tool_context.request_confirmation(hint=..., payload=...) with a rich before/after
diff and reversibility notice before mutating any state.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool

from app.config import FLASH_MODEL
from app.prompts.constitution import STATIC_REFERENCE_GUIDE, SYSTEM_CONSTITUTION
from app.tools.timeline_tools import (
    delete_student_data,
    export_deadline_ics_reminders,
    finalize_college_shortlist,
    lock_early_decision_choice,
    remove_college_from_shortlist,
    update_budget_or_citizenship_profile,
)


def build_action_execution_agent() -> LlmAgent:
    """Builds ActionExecutionAgent exposing all 6 HITL-confirmed mutation tools."""
    hitl_tools = [
        FunctionTool(func=lock_early_decision_choice),
        FunctionTool(func=finalize_college_shortlist),
        FunctionTool(func=remove_college_from_shortlist),
        FunctionTool(func=update_budget_or_citizenship_profile),
        FunctionTool(func=export_deadline_ics_reminders),
        FunctionTool(func=delete_student_data),
    ]
    return LlmAgent(
        name="action_execution_agent",
        model=FLASH_MODEL,
        description="Executes high-stakes shortlist, binding Early Decision, profile, ICS export, and data-deletion actions with explicit HITL confirmation.",
        static_instruction=STATIC_REFERENCE_GUIDE,
        instruction=(
            f"{SYSTEM_CONSTITUTION}\n\n"
            "ROLE: Execute state-mutating actions only via the HITL-confirmed tools. "
            "Before invoking lock_early_decision_choice, confirm that the student and parent "
            "reviewed Net Price Calculator affordability."
        ),
        tools=hitl_tools,
    )
