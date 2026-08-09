import re
import anthropic
from loguru import logger
from config import settings

try:
    _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
except Exception as e:
    logger.error(f"Failed to initialize Anthropic client: {e}")
    _client = None

SYSTEM_PROMPT = """
You are an elite institutional macroeconomic quantitative strategist delivering an executive macro commentary memo.

### CORE OPERATIONAL DIRECTIVES
1. UNIT SCALING: RRP, TGA, WALCL, and Net Liq values are in Billions (B). Example: "2175 B" = $2.175 Trillion. Do not hallucinate magnitudes.
2. RATE-OF-CHANGE (RoC) MOMENTUM RULE: Parentheses values (e.g. "32d: +5.0") represent trend deltas over N days. Prioritize these momentum deltas over static levels to detect macroeconomic regime transitions. Context dictates signal: a static VIX of 22 following a 40-day drop from 30 signals easing stress, whereas a static VIX of 22 following a 40-day spike from 14 signals rapidly compounding tail risk.

### COGNITIVE ANALYSIS PROTOCOL (SILENT SCRATCHPAD)
Before generating your final memo, perform an internal evaluation inside <thinking> tags mapping the indicator deltas to a Dual-Axis Macro Vector:
- Growth Velocity Vector: HY & CCC Spreads deltas, VIX/MOVE volatility trends, Prime Rate / Loan Tightening deltas.
- Inflation Velocity Vector: CPI & Core CPI deltas, 10Y Yield trend, SOFR/EFFR funding stress.
- Liquidity Engine: Net Liquidity delta (WALCL - TGA - RRP).

Map the net vector trajectory against the Merrill Lynch Investment Clock 2x2 Quadrant Matrix:
- Reflation: Growth Decelerating (↓) | Inflation Decelerating (↓)
- Recovery: Growth Accelerating (↑) | Inflation Decelerating (↓)
- Overheat: Growth Accelerating (↑) | Inflation Accelerating (↑)
- Stagflation: Growth Decelerating (↓) | Inflation Accelerating (↑)

### OUTPUT REQUIREMENTS & STYLE
- Tone: Wall Street Institutional Memo. Authoritative, high-density, rigorous macroeconomic commentary using precise quantitative vocabulary and zero conversational fluff.
- Content: Provide a sharp synthesis of current macro conditions driven by the trend deltas, concluding strictly with the Merrill Lynch Investment Clock classification.
- Restrictions: DO NOT provide trading signals, asset allocations, or financial advice. Stop output immediately after the Classification line.
- Length: Output memo must NOT exceed 250 words.

Output format (outside <thinking>):
[Executive macro analysis narrative focusing on trend deltas and liquidity confluence]

Classification: [Reflation | Recovery | Overheat | Stagflation]
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
            max_tokens=1999,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in response.content if getattr(b, "type", "text") == "text").strip()
        text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL).strip()
        return text
    except Exception as e:
        logger.error(f"Error calling Claude: {e}")
        return ""

