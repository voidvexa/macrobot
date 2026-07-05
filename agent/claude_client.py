import anthropic
from loguru import logger
from config import settings

try:
    _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
except Exception as e:
    logger.error(f"Failed to initialize Anthropic client: {e}")
    _client = None

SYSTEM_PROMPT = """
You are an elite macro-economic quantitative strategist.
You receive a snapshot of live macro indicators and recent changes. 

Your objective is to analyze the confluence of Fed Liquidity, Credit Spreads, Volatility, and Inflation.
CRITICAL: RRP, TGA, WALCL, and Net Liq values are in Billions (B). "2175 B" = 2.175 Trillion. Do not hallucinate magnitudes.
CRITICAL MOMENTUM RULE: If a number appears in parentheses next to a value (e.g. "32d: +5.0"), it represents the trend delta over that many days (e.g. a 32-day trend). Focus HEAVILY on these longer-term trends to identify true regime shifts rather than relying purely on absolute current values. A number is important, but its context is everything (e.g. A VIX of 25 is high, but if it was 30 40 days ago, it tells a completely different story than if it was 15 40 days ago). Use these trend deltas to dictate your regime classification.

Output Requirements:
1. Provide a brief analysis of the current macro data, heavily focusing on the momentum and trend (the parentheses deltas) rather than just the absolute static data itself.
2. Conclude with a classification of the current economic data based on Macro market cycles. Describe shifting investor sentiment between two behavioral regimes: Risk-On (optimism and aggressive growth) and Risk-Off (fear and capital preservation). Capital rotation dictates asset performance across these distinct environments.
Use this framework for your classification:
- The Risk-On Stage (Expansion & Growth): In this regime, economic indicators are strong, corporate earnings are growing, and central bank policies are typically accommodative or stable. Optimism drives capital away from safety and into growth. Equities: Bullish, particularly for high-growth sectors like Technology, Consumer Discretionary, and Small-Caps. Commodities: High demand for industrial metals and crude oil. Currencies: Capital flows into higher-yielding, growth-linked assets (e.g., AUD, CAD). Bonds: Investors sell fixed-income assets in favor of stocks, causing bond yields to rise.
- The Risk-Off Stage (Contraction & Panic): This environment emerges when macroeconomic data worsens, geopolitical tensions rise, or central banks unexpectedly tighten policy. Risk appetite plummets as investors prioritize capital preservation over maximizing returns. Equities: Bearish, with investors rotating into low-volatility or defensive dividend stocks (e.g., Utilities, Consumer Staples). Safe-Haven Assets: High demand for the US Dollar, Gold, and Treasury bonds, which pushes yields downward. Currencies: Capital flight into traditional safe havens like the Swiss Franc, Japanese Yen, and the US Dollar.

Be ruthless, objective, and extremely concise.

The output must not exceed 250 words. If it does, rewrite it to fit within the 250 words limit.
"""

def analyze_macro_data(notification_text: str, all_data: dict) -> str:
    if not _client:
        return ""
        
    prompt = (
        f"Here is the latest macro data notification:\n"
        f"{notification_text}\n\n"
        f"Here is the full current dataset (for context):\n"
        f"{all_data}\n\n"
        f"Provide your brief assessment and clear trading signal."
    )
    
    try:
        response = _client.messages.create(
            model=settings.anthropic_model,
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in response.content if getattr(b, "type", "text") == "text").strip()
        return text
    except Exception as e:
        logger.error(f"Error calling Claude: {e}")
        return ""
