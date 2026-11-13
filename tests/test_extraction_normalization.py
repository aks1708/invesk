"""Focused tests split from test_extraction.py."""

import pandas as pd
import pytest

from _extraction_support import (
    find_fund_quote,
    holdings_from_frame,
    normalize_percent,
    operations_from_frame,
    overview_metrics,
    sector_label,
)

# --- normalize_percent (boundary normalization) --------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0.013818, 1.3818),  # Yahoo's usual fraction → percent value
        ("1.38%", 1.38),  # explicit percent string passes through
        (1.38, 1.38),  # bare number above 1 is already a percent
        (1.0, 100.0),  # a bare 1 is a full fraction (100%)
        (0, 0.0),
        (" 0.5 ", 50.0),
    ],
)
def test_normalize_percent_accepts_fractions_and_percents(raw, expected):
    assert normalize_percent(raw) == pytest.approx(expected)


@pytest.mark.parametrize(
    "raw",
    [None, True, "abc", -0.5, 150.0, "150%", "", []],
)
def test_normalize_percent_rejects_unusable_values(raw):
    assert normalize_percent(raw) is None


# --- sector_label -------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("consumer_cyclical", "Consumer Cyclical"),
        ("healthcare", "Healthcare"),
        ("realestate", "Real Estate"),
    ],
)
def test_sector_label_humanizes_yahoo_keys(key, expected):
    assert sector_label(key) == expected


# --- find_fund_quote ----------------------------------------------------------


def test_find_fund_quote_skips_non_fund_quotes():
    quotes = [
        {"symbol": "AAPL", "quoteType": "EQUITY"},
        {
            "symbol": "0P00009DF8.TO",
            "longname": "Fidelity Special Situations",
            "quoteType": "MUTUALFUND",
        },
    ]
    assert find_fund_quote(quotes)["symbol"] == "0P00009DF8.TO"


@pytest.mark.parametrize(
    "quotes",
    [
        [],
        [{"symbol": "AAPL", "quoteType": "EQUITY"}],
        [{"quoteType": "ETF"}],  # no symbol
    ],
)
def test_find_fund_quote_returns_none_without_a_fund(quotes):
    assert find_fund_quote(quotes) is None


# --- holdings_from_frame (yfinance DataFrame → plain dicts) -------------------


def test_holdings_from_frame_converts_the_dataframe():
    frame = pd.DataFrame(
        {
            "Name": ["Balfour Beatty PLC", "Persimmon PLC"],
            "Holding Percent": [0.0138, 0.0131],
        },
        index=pd.Index(["BBY.L", "PSN.L"], name="Symbol"),
    )
    assert holdings_from_frame(frame) == [
        {"symbol": "BBY.L", "name": "Balfour Beatty PLC", "percent": 0.0138},
        {"symbol": "PSN.L", "name": "Persimmon PLC", "percent": 0.0131},
    ]


def test_holdings_from_frame_falls_back_to_legacy_columns():
    frame = pd.DataFrame(
        {"Name": ["Old Layout PLC"], "Percent": ["1.38%"]},
        index=pd.Index(["OLD.L"], name="Symbol"),
    )
    assert holdings_from_frame(frame) == [
        {"symbol": "OLD.L", "name": "Old Layout PLC", "percent": "1.38%"},
    ]


@pytest.mark.parametrize("frame", [None, pd.DataFrame()])
def test_holdings_from_frame_empty(frame):
    assert holdings_from_frame(frame) == []


# --- operations_from_frame (yfinance fund-operations DataFrame → plain dicts) --


def test_operations_from_frame_extracts_the_funds_own_column():
    frame = pd.DataFrame(
        {"VMID.L": [0.0003, 0.02, pd.NA], "Category Average": [0.0004, pd.NA, pd.NA]},
        index=pd.Index(
            ["Annual Report Expense Ratio", "Annual Holdings Turnover", "Total Net Assets"],
            name="Attributes",
        ),
    )
    assert operations_from_frame(frame, "VMID.L") == {
        "Annual Report Expense Ratio": 0.0003,
        "Annual Holdings Turnover": 0.02,
        "Total Net Assets": pd.NA,
    }


