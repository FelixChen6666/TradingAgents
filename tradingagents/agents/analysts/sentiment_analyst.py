"""Sentiment analyst — multi-source sentiment analysis for a target ticker.

Previously named ``social_media_analyst``. Renamed and redesigned because
the old version had a prompt that demanded social-media analysis but the
only tool available was Yahoo Finance news — which led LLMs to fabricate
Reddit/X/StockTwits content under prompt pressure (verified live).

The redesigned agent pre-fetches three complementary data sources before
the LLM is invoked and injects them into the prompt as structured blocks:

  1. News headlines     — Yahoo Finance (institutional framing)
  2. StockTwits messages — retail-trader posts indexed by cashtag, with
                           user-labeled Bullish/Bearish sentiment tags
  3. Reddit posts        — r/wallstreetbets, r/stocks, r/investing

The agent does not use tool-calling; the data is in the prompt from
turn 0. Output uses the structured-output pattern (json_schema for
OpenAI/xAI, response_schema for Gemini, tool-use for Anthropic), falling
back to free-text generation for providers that lack native support, so
the sentiment header (band + score + confidence) is deterministic across
runs and providers instead of free-form per-model prose.

See: https://github.com/TauricResearch/TradingAgents/issues/557
See: https://github.com/TauricResearch/TradingAgents/issues/796
"""

from datetime import datetime, timedelta

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.schemas import SentimentReport, render_sentiment_report
from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
    get_news,
    resolve_instrument_identity,
)
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)
from tradingagents.dataflows.interface import route_to_vendor


