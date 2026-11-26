"""Cloud Run & local FastAPI entrypoint serving the PathFinder AI ADK Web UI."""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from google.adk.cli.fast_api import get_fast_api_app

from app.plugins.observability import configure_observability

load_dotenv()
configure_observability()

AGENTS_DIR = str(Path(__file__).resolve().parent)
SESSION_DB_URL = os.getenv("SESSION_DB_URL", "sqlite+aiosqlite:///./pathfinder_sessions.db")

fastapi_app = get_fast_api_app(
    agents_dir=AGENTS_DIR,
    session_service_uri=SESSION_DB_URL,
    allow_origins=["*"],
    web=True,
)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(fastapi_app, host="0.0.0.0", port=port)
