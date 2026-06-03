"""News analyst — multi-layer news research for A-share market analysis.

Uses a 4-layer framework to produce comprehensive news reports:

  Layer 1 — Macro & Global Environment: Sets risk appetite / position limits.
  Layer 2 — Capital Flow & Sentiment: Gauges market timing / temperature.
  Layer 3 — Policy & Industry Direction: Identifies favored sectors.
  Layer 4 — Individual Stock Catalysts: Picks specific targets.

The agent uses tool-calling (6 tools total) so the LLM decides the
depth and order of data fetching for each layer.
"""

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_global_news,
    get_language_instruction,
    get_news,
    get_china_macro_news,
    get_china_policy_news,
    get_china_global_market_news,
    get_china_market_flow,
)
from tradingagents.dataflows.config import get_config


def create_news_analyst(llm):
    def news_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        asset_type = state.get("asset_type", "stock")
        asset_label = "company" if asset_type == "stock" else "asset"
        instrument_context = get_instrument_context_from_state(state)

        tools = [
            # Existing tools (backward compatible)
            get_news,
            get_global_news,
            # New 4-layer tools
            get_china_macro_news,
            get_china_global_market_news,
            get_china_market_flow,
            get_china_policy_news,
        ]

        system_message = (
            f"You are a strategic news researcher for A-share market analysis assigned to {ticker}. "
            f"Analyze news using a **4-layer framework** to build a complete market picture. "
            f"Always start with Layer 1 (broad context) and drill down to Layer 4 (specific).\n\n"
            f"### Layer 1 - Macro & Global Environment (set risk appetite)\n"
            f"  - Call **get_china_macro_news(start_date, end_date)** for GDP/CPI/PMI/社融 data\n"
            f"  - Call **get_china_global_market_news(start_date, end_date)** for US/HK markets, commodities, FX\n"
            f"  - Call **get_global_news(curr_date)** for broader macro headlines\n"
            f"  - Determine: Is the macro environment risk-on or risk-off? Rate hike or cut cycle?\n\n"
            f"### Layer 2 - Capital Flow & Market Sentiment (judge timing)\n"
            f"  - Call **get_china_market_flow(trade_date)** for northbound capital flow, margin trading, turnover\n"
            f"  - Check: Northbound flow direction (北向资金净流入/流出 = bullish/bearish)\n"
            f"  - Check: Margin balance trend (融资融券余额增加 = risk appetite increasing)\n"
            f"  - Check: Market turnover (成交额放大 = active, 缩量 = cautious)\n"
            f"  - Determine: Is money flowing in or out? Is the market active or dormant?\n\n"
            f"### Layer 3 - Policy & Industry Direction (choose sectors)\n"
            f"  - Call **get_china_policy_news(start_date, end_date)** for policy catalysts\n"
            f"  - Call **get_news(\"keyword\", start_date, end_date)** with industry keywords (e.g. \"新能源\", \"AI\", \"消费\")\n"
            f"  - Identify sectors benefiting from policy tailwinds vs facing headwinds\n\n"
            f"### Layer 4 - Individual {asset_label.title()} Catalyst (specific targets)\n"
            f"  - Call **get_news({ticker}, start_date, end_date)** for {ticker}-specific news\n"
            f"  - Relate {asset_label}-specific events to the macro/policy/capital-flow context\n\n"
            f"## Report Format\n"
            f"Write a comprehensive synthesis organized by the 4 layers above. "
            f"End with a Markdown summary table mapping each layer's key signal "
            f"(signal direction, evidence source, confidence level).\n\n"
            f"{get_language_instruction()}"
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the provided tools to progress towards answering the question."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                    " will help where you left off. Execute what you can to make progress."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    " You have access to the following tools: {tool_names}.\n{system_message}"
                    "For your reference, the current date is {current_date}. {instrument_context}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(state["messages"])

        report = ""

        if len(result.tool_calls) == 0:
            report = result.content

        return {
            "messages": [result],
            "news_report": report,
        }

    return news_analyst_node
