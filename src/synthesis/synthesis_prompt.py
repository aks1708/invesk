"""Build the bounded prompt sent to the synthesis model."""

from collections.abc import Mapping, Sequence
from typing import Any, Final

from src.core.formatting import format_percent
from src.core.models import FundProfile, NewsItem

CORRECTIVE_TEXT_LIMIT: Final[int] = 4000


def _news_line(item: NewsItem, source_number: int) -> str:
    """One NewsItem → a prompt line with a stable source token.

    The summary and the full article text ride along (FR3); the model is told
    to use them for depth, not to quote them wholesale.
    """
    about = f" [about: {item.related[0]}]" if item.related else ""
    line = (
        f"- [S{source_number}]{about} {item.title} — {item.source} "
        f"({item.published or 'date unknown'}): "
        f"{item.summary or 'no summary'} {item.url}"
    )
    if item.content:
        line += f"\n  Content: {item.content}"
    return line


def partition_news(
    profile: FundProfile, news: Sequence[NewsItem]
) -> tuple[list[NewsItem], list[NewsItem]]:
    """NewsItem[] → (company news, sector news) for the FR4 prompt.

    An item whose queried entity is one of the fund's sector weights feeds
    the sector-insights section; everything else (its query targeted a
    holding) feeds company insights. Order is preserved within each block.
    """
    company: list[NewsItem] = []
    sector: list[NewsItem] = []
    for item in news:
        entity = item.related[0] if item.related else None
        if entity is not None and entity in profile.sector_weights:
            sector.append(item)
        else:
            company.append(item)
    return company, sector


#: FR4 prompt budget: at most this many news items per entity are fed to
#: Gemma. A digest covering every searched result makes the reply outgrow
#: the model's output window, which drops the last sections (observed in
#: real runs).
MAX_ITEMS_PER_ENTITY: Final[int] = 3


def news_for_prompt(news: Sequence[NewsItem]) -> list[NewsItem]:
    """NewsItem[] → the digest for the FR4 prompt.

    Keeps the first MAX_ITEMS_PER_ENTITY items per related entity (run
    order, so the highest-relevance results win) — enough for a
    comprehensive section per entity without an unbounded reply. Items
    without a related entity share one capped bucket.
    """
    counts: dict[str | None, int] = {}
    selected: list[NewsItem] = []
    for item in news:
        entity = item.related[0] if item.related else None
        count = counts.get(entity, 0)
        if count >= MAX_ITEMS_PER_ENTITY:
            continue
        counts[entity] = count + 1
        selected.append(item)
    return selected


