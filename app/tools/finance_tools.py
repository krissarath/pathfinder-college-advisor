"""4-year Cost of Attendance, 4-tier non-citizen aid policy, and award normalizer tools."""

from __future__ import annotations

from typing import Any

from app.tools.schemas import (
    AwardNormalizationResult,
    CitizenshipStatus,
    FourYearCostResult,
    NonCitizenPolicyResult,
    ToolErrorResponse,
    build_provenance,
    guided_tool_error_handler,
    load_json_data,
    validate_state_code,
)


@guided_tool_error_handler
def estimate_four_year_college_cost(
    college_id: str,
    home_state: str,
    citizenship_status: str,
    annual_merit_scholarship_usd: int = 0,
    annual_need_grant_usd: int = 0,
    annual_inflation_rate: float = 0.045,
    needs_student_health_insurance: bool = False,
) -> dict[str, Any]:
    """Models 4-year Cost of Attendance (COA) including tuition inflation and hidden costs.

    Factors in in-state vs. out-of-state eligibility (checking verified state
    non-citizen residency rules and F-1 in-state ineligibility), annual tuition
    inflation (0.0-0.20, default 4.5%), mandatory student health insurance, and
    one-time application/deposit transition costs.

    Args:
        college_id: School identifier from the verified 2027-2028 catalog.
        home_state: Two-letter US state code of family residence (e.g., "TX", "NJ").
        citizenship_status: Student citizenship/visa status enum.
        annual_merit_scholarship_usd: Expected annual merit scholarship in USD (>= 0).
        annual_need_grant_usd: Expected annual need-based institutional grant in USD (>= 0).
        annual_inflation_rate: Annual COA inflation rate as a decimal (0.0 to 0.20, default 0.045).
        needs_student_health_insurance: Whether to add mandatory campus health insurance.

    Returns:
        Dictionary matching FourYearCostResult with year-by-year net cost, 4-year total, and provenance.
    """
    catalog = {c["id"]: c for c in load_json_data("colleges_2027_2028.json")["colleges"]}
    school = catalog.get(college_id.lower())
    if not school:
        return ToolErrorResponse(
            error_code="UNKNOWN_COLLEGE_ID",
            message=f"College '{college_id}' not found in verified catalog.",
            recovery_hint="Pick a valid college_id from valid_options.",
            valid_options=sorted(catalog.keys()),
        ).model_dump()

    state_upper = validate_state_code(home_state)
    if state_upper is None:
        return ToolErrorResponse(
            error_code="INVALID_STATE_CODE",
            message=f"home_state '{home_state}' is not a valid 2-letter US state abbreviation.",
            recovery_hint="Convert the state name to its 2-letter USPS code (e.g., 'TX', 'NJ', 'CA') and retry.",
        ).model_dump()

    try:
        status_enum = CitizenshipStatus(citizenship_status.upper())
    except ValueError:
        return ToolErrorResponse(
            error_code="INVALID_CITIZENSHIP_STATUS",
            message=f"Invalid citizenship_status '{citizenship_status}'.",
            recovery_hint="Use a valid CitizenshipStatus enum value.",
            valid_options=[s.value for s in CitizenshipStatus],
        ).model_dump()

    if not (0.0 <= annual_inflation_rate <= 0.20):
        return ToolErrorResponse(
            error_code="INVALID_INFLATION_RATE",
            message=f"annual_inflation_rate={annual_inflation_rate} must be a decimal between 0.0 and 0.20.",
            recovery_hint="Pass inflation as a decimal (e.g., 0.045 for 4.5%, not 4.5) and retry.",
        ).model_dump()

    if annual_merit_scholarship_usd < 0 or annual_need_grant_usd < 0:
        return ToolErrorResponse(
            error_code="NEGATIVE_AID_AMOUNT",
            message="annual_merit_scholarship_usd and annual_need_grant_usd must be >= 0.",
            recovery_hint="Pass non-negative USD integers for scholarships and grants.",
        ).model_dump()

    state_rules = load_json_data("noncitizen_state_rules.json")["state_in_state_tuition_rules"]
    h4_state_verified = state_rules.get(state_upper, {}).get("h4_in_state_eligible", False)

    residency_note: str | None = None
    if school["type"] == "public" and school["state"] == state_upper:
        if status_enum == CitizenshipStatus.F1_INTERNATIONAL:
            is_in_state = False
            residency_note = "F-1 international students cannot establish state domicile for in-state tuition."
        elif status_enum in (CitizenshipStatus.US_CITIZEN, CitizenshipStatus.GREEN_CARD):
            is_in_state = True
        elif h4_state_verified:
            is_in_state = True
            residency_note = f"Modeled at in-state tuition based on verified {state_upper} H-4/domicile rules; confirm with university registrar."
        else:
            is_in_state = False
            residency_note = (
                f"In-state eligibility for {status_enum.value} in {state_upper} is not verified locally; "
                "conservatively modeled at out-of-state tuition. Verify with the university registrar."
            )
    else:
        is_in_state = False

    base_coa = school["annual_coa_in_state"] if is_in_state else school["annual_coa_out_of_state"]
    insurance = (
        school["health_insurance_annual"]
        if (needs_student_health_insurance or status_enum == CitizenshipStatus.F1_INTERNATIONAL)
        else 0
    )

    yearly: list[dict[str, int]] = []
    total_net = 0
    for yr in range(1, 5):
        gross = round((base_coa + insurance) * ((1 + annual_inflation_rate) ** (yr - 1)))
        net = max(0, gross - annual_merit_scholarship_usd - annual_need_grant_usd)
        total_net += net
        yearly.append({"year": yr, "gross_coa_usd": gross, "net_cost_usd": net})

    return FourYearCostResult(
        college=school["name"],
        tuition_basis="in_state" if is_in_state else "out_of_state_or_private",
        residency_verification_note=residency_note,
        ppy_tax_year_note="Fall 2028 entry (2028-2029 aid year) uses 2026 Prior-Prior Year (PPY) tax returns.",
        yearly_breakdown=yearly,
        four_year_net_total_usd=total_net,
        estimated_transition_costs_usd={
            "application_fee_estimate": 75,
            "css_profile_first_school_fee": 25 if school["type"] == "private" else 0,
            "css_profile_additional_school_fee": 16,
            "enrollment_and_housing_deposit": 500,
            "sevis_i901_fee": 350 if status_enum == CitizenshipStatus.F1_INTERNATIONAL else 0,
        },
        npc_accuracy_caveat=(
            "University Net Price Calculators (NPCs) are frequently inaccurate for non-US citizens, "
            "families with RSU/variable income, business/rental owners, or divorced parents (NCP CSS Profile)."
        ),
        provenance=build_provenance(
            source_url=school["source_url"],
            last_verified_date=school["last_verified_date"],
        ),
    ).model_dump()


