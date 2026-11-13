"""Number presentation shared by the FR2 consumers (FR4 prompt, FR5 report).

Percent-denominated data arrives from FR2 as percent values — 10 means 10% —
and this module renders it the way the prompt, the report, and
`fund_profile.json` must read: `10%`, never `0.1`. Large amounts use
magnitude words: `2148292608` reads as `2.15 billion`, `1000000` as
`1 million`. Rounding is two decimals with trailing zeros stripped, so whole
values stay whole (`1 million`, `10%`). Pure functions, no state (P3).
"""

from __future__ import annotations

from typing import Final

#: Threshold → magnitude word, largest first; values below `thousand` stay plain.
_MAGNITUDES: Final[tuple[tuple[float, str], ...]] = (
    (1e12, "trillion"),
    (1e9, "billion"),
    (1e6, "million"),
    (1e3, "thousand"),
)


def _two_decimals(value: float) -> str:
    """Two-decimal text with trailing zeros stripped (`2.15`, `1`, `-1.23`)."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def format_percent(value: float) -> str:
    """Percent value → `10%`, `8.39%` (two decimals, trailing zeros stripped)."""
    return f"{_two_decimals(value)}%"


def format_amount(value: float) -> str:
    """Count or money value → human scale: `2148292608` → `2.15 billion`,
    `1000000` → `1 million`; below a thousand stays plain (`37.91`)."""
    magnitude = abs(value)
    for threshold, word in _MAGNITUDES:
        if magnitude >= threshold:
            return f"{_two_decimals(value / threshold)} {word}"
    return _two_decimals(value)
