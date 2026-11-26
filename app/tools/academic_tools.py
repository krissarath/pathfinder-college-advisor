"""Academic course rigor and Common App activities audit tools."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.tools.schemas import (
    ActivityAuditResult,
    ToolErrorResponse,
    guided_tool_error_handler,
)

# Each prerequisite is a tuple of (display_label, acceptable_aliases).
_MAJOR_PREREQS: dict[str, list[tuple[str, tuple[str, ...]]]] = {
    "computer science": [
        ("AP Calculus BC", ("ap calculus bc", "ib math aa hl", "calculus bc")),
        ("AP Physics C or AP Physics 1", ("ap physics c", "ap physics 1", "ib physics hl")),
        ("AP Computer Science A", ("ap computer science a", "ap csa", "ib computer science")),
    ],
    "engineering": [
        ("AP Calculus BC", ("ap calculus bc", "ib math aa hl", "calculus bc")),
        ("AP Physics C", ("ap physics c", "ib physics hl")),
        ("AP Chemistry", ("ap chemistry", "ib chemistry hl")),
    ],
    "pre-med": [
        ("AP Biology", ("ap biology", "ib biology hl")),
        ("AP Chemistry", ("ap chemistry", "ib chemistry hl")),
        ("AP Calculus AB/BC", ("ap calculus ab", "ap calculus bc", "ib math aa")),
        ("AP Statistics", ("ap statistics",)),
    ],
    "biology": [
        ("AP Biology", ("ap biology", "ib biology hl")),
        ("AP Chemistry", ("ap chemistry", "ib chemistry hl")),
        ("AP Statistics", ("ap statistics",)),
    ],
    "business": [
        ("AP Calculus AB/BC", ("ap calculus ab", "ap calculus bc")),
        ("AP Statistics", ("ap statistics",)),
        ("AP Macroeconomics/Microeconomics", ("ap macroeconomics", "ap microeconomics", "ib economics")),
    ],
    "economics": [
        ("AP Calculus BC", ("ap calculus bc", "ap calculus ab", "ib math aa hl")),
        ("AP Statistics", ("ap statistics",)),
        ("AP Macroeconomics/Microeconomics", ("ap macroeconomics", "ap microeconomics", "ib economics")),
    ],
    "data science": [
        ("AP Calculus BC", ("ap calculus bc", "ap calculus ab")),
        ("AP Statistics", ("ap statistics",)),
        ("AP Computer Science A", ("ap computer science a", "ap csa")),
    ],
    "mathematics": [
        ("AP Calculus BC", ("ap calculus bc", "ib math aa hl")),
        ("AP Statistics", ("ap statistics",)),
        ("AP Physics C", ("ap physics c",)),
    ],
    "physics": [
        ("AP Calculus BC", ("ap calculus bc", "ib math aa hl")),
        ("AP Physics C", ("ap physics c", "ib physics hl")),
        ("AP Chemistry", ("ap chemistry",)),
    ],
}


class CourseAuditResult(BaseModel):
    """Structured output for senior-year course rigor and GPA context audit."""

    status: str = "ok"
    target_major: str
    unweighted_gpa: float
    core_5_gaps: list[str]
    recommended_senior_courses: list[str]
    rigor_vs_gpa_warning: str | None = None
    testing_strategy: list[str]
    dual_enrollment_note: str


@guided_tool_error_handler
def evaluate_senior_course_rigor(
    target_major: str,
    unweighted_gpa: float,
    completed_ap_ib_courses: list[str],
    world_language_years: int = 3,
    has_visual_performing_arts: bool = True,
    max_aps_offered_at_school: int = 12,
    planned_senior_ap_count: int = 4,
) -> dict[str, Any]:
    """Audits a high school junior's course rigor and recommends senior-year courses.

    Evaluates Core-5 graduation/selective-admissions alignment, major-specific
    prerequisites, high school profile context, Dual Enrollment permanence, and
    modern Digital SAT / Enhanced ACT strategy.

    Args:
        target_major: Intended college major (e.g., "Computer Science", "Engineering",
            "Pre-Med", "Biology", "Business", "Economics", "Data Science", "Mathematics", "Physics").
        unweighted_gpa: Student's unweighted GPA on a 4.0 scale (0.0 to 4.0).
        completed_ap_ib_courses: List of AP, IB, or Dual Enrollment courses completed
            through junior year.
        world_language_years: Years completed in the same world language (0-6, target 3-4).
        has_visual_performing_arts: Whether student has 1 year of Visual/Performing Arts
            (required for UC/CSU a-g eligibility).
        max_aps_offered_at_school: Total AP/IB courses offered in the high school profile (>= 0).
        planned_senior_ap_count: Number of AP/IB courses planned for senior year (>= 0).

    Returns:
        Dictionary matching CourseAuditResult with recommended courses, Core-5 gaps,
        rigor-vs-GPA guardrails, and testing recommendations.
    """
    if not (0.0 <= unweighted_gpa <= 4.0):
        return ToolErrorResponse(
            error_code="INVALID_GPA",
            message=f"unweighted_gpa={unweighted_gpa} is outside the 0.0-4.0 scale.",
            recovery_hint="Ask the user for their unweighted GPA on a 4.0 scale and retry.",
            valid_options=["0.0 to 4.0"],
        ).model_dump()

    if world_language_years < 0 or max_aps_offered_at_school < 0 or planned_senior_ap_count < 0:
        return ToolErrorResponse(
            error_code="NEGATIVE_COURSE_COUNT",
            message="world_language_years, max_aps_offered_at_school, and planned_senior_ap_count must be >= 0.",
            recovery_hint="Pass non-negative integers for course counts and retry.",
        ).model_dump()

    major_key = target_major.strip().lower()
    if major_key not in _MAJOR_PREREQS:
        return ToolErrorResponse(
            error_code="UNSUPPORTED_MAJOR",
            message=f"Major '{target_major}' is not in the prerequisite catalog.",
            recovery_hint="Choose the closest supported major from valid_options and retry.",
            valid_options=sorted(_MAJOR_PREREQS.keys()),
        ).model_dump()

    completed_lower = {c.strip().lower() for c in completed_ap_ib_courses}
    recommended: list[str] = []
    for display_label, aliases in _MAJOR_PREREQS[major_key]:
        if not any(alias in comp for comp in completed_lower for alias in aliases):
            recommended.append(display_label)

    core_gaps: list[str] = []
    if world_language_years < 3:
        core_gaps.append("World Language: Selective colleges expect 3-4 years of the SAME language.")
    if not has_visual_performing_arts:
        core_gaps.append("Visual & Performing Arts: Missing 1-year VPA credit (required for UC/CSU a-g).")

    rigor_warning: str | None = None
    if planned_senior_ap_count >= 6:
        rigor_warning = (
            "Taking 6+ AP/IB courses in senior year risks GPA drops during fall applications; "
            "prioritize A grades in major-relevant rigor over raw AP count."
        )
    elif max_aps_offered_at_school >= 10 and len(completed_ap_ib_courses) + planned_senior_ap_count < 5:
        rigor_warning = (
            "Relative to your school profile, consider adding 1-2 core AP/IB courses so your "
            "counselor can rate your schedule 'Most Demanding'."
        )

    testing_strategy = [
        "Take first Digital SAT (built-in Desmos) or Enhanced ACT in Spring 2027 (Mar-Jun) and reserve Aug-Oct 2027 for one retake.",
        "For Enhanced ACT (Science optional), still take Science if targeting STEM/Engineering programs that recommend it.",
        "Self-report AP scores of 4 or 5 on Common App; send one free official AP report to your enrolled college in June 2028.",
        "Check whether each target school accepts self-reported scores or requires official score sends (e.g., Georgetown all-scores rule).",
    ]

    return CourseAuditResult(
        target_major=target_major,
        unweighted_gpa=unweighted_gpa,
        core_5_gaps=core_gaps,
        recommended_senior_courses=recommended or ["All core major prerequisites covered; consider Linear Algebra or Dual Enrollment research."],
        rigor_vs_gpa_warning=rigor_warning,
        testing_strategy=testing_strategy,
        dual_enrollment_note=(
            "Dual Enrollment grades live on a permanent college transcript (affecting future med/law school GPAs) "
            "and may not transfer to private or out-of-state universities."
        ),
    ).model_dump()


@guided_tool_error_handler
def audit_common_app_activities(
    activities: list[str],
    honors_count: int = 0,
) -> dict[str, Any]:
    """Audits a student's extracurricular list against Common App constraints.

    Checks the 10-activity limit, 150-character description budget per activity,
    5-honor cap, and provides quantifiable impact coaching tips.

    Args:
        activities: List of draft activity descriptions (max 10 slots on Common App).
        honors_count: Number of academic honors/awards drafted (>= 0, max 5 slots on Common App).

    Returns:
        Dictionary matching ActivityAuditResult with slot counts, over-limit flags, and tips.
    """
    if not activities:
        return ToolErrorResponse(
            error_code="EMPTY_ACTIVITIES",
            message="No activities were provided to audit.",
            recovery_hint="Ask the student for 3-10 extracurricular activities (clubs, sports, jobs, family duties, research) and retry.",
        ).model_dump()

    if honors_count < 0:
        return ToolErrorResponse(
            error_code="NEGATIVE_HONORS_COUNT",
            message="honors_count must be >= 0.",
            recovery_hint="Pass a non-negative integer for honors_count and retry.",
        ).model_dump()

    over_char_limit = [
        {"index": idx + 1, "length": len(text), "excess_chars": len(text) - 150}
        for idx, text in enumerate(activities)
        if len(text) > 150
    ]

    return ActivityAuditResult(
        total_activities=len(activities),
        exceeds_10_slot_limit=len(activities) > 10,
        honors_count=honors_count,
        exceeds_5_honor_limit=honors_count > 5,
        over_150_char_entries=over_char_limit,
        coaching_tips=[
            "Order activities by impact and commitment, not chronologically.",
            "Lead with active verbs and quantifiable outcomes within the 150-character limit.",
            "Use Additional Information (300 words max) only for genuinely critical context, not extra resumes.",
        ],
    ).model_dump()
