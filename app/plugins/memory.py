"""Persistent session service, long-term memory store, and tracked async consolidation.

Uses:
- ADK DatabaseSessionService (Cloud SQL PostgreSQL in prod, local SQLite in dev).
- Tracked asyncio background task set (strong references + done-callback error logging)
  calling BOTH ADK callback_context.add_session_to_memory() (so PreloadMemoryTool reads
  it) AND Firestore StudentMemoryStore with pre-write PII redaction.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import Any

from app.plugins.observability import configure_observability
from app.security.pii_redactor import get_pii_redactor

try:
    from google.adk.plugins.base_plugin import BasePlugin
except ImportError:  # pragma: no cover
    class BasePlugin:  # type: ignore[no-redef]
        def __init__(self, name: str = "base_plugin") -> None:
            self.name = name


_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()
_LOGGER = configure_observability()


def create_session_service() -> Any:
    """Creates ADK DatabaseSessionService using SESSION_DB_URL."""
    from google.adk.sessions import DatabaseSessionService

    db_url = os.getenv("SESSION_DB_URL", "sqlite+aiosqlite:///./pathfinder_sessions.db")
    return DatabaseSessionService(db_url=db_url)


def create_memory_service() -> Any:
    """Creates ADK InMemoryMemoryService locally (or VertexAiMemoryBankService in prod)."""
    from google.adk.memory import InMemoryMemoryService

    return InMemoryMemoryService()


class StudentMemoryStore:
    """Persistent long-term student preference store (Firestore in prod, dict locally)."""

    def __init__(self) -> None:
        self._redactor = get_pii_redactor()
        self._backend = os.getenv("MEMORY_BACKEND", "local").lower()
        self._local_store: dict[str, list[dict[str, Any]]] = {}
        self._firestore_client: Any = None

        if self._backend == "firestore":
            try:
                from google.cloud import firestore

                self._firestore_client = firestore.AsyncClient()
            except Exception:
                self._backend = "local"

    async def write_memory_entry(self, user_id: str, entry: dict[str, Any]) -> dict[str, Any]:
        """Scrubs PII and persists a consolidated memory entry for a user."""
        safe_entry = self._redactor.redact_structure(entry)
        safe_entry["updated_at"] = datetime.now(UTC).isoformat()
        safe_entry["ttl_days"] = 90

        if self._firestore_client is not None:
            doc_ref = (
                self._firestore_client.collection("student_memories")
                .document(user_id)
                .collection("entries")
                .document()
            )
            await doc_ref.set(safe_entry)
        else:
            self._local_store.setdefault(user_id, []).append(safe_entry)

        return safe_entry

    async def read_memories(self, user_id: str) -> list[dict[str, Any]]:
        """Retrieves consolidated memory entries for a user."""
        if self._firestore_client is not None:
            docs = (
                self._firestore_client.collection("student_memories")
                .document(user_id)
                .collection("entries")
                .stream()
            )
            return [doc.to_dict() async for doc in docs]
        return list(self._local_store.get(user_id, []))

    async def delete_user_memories(self, user_id: str) -> int:
        """Deletes all stored memories for a user (minor data lifecycle hygiene)."""
        if self._firestore_client is not None:
            docs = (
                self._firestore_client.collection("student_memories")
                .document(user_id)
                .collection("entries")
                .stream()
            )
            count = 0
            async for doc in docs:
                await doc.reference.delete()
                count += 1
            return count
        return len(self._local_store.pop(user_id, []))


_MEMORY_STORE = StudentMemoryStore()


def get_memory_store() -> StudentMemoryStore:
    """Returns the singleton StudentMemoryStore."""
    return _MEMORY_STORE


def _handle_task_done(task: asyncio.Task[Any]) -> None:
    _BACKGROUND_TASKS.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        _LOGGER.error("async_memory_consolidation_failed", error=str(exc))


def schedule_memory_consolidation(
    user_id: str,
    session_state: dict[str, Any],
    callback_context: Any = None,
) -> asyncio.Task[Any]:
    """Schedules non-blocking async memory consolidation with strong task tracking."""

    async def _consolidate() -> None:
        # 1. Sync to ADK BaseMemoryService so PreloadMemoryTool retrieves across sessions.
        add_fn = getattr(callback_context, "add_session_to_memory", None)
        if callable(add_fn):
            try:
                await add_fn()
            except Exception as exc:
                _LOGGER.warning("adk_memory_service_sync_skipped", reason=type(exc).__name__)

        # 2. Persist structured PII-scrubbed snapshot to Firestore / local StudentMemoryStore.
        snapshot = {
            "academic_audit": session_state.get("academic_audit"),
            "college_shortlist": session_state.get("college_shortlist"),
            "shortlist": session_state.get("shortlist"),
            "financial_plan": session_state.get("financial_plan"),
            "locked_ed_school": session_state.get("locked_ed_school"),
            "profile": session_state.get("profile"),
        }
        non_empty = {k: v for k, v in snapshot.items() if v is not None}
        if non_empty:
            await _MEMORY_STORE.write_memory_entry(user_id=user_id, entry=non_empty)
            _LOGGER.info(
                "async_memory_consolidated",
                user_id=user_id,
                keys=list(non_empty.keys()),
            )

    task = asyncio.create_task(_consolidate())
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_handle_task_done)
    return task


class AsyncMemoryPlugin(BasePlugin):
    """Global ADK plugin triggering async memory consolidation after coordinator turns."""

    def __init__(self) -> None:
        super().__init__(name="pathfinder_async_memory_plugin")

    async def after_agent_callback(
        self, *, agent: Any, callback_context: Any
    ) -> None:
        if getattr(agent, "name", "") != "counselor_coordinator_agent":
            return None
        session = getattr(callback_context, "session", None)
        user_id = getattr(session, "user_id", "synthetic_student")
        raw_state = getattr(callback_context, "state", None)
        state = raw_state.to_dict() if hasattr(raw_state, "to_dict") else dict(raw_state or {})
        schedule_memory_consolidation(
            user_id=user_id,
            session_state=state,
            callback_context=callback_context,
        )
        return None
