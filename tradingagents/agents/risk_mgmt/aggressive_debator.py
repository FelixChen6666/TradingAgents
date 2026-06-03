from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
)


def create_aggressive_debator(llm):
    def aggressive_node(state) -> dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        aggressive_history = risk_debate_state.get("aggressive_history", "")

        current_conservative_response = risk_debate_state.get("current_conservative_response", "")
        current_neutral_response = risk_debate_state.get("current_neutral_response", "")

        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        instrument_context = get_instrument_context_from_state(state)

        trader_decision = state["trader_investment_plan"]

        prompt = f"""As the Aggressive Risk Analyst, your role is to examine the trader's proposal from an upside-opportunity perspective, focusing on growth catalysts, positive trends, and factors that could drive returns above expectations. Assess the proposal based on the available data rather than predispositions. Here is the trader's decision:

{trader_decision}

Review the Conservative and Neutral Analysts' arguments, identifying areas where their assessments may overstate risks or overlook positive signals. Ground your analysis in the following data sources:

{instrument_context}
Market Research Report: {market_research_report}
Social Media Sentiment Report: {sentiment_report}
Latest World Affairs Report: {news_report}
Company Fundamentals Report: {fundamentals_report}
Here is the current conversation history: {history} Here are the last arguments from the conservative analyst: {current_conservative_response} Here are the last arguments from the neutral analyst: {current_neutral_response}. If there are no responses from the other viewpoints yet, present your own assessment based on the available data.

Reference specific data points, metrics, and evidence rather than making qualitative claims. Where you identify opportunities, cite the supporting numbers or facts. Output conversationally as if you are speaking without any special formatting.""" + get_language_instruction()

        response = llm.invoke(prompt)

        argument = f"Aggressive Analyst: {response.content}"

        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "aggressive_history": aggressive_history + "\n" + argument,
            "conservative_history": risk_debate_state.get("conservative_history", ""),
            "neutral_history": risk_debate_state.get("neutral_history", ""),
            "latest_speaker": "Aggressive",
            "current_aggressive_response": argument,
            "current_conservative_response": risk_debate_state.get("current_conservative_response", ""),
            "current_neutral_response": risk_debate_state.get(
                "current_neutral_response", ""
            ),
            "count": risk_debate_state["count"] + 1,
        }

        return {"risk_debate_state": new_risk_debate_state}

    return aggressive_node
