"""College matching, ED/EA/REA round-conflict validation, and TOEFL waiver tools."""

from __future__ import annotations

from typing import Any

from app.tools.schemas import (
    ApplicationRound,
    CitizenshipStatus,
    CollegeSearchResult,
    EnglishWaiverResult,
    RoundValidationResult,
    ToolErrorResponse,
    build_provenance,
    guided_tool_error_handler,
    load_json_data,
    validate_state_code,
)


@guided_tool_error_handler
def search_colleges_by_fit_and_major(
    target_major: str,
    max_annual_budget_usd: int,
    home_state: str,
    citizenship_status: str = "US_CITIZEN",
) -> dict[str, Any]:
    """Searches verified 2027-2028 colleges matching major, budget, and citizenship tier.

    Flags direct-admit/impacted majors, non-Common App portals, Demonstrated Interest,
    Honors deadlines, and non-citizen aid tiers (Tier 1-4).

    Args:
        target_major: Intended college major (e.g., "Computer Science", "Engineering", "Business").
        max_annual_budget_usd: Target maximum annual out-of-pocket budget in USD (> 0).
        home_state: Two-letter US state abbreviation (e.g., "NJ", "TX", "CA").
        citizenship_status: One of US_CITIZEN, GREEN_CARD, I485_PENDING_C09,
            H4_DEPENDENT, F1_INTERNATIONAL.

    Returns:
        Dictionary matching CollegeSearchResult with provenance metadata.
    """
    try:
        status_enum = CitizenshipStatus(citizenship_status.upper())
    except ValueError:
        return ToolErrorResponse(
            error_code="INVALID_CITIZENSHIP_STATUS",
            message=f"Unsupported citizenship_status '{citizenship_status}'.",
            recovery_hint="Pass one of the allowed CitizenshipStatus enum values.",
            valid_options=[s.value for s in CitizenshipStatus],
        ).model_dump()

    state_upper = validate_state_code(home_state)
    if state_upper is None:
        return ToolErrorResponse(
            error_code="INVALID_STATE_CODE",
            message=f"home_state '{home_state}' is not a valid 2-letter US state abbreviation.",
            recovery_hint="Convert the state name to its 2-letter USPS code (e.g., 'TX', 'NJ', 'CA') and retry.",
        ).model_dump()

    if max_annual_budget_usd <= 0:
        return ToolErrorResponse(
            error_code="INVALID_BUDGET",
            message="max_annual_budget_usd must be a positive integer.",
            recovery_hint="Ask the family for an approximate annual budget bracket in USD and retry.",
        ).model_dump()

    catalog = load_json_data("colleges_2027_2028.json")
    state_rules = load_json_data("noncitizen_state_rules.json")["state_in_state_tuition_rules"]
    major_lower = target_major.strip().lower()

    residency_warning: str | None = None
    h4_state_verified = state_rules.get(state_upper, {}).get("h4_in_state_eligible", False)
    if status_enum in (CitizenshipStatus.H4_DEPENDENT, CitizenshipStatus.I485_PENDING_C09) and not h4_state_verified:
        residency_warning = (
            f"In-state tuition eligibility for {status_enum.value} in {state_upper} is not verified in "
            "the local catalog; confirm directly with the state public university registrar."
        )

    matches: list[dict[str, Any]] = []
    for school in catalog["colleges"]:
        strong = [m.lower() for m in school["strong_majors"]]
        if major_lower not in strong:
            continue

        is_in_state = (
            school["type"] == "public"
            and school["state"] == state_upper
            and status_enum != CitizenshipStatus.F1_INTERNATIONAL
            and (
                status_enum in (CitizenshipStatus.US_CITIZEN, CitizenshipStatus.GREEN_CARD)
                or h4_state_verified
            )
        )
        sticker_coa = school["annual_coa_in_state"] if is_in_state else school["annual_coa_out_of_state"]

        direct_admit = major_lower in [m.lower() for m in school["direct_admit_majors"]]
        matches.append(
            {
                "id": school["id"],
                "name": school["name"],
                "tier": school["selectivity_tier"],
                "portal": school["portal"],
                "estimated_sticker_coa": sticker_coa,
                "within_sticker_budget": sticker_coa <= max_annual_budget_usd,
                "direct_admit_impacted_major": direct_admit,
                "testing_policy": school["testing_policy"],
                "noncitizen_aid_tier": school["noncitizen_aid_tier"],
                "noncitizen_aid_note": school["noncitizen_aid_note"],
                "merit_priority_deadline": school["merit_priority_deadline"],
                "honors_deadline": school["honors_deadline"],
                "demonstrated_interest_considered": school["demonstrated_interest_considered"],
                "provenance": build_provenance(
                    source_url=school["source_url"],
                    last_verified_date=school["last_verified_date"],
                    cycle_year=catalog["cycle_year"],
                ).model_dump(),
            }
        )

    if not matches:
        return CollegeSearchResult(
            status="abstain",
            disclaimer=(
                f"No verified schools found in the local 2027-2028 catalog for major '{target_major}'. "
                "Verify directly on official university admissions websites."
            ),
            cycle_year=catalog["cycle_year"],
            matches=[],
            residency_warning=residency_warning,
        ).model_dump()

    return CollegeSearchResult(
        disclaimer="Admissions tiers (Reach/Target/Safety) are non-guaranteed estimates.",
        cycle_year=catalog["cycle_year"],
        matches=matches,
        residency_warning=residency_warning,
    ).model_dump()


