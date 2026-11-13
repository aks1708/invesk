"""Transformation tests for fund-name suggestions (FR1 input UX)."""

import io

import pytest

from src.cli.app import _read_input
from src.cli.config import UsageError, validate
from src.cli.suggest import cached_suggester, yf_suggester


class _FakeSearch:
    def __init__(self, quotes: list[dict]):
        self.quotes = quotes


class _FakeYf:
    """Double for the yfinance module: Search(query).quotes."""

    def __init__(self, quotes: list[dict]):
        self._quotes = quotes
        self.queries: list[str] = []

    def Search(self, query: str, max_results: int) -> _FakeSearch:
        self.queries.append(query)
        return _FakeSearch(self._quotes)


def _quote(quote_type: str, shortname: str = "", longname: str = "") -> dict:
    return {
        "symbol": "SYM",
        "quoteType": quote_type,
        "shortname": shortname,
        "longname": longname,
    }


def test_yf_suggester_returns_fund_names_only_in_relevance_order() -> None:
    yf = _FakeYf(
        [
            _quote("ETF", shortname="Vanguard FTSE 250"),
            _quote("MUTUALFUND", longname="Fidelity International Index Fund"),
            _quote("EQUITY", shortname="Vanguard Group Inc"),  # not a fund
            _quote("ETF", longname="Vanguard FTSE 250 UCITS ETF"),
        ]
    )
    suggest = yf_suggester(yf)
    assert suggest("vanguard") == [
        "Vanguard FTSE 250",
        "Fidelity International Index Fund",
        "Vanguard FTSE 250 UCITS ETF",
    ]


def test_yf_suggester_deduplicates_and_skips_blank_names() -> None:
    yf = _FakeYf(
        [
            _quote("ETF", shortname="Same Name"),
            _quote("MUTUALFUND", shortname="Same Name"),
            _quote("ETF", shortname="   "),
        ]
    )
    assert yf_suggester(yf)("same") == ["Same Name"]


def test_yf_suggester_never_suggests_a_ticker_shortname() -> None:
    """Yahoo ships some funds with the ticker in `shortname` (2026-11-13).

    Real payload: symbol `0P00017EQ6.L`, quoteType MUTUALFUND,
    shortname `0P00017EQ6.L`, longname `Jupiter Asian Income L Acc`.
    """
    yf = _FakeYf(
        [
            {
                "symbol": "0P00017EQ6.L",
                "quoteType": "MUTUALFUND",
                "shortname": "0P00017EQ6.L",
                "longname": "Jupiter Asian Income L Acc",
            },
            {
                "symbol": "0P00017EQ9.L",
                "quoteType": "MUTUALFUND",
                "shortname": "0P00017EQ9.L",
                "longname": "",
            },
        ]
    )
    suggest = yf_suggester(yf)
    assert suggest("jupiter") == ["Jupiter Asian Income L Acc"]


def test_yf_suggester_prefers_the_longname_over_the_shortname() -> None:
    yf = _FakeYf(
        [
            {
                "symbol": "VMID.L",
                "quoteType": "ETF",
                "shortname": "VANGUARD FUNDS PLC VANGUARD FTS",
                "longname": "Vanguard FTSE 250 UCITS ETF",
            }
        ]
    )
    assert yf_suggester(yf)("vanguard") == ["Vanguard FTSE 250 UCITS ETF"]


def test_yf_suggester_skips_quotes_whose_only_name_is_the_symbol() -> None:
    yf = _FakeYf(
        [
            {
                "symbol": "GOLD",
                "quoteType": "ETF",
                "shortname": "GOLD",
                "longname": "",
            }
        ]
    )
    assert yf_suggester(yf)("gold") == []


def test_cached_suggester_refetches_same_query_once_and_swallows_errors() -> None:
    calls: list[str] = []

    def flaky(query: str) -> list[str]:
        calls.append(query)
        if len(calls) == 1:
            raise RuntimeError("network down")
        return ["Fund A"]

    cached = cached_suggester(flaky)
    assert cached("fund") == []  # first call fails → best-effort empty
    assert cached("fund") == []  # failure cached, no refetch
    assert calls == ["fund"]

    cached = cached_suggester(lambda query: ["Fund B"])
    assert cached("fund") == ["Fund B"]
    assert cached("fund") == ["Fund B"]  # cache hit, suggester not called again


def test_read_input_plain_prompt_when_not_a_tty() -> None:
    run_input = _read_input(io.StringIO("Vanguard FTSE 250\n"), io.StringIO(), None)
    assert run_input.fund == "Vanguard FTSE 250"


def test_read_input_plain_prompt_eof_is_usage_error() -> None:
    with pytest.raises(UsageError):
        _read_input(io.StringIO(""), io.StringIO(), None)


def test_validate_still_rejects_blank_fund() -> None:
    with pytest.raises(UsageError):
        validate("   ")
