"""Central model routing configuration for PathFinder AI.

Supports strategic model routing (Flash for fast routing/checklists/actions,
Pro for deep multi-constraint matching and financial/non-citizen reasoning)
with environment-variable overrides for zero-rebuild deployment tuning.
"""

from __future__ import annotations

import os

FLASH_MODEL: str = os.getenv("PATHFINDER_FLASH_MODEL", "gemini-3.8-flash")
PRO_MODEL: str = os.getenv("PATHFINDER_PRO_MODEL", "gemini-3.1-pro")
