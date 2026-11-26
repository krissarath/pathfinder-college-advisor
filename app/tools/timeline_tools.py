"""2027-2028 Common App deadline planner and 6 HITL-gated state-mutating tools.

All 6 mutating/destructive tools validate inputs and financial-readiness gates
first, then enforce explicit Human-in-the-Loop (HITL) confirmation via ADK
tool_context.request_confirmation(hint=..., payload=...) with before/after diffs
and reversibility notices.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from app.plugins.memory import get_memory_store
from app.tools.schemas import (
    CitizenshipStatus,
    DeadlineScheduleResult,
    ToolErrorResponse,
    build_provenance,
    guided_tool_error_handler,
    load_json_data,
    validate_state_code,
)

# In-memory session state mirror for standalone local testing (ADK ToolContext overrides in runtime).
_LOCAL_STATE: dict[str, Any] = {
    "shortlist": [],
    "locked_ed_school": None,
    "profile": {},
}

_KNOWN_STATE_KEYS = (
    "shortlist",
    "college_shortlist",
    "locked_ed_school",
    "profile",
    "academic_audit",
    "financial_plan",
    "synthesized_plan",
)


@guided_tool_error_handler
def build_common_app_deadline_schedule(
    citizenship_status: str = "US_CITIZEN",
    applying_uc: bool = False,
) -> dict[str, Any]:
    """Generates a personalized 2027-2028 (Fall 2028 Entry) application deadline schedule.

    Includes Common App rollover specs (300w Additional Info, 250w Challenges &
    Circumstances), 2026 PPY tax year reminders, FERPA waiver, portal activation,
    and citizenship-specific milestones (CSS/ISFAA, TOEFL waivers, I-20 / COS timing).

    Args:
        citizenship_status: Student citizenship/visa status enum.
        applying_uc: Whether the student is also applying to University of California campuses.

    Returns:
        Dictionary matching DeadlineScheduleResult with ordered milestones and provenance.
    """
    try:
        status_enum = CitizenshipStatus(citizenship_status.upper())
    except ValueError:
        return ToolErrorResponse(
            error_code="INVALID_CITIZENSHIP_STATUS",
            message=f"Unsupported citizenship_status '{citizenship_status}'.",
            recovery_hint="Pass a valid CitizenshipStatus enum value.",
            valid_options=[s.value for s in CitizenshipStatus],
        ).model_dump()

    data = load_json_data("common_app_deadlines_2027_2028.json")
    milestones: list[dict[str, str]] = []
    for raw_m in data["milestones"]:
        m = dict(raw_m)
        if not applying_uc and "UC Application Submission" in m["title"]:
            continue
        if not applying_uc and "UC Application Window" in m["title"]:
            m["title"] = "FAFSA & CSS Profile Open (2028-2029 Aid Year)"
        milestones.append(m)

    if status_enum in (
        CitizenshipStatus.H4_DEPENDENT,
        CitizenshipStatus.F1_INTERNATIONAL,
        CitizenshipStatus.I485_PENDING_C09,
    ):
        milestones.append(
            {
                "phase": "Early Round & Aid Open",
                "date": "2027-11-04",
                "title": "Portal TOEFL/IELTS Waiver Verification (72 hrs Post-Submit)",
                "category": "noncitizen",
                "details": "Log into every college portal within 72 hours to clear auto-triggered English proficiency holds.",
            }
        )

    if status_enum == CitizenshipStatus.F1_INTERNATIONAL:
        milestones.append(
            {
                "phase": "Post-Submission & Decision",
                "date": "2028-05-05",
                "title": "Submit Certificate of Finances for Form I-20 & Pay SEVIS I-901 ($350)",
                "category": "noncitizen",
                "details": "Provide liquid proof of Year 1 COA minus institutional aid to receive Form I-20 for F-1 visa stamping.",
            }
        )
    elif status_enum == CitizenshipStatus.H4_DEPENDENT:
        milestones.append(
            {
                "phase": "Post-Submission & Decision",
                "date": "2028-04-15",
                "title": "H-4 vs. F-1 Tuition & Change-of-Status Planning Review",
                "category": "noncitizen",
                "details": "Verify in-state residency with registrar and review H-4 age-out/CPT/OPT timing (note USCIS Form I-539 / optional I-907 premium processing).",
            }
        )

    milestones.sort(key=lambda item: item["date"])

    return DeadlineScheduleResult(
        cycle_year=data["cycle_year"],
        entry_term=data["entry_term"],
        ppy_tax_year=data["ppy_tax_year"],
        common_app_specs=data["common_app_specs"],
        milestones=milestones,
        provenance=build_provenance(
            source_url=data["source_url"],
            last_verified_date=data["last_verified_date"],
            cycle_year=data["cycle_year"],
        ),
    ).model_dump()


def _check_hitl(tool_context: Any, hint: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """Enforces ADK ToolConfirmation pause when running inside an ADK session."""
    if tool_context is None:
        return None
    confirmation = getattr(tool_context, "tool_confirmation", None)
    if confirmation is None:
        request_fn = getattr(tool_context, "request_confirmation", None)
        if callable(request_fn):
            request_fn(hint=hint, payload=payload)
            actions = getattr(tool_context, "actions", None)
            if actions is not None and hasattr(actions, "skip_summarization"):
                actions.skip_summarization = True
            return {
                "status": "pending_confirmation",
                "hint": hint,
                "confirmation_payload": payload,
            }
    elif not getattr(confirmation, "confirmed", False):
        return {
            "status": "cancelled_by_user",
            "message": "Action cancelled because human confirmation was declined.",
        }
    return None


@guided_tool_error_handler
def lock_early_decision_choice(
    college_id: str,
    npc_reviewed_with_parent: bool,
    tool_context: Any = None,
) -> dict[str, Any]:
    """Locks a binding Early Decision I school after explicit HITL + parent confirmation.

    High-stakes binding action: committing to Early Decision requires withdrawing
    all other applications if admitted and forfeits financial aid offer comparison.

    Args:
        college_id: School identifier from the verified catalog (must offer ED_I).
        npc_reviewed_with_parent: Must be True confirming a parent/guardian reviewed
            the Net Price Calculator and affordability.
        tool_context: Optional ADK ToolContext for HITL confirmation and session state.

    Returns:
        Confirmation status, before/after state diff, and binding commitment notice.
    """
    catalog = {c["id"]: c for c in load_json_data("colleges_2027_2028.json")["colleges"]}
    school = catalog.get(college_id.strip().lower())
    if not school or "ED_I" not in school["rounds"]:
        return ToolErrorResponse(
            error_code="ED_NOT_AVAILABLE",
            message=f"College '{college_id}' does not offer binding Early Decision I in our catalog.",
            recovery_hint="Choose a college that offers ED_I (e.g., 'cornell') or use EA/RD instead.",
            valid_options=[c["id"] for c in catalog.values() if "ED_I" in c["rounds"]],
        ).model_dump()

    if not npc_reviewed_with_parent:
        return ToolErrorResponse(
            error_code="FINANCIAL_READINESS_GATE_BLOCKED",
            message="Binding Early Decision cannot be locked until a parent/guardian reviews the Net Price Calculator.",
            recovery_hint="Ask the student and parent to confirm NPC affordability first, then re-invoke with npc_reviewed_with_parent=True.",
        ).model_dump()

    state = getattr(tool_context, "state", _LOCAL_STATE)
    previous = state.get("locked_ed_school")
    payload = {
        "action": "lock_early_decision_choice",
        "before": {"locked_ed_school": previous},
        "after": {"locked_ed_school": school["name"]},
        "reversibility": "High-stakes binding commitment once submitted on Common App (requires student, parent, and counselor signatures).",
        "parent_guardian_check": "Confirmed Net Price Calculator affordability reviewed with parent/guardian.",
    }
    pending = _check_hitl(
        tool_context,
        hint=f"Confirm locking {school['name']} as your BINDING Early Decision I choice?",
        payload=payload,
    )
    if pending:
        return pending

    state["locked_ed_school"] = school["name"]
    return {"status": "ok", "locked_ed_school": school["name"], "diff": payload}


@guided_tool_error_handler
def finalize_college_shortlist(
    college_ids: list[str],
    tool_context: Any = None,
) -> dict[str, Any]:
    """Saves the student's finalized college shortlist after HITL confirmation.

    Deduplicates and normalizes IDs to lowercase and enforces the 20-college
    Common App submission cap.

    Args:
        college_ids: Non-empty list of college IDs to save (max 20 Common App schools).
        tool_context: Optional ADK ToolContext.

    Returns:
        Updated shortlist with before/after diff.
    """
    normalized = list(dict.fromkeys(cid.strip().lower() for cid in college_ids if cid.strip()))
    if not normalized:
        return ToolErrorResponse(
            error_code="EMPTY_SHORTLIST",
            message="college_ids must contain at least one valid college ID.",
            recovery_hint="Ask the student which colleges to include and retry.",
        ).model_dump()

    if len(normalized) > 20:
        return ToolErrorResponse(
            error_code="COMMON_APP_20_LIMIT_EXCEEDED",
            message=f"Received {len(normalized)} unique colleges; Common App caps submissions at 20.",
            recovery_hint="Trim the Common App shortlist to 20 or fewer colleges and retry.",
        ).model_dump()

    state = getattr(tool_context, "state", _LOCAL_STATE)
    before = list(state.get("shortlist", []) or [])
    payload = {
        "action": "finalize_college_shortlist",
        "before": before,
        "after": normalized,
        "reversibility": "Reversible inside PathFinder AI before Common App submission.",
    }
    pending = _check_hitl(tool_context, hint=f"Save shortlist of {len(normalized)} colleges?", payload=payload)
    if pending:
        return pending

    state["shortlist"] = normalized
    return {"status": "ok", "shortlist": normalized, "diff": payload}


@guided_tool_error_handler
def remove_college_from_shortlist(
    college_id: str,
    tool_context: Any = None,
) -> dict[str, Any]:
    """Removes a college from the student's saved shortlist after HITL confirmation.

    Args:
        college_id: College ID to remove (case-insensitive).
        tool_context: Optional ADK ToolContext.

    Returns:
        Updated shortlist with before/after diff.
    """
    target = college_id.strip().lower()
    state = getattr(tool_context, "state", _LOCAL_STATE)
    before = list(state.get("shortlist", []) or [])
    before_lower = [c.strip().lower() for c in before]
    if target not in before_lower:
        return ToolErrorResponse(
            error_code="COLLEGE_NOT_IN_SHORTLIST",
            message=f"'{college_id}' is not in the current shortlist.",
            recovery_hint="Inspect current shortlist and pass an existing college_id.",
            valid_options=before,
        ).model_dump()

    after = [c for c in before if c.strip().lower() != target]
    payload = {
        "action": "remove_college_from_shortlist",
        "before": before,
        "after": after,
        "reversibility": "Reversible by re-adding the college.",
    }
    pending = _check_hitl(tool_context, hint=f"Remove '{target}' from your shortlist?", payload=payload)
    if pending:
        return pending

    state["shortlist"] = after
    return {"status": "ok", "shortlist": after, "diff": payload}


@guided_tool_error_handler
def update_budget_or_citizenship_profile(
    annual_budget_bracket: str,
    citizenship_status: str,
    home_state: str,
    tool_context: Any = None,
) -> dict[str, Any]:
    """Updates family budget bracket and citizenship status after HITL confirmation.

    Follows Data Minimization: accepts income/budget brackets only (never exact tax returns).

    Args:
        annual_budget_bracket: Approximate annual budget bracket (e.g., "$30k-$50k").
        citizenship_status: CitizenshipStatus enum value.
        home_state: Two-letter US state abbreviation.
        tool_context: Optional ADK ToolContext.

    Returns:
        Updated profile with before/after diff.
    """
    try:
        status_enum = CitizenshipStatus(citizenship_status.upper())
    except ValueError:
        return ToolErrorResponse(
            error_code="INVALID_CITIZENSHIP_STATUS",
            message=f"Invalid citizenship_status '{citizenship_status}'.",
            recovery_hint="Use one of the allowed CitizenshipStatus enum values.",
            valid_options=[s.value for s in CitizenshipStatus],
        ).model_dump()

    state_upper = validate_state_code(home_state)
    if state_upper is None:
        return ToolErrorResponse(
            error_code="INVALID_STATE_CODE",
            message=f"home_state '{home_state}' is not a valid 2-letter US state abbreviation.",
            recovery_hint="Pass a 2-letter USPS code (e.g., 'TX', 'NJ', 'CA') and retry.",
        ).model_dump()

    state = getattr(tool_context, "state", _LOCAL_STATE)
    before = dict(state.get("profile", {}) or {})
    after = {
        "annual_budget_bracket": annual_budget_bracket.strip(),
        "citizenship_status": status_enum.value,
        "home_state": state_upper,
    }
    payload = {
        "action": "update_budget_or_citizenship_profile",
        "before": before,
        "after": after,
        "reversibility": "Reversible at any time; triggers re-evaluation of financial aid recommendations.",
    }
    pending = _check_hitl(tool_context, hint="Confirm updating budget bracket and citizenship profile?", payload=payload)
    if pending:
        return pending

    state["profile"] = after
    return {"status": "ok", "profile": after, "diff": payload}


@guided_tool_error_handler
def export_deadline_ics_reminders(
    milestones: list[dict[str, str]],
    tool_context: Any = None,
) -> dict[str, Any]:
    """Generates RFC 5545 read-only iCalendar (.ics) content after HITL confirmation.

    Does not write directly to external Calendar APIs in v1; returns .ics text
    for manual import by the student or parent.

    Args:
        milestones: List of milestone dicts with 'date' (YYYY-MM-DD) and 'title'.
        tool_context: Optional ADK ToolContext.

    Returns:
        Dictionary containing RFC 5545 .ics text and event count.
    """
    if not milestones:
        return ToolErrorResponse(
            error_code="EMPTY_MILESTONES",
            message="No milestones provided to export.",
            recovery_hint="Call build_common_app_deadline_schedule first and pass its milestones.",
        ).model_dump()

    for idx, item in enumerate(milestones):
        try:
            date.fromisoformat(item.get("date", ""))
        except ValueError:
            return ToolErrorResponse(
                error_code="INVALID_MILESTONE_DATE",
                message=f"Milestone #{idx + 1} has invalid ISO date '{item.get('date')}'.",
                recovery_hint="Use YYYY-MM-DD format for every milestone date.",
            ).model_dump()

    payload = {
        "action": "export_deadline_ics_reminders",
        "event_count": len(milestones),
        "reversibility": "Read-only .ics export; does not mutate any live Google Calendar.",
    }
    pending = _check_hitl(tool_context, hint=f"Generate read-only .ics calendar for {len(milestones)} deadlines?", payload=payload)
    if pending:
        return pending

    dtstamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//PathFinder AI//College Prep 2027-2028//EN"]
    for item in milestones:
        dt = item["date"].replace("-", "")
        title = item.get("title", "College Milestone").replace("\n", " ")
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{uuid.uuid4()}@pathfinder.example.com",
            f"DTSTAMP:{dtstamp}",
            f"DTSTART;VALUE=DATE:{dt}",
            f"SUMMARY:{title}",
            "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    return {"status": "ok", "event_count": len(milestones), "ics_content": "\n".join(lines)}


@guided_tool_error_handler
async def delete_student_data(
    user_id: str = "",
    tool_context: Any = None,
) -> dict[str, Any]:
    """Deletes stored session state AND purges long-term memories after HITL confirmation.

    Derives the authenticated user_id from ADK session context when available to
    prevent IDOR, safely resets ADK State keys (without calling State.clear()),
    and awaits StudentMemoryStore.delete_user_memories().

    Args:
        user_id: Optional user identifier used only in standalone offline tests
            when tool_context is None.
        tool_context: Optional ADK ToolContext.

    Returns:
        Deletion summary including purged memory count.
    """
    inv_ctx = getattr(tool_context, "_invocation_context", None)
    session_user = getattr(getattr(inv_ctx, "session", None), "user_id", None)
    effective_user_id = session_user or user_id or "synthetic_student"

    payload = {
        "action": "delete_student_data",
        "user_id": effective_user_id,
        "reversibility": "Permanent deletion of saved shortlist, profile, and consolidated memories.",
    }
    pending = _check_hitl(
        tool_context,
        hint=f"Permanently delete all saved PathFinder data for '{effective_user_id}'?",
        payload=payload,
    )
    if pending:
        return pending

    state = getattr(tool_context, "state", _LOCAL_STATE)
    if isinstance(state, dict):
        state.clear()
    else:
        for key in _KNOWN_STATE_KEYS:
            state[key] = None

    purged_memories = await get_memory_store().delete_user_memories(effective_user_id)
    return {
        "status": "ok",
        "deleted_user_id": effective_user_id,
        "purged_memory_entries": purged_memories,
        "message": f"Session state reset and {purged_memories} persisted memory entries purged.",
    }
