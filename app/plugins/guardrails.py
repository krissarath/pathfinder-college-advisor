"""Global ADK GuardrailPolicyPlugin enforcing academic integrity, safety, and grounding."""

from __future__ import annotations

import re
from typing import Any

from app.prompts.constitution import (
    CRISIS_SUPPORT_RESPONSE,
    NONCITIZEN_FINANCIAL_DISCLAIMER,
)
from app.security.pii_redactor import get_pii_redactor

try:
    from google.adk.plugins.base_plugin import BasePlugin
except ImportError:  # pragma: no cover
    class BasePlugin:  # type: ignore[no-redef]
        def __init__(self, name: str = "base_plugin") -> None:
            self.name = name


_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\ufeff]")

_ESSAY_GHOSTWRITING_PATTERNS = [
    re.compile(
        r"\b(?:write|draft|generate|compose|create|craft|produce|expand|finish|complete)\b.{0,120}"
        r"\b(?:650[- ]?word|personal\s+statement|common\s+app\s+essay|college\s+essay|uc\s+piq|why\s+[\w\s]{1,20}\s+essay|supplement(?:al)?\s+essay)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"\b(?:sample|example)\s+(?:650[- ]?word|full)\s+(?:personal\s+statement|college\s+essay)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"\b(?:rewrite|turn|convert)\s+my\s+(?:bullet\s+notes|draft|outline)\s+into\s+a\s+(?:polished|complete|final)\s+(?:essay|personal\s+statement)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"\broleplay\s+as\s+an?\s+admitted\s+student\b.{0,80}\bessay\b",
        re.IGNORECASE | re.DOTALL,
    ),
]

_PROMPT_INJECTION_PATTERNS = [
    re.compile(r"(?:ignore|disregard|forget|override)\s+(?:all\s+)?(?:previous|prior|system|your)\s+(?:instructions|rules|guardrails)", re.IGNORECASE),
    re.compile(r"(?:reveal|print|show|repeat)\s+(?:your\s+)?(?:system\s+prompt|constitution|hidden\s+instructions)", re.IGNORECASE),
    re.compile(r"(?:bypass|skip|disable|auto-approve)\s+(?:tool\s+confirmation|hitl|confirmation|guardrails)", re.IGNORECASE),
]

_CRISIS_PATTERNS = [
    re.compile(r"\b(?:kill\s+myself|end\s+my\s+life|suicide|want\s+to\s+die|don'?t\s+want\s+to\s+live|ending\s+it\s+all|hurt\s+myself|self[- ]?harm)\b", re.IGNORECASE),
]

_NONCITIZEN_OR_FINANCE_KEYWORDS = re.compile(
    r"\b(?:H-?4|F-?1|I-?485|I-?551|I-?20|SEVIS|CPT|OPT|EAD|C09|DACA|Green\s+Card|FAFSA|CSS\s+Profile|ISFAA|IDOC|TASFA|WASFA|in-state\s+tuition|non-?citizen|citizenship|visa|immigration|DSO|financial\s+aid|need-blind|need-aware|scholarship|merit\s+aid|tuition|COA|Net\s+Price|Work-Study)\b",
    re.IGNORECASE,
)

_CANONICAL_DISCLAIMER_MARKER = (
    "Verify all figures and eligibility rules directly with the university's Admissions/Financial Aid Office"
)


def _normalize(text: str) -> str:
    cleaned = _ZERO_WIDTH_RE.sub("", text)
    return re.sub(r"\s+", " ", cleaned).strip()