@pytest.mark.parametrize("frame", [None, pd.DataFrame()])
def test_operations_from_frame_empty(frame):
    assert operations_from_frame(frame, "VMID.L") == {}


# --- overview_metrics (Yahoo's mixed ratio units → percent values) ------------


def test_overview_metrics_converts_fractions_and_passes_percents_through():
    metrics = overview_metrics(
        {
            "yield": 0.0342,  # fraction → percent value
            "threeYearAverageReturn": 0.1537812,
            "expenseRatio": 0.0019,
            "ytdReturn": 11.83837,  # already a percent
            "totalAssets": 2148292608,  # amount: untouched
            "currency": "GBP",  # non-numeric: untouched
        }
    )
    assert metrics == {
        "yield": 3.42,
        "threeYearAverageReturn": 15.37812,
        "expenseRatio": 0.19,
        "ytdReturn": 11.83837,
        "totalAssets": 2148292608,
        "currency": "GBP",
    }


def test_overview_metrics_ignores_unusable_ratio_values():
    # None values never enter the overview; unusable strings pass through
    assert overview_metrics({"yield": "n/a", "ytdReturn": None}) == {"yield": "n/a"}


def test_overview_metrics_passes_new_performance_fields_through_in_their_units():
    # Verified live 2026-11-13 (VOO/VFIAX): these three arrive already in
    # percent; beta and the Morningstar ratings are unitless; dividendRate
    # is a currency amount. None of them may be multiplied by 100.
    metrics = overview_metrics(
        {
            "ytdReturn": 11.73498,
            "trailingThreeMonthReturns": 1.47023,
            "dividendYield": 1.07,
            "dividendRate": 5.6485,
            "beta3Year": 0.97,
            "morningStarOverallRating": 4,
            "morningStarRiskRating": 5,
        }
    )
    assert metrics == {
        "ytdReturn": 11.73498,
        "trailingThreeMonthReturns": 1.47023,
        "dividendYield": 1.07,
        "dividendRate": 5.6485,
        "beta3Year": 0.97,
        "morningStarOverallRating": 4,
        "morningStarRiskRating": 5,
    }


def test_overview_metrics_converts_the_inception_epoch_to_an_iso_date():
    metrics = overview_metrics({"fundInceptionDate": 1283817600})
    assert metrics == {"inception": "2010-09-07"}


def test_overview_metrics_falls_back_to_fund_operations_for_cost():
    # Yahoo omits expenseRatio from info for most funds; the funds-operations
    # frame (Annual Report Expense Ratio) reliably carries it, as a fraction.
    metrics = overview_metrics(
        {"yield": 0.0107},
        fund_operations={
            "Annual Report Expense Ratio": 0.0003,
            "Annual Holdings Turnover": 0.02,
            "Total Net Assets": 542960.3,  # unverifiable units: never read
        },
    )
    assert metrics == {"yield": 1.07, "expenseRatio": 0.03, "annualHoldingsTurnover": 2.0}


def test_overview_metrics_never_overrides_info_with_fund_operations():
    metrics = overview_metrics(
        {"expenseRatio": 0.0019},
        fund_operations={"Annual Report Expense Ratio": 0.011},
    )
    assert metrics == {"expenseRatio": 0.19}


def test_overview_metrics_drops_unusable_fund_operations_values():
    # pd.NA / NaN / text all become no entry, never a default
    metrics = overview_metrics(
        {}, fund_operations={"Annual Report Expense Ratio": "not-a-number"}
    )
    assert metrics == {}
    nan_operations = {"Annual Report Expense Ratio": float("nan")}
    assert overview_metrics({}, fund_operations=nan_operations) == {}


def test_overview_metrics_adds_category_from_fund_overview():
    metrics = overview_metrics(
        {}, fund_overview={"categoryName": "Large Blend", "family": "Vanguard"}
    )
    assert metrics == {"category": "Large Blend"}