@guided_tool_error_handler
def validate_application_round_conflicts(
    planned_rounds: dict[str, str],
) -> dict[str, Any]:
    """Validates a student's ED I, ED II, EA, and REA/SCEA plan for rule conflicts.

    Enforces:
    - Single binding Early Decision I rule and single Early Decision II rule.
    - Single Restrictive Early Action (REA/SCEA) rule and conflicts against private ED/EA.
    - Flags out-of-catalog schools and binding ED I / ED II financial-readiness warnings.

    Args:
        planned_rounds: Mapping of college_id (e.g., "cornell", "stanford", "purdue")
            to ApplicationRound value ("ED_I", "ED_II", "EA", "REA", "RD", "ROLLING").

    Returns:
        Dictionary matching RoundValidationResult with is_valid, conflicts, and warnings.
    """
    if not planned_rounds:
        return ToolErrorResponse(
            error_code="EMPTY_ROUND_PLAN",
            message="planned_rounds cannot be empty.",
            recovery_hint="Pass a mapping of college_id -> round (e.g., {'cornell': 'ED_I', 'purdue': 'EA'}).",
            valid_options=[r.value for r in ApplicationRound],
        ).model_dump()

    catalog = {c["id"]: c for c in load_json_data("colleges_2027_2028.json")["colleges"]}
    conflicts: list[str] = []
    warnings: list[str] = []

    ed1_schools: list[str] = []
    ed2_schools: list[str] = []
    rea_schools: list[str] = []
    private_ea_schools: list[str] = []

    for college_id, round_str in planned_rounds.items():
        try:
            rnd = ApplicationRound(round_str.upper())
        except ValueError:
            return ToolErrorResponse(
                error_code="INVALID_APPLICATION_ROUND",
                message=f"Invalid round '{round_str}' for '{college_id}'.",
                recovery_hint="Use one of the allowed ApplicationRound enum values.",
                valid_options=[r.value for r in ApplicationRound],
            ).model_dump()

        school = catalog.get(college_id.lower())
        if school is None:
            warnings.append(
                f"'{college_id}' is not in the local verified catalog; verify its {rnd.value} "
                "eligibility and private/public REA carve-outs on the official admissions site."
            )
        elif rnd.value not in school["rounds"]:
            conflicts.append(
                f"{school['name']} does not offer {rnd.value}. Available rounds: {school['rounds']}."
            )

        if rnd == ApplicationRound.ED_I:
            ed1_schools.append(college_id)
        elif rnd == ApplicationRound.ED_II:
            ed2_schools.append(college_id)
        elif rnd == ApplicationRound.REA:
            rea_schools.append(college_id)
        elif rnd == ApplicationRound.EA and school and school["type"] == "private":
            private_ea_schools.append(college_id)

    if len(ed1_schools) > 1:
        conflicts.append(
            f"Binding ED I conflict: You cannot apply ED I to multiple schools ({ed1_schools}). Choose at most one."
        )
    if len(ed2_schools) > 1:
        conflicts.append(
            f"Binding ED II conflict: You cannot apply ED II to multiple schools ({ed2_schools}). Choose at most one."
        )
    if len(rea_schools) > 1:
        conflicts.append(
            f"REA/SCEA conflict: You cannot apply Restrictive Early Action to multiple schools ({rea_schools})."
        )
    if rea_schools and (ed1_schools or private_ea_schools):
        conflicts.append(
            f"REA/SCEA conflict: Applying REA ({rea_schools}) typically prohibits private ED I ({ed1_schools}) "
            f"and private EA ({private_ea_schools}). Public EA and rolling admissions are usually allowed; verify carve-outs."
        )

    if ed1_schools or ed2_schools:
        warnings.append(
            "Binding Early Decision (ED I / ED II) removes the ability to compare financial/merit aid offers. "
            "Verify Net Price Calculator affordability with a parent/guardian before locking ED. "
            "If admitted ED I, you must withdraw any pending ED II or other applications."
        )

    return RoundValidationResult(
        is_valid=len(conflicts) == 0,
        conflicts=conflicts,
        warnings=warnings,
    ).model_dump()


