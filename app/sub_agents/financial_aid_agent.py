"""FinancialAidAndCitizenshipAgent — Pro reasoning specialist for COA, aid & non-citizen rules."""

from __future__ import annotations

from google.adk.agents import LlmAgent

from app.prompts.constitution import STATIC_REFERENCE_GUIDE, SYSTEM_CONSTITUTION
from app.tools.finance_tools import (
    estimate_four_year_college_cost,
    lookup_noncitizen_aid_policy,
    normalize_financial_aid_awards,
)


def build_financial_aid_agent() -> LlmAgent:
    """Builds FinancialAidAndCitizenshipAgent (gemini-2.5-pro) writing to session.state['financial_plan']."""
    return LlmAgent(
        name="financial_aid_and_citizenship_agent",
        model="gemini-2.5-pro",
        description="Models 4-year COA, FAFSA/CSS/IDOC/ISFAA, merit aid, and H-4/I-485/F-1 non-citizen residency and aid rules.",
        static_instruction=STATIC_REFERENCE_GUIDE,
        instruction=(
            f"{SYSTEM_CONSTITUTION}\n\n"
            "ROLE: Use lookup_noncitizen_aid_policy, estimate_four_year_college_cost, and "
            "normalize_financial_aid_awards to provide clear 4-year cost projections, 2026 PPY "
            "tax-year reminders, merit vs. need-based guidance, and H-4/I-485/F-1 trade-offs."
        ),
        tools=[
            lookup_noncitizen_aid_policy,
            estimate_four_year_college_cost,
            normalize_financial_aid_awards,
        ],
        output_key="financial_plan",
    )
