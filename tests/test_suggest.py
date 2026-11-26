"""Transformation tests for browser fund-name suggestions."""

from src.fund_suggestions import cached_suggester, yf_suggester


class _FakeSearch:
    def __init__(self, quotes: list[dict]):
        self.quotes = quotes


class _FakeYf:
    """Double for the yfinance module: Search(query).quotes."""

    def __init__(self, quotes: list[dict]):
        self._quotes = quotes
        self.queries: list[str] = []
        self.max_results: list[int] = []

    def Search(self, query: str, max_results: int) -> _FakeSearch:
        self.queries.append(query)
        self.max_results.append(max_results)
        return _FakeSearch(self._quotes)


def _quote(quote_type: str, shortname: str = "", longname: str = "") -> dict:
    return {
        "symbol": "SYM",
        "quoteType": quote_type,
        "shortname": shortname,
        "longname": longname,
    }


class _FakeScreenQuery:
    valid_values = {"fundfamilyname": {"JPMorgan"}}

    def __init__(self, operator: str, operands: list[str]) -> None:
        self.operator = operator
        self.operands = operands
        self.quote_type = "ETF"


class _FakeFundQuery(_FakeScreenQuery):
    def __init__(self, operator: str, operands: list[str]) -> None:
        super().__init__(operator, operands)
        self.quote_type = "MUTUALFUND"


class _FakeFamilyYf:
    ETFQuery = _FakeScreenQuery
    FundQuery = _FakeFundQuery

    def __init__(self) -> None:
        self.screen_calls: list[tuple[str, int]] = []

    def screen(self, query, *, offset: int, size: int) -> dict:
        self.screen_calls.append((query.quote_type, offset))
        total = 252
        quotes = [
            {
                "quoteType": query.quote_type,
                "symbol": f"{query.quote_type}-{index}",
                "longName": (
                    "JPMorgan Fundamental Data Science Large Value ETF"
                    if query.quote_type == "ETF" and index == 0
                    else f"JPMorgan {query.quote_type} Fund {index}"
                ),
            }
            for index in range(offset, min(offset + size, total))
        ]
        return {"total": total, "quotes": quotes}


def test_yf_suggester_returns_all_matching_fund_names_in_relevance_order() -> None:
    yf = _FakeYf(
        [
            _quote("ETF", shortname="JPMorgan Equity Premium Income ETF"),
            _quote("MUTUALFUND", longname="Fidelity International Index Fund"),
            _quote("EQUITY", shortname="JPMorgan Chase & Co"),  # not a fund
            _quote("ETF", longname="JPMorgan US Research Enhanced Index Equity ETF"),
            _quote("ETF", longname="JP Morgan Income Fund"),
        ]
    )
    suggest = yf_suggester(yf)
    assert suggest("jPmOrGaN") == [
        "JPMorgan Equity Premium Income ETF",
        "JPMorgan US Research Enhanced Index Equity ETF",
    ]
    assert yf.max_results == [100]


def test_yf_suggester_pages_all_etfs_and_mutual_funds_for_a_family() -> None:
    yf = _FakeFamilyYf()

    suggestions = yf_suggester(yf)("jPmOrGaN")

    assert len(suggestions) == 504
    assert suggestions[0] == "JPMorgan Fundamental Data Science Large Value ETF"
    assert suggestions[252] == "JPMorgan MUTUALFUND Fund 0"
    assert yf.screen_calls == [
        ("ETF", 0),
        ("ETF", 250),
        ("MUTUALFUND", 0),
        ("MUTUALFUND", 250),
    ]


def test_yf_suggester_matches_query_words_in_any_order() -> None:
    suggest = yf_suggester(_FakeFamilyYf())

    assert suggest("jpmorgan data science") == [
        "JPMorgan Fundamental Data Science Large Value ETF"
    ]
    assert suggest("science JPMorgan data") == [
        "JPMorgan Fundamental Data Science Large Value ETF"
    ]


def test_yf_suggester_expands_matching_index_to_tracking_funds() -> None:
    class _IndexSearchYf:
        def __init__(self) -> None:
            self.queries: list[str] = []

        def Search(self, query: str, max_results: int) -> _FakeSearch:
            self.queries.append(query)
            if query == "FTSE":
                return _FakeSearch(
                    [
                        {
                            "quoteType": "ETF",
                            "symbol": "VWCE.DE",
                            "longName": "Vanguard FTSE All-World UCITS ETF",
                        },
                        {
                            "quoteType": "INDEX",
                            "symbol": "^FTSE",
                            "longName": "FTSE 100",
                        },
                    ]
                )
            return _FakeSearch(
                [
                    {
                        "quoteType": "ETF",
                        "symbol": "ISF.L",
                        "longName": "iShares Core FTSE 100 UCITS ETF GBP",
                    },
                    {
                        "quoteType": "ETF",
                        "symbol": "VUKG.L",
                        "longName": "Vanguard FTSE 100 UCITS ETF GBP Accumulation",
                    },
                    {
                        "quoteType": "INDEX",
                        "symbol": "^FTSE",
                        "longName": "FTSE 100",
                    },
                ]
            )

    yf = _IndexSearchYf()

    assert yf_suggester(yf)("FTSE") == [
        "Vanguard FTSE All-World UCITS ETF",
        "iShares Core FTSE 100 UCITS ETF GBP",
        "Vanguard FTSE 100 UCITS ETF GBP Accumulation",
    ]
    assert yf.queries == ["FTSE", "FTSE 100"]


def test_yf_suggester_deduplicates_and_skips_blank_names() -> None:
    yf = _FakeYf(
        [
            _quote("ETF", shortname="Same Name"),
            _quote("MUTUALFUND", shortname="Same Name"),
            _quote("ETF", shortname="   "),
        ]
    )
    assert yf_suggester(yf)("same") == ["Same Name"]


def test_yf_suggester_uses_matching_shortname_if_longname_does_not_match() -> None:
    yf = _FakeYf(
        [
            {
                "symbol": "JPM",
                "quoteType": "ETF",
                "longname": "US Large Cap Equity ETF",
                "shortname": "JPMorgan US Equity",
            }
        ]
    )
    assert yf_suggester(yf)("jpmorgan") == ["JPMorgan US Equity"]


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
