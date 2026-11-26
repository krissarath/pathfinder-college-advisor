"""PathFinder AI package entrypoint exporting root_agent and app for adk web / adk eval."""

from __future__ import annotations

try:
    from app.agent import app, root_agent
except ImportError:  # pragma: no cover - allows offline tool/security unit tests without ADK
    app = None  # type: ignore[assignment]
    root_agent = None  # type: ignore[assignment]

__all__ = ["app", "root_agent"]
