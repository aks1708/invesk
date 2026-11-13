"""Focused tests split from test_search.py."""

from _search_support import (
    Holding,
    SearchQuery,
    SimpleNamespace,
    build_queries,
    dedupe_news,
    make_profile,
    news,
    news_from_result,
    raw_result,
)
import pytest

# --- build_queries (fan-out) --------------------------------------------------


def test_build_queries_orders_holdings_by_weight_desc():
    profile = make_profile(
        holdings=(
            Holding(name="Balfour Beatty PLC", symbol="BBY.L", weight=0.0138),
            Holding(name="Persimmon PLC", symbol="PSN.L", weight=0.0311),
        )
    )
    assert build_queries(profile, max_searches=20) == (
        SearchQuery(
            text="Persimmon PLC company news",
            entity="Persimmon PLC",
            kind="holding",
        ),
        SearchQuery(
            text="Balfour Beatty PLC company news",
            entity="Balfour Beatty PLC",
            kind="holding",
        ),
    )


def test_build_queries_fills_sectors_after_holdings_within_the_cap():
    holdings = tuple(
        Holding(name=f"Company {i}", symbol=f"C{i}.L", weight=0.01) for i in range(3)
    )
    profile = make_profile(
        holdings=holdings,
        sectors={"Industrials": 0.2055, "Healthcare": 0.1577, "Energy": 0.05},
    )
    queries = build_queries(profile, max_searches=12)
    assert [q.kind for q in queries] == ["holding"] * 3 + ["sector"] * 3
    assert [q.entity for q in queries[3:]] == ["Industrials", "Healthcare", "Energy"]


def test_build_queries_never_exceeds_the_cap():
    holdings = tuple(
        Holding(name=f"Company {i}", symbol=f"C{i}.L", weight=0.01) for i in range(10)
    )
    profile = make_profile(
        holdings=holdings,
        sectors={f"Sector {i}": 0.01 for i in range(20)},
    )
    # 5 holding + 5 sector queries, even when the budget allows more.
    assert len(build_queries(profile, max_searches=50)) == 10
    assert len(build_queries(profile, max_searches=20)) == 10
    assert len(build_queries(profile, max_searches=3)) == 3
    assert len(build_queries(profile, max_searches=0)) == 0


def test_build_queries_caps_holdings_at_five():
    holdings = tuple(
        Holding(name=f"Company {i}", symbol=f"C{i}.L", weight=0.01) for i in range(10)
    )
    profile = make_profile(holdings=holdings)
    queries = build_queries(profile, max_searches=20)
    assert [q.entity for q in queries] == [f"Company {i}" for i in range(5)]


def test_build_queries_caps_sectors_at_five():
    holdings = tuple(
        Holding(name=f"Company {i}", symbol=f"C{i}.L", weight=0.01) for i in range(5)
    )
    profile = make_profile(
        holdings=holdings,
        sectors={f"Sector {i}": 0.01 for i in range(20)},
    )
    queries = build_queries(profile, max_searches=20)
    sector_queries = [q for q in queries if q.kind == "sector"]
    assert len(sector_queries) == 5
    assert [q.text for q in sector_queries] == [
        f"Sector {i} sector outlook" for i in range(5)
    ]


def test_build_queries_sector_queries_ask_where_the_sector_is_heading():
    profile = make_profile(sectors={"Industrials": 0.2055})
    queries = build_queries(profile, max_searches=20)
    assert queries[0].text == "Industrials sector outlook"


def test_build_queries_skips_unnamed_holdings():
    profile = make_profile(
        holdings=(
            Holding(name="", symbol="BAD.L", weight=0.5),
            Holding(name="  ", symbol="BAD2.L", weight=0.3),
            Holding(name="Persimmon PLC", symbol="PSN.L", weight=0.1),
        )
    )
    assert [q.entity for q in build_queries(profile, max_searches=20)] == ["Persimmon PLC"]


# --- news_from_result (boundary adapter) --------------------------------------


def test_news_from_result_maps_the_full_result():
    assert news_from_result(
        raw_result(url="https://www.ft.com/content/abc"), entity="Balfour Beatty PLC", rank=2
    ) == news(
        url="https://www.ft.com/content/abc", source="www.ft.com", relevance=2
    )


def test_news_from_result_keeps_the_text_as_exa_returns_it():
    # The 10000-character cap is Exa's concern (contents.text.maxCharacters);
    # the boundary adapter never truncates client-side.
    item = news_from_result(
        raw_result(text="A" * 5000 + "tail"), entity="E", rank=1
    )
    assert item.content is not None
    assert len(item.content) == 5004


@pytest.mark.parametrize(
    "result",
    [
        SimpleNamespace(title=None, url="https://example.com/a"),  # no title
        SimpleNamespace(title="t", url=""),  # empty url
        SimpleNamespace(title="t", url=None),  # no url
        SimpleNamespace(title="t", url="ftp://example.com/a"),  # not http(s)
        SimpleNamespace(title="   ", url="https://example.com/a"),  # blank title
    ],
)
def test_news_from_result_drops_unusable_results(result):
    assert news_from_result(result, entity="E", rank=1) is None


@pytest.mark.parametrize(
    ("published", "summary"),
    [
        (None, None),  # explicit Nones (how the SDK represents absence)
        (1234, {"unexpected": True}),  # not strings
    ],
)
def test_news_from_result_keeps_optional_fields_only_when_they_are_strings(
    published, summary
):
    result = SimpleNamespace(
        title="t", url="https://e.example/a", published_date=published, summary=summary
    )

    item = news_from_result(result, entity="E", rank=1)

    assert item.published is None
    assert item.summary is None


# --- dedupe_news (FR3 dedupes by URL) -----------------------------------------


def test_dedupe_keeps_the_first_item_per_url():
    first = news(relevance=1)
    later = news(summary="Different query found it too", relevance=3)
    third = news(url="https://www.ft.com/content/abc", source="www.ft.com")
    assert dedupe_news([first, later, third]) == [first, third]
