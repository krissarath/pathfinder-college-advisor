"""CollegeFitAndListAgent — Pro reasoning specialist for Reach/Target/Safety & round rules."""

from __future__ import annotations

from google.adk.agents import LlmAgent

from app.config import PRO_MODEL
from app.prompts.constitution import STATIC_REFERENCE_GUIDE, SYSTEM_CONSTITUTION
from app.tools.college_tools import (
    check_english_proficiency_waiver,
    search_colleges_by_fit_and_major,
    validate_application_round_conflicts,
)


def build_college_fit_agent() -> LlmAgent:
    """Builds the CollegeFitAndListAgent (gemini-2.5-pro) writing to session.state['college_shortlist']."""
    return LlmAgent(
        name="college_fit_and_list_agent",
        model=PRO_MODEL,
        description="Matches Reach/Target/Safety colleges by major and budget, checks ED/EA/REA conflicts, and verifies TOEFL waivers.",
        static_instruction=STATIC_REFERENCE_GUIDE,
        instruction=(
            f"{SYSTEM_CONSTITUTION}\n\n"
            "ROLE: Use search_colleges_by_fit_and_major, validate_application_round_conflicts, "
            "and check_english_proficiency_waiver to assemble a balanced Reach/Target/Safety list "
            "with direct-admit flags, portal notes, and TOEFL waiver actions. Always frame tiers "
            "as non-guaranteed estimates."
        ),
        tools=[
            search_colleges_by_fit_and_major,
            validate_application_round_conflicts,
            check_english_proficiency_waiver,
        ],
        output_key="college_shortlist",
    )
