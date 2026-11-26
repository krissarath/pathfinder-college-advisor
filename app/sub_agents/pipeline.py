"""ApplicationPrepPipeline — SequentialAgent chaining ParallelAgent fan-out + synthesis."""

from __future__ import annotations

from google.adk.agents import LlmAgent, ParallelAgent, SequentialAgent

from app.config import PRO_MODEL
from app.prompts.constitution import STATIC_REFERENCE_GUIDE, SYSTEM_CONSTITUTION
from app.sub_agents.academic_course_agent import build_academic_course_agent
from app.sub_agents.college_fit_agent import build_college_fit_agent
from app.sub_agents.common_app_agent import build_common_app_agent
from app.sub_agents.financial_aid_agent import build_financial_aid_agent


def build_application_prep_pipeline() -> SequentialAgent:
    """Builds ResearchFanOut (ParallelAgent) -> PlanSynthesizerAgent -> CommonAppAndTimelineAgent."""
    research_fan_out = ParallelAgent(
        name="research_fan_out",
        description="Runs academic rigor, college fit, and financial/non-citizen specialists concurrently.",
        sub_agents=[
            build_academic_course_agent(),
            build_college_fit_agent(),
            build_financial_aid_agent(),
        ],
    )

    plan_synthesizer = LlmAgent(
        name="plan_synthesizer_agent",
        model=PRO_MODEL,
        description="Synthesizes parallel academic, college-fit, and financial/non-citizen findings into one coherent strategy.",
        static_instruction=STATIC_REFERENCE_GUIDE,
        instruction=(
            f"{SYSTEM_CONSTITUTION}\n\n"
            "ROLE: Synthesize the parallel specialist outputs below into a single unified strategy "
            "highlighting conflicts, trade-offs, and the top 3 immediate next steps.\n\n"
            "Academic Audit:\n{academic_audit?}\n\n"
            "College Shortlist:\n{college_shortlist?}\n\n"
            "Financial & Non-Citizen Plan:\n{financial_plan?}"
        ),
        output_key="synthesized_plan",
    )

    return SequentialAgent(
        name="application_prep_pipeline",
        description="End-to-end sequential college preparation pipeline: parallel research -> synthesis -> Common App timeline.",
        sub_agents=[
            research_fan_out,
            plan_synthesizer,
            build_common_app_agent(),
        ],
    )
