"""Structured JSON logging, OpenTelemetry tracing, and Intent-vs-Outcome plugin.

Implements:
- structlog JSON logging with automatic Cloud Logging trace correlation.
- Fail-closed logging & OpenTelemetry SpanProcessor when Cloud DLP is degraded.
- Global ADK BasePlugin capturing agent-level and tool-level intent vs. outcome.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from app.security.pii_redactor import get_pii_redactor

try:
    import structlog
except ImportError:  # pragma: no cover
    structlog = None  # type: ignore[assignment]

try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
except ImportError:  # pragma: no cover
    trace = None  # type: ignore[assignment]
    SpanProcessor = object  # type: ignore[assignment,misc]

try:
    from google.adk.plugins.base_plugin import BasePlugin
except ImportError:  # pragma: no cover
    class BasePlugin:  # type: ignore[no-redef]
        def __init__(self, name: str = "base_plugin") -> None:
            self.name = name


_TRACING_INITIALIZED = False

_SAFE_LOG_ALLOWLIST = frozenset(
    {
        "event",
        "level",
        "timestamp",
        "agent_name",
        "tool_name",
        "invocation_id",
        "session_id",
        "status",
        "latency_ms",
        "trace_id",
        "span_id",
        "logging.googleapis.com/trace",
        "logging.googleapis.com/spanId",
        "keys",
        "arg_keys",
        "redacted_result_keys",
        "dlp_degraded",
    }
)


class PiiScrubbingSpanProcessor(SpanProcessor):  # type: ignore[misc]
    """OpenTelemetry SpanProcessor that redacts PII and fails closed if DLP is degraded."""

    _SENSITIVE_ATTR_PREFIXES = (
        "gen_ai.prompt",
        "gen_ai.completion",
        "gen_ai.content",
        "gen_ai.input",
        "gen_ai.output",
        "gcp.vertex.agent.llm_request",
        "gcp.vertex.agent.llm_response",
        "gcp.vertex.agent.tool_call_args",
        "gcp.vertex.agent.tool_response",
    )

    def __init__(self) -> None:
        self._redactor = get_pii_redactor()
        self._capture_content = os.getenv("CAPTURE_MESSAGE_CONTENT", "false").lower() == "true"

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        return None

    def on_end(self, span: Any) -> None:
        attributes = getattr(span, "_attributes", None)
        if not isinstance(attributes, dict):
            return
        for key in list(attributes.keys()):
            if not self._capture_content and key.startswith(self._SENSITIVE_ATTR_PREFIXES):
                attributes[key] = "[REDACTED_CONTENT_DISABLED]"
                continue
            val = attributes[key]
            if isinstance(val, str):
                if self._redactor.dlp_degraded and key not in _SAFE_LOG_ALLOWLIST:
                    attributes[key] = "[SUPPRESSED_DLP_DEGRADED]"
                else:
                    attributes[key] = self._redactor.redact_text(val)


def _otel_trace_processor(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Injects OpenTelemetry trace_id and span_id for Cloud Logging correlation."""
    if trace is not None:
        span = trace.get_current_span()
        ctx = span.get_span_context() if span else None
        if ctx and ctx.is_valid:
            trace_id = format(ctx.trace_id, "032x")
            span_id = format(ctx.span_id, "016x")
            project = os.getenv("GOOGLE_CLOUD_PROJECT", "local-project")
            event_dict["trace_id"] = trace_id
            event_dict["span_id"] = span_id
            event_dict["logging.googleapis.com/trace"] = f"projects/{project}/traces/{trace_id}"
            event_dict["logging.googleapis.com/spanId"] = span_id
    return event_dict


