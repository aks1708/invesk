"""Focused tests split from test_synthesis.py."""

from dataclasses import replace

from _synthesis_support import (
    Holding,
    MAX_ITEMS_PER_ENTITY,
    build_prompt,
    make_profile,
    news,
    news_for_prompt,
)

# --- build_prompt (the FR4 prompt) ---------------------------------------------


def test_build_prompt_carries_task_simple_language_fund_data_and_news():
    profile = replace(
        make_profile(
            holdings=(
                Holding(name="Persimmon PLC", symbol="PSN.L", weight=3.11),
                Holding(name="Balfour Beatty PLC", symbol="BBY.L", weight=1.38),
            ),
            sectors={"Industrials": 20.55, "Healthcare": 15.77},
        ),
        overview={"totalAssets": 2148292608, "expenseRatio": 0.1},
        gaps=("sector weights not available",),
    )
    prompt = build_prompt(
        profile,
        (
            news(),
            news(
                title="Construction demand rises",
                url="https://www.bb.com/sector",
                related=("Industrials",),
            ),
        ),
    )

    assert (
        "- Fund: Vanguard FTSE 250 UCITS ETF (ticker VMID.L), "
        "family Vanguard, currency GBX"
    ) in prompt
    assert "- Sector weights: Industrials 20.55%, Healthcare 15.77%" in prompt
    assert "- Top holdings: Persimmon PLC 3.11%, Balfour Beatty PLC 1.38%" in prompt
    assert "Overview metrics" not in prompt
    assert "Data gaps" not in prompt
    assert "write only the company_insights and sector_insights sections" in prompt
    assert "Do not write a fund snapshot, financial-health summary" in prompt
    # The news is split by the entity its search targeted: holdings feed the
    # company block, sector weights feed the sector block.
    assert "Company news:" in prompt
    assert "Sector news:" in prompt
    assert (
        "- [S1] [about: Balfour Beatty PLC] Balfour Beatty wins contract — "
        "www.reuters.com (2026-11-01T00:00:00.000Z): It won a contract. "
        "https://www.reuters.com/article/x"
    ) in prompt
    assert (
        "\n  Content: It won a 200 million pound contract on Tuesday." in prompt
    )
    assert (
        "- [S2] [about: Industrials] Construction demand rises — www.reuters.com "
        "(2026-11-01T00:00:00.000Z): It won a contract. "
        "https://www.bb.com/sector"
    ) in prompt
    assert prompt.index("Company news:") < prompt.index("Sector news:")
    assert "Write in English only." in prompt
    assert "percentages as percents (10%, never 0.1)" in prompt
    assert "Write in simple, everyday language for a general reader." in prompt
    assert '"company_insights": "..."' in prompt
    assert '"sector_insights": "..."' in prompt
    assert "Write several substantive sentences" in prompt
    assert "relevant risk or opportunity" in prompt
    assert "explain it briefly in plain words the first time it appears" in prompt
    assert "in the same sentence" in prompt
    assert "fits this specific company or sector context" in prompt
    assert "Connect the explanation to why the development matters" in prompt
    assert "do not insert a dictionary-style aside" in prompt
    assert "spell out an acronym on first use" in prompt
    assert "not as a separate definition" in prompt
    assert "what it could mean for an investor in this fund" in prompt
    assert "business mechanism such as revenue" in prompt
    assert "fund's holding/weight" in prompt
    assert "fund's sector allocation" in prompt
    assert "sourced development → business/sector effect → why it matters" in prompt
    assert "do not predict share-price moves or give buy/sell advice" in prompt
    assert "Distinguish reported facts from" in prompt


def test_build_prompt_partitions_news_by_holding_or_sector_entity():
    profile = make_profile(
        holdings=(Holding(name="Balfour Beatty PLC", symbol="BBY.L", weight=1.38),),
        sectors={"Industrials": 20.55},
    )
    items = (
        news(),
        news(
            title="Industrials orders rise",
            url="https://www.bb.com/b",
            related=("Industrials",),
        ),
        news(  # an untagged item stays in the company block
            title="Wire report",
            url="https://wire.example/w",
            related=(),
        ),
    )
    prompt = build_prompt(profile, items)

    company_block = prompt.split("Company news:", 1)[1].split("Sector news:", 1)[0]
    sector_block = prompt.split("Sector news:", 1)[1]
    assert "[S1] [about: Balfour Beatty PLC]" in company_block
    assert "Wire report" in company_block
    assert "[S2] [about: Industrials]" in sector_block
    assert "Balfour Beatty wins contract" not in sector_block




def test_build_prompt_reports_unavailable_fund_fields_and_empty_news():
    prompt = build_prompt(make_profile(), ())
    assert "- Sector weights: not available" in prompt
    assert "- Top holdings: not available" in prompt
    assert "Overview metrics" not in prompt
    assert "Data gaps" not in prompt
    assert (
        "- No news items were found in this run's searches" in prompt
    )


# --- news_for_prompt (the FR4 digest budget) ------------------------------------


def test_news_for_prompt_keeps_the_top_items_per_entity_in_run_order():
    items = [
        news(url=f"https://e.example/{i}", relevance=i, related=("Balfour Beatty PLC",))
        for i in range(1, 6)
    ] + [
        news(title="Sector item", url="https://s.example/a", related=("Industrials",))
    ]
    selected = news_for_prompt(items)
    assert [item.url for item in selected] == [
        "https://e.example/1",
        "https://e.example/2",
        "https://e.example/3",
        "https://s.example/a",
    ]


def test_news_for_prompt_caps_untagged_items_too():
    items = [
        news(title=f"Wire {i}", url=f"https://w.example/{i}", related=())
        for i in range(5)
    ]
    assert len(news_for_prompt(items)) == MAX_ITEMS_PER_ENTITY


def test_news_for_prompt_keeps_everything_under_the_cap():
    items = [news(url=f"https://e.example/{i}", related=(f"Company {i}",)) for i in range(5)]
    assert news_for_prompt(items) == list(items)
