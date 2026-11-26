"""Secure secret loader backed by Google Cloud Secret Manager.

Enforces zero hardcoded credentials in source code. Falls back to environment
variables only for local development when Secret Manager is not configured,
logging a structured warning without ever logging secret values.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

_LOGGER = logging.getLogger("pathfinder.secrets")


@lru_cache(maxsize=32)
def get_secret(
    secret_id: str,
    project_id: str | None = None,
    version: str = "latest",
    env_fallback: str | None = None,
) -> str:
    """Retrieves a secret payload from Google Cloud Secret Manager.

    Args:
        secret_id: Name of the secret in Secret Manager.
        project_id: Optional GCP project ID (defaults to GOOGLE_CLOUD_PROJECT).
        version: Secret version (defaults to "latest").
        env_fallback: Optional environment variable name for local development.

    Returns:
        The secret string value.

    Raises:
        RuntimeError: If the secret cannot be retrieved from Secret Manager or env fallback.
    """
    resolved_project = project_id or os.getenv("GOOGLE_CLOUD_PROJECT", "")
    if resolved_project and resolved_project != "your-gcp-project-id":
        try:
            from google.cloud import secretmanager

            client = secretmanager.SecretManagerServiceClient()
            name = f"projects/{resolved_project}/secrets/{secret_id}/versions/{version}"
            response = client.access_secret_version(request={"name": name})
            return response.payload.data.decode("utf-8").strip()
        except Exception as exc:
            _LOGGER.warning(
                "Secret Manager lookup failed for secret_id=%s (%s); attempting env fallback.",
                secret_id,
                type(exc).__name__,
            )
            if not env_fallback:
                raise

    if env_fallback:
        value = os.getenv(env_fallback, "").strip()
        if value:
            return value

    raise RuntimeError(
        f"Secret '{secret_id}' is unavailable. Configure Google Cloud Secret Manager "
        f"or set local env var '{env_fallback}' (never hardcode secrets in code)."
    )
