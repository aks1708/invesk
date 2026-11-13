"""CLI input and environment configuration transformations."""

import os
import re
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

from src.core.models import RunInput
from src.search.search import SearchConfig

EXIT_OK = 0
EXIT_RUNTIME_FAILURE = 1
EXIT_USAGE = 2
DEFAULT_ENV_FILE = Path(".env")
_NON_SLUG_RE = re.compile(r"[^a-z0-9]+")


class UsageError(Exception):
    """Invalid CLI input; exits 2 before any external call (PRD FR1)."""


def validate(fund: str | None) -> RunInput:
    """Validate raw CLI input per FR1: fund name must be non-empty."""
    if fund is None or not fund.strip():
        raise UsageError("fund name must be a non-empty string")
    return RunInput(fund=fund.strip())


def slugify(fund: str) -> str:
    """Filesystem-safe artifact slug from a fund name (PRD §10).

    Keeps only [a-z0-9-], so the result can never traverse paths.
    """
    slug = _NON_SLUG_RE.sub("-", fund.strip().lower()).strip("-")
    return slug or "fund"


def default_run_id() -> str:
    """Unique run id: UTC timestamp plus a random suffix (PRD §10)."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def read_env_file(path: Path) -> dict[str, str]:
    """Parse a `.env` file: `KEY=VALUE` lines, `#` comments, optional quotes.

    Values may contain `=` (API keys are often base64). Malformed lines are
    skipped; the file is only read here, at the composition root (P3).
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def compose_env(env: Mapping[str, str] | None) -> dict[str, str]:
    """Build the run environment: injected mapping wins; else environ + .env.

    Explicit mappings (tests, embedders) are authoritative and never touch
    the `.env` file. The default path reads the process environment and lets
    `.env` fill only unset variables (P3: one composition-root read).
    """
    if env is not None:
        return dict(env)
    merged = dict(os.environ)
    merged.update(
        {
            key: value
            for key, value in read_env_file(DEFAULT_ENV_FILE).items()
            if key not in merged
        }
    )
    return merged


def _int_env(env: Mapping[str, str], name: str, default: int) -> int:
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise UsageError(f"{name} must be an integer, got {raw!r}") from None
    if value < 1:
        raise UsageError(f"{name} must be at least 1, got {value}")
    return value


def _bool_env(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    lowered = raw.lower()
    if lowered in ("1", "true", "yes", "on"):
        return True
    if lowered in ("0", "false", "no", "off"):
        return False
    raise UsageError(f"{name} must be a boolean (true/false), got {raw!r}")


def parse_search_config(env: Mapping[str, str]) -> SearchConfig:
    """EXA_* environment overrides → SearchConfig (contracts/exa.v1.md).

    Invalid values are usage errors detected before any external call.
    """
    return SearchConfig(
        max_searches=_int_env(env, "EXA_MAX_SEARCHES", 10),
        results_per_search=_int_env(env, "EXA_RESULTS_PER_SEARCH", 5),
        window_days=_int_env(env, "EXA_WINDOW_DAYS", 90),
        max_parallel=_int_env(env, "EXA_MAX_PARALLEL", 4),
        degrade_on_total_failure=_bool_env(env, "EXA_DEGRADE_ON_FAILURE", True),
    )


