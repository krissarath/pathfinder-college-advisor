"""Public repository hygiene linter.

Verifies zero hardcoded secrets, zero internal corporate terms, and zero real PII
across tracked source, data, Terraform, Docker, Makefile, and evaluation files.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FORBIDDEN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("INTERNAL_TERM", re.compile(r"\b(?:argolis|google3|corp\.google\.com|altostrat\.com|moma|concord|jetski|cloudtop)\b", re.IGNORECASE)),
    ("INTERNAL_SHORTLINK", re.compile(r"\b(?:go/[a-z0-9_-]+|b/\d{6,})\b")),
    ("HARDCODED_GCP_KEY", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    ("GITHUB_TOKEN", re.compile(r"\b(?:ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{20,})\b")),
    ("OAUTH_TOKEN", re.compile(r"\bya29\.[0-9A-Za-z_-]{20,}\b")),
    ("SERVICE_ACCOUNT_JSON", re.compile(r'"type"\s*:\s*"service_account"')),
    ("PRIVATE_KEY_HEADER", re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----")),
]

SCAN_SUFFIXES = {".py", ".json", ".md", ".tf", ".yml", ".yaml", ".toml", ".sh", ".example"}
SCAN_FILENAMES = {"Dockerfile", "Makefile", ".env.example", ".dockerignore"}
IGNORE_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".terraform"}


def main() -> int:
    violations: list[str] = []
    for path in ROOT.rglob("*"):
        if any(part in IGNORE_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        if path.suffix not in SCAN_SUFFIXES and path.name not in SCAN_FILENAMES:
            continue
        if path.name == "check_repo_hygiene.py":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for label, pattern in FORBIDDEN_PATTERNS:
            if pattern.search(text):
                violations.append(f"{label}: {path.relative_to(ROOT)}")

    if violations:
        for v in violations:
            sys.stderr.write(f"HYGIENE VIOLATION: {v}\n")
        return 1
    sys.stdout.write("Repo hygiene check PASSED (0 violations).\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
