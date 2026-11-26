"""Root CounselorCoordinatorAgent and ADK App wiring all plugins, compaction, and HITL."""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps.app import App, EventsCompactionConfig, ResumabilityConfig
from google.adk.apps.llm_event_summarizer import LlmEventSummarizer
from google.adk.models.google_llm import Gemini
from google.adk.tools.preload_memory_tool import PreloadMemoryTool

from app.plugins.guardrails import GuardrailPolicyPlugin
from app.plugins.memory import AsyncMemoryPlugin
from app.plugins.observability import ObservabilityPlugin
from app.plugins.pii_plugin import PiiRedactionPlugin
from app.prompts.constitution import STATIC_REFERENCE_GUIDE, SYSTEM_CONSTITUTION
from app.sub_agents.action_agent import build_action_execution_agent
from app.sub_agents.pipeline import build_application_prep_pipeline


def build_root_agent() -> LlmAgent:
    """Builds the root CounselorCoordinatorAgent (gemini-2.5-flash) with PreloadMemoryTool."""
    return LlmAgent(
        name="counselor_coordinator_agent",
        model="gemini-2.5-flash",
        description="Root PathFinder AI coordinator routing college planning queries to specialist sub-agents and HITL action tools.",
        static_instruction=STATIC_REFERENCE_GUIDE,
        instruction=(
            f"{SYSTEM_CONSTITUTION}\n\n"
            "ROUTING RULES:\n"
            "- For full planning (courses, college list, financial aid, non-citizen rules, or 2027-2028 deadlines), "
            "delegate to `application_prep_pipeline`.\n"
            "- For state-mutating actions (locking Early Decision, saving/removing shortlist schools, "
            "updating budget/citizenship profile, exporting .ics reminders, or deleting student data), "
            "delegate to `action_execution_agent`.\n"
            "- For essay brainstorming, provide questions and structure feedback directly without ghostwriting."
        ),
        tools=[PreloadMemoryTool()],
        sub_agents=[
            build_application_prep_pipeline(),
            build_action_execution_agent(),
        ],
    )


root_agent = build_root_agent()

# App.name matches the package directory ("app") so adk web / FastAPI / Runner share one namespace.
app = App(
    name="app",
    root_agent=root_agent,
    resumability_config=ResumabilityConfig(is_resumable=True),
    events_compaction_config=EventsCompactionConfig(
        compaction_interval=5,
        overlap_size=1,
        summarizer=LlmEventSummarizer(llm=Gemini(model="gemini-2.5-flash")),
    ),
    context_cache_config=ContextCacheConfig(
        min_tokens=1024,
        ttl_seconds=1800,
    ),
    plugins=[
        PiiRedactionPlugin(),
        GuardrailPolicyPlugin(),
        ObservabilityPlugin(),
        AsyncMemoryPlugin(),
    ],
)
