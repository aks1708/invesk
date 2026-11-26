"""Environment configuration boundary tests."""

import pytest

from src.core.config import (
    UsageError,
    parse_search_config,
)


def test_search_config_defaults_match_fr3_limits():
    config = parse_search_config({})

    assert config.max_searches == 10
    assert config.results_per_search == 5
    assert config.window_days == 90


@pytest.mark.parametrize(
    ("name", "value", "maximum"),
    [
        ("EXA_MAX_SEARCHES", "11", 10),
        ("EXA_RESULTS_PER_SEARCH", "6", 5),
    ],
)
def test_search_config_rejects_values_above_fr3_caps(name, value, maximum):
    with pytest.raises(UsageError, match=f"at most {maximum}"):
        parse_search_config({name: value})
