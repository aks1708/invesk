"""FR5 public report API: rendering and versioned artifact writing."""

from src.reporting.report_artifacts import (
    Clock,
    NEWS_SCHEMA_VERSION,
    PROFILE_SCHEMA_VERSION,
    fund_profile_document,
    news_document,
    write_report,
)
from src.reporting.report_rendering import (
    _financial_health_text,
    _metric_label,
    _overview_display,
    render_report,
)
