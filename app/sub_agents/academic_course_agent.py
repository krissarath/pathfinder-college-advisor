"""AcademicAndCourseAgent — fast Flash specialist for course rigor, testing, and activities."""

from __future__ import annotations

from google.adk.agents import LlmAgent

from app.config import FLASH_MODEL
from app.prompts.constitution import STATIC_REFERENCE_GUIDE, SYSTEM_CONSTITUTION
from app.tools.academic_tools import (
    audit_common_app_activities,
    evaluate_senior_course_rigor,
)


def build_academic_course_agent() -> LlmAgent:
    """Builds the AcademicAndCourseAgent writing to session.state['academic_audit']."""
    return LlmAgent(
        name="academic_and_course_agent",
        model=FLASH_MODEL,
        description="Audits high school course rigor, Core-5 gaps, Digital SAT/ACT strategy, and Common App activities.",
        static_instruction=STATIC_REFERENCE_GUIDE,
        instruction=(
            f"{SYSTEM_CONSTITUTION}\n\n"
            "ROLE: Audit the student's academic rigor, Core-5 alignment, testing plan, and "
            "Common App activities using evaluate_senior_course_rigor and audit_common_app_activities. "
            "Produce a concise, actionable academic audit."
        ),
        tools=[evaluate_senior_course_rigor, audit_common_app_activities],
        output_key="academic_audit",
    )
