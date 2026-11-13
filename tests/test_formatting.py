"""FR2 presentation helpers: percent and magnitude-word formatting.

Percent values read as percents (10 = 10%) and amounts read with magnitude
words (2148292608 → 2.15 billion) — the notation rule every FR4/FR5
presentation surface shares (PRD FR2, contracts/artifacts.v1.md schema 3).
"""

import pytest

from src.core.formatting import format_amount, format_percent


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (10.0, "10%"),  # whole percents stay whole
        (8.392, "8.39%"),  # two decimals, no trailing zeros
        (1.3818, "1.38%"),
        (0.5, "0.5%"),
        (21.46343, "21.46%"),
        (0, "0%"),
    ],
)
def test_format_percent_renders_percent_values(value, expected):
    assert format_percent(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (2148292608, "2.15 billion"),
        (1735726989312, "1.74 trillion"),
        (1000000, "1 million"),
        (1234567, "1.23 million"),
        (1500, "1.5 thousand"),
        (37.913, "37.91"),  # below a thousand: plain, two decimals
        (698.3, "698.3"),
        (0, "0"),
        (-1234567, "-1.23 million"),  # negative amounts keep the sign
    ],
)
def test_format_amount_uses_magnitude_words(value, expected):
    assert format_amount(value) == expected