def _pii_log_processor(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Scrubs all string fields in structured JSON logs and fails closed when DLP is degraded."""
    redactor = get_pii_redactor()
    if redactor.dlp_degraded:
        return {
            k: (v if k in _SAFE_LOG_ALLOWLIST else "[SUPPRESSED_DLP_DEGRADED]")
            for k, v in event_dict.items()
        }
    return redactor.redact_structure(event_dict)


def configure_observability() -> Any:
    """Initializes structlog JSON logging and global OpenTelemetry TracerProvider."""
    global _TRACING_INITIALIZED

    if trace is not None and not _TRACING_INITIALIZED:
        provider = TracerProvider()
        provider.add_span_processor(PiiScrubbingSpanProcessor())
        if os.getenv("ENABLE_CLOUD_TRACE", "false").lower() == "true":
            try:
                from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

                provider.add_span_processor(BatchSpanProcessor(CloudTraceSpanExporter()))
            except Exception:
                # Never fall back to ConsoleSpanExporter in prod (avoids raw span stdout dumps).
                pass
        trace.set_tracer_provider(provider)
        _TRACING_INITIALIZED = True

    if structlog is not None:
        structlog.configure(
            processors=[
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.add_log_level,
                _otel_trace_processor,
                _pii_log_processor,
                structlog.processors.JSONRenderer(),
            ],
            logger_factory=structlog.PrintLoggerFactory(),
            cache_logger_on_first_use=True,
        )
        return structlog.get_logger("pathfinder")

    return logging.getLogger("pathfinder")


class ObservabilityPlugin(BasePlugin):
    """Global ADK plugin recording agent-level and tool-level Intent vs. Outcome."""

    def __init__(self) -> None:
        super().__init__(name="pathfinder_observability_plugin")
        self._logger = configure_observability()
        self._redactor = get_pii_redactor()
        self._timers: dict[str, float] = {}

    async def before_agent_callback(
        self, *, agent: Any, callback_context: Any
    ) -> None:
        agent_name = getattr(agent, "name", "unknown_agent")
        inv_id = getattr(callback_context, "invocation_id", "unknown")
        self._timers[f"agent:{inv_id}:{agent_name}"] = time.perf_counter()
        self._logger.info(
            "agent_intent",
            agent_name=agent_name,
            invocation_id=inv_id,
            session_id=getattr(getattr(callback_context, "session", None), "id", "unknown"),
        )
        return None

    async def after_agent_callback(
        self, *, agent: Any, callback_context: Any
    ) -> None:
        agent_name = getattr(agent, "name", "unknown_agent")
        inv_id = getattr(callback_context, "invocation_id", "unknown")
        start = self._timers.pop(f"agent:{inv_id}:{agent_name}", None)
        latency_ms = round((time.perf_counter() - start) * 1000, 2) if start else None
        self._logger.info(
            "agent_outcome",
            agent_name=agent_name,
            invocation_id=inv_id,
            latency_ms=latency_ms,
        )
        return None

    async def before_tool_callback(
        self, *, tool: Any, tool_args: dict[str, Any], tool_context: Any
    ) -> None:
        tool_name = getattr(tool, "name", str(tool))
        inv_id = getattr(tool_context, "invocation_id", "unknown")
        self._timers[f"tool:{inv_id}:{tool_name}"] = time.perf_counter()
        if self._redactor.dlp_degraded:
            self._logger.info(
                "tool_intent",
                tool_name=tool_name,
                invocation_id=inv_id,
                arg_keys=list(tool_args.keys()),
                dlp_degraded=True,
            )
        else:
            safe_args = self._redactor.redact_structure(tool_args)
            self._logger.info(
                "tool_intent",
                tool_name=tool_name,
                invocation_id=inv_id,
                redacted_args=safe_args,
            )
        return None

    async def after_tool_callback(
        self, *, tool: Any, tool_args: dict[str, Any], tool_context: Any, result: dict[str, Any]
    ) -> None:
        tool_name = getattr(tool, "name", str(tool))
        inv_id = getattr(tool_context, "invocation_id", "unknown")
        start = self._timers.pop(f"tool:{inv_id}:{tool_name}", None)
        latency_ms = round((time.perf_counter() - start) * 1000, 2) if start else None
        status = result.get("status", "ok") if isinstance(result, dict) else "ok"
        self._logger.info(
            "tool_outcome",
            tool_name=tool_name,
            invocation_id=inv_id,
            status=status,
            latency_ms=latency_ms,
            redacted_result_keys=list(result.keys()) if isinstance(result, dict) else [],
        )
        return None
