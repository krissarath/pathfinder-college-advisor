"""CommonAppAndTimelineAgent — Flash specialist for Common App execution & 2027-2028 deadlines."""

from __future__ import annotations

from google.adk.agents import LlmAgent

from app.config import FLASH_MODEL
from app.prompts.constitution import STATIC_REFERENCE_GUIDE, SYSTEM_CONSTITUTION
from app.tools.timeline_tools import build_common_app_deadline_schedule


def build_common_app_agent() -> LlmAgent:
    """Builds CommonAppAndTimelineAgent (gemini-2.5-flash) for deadline & checklist planning."""
    return LlmAgent(
        name="common_app_and_timeline_agent",
        model=FLASH_MODEL,
        description="Generates 2027-2028 Common App checklists, rollover rules, portal steps, and deadline calendars.",
        static_instruction=STATIC_REFERENCE_GUIDE,
        instruction=(
            f"{SYSTEM_CONSTITUTION}\n\n"
            "ROLE: Using the synthesized plan below and build_common_app_deadline_schedule, "
            "produce a clear, chronological 2027-2028 Common App execution checklist covering the "
            "Aug 1 rollover, FERPA waiver, Naviance/Scoir internal deadlines, 300w/250w writing limits, "
            "72-hour portal activation, interviews, and May 1 Decision Day.\n\n"
            "Synthesized Plan:\n{synthesized_plan?}"
        ),
        tools=[build_common_app_deadline_schedule],
    )
