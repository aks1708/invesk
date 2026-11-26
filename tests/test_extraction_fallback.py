import io
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from src.core.events import EventEmitter
from src.extraction.extraction import ExtractionError, extract_fund


FUND_NAME = "JPMorgan Fundamental Data Science Large Growth ETF"
QUOTES = [
    {
        "symbol": "LGDS",
        "quoteType": "EQUITY",
        "longname": (
            "J P MORGAN Exchange-Traded Fund Trust - "
            "Fundamental Data Science Large Growth ETF"
        ),
    },
    {
        "symbol": "JGISX",
        "quoteType": "MUTUALFUND",
        "longname": (
            "J.P. Morgan Exchange-Traded Fund Trust - "
            "JPMorgan Fundamental Data Science Large Growth ETF"
        ),
    },
]


class _Ticker:
    def __init__(self, symbol):
        self.symbol = symbol
        if symbol == "JGISX":
            self.info = {"quoteType": "MUTUALFUND", "longName": FUND_NAME}
        else:
            self.info = {
                "quoteType": "ETF",
                "longName": FUND_NAME,
                "totalAssets": 1_000_000,
            }

    @property
    def funds_data(self):
        if self.symbol == "JGISX":
            raise RuntimeError("JGISX: No Fund data found.")
        return SimpleNamespace(
            top_holdings=None,
            sector_weightings={"technology": 0.5},
            fund_operations=None,
            fund_overview={"family": "JPMorgan"},
        )


class _Yahoo:
    @staticmethod
    def Search(_query, max_results):
        assert max_results == 5
        return SimpleNamespace(quotes=QUOTES)

    Ticker = _Ticker


def _events():
    sink = io.StringIO()
    return EventEmitter(
        "test-run",
        lambda: datetime(2026, 11, 26, tzinfo=UTC),
        sink,
    )


def test_extract_fund_uses_verified_etf_when_legacy_share_class_has_no_fund_data():
    profile = extract_fund(FUND_NAME, yf=_Yahoo(), events=_events())

    assert profile.ticker == "LGDS"
    assert profile.name == FUND_NAME
    assert profile.sector_weights == {"Technology": 50.0}
    assert profile.family == "JPMorgan"


def test_extract_fund_does_not_hide_other_fund_data_errors():
    class BrokenTicker(_Ticker):
        @property
        def funds_data(self):
            raise RuntimeError("temporary quoteSummary failure")

    class BrokenYahoo(_Yahoo):
        Ticker = BrokenTicker

    with pytest.raises(ExtractionError, match="temporary quoteSummary failure"):
        extract_fund(FUND_NAME, yf=BrokenYahoo(), events=_events())
