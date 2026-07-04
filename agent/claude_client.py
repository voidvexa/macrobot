import anthropic
from loguru import logger
from config import settings

try:
    _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
except Exception as e:
    logger.error(f"Failed to initialize Anthropic client: {e}")
    _client = None

SYSTEM_PROMPT = """
You are a macro-economic analyst with years of experience in financial markets.
You have seen many market cycles and are skilled at interpreting macroeconomic data to provide actionable insights.
You receive a list of recent macro data changes and current values.
Your task is to provide a brief (2-4 sentences max) assessment of the current market regime (e.g. risk-on/off, inflation trends, rate expectations) or a potential trade idea based on this data.
You should not provide generic statements; focus on the specific data provided.
Be direct, professional, and concise.
"""

def analyze_macro_data(notification_text: str, all_data: dict) -> str:
    if not _client:
        return ""
        
    prompt = (
        f"Here is the latest macro data notification:\n"
        f"{notification_text}\n\n"
        f"Here is the full current dataset (for context):\n"
        f"{all_data}\n\n"
        f"Provide your brief assessment."
    )
    
    try:
        response = _client.messages.create(
            model=settings.anthropic_model,
            max_tokens=256,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in response.content if getattr(b, "type", "text") == "text").strip()
        return text
    except Exception as e:
        logger.error(f"Error calling Claude: {e}")
        return ""
