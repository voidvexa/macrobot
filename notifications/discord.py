import requests
from loguru import logger
from config import settings

def send_message(text: str) -> None:
    if not settings.discord_webhook_url:
        return
    
    try:
        resp = requests.post(
            settings.discord_webhook_url,
            json={"content": text},
            timeout=10,
        )
        if not resp.ok:
            logger.warning(f"Discord send failed: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.error(f"Discord error: {e}")