@guided_tool_error_handler
def check_english_proficiency_waiver(
    college_id: str,
    citizenship_status: str,
    years_in_us_high_school: int,
) -> dict[str, Any]:
    """Checks TOEFL/IELTS/DET waiver eligibility for non-US citizens in US high schools.

    Universities often auto-trigger English proficiency holds based on citizenship
    even for students who attended 3-4 years of US high school.

    Args:
        college_id: School identifier from catalog (e.g., "cornell", "purdue", "usc", "stanford").
        citizenship_status: Student citizenship/visa status enum.
        years_in_us_high_school: Number of years attending a non-ESL US high school (0-4).

    Returns:
        Dictionary matching EnglishWaiverResult with portal action checklist and provenance.
    """
    if not (0 <= years_in_us_high_school <= 4):
        return ToolErrorResponse(
            error_code="INVALID_HS_YEARS",
            message=f"years_in_us_high_school={years_in_us_high_school} must be between 0 and 4.",
            recovery_hint="Pass an integer between 0 and 4 representing years in a US high school.",
        ).model_dump()

    catalog = {c["id"]: c for c in load_json_data("colleges_2027_2028.json")["colleges"]}
    school = catalog.get(college_id.lower())
    if not school:
        return ToolErrorResponse(
            error_code="UNKNOWN_COLLEGE_ID",
            message=f"College '{college_id}' not found in verified catalog.",
            recovery_hint="Use one of the valid college_id values or direct user to the university admissions page.",
            valid_options=sorted(catalog.keys()),
        ).model_dump()

    try:
        status_enum = CitizenshipStatus(citizenship_status.upper())
    except ValueError:
        return ToolErrorResponse(
            error_code="INVALID_CITIZENSHIP_STATUS",
            message=f"Unsupported citizenship_status '{citizenship_status}'.",
            recovery_hint="Use a valid CitizenshipStatus enum value.",
            valid_options=[s.value for s in CitizenshipStatus],
        ).model_dump()

    provenance = build_provenance(
        source_url=school["source_url"],
        last_verified_date=school["last_verified_date"],
    )

    if status_enum in (CitizenshipStatus.US_CITIZEN, CitizenshipStatus.GREEN_CARD):
        return EnglishWaiverResult(
            college=school["name"],
            english_test_required=False,
            years_in_us_high_school=years_in_us_high_school,
            minimum_us_hs_years_for_waiver=0,
            likely_waived=True,
            policy_note="English proficiency tests are not required for US citizens or Green Card holders.",
            portal_action="No TOEFL/IELTS action required.",
            provenance=provenance,
        ).model_dump()

    school_requires_test = school.get("english_test_required", True)
    min_years = school["toefl_waiver_us_hs_years"]
    likely_waived = (not school_requires_test) or (years_in_us_high_school >= min_years)

    return EnglishWaiverResult(
        college=school["name"],
        english_test_required=school_requires_test and not likely_waived,
        years_in_us_high_school=years_in_us_high_school,
        minimum_us_hs_years_for_waiver=min_years,
        likely_waived=likely_waived,
        policy_note=school["toefl_waiver_note"],
        portal_action=(
            "Activate your applicant portal within 72 hours of submitting. If an automatic TOEFL/IELTS "
            "hold appears because of your citizenship, email admissions immediately to request a manual waiver."
        ),
        provenance=provenance,
    ).model_dump()
