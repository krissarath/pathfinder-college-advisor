"""Global ADK PII Redaction Plugin & Pre-Session Ingress Scrubber.

Implements on_user_message_callback (runs BEFORE ADK persists user events to
DatabaseSessionService), plus before_model_callback, before_tool_callback, and
in-place after_tool_callback (returning None so downstream plugins always run).
"""

from __future__ import annotations

from typing import Any

from app.security.pii_redactor import get_pii_redactor

try:
    from google.adk.plugins.base_plugin import BasePlugin
except ImportError:  # pragma: no cover
    class BasePlugin:  # type: ignore[no-redef]
        def __init__(self, name: str = "base_plugin") -> None:
            self.name = name


def scrub_user_ingress(raw_message: str) -> tuple[str, list[str]]:
    """Scrubs PII at API ingress BEFORE ADK DatabaseSessionService persists events.

    Args:
        raw_message: Raw user prompt text.

    Returns:
        Tuple of (redacted_message, prohibited_document_flags).
    """
    redactor = get_pii_redactor()
    prohibited = redactor.detect_prohibited_document(raw_message)
    scrubbed = redactor.redact_text(raw_message)
    return scrubbed, prohibited


class PiiRedactionPlugin(BasePlugin):
    """Global ADK plugin scrubbing PII across ingress, model requests, and tool payloads."""

    def __init__(self) -> None:
        super().__init__(name="pathfinder_pii_redaction_plugin")
        self._redactor = get_pii_redactor()

    async def on_user_message_callback(
        self, *, invocation_context: Any, user_message: Any
    ) -> None:
        parts = getattr(user_message, "parts", None) or []
        prohibited_hits: list[str] = []
        for part in parts:
            text = getattr(part, "text", None)
            if isinstance(text, str) and text:
                scrubbed, prohibited = scrub_user_ingress(text)
                part.text = scrubbed
                prohibited_hits.extend(prohibited)
        session = getattr(invocation_context, "session", None)
        if session is not None and getattr(session, "state", None) is not None:
            session.state["_prohibited_doc_flags"] = sorted(set(prohibited_hits))
        return None

    async def before_model_callback(
        self, *, callback_context: Any, llm_request: Any
    ) -> None:
        contents = getattr(llm_request, "contents", None) or []
        for content in contents:
            parts = getattr(content, "parts", None) or []
            for part in parts:
                text = getattr(part, "text", None)
                if isinstance(text, str) and text:
                    part.text = self._redactor.redact_text(text)
        return None

    async def before_tool_callback(
        self, *, tool: Any, tool_args: dict[str, Any], tool_context: Any
    ) -> None:
        for key, value in list(tool_args.items()):
            tool_args[key] = self._redactor.redact_structure(value)
        return None

    async def after_tool_callback(
        self, *, tool: Any, tool_args: dict[str, Any], tool_context: Any, result: dict[str, Any]
    ) -> None:
        # Mutate in-place and return None so ADK PluginManager does not short-circuit
        # ObservabilityPlugin.after_tool_callback.
        if isinstance(result, dict):
            redacted = self._redactor.redact_structure(result)
            result.clear()
            result.update(redacted)
        return None