def evaluate_input_guardrails(
    user_text: str,
    prohibited_doc_flags: list[str] | None = None,
) -> dict[str, Any]:
    """Deterministic pre-model guardrail evaluation (unit-testable offline).

    Returns:
        Dict with keys: action ("allow" | "block"), reason, response_text.
    """
    normalized = _normalize(user_text or "")

    for pattern in _CRISIS_PATTERNS:
        if pattern.search(normalized):
            return {
                "action": "block",
                "reason": "CRISIS_SUPPORT_TRIGGERED",
                "response_text": CRISIS_SUPPORT_RESPONSE,
            }

    prohibited_docs = list(prohibited_doc_flags or [])
    if not prohibited_docs and normalized:
        prohibited_docs = get_pii_redactor().detect_prohibited_document(normalized)
    if prohibited_docs:
        return {
            "action": "block",
            "reason": f"PROHIBITED_SENSITIVE_DOCUMENT:{','.join(sorted(set(prohibited_docs)))}",
            "response_text": (
                "For your family's privacy and safety, please do not paste raw tax returns "
                "(1040/W-2), bank statements, or passport/I-20 scans. Share approximate "
                "income/budget brackets (for example, '$100k-$150k') and visa category instead."
            ),
        }

    for pattern in _PROMPT_INJECTION_PATTERNS:
        if pattern.search(normalized):
            return {
                "action": "block",
                "reason": "PROMPT_INJECTION_BLOCKED",
                "response_text": (
                    "I cannot override safety rules, reveal system instructions, or bypass "
                    "Human-in-the-Loop confirmations. How can I help with your 2027-2028 "
                    "college application plan?"
                ),
            }

    for pattern in _ESSAY_GHOSTWRITING_PATTERNS:
        if pattern.search(normalized):
            return {
                "action": "block",
                "reason": "ACADEMIC_INTEGRITY_ESSAY_REFUSAL",
                "response_text": (
                    "I cannot write, draft, or wholesale-rewrite your Common App personal "
                    "statement or supplemental essays — admissions essays must be in your own voice. "
                    "I can help you brainstorm themes, build a 4-part outline, or give rubric "
                    "feedback on a draft you write. Would you like 5 brainstorming questions?"
                ),
            }

    return {"action": "allow", "reason": None, "response_text": None}


def apply_output_guardrails(response_text: str, agent_name: str = "") -> str:
    """Deterministically enforces post-model disclaimers and output safety checks."""
    if not response_text:
        return response_text

    needs_disclaimer = (
        agent_name == "financial_aid_and_citizenship_agent"
        or bool(_NONCITIZEN_OR_FINANCE_KEYWORDS.search(response_text))
    )
    if needs_disclaimer and _CANONICAL_DISCLAIMER_MARKER not in response_text:
        return response_text + NONCITIZEN_FINANCIAL_DISCLAIMER
    return response_text


def wrap_untrusted_student_input(text: str) -> str:
    """Wraps pasted external text/drafts in untrusted-data delimiters, escaping closing tags."""
    safe = text.replace("</untrusted_student_input>", "&lt;/untrusted_student_input&gt;")
    return f"<untrusted_student_input>\n{safe}\n</untrusted_student_input>"


class GuardrailPolicyPlugin(BasePlugin):
    """Global ADK BasePlugin enforcing safety, integrity, and deterministic disclaimers."""

    MAX_SELF_EVAL_RETRIES = 1

    def __init__(self) -> None:
        super().__init__(name="pathfinder_guardrail_policy_plugin")

    async def before_model_callback(
        self, *, callback_context: Any, llm_request: Any
    ) -> Any:
        # Only inspect the root coordinator's actual user turn; skip internal ADK
        # sub-agent handoff turns ("For context: [...]") so agent-authored mentions
        # of W-2/IDOC/1040 never false-trigger the raw-document No-Ingest blocker.
        agent_name = getattr(callback_context, "agent_name", "")
        if agent_name and agent_name != "counselor_coordinator_agent":
            return None

        contents = getattr(llm_request, "contents", None) or []
        latest_user_text = ""
        for content in reversed(contents):
            if getattr(content, "role", None) == "user":
                parts = getattr(content, "parts", None) or []
                candidate = " ".join(getattr(p, "text", "") or "" for p in parts).strip()
                if candidate and not candidate.startswith("For context:"):
                    latest_user_text = candidate
                    break

        state = getattr(callback_context, "state", None)
        prohibited_flags = state.get("_prohibited_doc_flags", []) if state is not None else []
        verdict = evaluate_input_guardrails(latest_user_text, prohibited_doc_flags=prohibited_flags)

        if verdict["action"] == "block":
            if state is not None:
                state["_prohibited_doc_flags"] = []
            try:
                from google.adk.models.llm_response import LlmResponse
                from google.genai import types

                return LlmResponse(
                    content=types.Content(
                        role="model",
                        parts=[types.Part(text=verdict["response_text"])],
                    )
                )
            except ImportError:
                return {"blocked": True, "reason": verdict["reason"], "text": verdict["response_text"]}
        return None

    async def after_model_callback(
        self, *, callback_context: Any, llm_response: Any
    ) -> None:
        content = getattr(llm_response, "content", None)
        parts = getattr(content, "parts", None) or []
        agent_name = getattr(callback_context, "agent_name", "")
        text_parts = [p for p in parts if isinstance(getattr(p, "text", None), str) and p.text]
        if text_parts:
            last_part = text_parts[-1]
            last_part.text = apply_output_guardrails(last_part.text, agent_name=agent_name)
        # Return None so downstream plugins are never short-circuited.
        return None
