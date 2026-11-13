"""Focused tests split from test_extraction.py."""

import pytest

from _extraction_support import (
    HOLDINGS,
    INFO,
    QUOTE,
    SECTORS,
    build_profile,
)

# --- build_profile (the FundProfile adapter) ----------------------------------

def test_build_profile_normalizes_complete_data():
    profile = build_profile("Vanguard FTSE 250", QUOTE, INFO, HOLDINGS, SECTORS)

    assert profile.fund == "Vanguard FTSE 250"
    assert profile.ticker == "VMID.L"
    assert profile.name == "Vanguard FTSE 250 UCITS ETF"
    assert profile.provider == "yahoo"
    assert profile.family == "Vanguard Group (Ireland) Limited"
    assert profile.currency == "GBP"
    assert [(h.name, h.symbol) for h in profile.holdings] == [
        ("Balfour Beatty PLC", "BBY.L"),
        ("Persimmon PLC", "PSN.L"),
    ]
    assert [h.weight for h in profile.holdings] == pytest.approx([1.38, 1.31])
    assert profile.sector_weights == {
        "Industrials": pytest.approx(20.55),
        "Consumer Cyclical": pytest.approx(15.77),
    }
    assert profile.overview == {
        "totalAssets": 2148292608,
        "yield": 3.42,  # Yahoo's fraction → percent value
        "navPrice": 37.913,
        "currency": "GBP",
        "threeYearAverageReturn": 15.37812,
        "ytdReturn": 11.83837,  # arrives in percent, passes through
    }
    # complete data: no gaps at all
    assert profile.gaps == ()


def test_build_profile_partial_data_becomes_gaps_not_defaults():
    profile = build_profile("Some Fund", {"symbol": "X.Y", "longname": None}, {}, [], {})

    assert profile.holdings == ()
    assert profile.sector_weights == {}
    assert profile.overview == {}
    assert profile.name == "Some Fund"  # falls back to the requested name
    assert profile.gaps == (
        "top holdings not available",
        "sector weights not available",
        "overview metrics not available",
    )


def test_build_profile_flags_unusable_individual_weights():
    holdings = [{"symbol": "BAD.L", "name": "Broken", "percent": "n/a"}]
    profile = build_profile("F", QUOTE, INFO, holdings, SECTORS)

    assert profile.holdings == ()
    assert "holding weight unusable for Broken" in profile.gaps


def test_build_profile_family_falls_back_to_fund_overview():
    # info.fundFamily is absent for most funds; funds_data.fund_overview
    # (the fundProfile module) reliably carries the family name
    profile = build_profile(
        "Vanguard FTSE 250",
        QUOTE,
        {k: v for k, v in INFO.items() if k != "fundFamily"},
        HOLDINGS,
        SECTORS,
        fund_overview={
            "family": "Vanguard",
            "categoryName": "Large Blend",
            "legalType": None,
        },
    )
    assert profile.family == "Vanguard"
    assert profile.overview["category"] == "Large Blend"
