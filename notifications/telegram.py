import requests
from loguru import logger
from config import settings

_TELEGRAM_API = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"


def send_message(text: str) -> None:
    try:
        resp = requests.post(
            _TELEGRAM_API,
            json={
                "chat_id": settings.telegram_chat_id,
                "text": text,
                "parse_mode": "Markdown",
            },
            timeout=10,
        )
        if not resp.ok:
            logger.warning(f"Telegram send failed: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.error(f"Telegram error: {e}")
