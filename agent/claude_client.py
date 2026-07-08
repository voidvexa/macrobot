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
2. Conclude with a classification of the current economic data into one of the four Merrill Lynch Investment Clock regimes: Reflation, Recovery, Overheat, or Stagflation. Use your own deep macroeconomic knowledge to determine which of these four regimes best fits the provided data, ensuring your determination is heavily driven by the rate of change (the parentheses trend deltas).
DO NOT provide any trading signals or asset recommendations. Stop your output immediately after providing the Classification and its brief justification.

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
        f"Provide your brief assessment and stop immediately after the classification."
    )
    
    try:
        response = _client.messages.create(
            model=settings.anthropic_model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in response.content if getattr(b, "type", "text") == "text").strip()
        return text
    except Exception as e:
        logger.error(f"Error calling Claude: {e}")
        return ""
