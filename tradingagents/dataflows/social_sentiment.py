"""Social sentiment data — vendor-routed wrapper around multiple sources.

StockTwits + Reddit (global) + Chinese sources (Baidu vote, East Money 千股千评).
All sources require no API key — Chinese sources use AKShare under the hood.

Adding a new social sentiment source: write a module that calls
``register_vendor("get_social_sentiment", "your_name", your_func)`` and import
it here so the registration fires at startup.
"""

from __future__ import annotations

import logging

from .reddit import fetch_reddit_posts as _fetch_reddit
from .registry import register_vendor
from .stocktwits import fetch_stocktwits_messages as _fetch_stocktwits

logger = logging.getLogger(__name__)


def get_social_sentiment_stocktwits(
    ticker: str,
    start_date: str = "",
    end_date: str = "",
    limit: int = 30,
) -> str:
    """Fetch StockTwits messages for *ticker*.

    See ``tradingagents.dataflows.stocktwits.fetch_stocktwits_messages``
    for details.
    """
    return _fetch_stocktwits(ticker, limit=limit)


def get_social_sentiment_reddit(
    ticker: str,
    start_date: str = "",
    end_date: str = "",
    limit: int = 50,
) -> str:
    """Fetch Reddit posts mentioning *ticker*.

    See ``tradingagents.dataflows.reddit.fetch_reddit_posts`` for details.
    """
    # Reddit doesn't support limit control in its current interface
    return _fetch_reddit(ticker)


def get_social_sentiment_all(
    ticker: str,
    start_date: str = "",
    end_date: str = "",
    limit: int = 30,
) -> str:
    """Aggregate sentiment from both StockTwits and Reddit."""
    stocktwits = _fetch_stocktwits(ticker, limit=limit)
    reddit = _fetch_reddit(ticker)
    return (
        f"## Social Sentiment for {ticker}\n\n"
        f"### StockTwits\n{stocktwits}\n\n"
        f"### Reddit\n{reddit}\n"
    )


# ---------------------------------------------------------------------------
# Registration — each source registers individually so ``route_to_vendor``
# can build a per-source fallback chain.
# ---------------------------------------------------------------------------

register_vendor(
    "get_social_sentiment", "stocktwits", get_social_sentiment_stocktwits,
    category="social_sentiment",
    category_description="Social media sentiment data",
)
register_vendor(
    "get_social_sentiment", "reddit", get_social_sentiment_reddit,
)
register_vendor(
    "get_social_sentiment", "all", get_social_sentiment_all,
)