def build_prompt(
    profile: FundProfile,
    news: Sequence[NewsItem],
    *,
    source_numbers: Mapping[str, int] | None = None,
) -> str:
    """FundProfile + NewsItem[] → the single Gemma user prompt.

    Structure fixed by contracts/ollama.v1.md: task and constraints (English
    only, FR2-normalized number formatting), simple-language guidance,
    fund composition context, the news split into company and sector blocks,
    stable source tokens, and the exact output JSON schema. `source_numbers`
    lets synthesis preserve each item's position in the full searched list
    even when the prompt digest omits some results.
    """
    if source_numbers is None:
        source_numbers = {item.url: index for index, item in enumerate(news, start=1)}
    lines = [
        "You write only the company insights and sector insights for an "
        "investment-research report about a fund.",
        "",
        "Task: write only the company_insights and sector_insights sections "
        "using the fund context and news below. Do not write a fund snapshot, "
        "financial-health summary, or any other report section. Every claim "
        "and number must be supported by the supplied fund data or news; "
        "never guess.",
        "",
        "Write in simple, everyday language for a general reader. Use short, "
        "clear sentences. When a financial or industry term or acronym is "
        "useful, explain it briefly in plain words the first time it appears, "
        "in the same sentence and in a way that fits this specific company or "
        "sector context. Connect the explanation to why the development "
        "matters; do not insert a dictionary-style aside, a detached glossary "
        "definition, or jargon just to sound technical. Prefer everyday "
        "wording when it is clearer, and spell out an acronym on first use.",
        "Write in English only. Reproduce the numbers exactly as formatted in "
        "the fund data: percentages as percents (10%, never 0.1) and large "
        "amounts with magnitude words (2.15 billion, 1 million).",
        "",
        "Fund data:",
        (
            f"- Fund: {profile.name} (ticker {profile.ticker}), "
            f"family {profile.family or 'unknown'}, "
            f"currency {profile.currency or 'unknown'}"
        ),
    ]
    if profile.sector_weights:
        weights = ", ".join(
            f"{sector} {format_percent(weight)}"
            for sector, weight in sorted(
                profile.sector_weights.items(), key=lambda kv: kv[1], reverse=True
            )
        )
        lines.append(f"- Sector weights: {weights}")
    else:
        lines.append("- Sector weights: not available")
    if profile.holdings:
        holdings = ", ".join(
            f"{holding.name} {format_percent(holding.weight)}"
            for holding in sorted(
                profile.holdings, key=lambda holding: holding.weight, reverse=True
            )
        )
        lines.append(f"- Top holdings: {holdings}")
    else:
        lines.append("- Top holdings: not available")
    lines.append("")
    company_news, sector_news = partition_news(profile, news)
    lines.append(
        "News (the top few items per company or sector; each item is tagged "
        "with the entity its search targeted, and carries its summary plus "
        "the article's full text — draw on that text for depth and detail, "
        "paraphrasing rather than quoting wholesale):"
    )
    if company_news or sector_news:
        lines.append("Company news:")
        for item in company_news:
            lines.append(_news_line(item, source_numbers[item.url]))
        lines.append("Sector news:")
        for item in sector_news:
            lines.append(_news_line(item, source_numbers[item.url]))
    else:
        lines.append(
            "- No news items were found in this run's searches; "
            "both insight sections must say that."
        )
    lines += [
        "",
        "Output: reply with ONLY one JSON object — no markdown, no code "
        "fences, no commentary — with exactly these keys:",
        '{"company_insights": "...", "sector_insights": "..."}',
        "- company_insights: a detailed, informative section on companies "
        "covered by the company news, grouped by company. Do not stop at "
        "reciting events: for each material development, explain what "
        "happened, why it matters to the business, and what it could mean "
        "for an investor in this fund. Where the supplied evidence supports "
        "it, connect the development to a business mechanism such as revenue, "
        "costs, cash flow, contracts/order book, competition, or regulation; "
        "then explain the likely significance and relevant risk or "
        "opportunity. Relate the company to the fund's holding/weight when "
        "useful and available, without implying that one holding determines "
        "the fund's performance. Distinguish reported facts from your "
        "evidence-based interpretation, qualify uncertain or conditional "
        "impacts, and do not predict share-price moves or give buy/sell "
        "advice. Cite each factual claim and the source-grounded reasoning "
        "with the exact source token shown beside the relevant news item "
        "(for example [S1]); do not invent source tokens. Leave companies "
        "without news out rather than guessing.",
        "- sector_insights: a detailed, informative section on sectors "
        "covered by the sector news, grouped by sector. Do not just list "
        "trends: explain what is driving the sector, why that matters "
        "economically to companies in it, and what it could mean for an "
        "investor in this fund. Where supported, connect the driver to "
        "companies' demand, pricing, costs, investment, or regulation and "
        "identify who may benefit or face pressure. Relate the implications "
        "to the fund's sector allocation when available; do not imply every "
        "company is affected equally. Distinguish reported facts from "
        "outlook and your interpretation, qualify uncertain or conditional "
        "impacts, and do not predict share-price moves or give buy/sell "
        "advice. Cite each factual claim and the source-grounded reasoning "
        "with the exact source token shown beside the relevant news item "
        "(for example [S1]); do not invent source tokens.",
        "Every key in the object is required — never omit a key and never "
        "leave one empty. Keep the writing simple and easy to understand. "
        "Make any necessary jargon explanation read as part of the insight "
        "and its reasoning, not as a separate definition.",
        "Length: keep the whole reply within about 1500 words. For each "
        "company or sector, make the chain clear: sourced development → "
        "business/sector effect → why it matters to the fund's investor. "
        "Write several substantive sentences, with enough detail to be useful "
        "but no repetition or unsupported speculation.",
    ]
    return "\n".join(lines)


def request_messages(prompt: str) -> list[dict[str, Any]]:
    """The chat messages (contracts/ollama.v1.md).

    One user message — the task, simple-language guidance, fund data, news,
    and output schema. FR4 intentionally keeps its existing request shape.
    Plain dicts — the SDK converts them to its typed models, keeping this
    module free of SDK imports.
    """
    return [{"role": "user", "content": prompt}]


def request_options() -> dict[str, Any]:
    """The chat options (contracts/ollama.v1.md).

    Temperature 0 — deterministic synthesis. The context window and
    generation cap stay at the server's defaults. No `format` (Gemma does
    not reliably support JSON mode; the prompt demands bare JSON instead),
    and no tools or thinking config.
    """
    return {"temperature": 0}


def corrective_prompt(prompt: str, reason: str, previous_text: str | None) -> str:
    """The FR4 corrective retry: the original prompt plus what went wrong."""
    previous = (previous_text or "(the reply contained no text)").strip()
    if len(previous) > CORRECTIVE_TEXT_LIMIT:
        previous = previous[:CORRECTIVE_TEXT_LIMIT] + "…"
    return (
        f"{prompt}\n\n"
        f"Your previous reply was invalid: {reason}\n\n"
        f"{previous}\n\n"
        "Reply again with only the corrected JSON object. Every key in the "
        "output schema is required — do not omit any, and leave none empty."
    )
