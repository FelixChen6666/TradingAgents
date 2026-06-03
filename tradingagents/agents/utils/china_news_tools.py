"""LangChain tools for China macro, policy, global, and market-flow news.

These tools wrap the new four-layer news data sources and are exposed
to agents that need broader news context — primarily the News Analyst
(Layer 1-4) and optionally the Sentiment Analyst.
"""

from typing import Annotated, Optional

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor


@tool
def get_china_macro_news(
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
    limit: Annotated[Optional[int], "Max articles/indicators to return"] = None,
) -> str:
    """Fetch China macroeconomic news and economic indicator data.

    Covers GDP, CPI, PPI, PMI, social financing (社融), LPR interest rate
    decisions, RRR changes, and other macroeconomic data releases. Returns
    both news articles (keyword search) and numerical indicator tables (AKShare).

    Use this tool for Layer 1 (Macro/Global) analysis: determining the
    overall risk appetite and macro environment for A-share markets.
    """
    return route_to_vendor("get_china_macro_news", start_date, end_date, limit)


@tool
def get_china_policy_news(
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
    limit: Annotated[Optional[int], "Max articles to return"] = None,
) -> str:
    """Fetch China policy and regulatory news.

    Covers industrial policies (双碳/数字经济/设备更新/以旧换新/AI),
    regulatory actions (反垄断/游戏版号/平台经济), and capital market
    reforms (印花税/减持新规/注册制).

    Use this tool for Layer 3 (Policy/Industry) analysis: identifying
    which sectors are favored by policy tailwinds or facing regulatory headwinds.
    """
    return route_to_vendor("get_china_policy_news", start_date, end_date, limit)


@tool
def get_china_global_market_news(
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
    limit: Annotated[Optional[int], "Max articles to return"] = None,
) -> str:
    """Fetch global market and geopolitical news filtered for A-share relevance.

    Covers US/HK markets (美股/港股/中概股), commodities (原油/铜/铁矿石),
    foreign exchange (USD/CNY), geopolitics (US-China relations, trade
    frictions), and Asia-Pacific market trends.

    Use this tool for Layer 1 (Global) analysis alongside get_china_macro_news
    to understand cross-market influences on A-shares.
    """
    return route_to_vendor("get_china_global_market_news", start_date, end_date, limit)


@tool
def get_china_market_flow(
    trade_date: Annotated[str, "Trade date in yyyy-mm-dd format"],
) -> str:
    """Fetch A-share market sentiment and capital flow statistics.

    Includes: market turnover (两市成交额/涨跌家数), northbound capital
    flow (北向资金净流入), margin trading balances (融资融券余额), main
    capital flow by sector (主力资金流向), and limit-up/down statistics
    (涨停/跌停).

    Use this tool for Layer 2 (Capital Flow/Sentiment) analysis: judging
    market state and timing. Northbound flow > 0 is bullish for large-caps;
    rising margin balances indicate increasing retail risk appetite;
    high turnover confirms active participation.
    """
    return route_to_vendor("get_china_market_flow", trade_date)
