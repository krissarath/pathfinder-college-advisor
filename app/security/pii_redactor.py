"""Five-choke-point PII redaction engine using Google Cloud DLP with regex fallback.

Covers minor student identifiers (FERPA/COPPA-aware), financial/tax numbers,
and immigration/visa identifiers. Signals dlp_degraded=True on Cloud DLP
initialization or runtime failures so loggers and trace processors fail closed.
"""

from __future__ import annotations

import os
import re
from typing import Any

# Deterministic regex rules for offline/CI execution and defense-in-depth fallback.
_PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("SSN_OR_ITIN", re.compile(r"\b\d{3}[-\s]\d{2}[-\s]\d{4}\b|\b(?:SSN|ITIN)[\s:#-]*\d{9}\b", re.IGNORECASE)),
    ("USCIS_A_NUMBER", re.compile(r"\bA-?\d{3}-?\d{3}-?\d{3}\b", re.IGNORECASE)),
    ("SEVIS_ID", re.compile(r"\bN00\d{8}\b")),
    ("USCIS_RECEIPT", re.compile(r"\b(?:EAC|WAC|LIN|SRC|MSC|IOE)\d{10}\b")),
    ("I94_NUMBER", re.compile(r"\b(?:I-?94[\s:#-]*)[A-Z0-9]{9,11}\b", re.IGNORECASE)),
    ("PASSPORT_NUMBER", re.compile(r"\b(?:passport[\s:#-]*)[A-Z0-9]{6,12}\b", re.IGNORECASE)),
    ("COMMON_APP_ID", re.compile(r"\b(?:CAID|Common\s*App\s*ID)[\s:#-]*\d{6,10}\b", re.IGNORECASE)),
    ("EMAIL_ADDRESS", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("PHONE_NUMBER", re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")),
    ("BANK_ROUTING_OR_ACCT", re.compile(r"\b(?:acct|account|routing)[\s:#-]*\d{6,17}\b", re.IGNORECASE)),
    ("TAX_FORM_OR_EIN", re.compile(r"\b(?:EIN[\s:#-]*\d{2}-\d{7}|1040\s*AGI[\s:$]*[\d,]+)\b", re.IGNORECASE)),
    (
        "DATE_OF_BIRTH",
        re.compile(
            r"\b(?:DOB|date\s+of\s+birth)[\s:#-]*(?:\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|[A-Z][a-z]+\s+\d{1,2},?\s+\d{4})\b",
            re.IGNORECASE,
        ),
    ),
    ("STREET_ADDRESS", re.compile(r"\b\d{1,5}\s+[A-Za-z0-9.\s]{2,30}\s(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Ln|Lane|Dr|Drive|Ct|Court)\b", re.IGNORECASE)),
]

# Keywords indicating raw sensitive document uploads prohibited by the No-Ingest Policy.
_PROHIBITED_DOC_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("RAW_TAX_RETURN", re.compile(r"\b(?:Form\s+1040(?:-NR)?|W-2\b|Adjusted\s+Gross\s+Income\s+line)\b", re.IGNORECASE)),
    ("RAW_BANK_STATEMENT", re.compile(r"\b(?:bank\s+statement|routing\s+number|account\s+balance\s+statement)\b", re.IGNORECASE)),
    ("RAW_PASSPORT_OR_IMMIGRATION_DOC", re.compile(r"\b(?:passport\s+scan|I-20\s+form\s+text|visa\s+foil\s+number|DS-160|Green\s+Card\s+scan|EAD\s+card\s+scan)\b", re.IGNORECASE)),
]

_CLOUD_DLP_INFO_TYPES = [
    "PERSON_NAME",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "US_SOCIAL_SECURITY_NUMBER",
    "US_INDIVIDUAL_TAXPAYER_IDENTIFICATION_NUMBER",
    "PASSPORT",
    "DATE_OF_BIRTH",
    "STREET_ADDRESS",
    "US_BANK_ROUTING_MICR",
]


class PiiRedactor:
    """Scrubs sensitive minor, financial, and immigration PII via Cloud DLP + regex."""

    def __init__(
        self,
        project_id: str | None = None,
        enable_cloud_dlp: bool | None = None,
    ) -> None:
        self.project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT", "")
        if enable_cloud_dlp is None:
            self.enable_cloud_dlp = os.getenv("ENABLE_CLOUD_DLP", "false").lower() == "true"
        else:
            self.enable_cloud_dlp = enable_cloud_dlp
        self._dlp_client: Any = None
        self.dlp_degraded = False

        if self.enable_cloud_dlp:
            if not self.project_id or self.project_id == "your-gcp-project-id":
                self.dlp_degraded = True
            else:
                try:
                    from google.cloud import dlp_v2

                    self._dlp_client = dlp_v2.DlpServiceClient()
                except Exception:
                    # Fail-closed signal: regex still runs, and loggers/spans suppress raw text.
                    self.dlp_degraded = True

    def detect_prohibited_document(self, text: str) -> list[str]:
        """Checks whether text appears to contain prohibited raw tax/bank/passport documents."""
        if not text:
            return []
        hits: list[str] = []
        for label, pattern in _PROHIBITED_DOC_PATTERNS:
            if pattern.search(text):
                hits.append(label)
        return hits

    def redact_text(self, text: str) -> str:
        """Redacts PII from free text using Cloud DLP (when enabled) and deterministic regex."""
        if not text:
            return text

        redacted = text
        if self._dlp_client and self.project_id:
            try:
                parent = f"projects/{self.project_id}/locations/global"
                inspect_config = {
                    "info_types": [{"name": name} for name in _CLOUD_DLP_INFO_TYPES]
                }
                deidentify_config = {
                    "info_type_transformations": {
                        "transformations": [
                            {"primitive_transformation": {"replace_with_info_type_config": {}}}
                        ]
                    }
                }
                response = self._dlp_client.deidentify_content(
                    request={
                        "parent": parent,
                        "inspect_config": inspect_config,
                        "deidentify_config": deidentify_config,
                        "item": {"value": redacted},
                    }
                )
                redacted = response.item.value
            except Exception:
                self.dlp_degraded = True

        # Always apply deterministic regex pass as defense-in-depth.
        for label, pattern in _PII_PATTERNS:
            redacted = pattern.sub(f"[REDACTED_{label}]", redacted)
        return redacted

    def redact_structure(self, payload: Any) -> Any:
        """Recursively scrubs PII from dicts, lists, and strings."""
        if isinstance(payload, str):
            return self.redact_text(payload)
        if isinstance(payload, dict):
            return {k: self.redact_structure(v) for k, v in payload.items()}
        if isinstance(payload, list):
            return [self.redact_structure(item) for item in payload]
        if isinstance(payload, tuple):
            return tuple(self.redact_structure(item) for item in payload)
        return payload


_DEFAULT_REDACTOR: PiiRedactor | None = None


def get_pii_redactor() -> PiiRedactor:
    """Returns the singleton PiiRedactor instance."""
    global _DEFAULT_REDACTOR
    if _DEFAULT_REDACTOR is None:
        _DEFAULT_REDACTOR = PiiRedactor()
    return _DEFAULT_REDACTOR
