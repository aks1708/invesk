"""Load and validate the immutable artifacts used by an FR7 session."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.reporting.report_rendering import NEWS_SCHEMA_VERSION, PROFILE_SCHEMA_VERSION
from src.qa.errors import QAError


@dataclass(frozen=True)
class QANewsItem:
    title: str
    url: str
    source: str | None
    published: str | None
    summary: str | None
    content: str | None


@dataclass(frozen=True)
class QARun:
    run_dir: Path
    report: str
    profile: dict[str, Any]
    news: tuple[QANewsItem, ...]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise QAError(f"could not read {path.name}: {exc}", error_code="qa_artifact_invalid") from exc


def _read_json(path: Path, schema_version: int) -> dict[str, Any]:
    try:
        document = json.loads(_read_text(path))
    except json.JSONDecodeError as exc:
        raise QAError(
            f"{path.name} is not valid JSON: {exc}",
            error_code="qa_artifact_invalid",
        ) from exc
    if (
        not isinstance(document, dict)
        or isinstance(document.get("schema_version"), bool)
        or document.get("schema_version") != schema_version
    ):
        raise QAError(
            f"{path.name} has an unsupported schema_version",
            error_code="qa_artifact_invalid",
        )
    return document


def _required_string(value: object, name: str, filename: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise QAError(
            f"{filename} has an invalid {name}",
            error_code="qa_artifact_invalid",
        )
    return value


def _optional_string(value: object, name: str, filename: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise QAError(
            f"{filename} has an invalid {name}",
            error_code="qa_artifact_invalid",
        )
    return value


def load_run(run_dir: Path) -> QARun:
    """Load the required artifacts and preserve `news.json` source ordering."""
    if not run_dir.exists() or not run_dir.is_dir():
        raise QAError(f"run directory does not exist: {run_dir}", error_code="qa_run_not_found")
    required = ("report.md", "fund_profile.json", "news.json")
    for filename in required:
        if not (run_dir / filename).is_file():
            raise QAError(
                f"required artifact is missing: {filename}",
                error_code="qa_artifact_missing",
            )

    report = _read_text(run_dir / "report.md")
    if not report.strip():
        raise QAError("report.md is empty", error_code="qa_artifact_invalid")
    profile = _read_json(run_dir / "fund_profile.json", PROFILE_SCHEMA_VERSION)
    for key in ("fund", "ticker", "name", "provider"):
        _required_string(profile.get(key), key, "fund_profile.json")
    holdings = profile.get("holdings")
    sectors = profile.get("sector_weights")
    if (
        not isinstance(holdings, list)
        or any(
            not isinstance(item, dict)
            or not isinstance(item.get("name"), str)
            or not isinstance(item.get("symbol"), str)
            or not isinstance(item.get("weight"), str)
            for item in holdings
        )
        or not isinstance(sectors, dict)
        or any(
            not isinstance(name, str) or not isinstance(weight, str)
            for name, weight in sectors.items()
        )
    ):
        raise QAError(
            "fund_profile.json has invalid holdings or sector_weights",
            error_code="qa_artifact_invalid",
        )
    if (
        not isinstance(profile.get("overview"), dict)
        or any(not isinstance(value, str) for value in profile["overview"].values())
        or not isinstance(profile.get("gaps"), list)
        or any(not isinstance(gap, str) for gap in profile["gaps"])
    ):
        raise QAError(
            "fund_profile.json has invalid provider, overview, or gaps fields",
            error_code="qa_artifact_invalid",
        )
    for key in ("family", "currency"):
        if key not in profile:
            raise QAError(
                f"fund_profile.json is missing {key}",
                error_code="qa_artifact_invalid",
            )
        if profile.get(key) is not None and not isinstance(profile.get(key), str):
            raise QAError(
                f"fund_profile.json has an invalid {key}",
                error_code="qa_artifact_invalid",
            )
    news_doc = _read_json(run_dir / "news.json", NEWS_SCHEMA_VERSION)
    raw_news = news_doc.get("news")
    if not isinstance(raw_news, list):
        raise QAError("news.json has no news array", error_code="qa_artifact_invalid")
    news: list[QANewsItem] = []
    for index, item in enumerate(raw_news, start=1):
        if not isinstance(item, dict):
            raise QAError(
                f"news.json item {index} is invalid",
                error_code="qa_artifact_invalid",
            )
        if (
            isinstance(item.get("relevance"), bool)
            or not isinstance(item.get("relevance"), int)
            or not isinstance(item.get("related"), list)
            or any(not isinstance(entity, str) for entity in item["related"])
        ):
            raise QAError(
                f"news.json item {index} has invalid relevance or related fields",
                error_code="qa_artifact_invalid",
            )
        content = _optional_string(item.get("content"), "content", "news.json")
        news.append(
            QANewsItem(
                title=_required_string(item.get("title"), "title", "news.json"),
                url=_required_string(item.get("url"), "url", "news.json"),
                source=_optional_string(item.get("source"), "source", "news.json"),
                published=_optional_string(item.get("published"), "published", "news.json"),
                summary=_optional_string(item.get("summary"), "summary", "news.json"),
                content=content or None,
            )
        )
    return QARun(run_dir, report, profile, tuple(news))
