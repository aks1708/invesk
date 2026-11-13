"""Core FR1 input validation tests."""

import pytest

from src.cli.config import UsageError, validate


def test_validate_strips_a_valid_fund_name():
    assert validate("  Vanguard FTSE 250  ").fund == "Vanguard FTSE 250"


@pytest.mark.parametrize("fund", [None, "", " \t\n"])
def test_validate_rejects_an_empty_fund_name(fund):
    with pytest.raises(UsageError):
        validate(fund)