def _seven_days_back(trade_date: str) -> str:
    return (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")


def create_sentiment_analyst(llm):
    """Create a sentiment analyst node for the trading graph.

    Pre-fetches news + StockTwits + Reddit data, injects them into the
    prompt as structured blocks, and produces a deterministic sentiment
    report via structured output (with a free-text fallback for providers
    that do not support it).
    """
    structured_llm = bind_structured(llm, SentimentReport, "Sentiment Analyst")

    def sentiment_analyst_node(state):
        ticker = state["company_of_interest"]
        end_date = state["trade_date"]
        start_date = _seven_days_back(end_date)
        instrument_context = get_instrument_context_from_state(state)

        # Pre-fetch data sources. Each fetcher degrades gracefully and
        # returns a string (no exceptions surface from here), so the LLM
        # always sees something — either real data or a clear placeholder.
        news_block = get_news.func(ticker, start_date, end_date)

        # When per-ticker news is sparse, supplement with industry/sector news
        # by searching with the company name and industry keywords.
        industry_block = _fetch_industry_news(
            ticker, news_block, start_date, end_date,
        )

        sentiment_block = route_to_vendor(
            "get_social_sentiment", ticker, start_date, end_date, limit=30,
        )

        # Pre-fetch A-share market sentiment and capital flow data
        market_flow_block = route_to_vendor(
            "get_china_market_flow", end_date,
        )

        system_message = _build_system_message(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            news_block=news_block,
            industry_block=industry_block,
            sentiment_block=sentiment_block,
            market_flow_block=market_flow_block,
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    "\n{system_message}\n"
                    "For your reference, the current date is {current_date}. {instrument_context}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(current_date=end_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        # Format the template into a concrete message list so the structured
        # and free-text paths receive the same input. No bind_tools — the
        # data is already in the prompt.
        formatted_messages = prompt.format_messages(messages=state["messages"])

        report_text = invoke_structured_or_freetext(
            structured_llm,
            llm,
            formatted_messages,
            render_sentiment_report,
            "Sentiment Analyst",
        )

        return {
            "messages": [AIMessage(content=report_text)],
            "sentiment_report": report_text,
        }

    return sentiment_analyst_node


def _fetch_industry_news(
    ticker: str,
    current_news: str,
    start_date: str,
    end_date: str,
) -> str:
    """Fetch supplementary industry/sector news when per-ticker news is sparse.

    Uses the company's resolved identity (name, sector, industry) to build
    keyword searches via the East Money search API.

    For A-share tickers, uses the stock code (e.g. ``"600519"``) as the
    primary keyword — East Money's search indexes Chinese news by stock code.
    For non-A-shares, uses the English company name and industry label.

    Returns a formatted industry news block, or an empty string if the
    per-ticker news already has content or identity resolution fails.
    """
    from tradingagents.dataflows.symbol_utils import is_a_share, strip_exchange_suffix

    # Check if per-ticker news is insufficient
    _empty_indicators = (
        "no news found", "no data", "no market data",
        "no article", "unavailable", "<",
    )
    has_news = not current_news.strip().lower().startswith(_empty_indicators)
    if has_news:
        return ""  # Per-ticker news is sufficient, no supplement needed

    identity = resolve_instrument_identity(ticker)
    if not identity:
        return ""

    # Build search keywords
    keywords: list[str] = []
    if is_a_share(ticker):
        # A-shares: stock code works best with East Money search
        code = strip_exchange_suffix(ticker)
        keywords.append(code)
        # Also try the industry Chinese name if available from identity
        industry = identity.get("industry", "")
        if industry:
            keywords.append(industry)
    else:
        # Non-A-shares: use English company name + industry
        name = identity.get("company_name", "")
        if name:
            keywords.append(name)
        sector = identity.get("sector", "")
        industry = identity.get("industry", "")
        if industry:
            keywords.append(industry)
        elif sector:
            keywords.append(sector)

    if not keywords:
        return ""

    result = route_to_vendor(
        "search_news", keywords, start_date, end_date, limit=15,
    )
    if result.startswith("<no keyword search"):
        return ""

    return result


def _build_system_message(
    *,
    ticker: str,
    start_date: str,
    end_date: str,
    news_block: str,
    industry_block: str = "",
    sentiment_block: str,
    market_flow_block: str = "",
) -> str:
    """Assemble the sentiment-analyst system message with structured data blocks."""
    industry_section = ""
    if industry_block:
        industry_section = f"""
### Industry / Sector news — keyword search (东方财富)
Broader industry coverage when per-ticker news was limited. Provides sector context, competitive landscape, and macro trends affecting the company's industry.

<start_of_industry_news>
{industry_block}
<end_of_industry_news>
"""

    market_flow_section = ""
    if market_flow_block and not market_flow_block.startswith("<no"):
        market_flow_section = f"""
### Market Sentiment & Capital Flow (市场情绪与资金流向)
Pre-fetched A-share market data: northbound capital flow, margin trading, market turnover, main capital flow direction, and limit-up/down counts. Provides the broader market state context — use it as a macro-sentiment filter.

<start_of_market_flow>
{market_flow_block}
<end_of_market_flow>
"""

    return f"""You are a financial market sentiment analyst. Your task is to produce a comprehensive sentiment report for {ticker} covering the period from {start_date} to {end_date}, drawing on multiple complementary data sources that have already been collected for you.

## Data sources (pre-fetched, in this prompt)

### News headlines — Yahoo Finance (or configured news vendor), past 7 days
Institutional framing. Fact-driven, slower-moving signal.

<start_of_news>
{news_block}
<end_of_news>
{industry_section}
### Social media / community sentiment — StockTwits + Reddit (+ Chinese A-share sources)
Fast-moving retail signal with sentiment labels. Reddit provides community discussion context.
Chinese sources (Baidu vote, East Money 千股千评) provide bullish/bearish ratios and composite evaluation scores for A-share tickers.

<start_of_social_sentiment>
{sentiment_block}
<end_of_social_sentiment>
{market_flow_section}
## How to analyze this data (best practices)

1. **Read the social sentiment Bullish/Bearish ratio as a leading retail-sentiment signal.** A 70/30 bullish/bearish split is moderately bullish; ≥90/10 may indicate over-extension and contrarian risk; 50/50 is uncertainty. Sample size matters — base rates on the actual message count, not percentages alone.

2. **Look for cross-source divergences.** If news framing is bearish but social sentiment is overwhelmingly bullish, that mismatch is itself a signal — it can mean retail is leaning into a thesis the news flow hasn't caught up to (or vice versa, that retail is chasing while institutions are cautious).

3. **Weight community content by engagement.** For Reddit: a 400-upvote / 200-comment thread reflects community attention; a 3-upvote post is noise. For StockTwits: message volume itself is a signal. Read the body excerpts for context — the title alone often misleads.

4. **Distinguish opinion from event.** A news headline ("Nvidia announces $500M Corning deal") is an event; a StockTwits post ("buying NVDA, this is going to moon") is opinion. Both are inputs but should be weighted differently in your conclusions.

5. **Identify recurring narrative themes.** What topic keeps coming up across sources? That's the dominant narrative driving current sentiment.

6. **Be honest about data limits.** If a source returned only a handful of messages, or returned an "<unavailable>" placeholder, the sentiment read is less robust — flag this explicitly in the `confidence` field and the narrative.

7. **Identify catalysts and risks** that emerge across sources — news of upcoming earnings, product launches, competitive threats, macro headlines, etc.

8. **Past sentiment is not predictive.** Frame your conclusions as signal for the trader to weigh alongside fundamentals and technicals, not as a price call.

9. **Use capital flow data as a macro-sentiment filter.** If northbound capital is flowing out heavily (北向资金大幅流出) or margin balances are shrinking (融资融券余额下降), the broader market environment is cautious regardless of stock-level sentiment. Conversely, strong northbound inflows combined with rising margin balances support bullish stock-level sentiment. Let the capital flow data adjust your confidence in the stock-specific signals. If capital flow data is unavailable (e.g. non-A-share tickers), ignore this filter.

## Output fields

Fill the following fields:

- **overall_band**: Exactly one of Bullish / Mildly Bullish / Neutral / Mixed / Mildly Bearish / Bearish. Use Mixed when sources point in clearly different directions; Neutral only when all sources are genuinely silent.
- **overall_score**: A number from 0 (maximally bearish) to 10 (maximally bullish); 5 is neutral. Keep it consistent with overall_band.
- **confidence**: low / medium / high, based on data quality and sample size.
- **narrative**: Full source-by-source breakdown, divergences, dominant narrative themes, catalysts and risks, and a markdown summary table of key sentiment signals (direction, source, supporting evidence).

{get_language_instruction()}"""


# ---------------------------------------------------------------------------
# Backwards-compatibility shim
# ---------------------------------------------------------------------------
def create_social_media_analyst(llm):
    """Deprecated alias for :func:`create_sentiment_analyst`.

    Kept so existing code that imports ``create_social_media_analyst``
    continues to work.

    .. deprecated::
        Import :func:`create_sentiment_analyst` directly instead.
    """
    import warnings
    warnings.warn(
        "create_social_media_analyst is deprecated and will be removed in a "
        "future version. Use create_sentiment_analyst instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return create_sentiment_analyst(llm)
