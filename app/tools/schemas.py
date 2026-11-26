"""Strict Pydantic v2 schemas, provenance metadata, and async-aware guided error wrapper.

All PathFinder AI tools validate inputs/outputs with explicit Pydantic v2 schemas
and return structured ToolErrorResponse dictionaries with actionable recovery_hint
values instead of raising unhandled exceptions.
"""

from __future__ import annotations

import functools
import inspect
import json
from collections.abc import Callable
from datetime import date
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, Field, ValidationError

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STALENESS_THRESHOLD_DAYS = 180

US_STATE_CODES = frozenset(
    {
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
        "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
        "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
        "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
        "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
    }
)


class CitizenshipStatus(StrEnum):
    US_CITIZEN = "US_CITIZEN"
    GREEN_CARD = "GREEN_CARD"
    I485_PENDING_C09 = "I485_PENDING_C09"
    H4_DEPENDENT = "H4_DEPENDENT"
    F1_INTERNATIONAL = "F1_INTERNATIONAL"


class ApplicationRound(StrEnum):
    ED_I = "ED_I"
    ED_II = "ED_II"
    EA = "EA"
    REA = "REA"
    RD = "RD"
    ROLLING = "ROLLING"


class ProvenanceMetadata(BaseModel):
    """Data provenance and freshness metadata attached to every factual tool output."""

    source_url: str = Field(description="Official URL where the policy or deadline was verified.")
    last_verified_date: str = Field(description="ISO date (YYYY-MM-DD) when data was last verified.")
    cycle_year: str = Field(default="2027-2028", description="Target college application cycle.")
    staleness_warning: str | None = Field(
        default=None,
        description="Warning populated automatically if data is older than 180 days.",
    )


class ToolErrorResponse(BaseModel):
    """Structured error envelope with guided recovery instructions for the LLM."""

    status: str = Field(default="error")
    error_code: str = Field(description="Machine-readable error identifier.")
    message: str = Field(description="Human-readable explanation of what failed.")
    recovery_hint: str = Field(description="Actionable instruction telling the LLM how to recover.")
    valid_options: list[str] = Field(
        default_factory=list,
        description="Allowed parameter values when input validation fails.",
    )


class ActivityAuditResult(BaseModel):
    status: str = "ok"
    total_activities: int
    exceeds_10_slot_limit: bool
    honors_count: int
    exceeds_5_honor_limit: bool
    over_150_char_entries: list[dict[str, int]]
    coaching_tips: list[str]


class CollegeSearchResult(BaseModel):
    status: str = "ok"
    disclaimer: str
    cycle_year: str
    matches: list[dict[str, Any]]
    residency_warning: str | None = None


class RoundValidationResult(BaseModel):
    status: str = "ok"
    is_valid: bool
    conflicts: list[str]
    warnings: list[str]


class EnglishWaiverResult(BaseModel):
    status: str = "ok"
    college: str
    english_test_required: bool
    years_in_us_high_school: int
    minimum_us_hs_years_for_waiver: int
    likely_waived: bool
    policy_note: str
    portal_action: str
    provenance: ProvenanceMetadata


class FourYearCostResult(BaseModel):
    status: str = "ok"
    college: str
    tuition_basis: str
    residency_verification_note: str | None = None
    ppy_tax_year_note: str
    yearly_breakdown: list[dict[str, int]]
    four_year_net_total_usd: int
    estimated_transition_costs_usd: dict[str, int]
    npc_accuracy_caveat: str
    provenance: ProvenanceMetadata


class NonCitizenPolicyResult(BaseModel):
    status: str = "ok"
    citizenship_status: str
    fafsa_eligible: bool
    admissions_pool: str
    aid_pool: str
    work_authorization: str
    key_notes: list[str]
    home_state: str
    state_residency_policy: dict[str, Any]
    four_tier_aid_framework: dict[str, str]
    provenance: ProvenanceMetadata


class AwardNormalizationResult(BaseModel):
    status: str = "ok"
    college_name: str
    annual_coa_usd: int
    free_gift_aid_usd: int
    self_help_aid_usd: int
    true_annual_net_price_usd: int
    warnings: list[str]
    appeal_tip: str


class DeadlineScheduleResult(BaseModel):
    status: str = "ok"
    cycle_year: str
    entry_term: str
    ppy_tax_year: int
    common_app_specs: dict[str, Any]
    milestones: list[dict[str, str]]
    provenance: ProvenanceMetadata


def validate_state_code(home_state: str) -> str | None:
    """Normalizes and validates a 2-letter US state code, returning None if invalid."""
    normalized = home_state.strip().upper()
    return normalized if normalized in US_STATE_CODES else None


def build_provenance(
    source_url: str,
    last_verified_date: str,
    cycle_year: str = "2027-2028",
) -> ProvenanceMetadata:
    """Builds ProvenanceMetadata and flags records older than 180 days."""
    warning: str | None = None
    try:
        verified = date.fromisoformat(last_verified_date)
        age_days = (date.today() - verified).days
        if age_days > STALENESS_THRESHOLD_DAYS:
            warning = (
                f"Data is {age_days} days old (last verified {last_verified_date}). "
                "Verify directly on the official university website before acting."
            )
    except ValueError:
        warning = "Unable to parse last_verified_date; verify directly on the official website."
    return ProvenanceMetadata(
        source_url=source_url,
        last_verified_date=last_verified_date,
        cycle_year=cycle_year,
        staleness_warning=warning,
    )


@lru_cache(maxsize=8)
def load_json_data(filename: str) -> dict[str, Any]:
    """Loads and caches a verified synthetic/public JSON dataset from app/data/."""
    path = DATA_DIR / filename
    return json.loads(path.read_text(encoding="utf-8"))


F = TypeVar("F", bound=Callable[..., Any])


def _format_error(func_name: str, exc: Exception) -> dict[str, Any]:
    if isinstance(exc, ValidationError):
        return ToolErrorResponse(
            error_code="INVALID_TOOL_ARGUMENTS",
            message=f"Input validation failed for {func_name}: {exc.errors()}",
            recovery_hint="Correct the argument types or enum values using the schema and retry.",
        ).model_dump()
    if isinstance(exc, ValueError):
        return ToolErrorResponse(
            error_code="VALUE_ERROR",
            message=str(exc),
            recovery_hint="Check the allowed options and re-invoke the tool with valid arguments.",
        ).model_dump()
    return ToolErrorResponse(
        error_code="UNEXPECTED_TOOL_ERROR",
        message=f"Unexpected error in {func_name}: {exc}",
        recovery_hint="Inform the user of the temporary tool error and direct them to the official source.",
    ).model_dump()


def guided_tool_error_handler(func: F) -> F:
    """Sync/async decorator converting ValidationError and runtime errors into ToolErrorResponse."""
    if inspect.iscoroutinefunction(func):
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
            try:
                return await func(*args, **kwargs)
            except Exception as exc:  # pragma: no cover
                return _format_error(func.__name__, exc)

        return async_wrapper  # type: ignore[return-value]

    @functools.wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # pragma: no cover
            return _format_error(func.__name__, exc)

    return sync_wrapper  # type: ignore[return-value]
