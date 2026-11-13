"""Shared fixtures and doubles for focused transformation tests."""

from src.extraction.extraction import (
    build_profile,
    find_fund_quote,
    holdings_from_frame,
    normalize_percent,
    operations_from_frame,
    overview_metrics,
    sector_label,
)

QUOTE = {
    "symbol": "VMID.L",
    "longname": "Vanguard FTSE 250 UCITS ETF",
    "quoteType": "ETF",
}
INFO = {
    "longName": "Vanguard FTSE 250 UCITS ETF",
    "fundFamily": "Vanguard Group (Ireland) Limited",
    "totalAssets": 2148292608,
    "yield": 0.0342,
    "navPrice": 37.913,
    "currency": "GBP",
    "threeYearAverageReturn": 0.1537812,
    "ytdReturn": 11.83837,
}
SECTORS = {"industrials": 0.2055, "consumer_cyclical": 0.1577}
HOLDINGS = [
    {"symbol": "BBY.L", "name": "Balfour Beatty PLC", "percent": 0.0138},
    {"symbol": "PSN.L", "name": "Persimmon PLC", "percent": "1.31%"},
]