@guided_tool_error_handler
def lookup_noncitizen_aid_policy(
    citizenship_status: str,
    home_state: str,
) -> dict[str, Any]:
    """Retrieves verified non-citizen financial aid, residency, and visa trade-off rules.

    Distinguishes US Citizen, Green Card (I-551), I-485 Pending + C09 EAD,
    H-4 Dependent, and F-1 International statuses, plus state in-state tuition rules
    and the 4-tier non-citizen aid classification.

    Args:
        citizenship_status: One of US_CITIZEN, GREEN_CARD, I485_PENDING_C09,
            H4_DEPENDENT, F1_INTERNATIONAL.
        home_state: Two-letter US state abbreviation (e.g., "TX", "CA", "NJ", "NY").

    Returns:
        Dictionary matching NonCitizenPolicyResult with state residency and provenance.
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

    rules = load_json_data("noncitizen_state_rules.json")
    status_info = rules["citizenship_statuses"][status_enum.value]
    state_info = rules["state_in_state_tuition_rules"].get(state_upper)

    return NonCitizenPolicyResult(
        citizenship_status=status_enum.value,
        fafsa_eligible=status_info["fafsa_eligible"],
        admissions_pool=status_info["admissions_pool"],
        aid_pool=status_info["aid_pool"],
        work_authorization=status_info["work_authorization"],
        key_notes=status_info["key_notes"],
        home_state=state_upper,
        state_residency_policy=state_info or {
            "rule_summary": (
                f"State '{state_upper}' is not in the local verified catalog. "
                "Verify H-4/non-citizen in-state tuition rules directly with your state public university registrar."
            )
        },
        four_tier_aid_framework={
            "tier_1": "Need-blind + 100% demonstrated need met (~10 selective privates; verify annually).",
            "tier_2": "Need-aware + 100% demonstrated need met if admitted.",
            "tier_3": "Merit-generous public & private universities open to H-4/F-1 applicants (e.g., ASU, UTD, USC).",
            "tier_4": "No institutional need-based aid for non-citizens (most OOS publics).",
        },
        provenance=build_provenance(
            source_url=status_info["source_url"],
            last_verified_date=rules["data_as_of"],
            cycle_year=rules["cycle_year"],
        ),
    ).model_dump()


@guided_tool_error_handler
def normalize_financial_aid_awards(
    college_name: str,
    annual_coa_usd: int,
    grants_and_scholarships_usd: int,
    loans_usd: int = 0,
    work_study_usd: int = 0,
    citizenship_status: str = "US_CITIZEN",
) -> dict[str, Any]:
    """Normalizes a college financial aid award letter into true net out-of-pocket cost.

    Separates free money (grants/scholarships) from self-help aid (loans and
    work-study) and flags Federal Work-Study ineligibility for non-FAFSA statuses
    (H-4, F-1, and I-485 pending).

    Args:
        college_name: Name of the university issuing the award letter.
        annual_coa_usd: Total annual Cost of Attendance listed on the award letter (> 0).
        grants_and_scholarships_usd: Total non-repayable grants and merit scholarships (>= 0).
        loans_usd: Total student/parent loans packaged in the offer (>= 0).
        work_study_usd: Federal Work-Study amount packaged in the offer (>= 0).
        citizenship_status: Student citizenship/visa status enum.

    Returns:
        Dictionary matching AwardNormalizationResult with true net price and warnings.
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

    if annual_coa_usd <= 0:
        return ToolErrorResponse(
            error_code="INVALID_COA",
            message="annual_coa_usd must be greater than zero.",
            recovery_hint="Provide the positive annual Cost of Attendance from the award letter.",
        ).model_dump()

    if grants_and_scholarships_usd < 0 or loans_usd < 0 or work_study_usd < 0:
        return ToolErrorResponse(
            error_code="NEGATIVE_AID_AMOUNT",
            message="grants_and_scholarships_usd, loans_usd, and work_study_usd must be >= 0.",
            recovery_hint="Pass non-negative integers from the financial aid award letter.",
        ).model_dump()

    true_net_price = max(0, annual_coa_usd - grants_and_scholarships_usd)
    warnings: list[str] = []
    if work_study_usd > 0 and status_enum in (
        CitizenshipStatus.H4_DEPENDENT,
        CitizenshipStatus.F1_INTERNATIONAL,
        CitizenshipStatus.I485_PENDING_C09,
    ):
        warnings.append(
            "Federal Work-Study is Title IV federal aid requiring FAFSA eligibility (US Citizen or Green Card in hand); "
            "do not count it as guaranteed cash."
        )
    if loans_usd > 0:
        warnings.append(
            f"Offer includes ${loans_usd:,}/yr in loans — remember loans must be repaid and do not reduce true net price."
        )

    return AwardNormalizationResult(
        college_name=college_name,
        annual_coa_usd=annual_coa_usd,
        free_gift_aid_usd=grants_and_scholarships_usd,
        self_help_aid_usd=loans_usd + work_study_usd,
        true_annual_net_price_usd=true_net_price,
        warnings=warnings,
        appeal_tip=(
            "If you have a lower net-price offer from a peer institution or 2026-2027 income changes, "
            "submit a polite Financial Aid Appeal before May 1, 2028."
        ),
    ).model_dump()
