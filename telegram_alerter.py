"""
Telegram alerter - sends notifications to bot owner.
Used for usage alerts and system notifications.
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)


async def send_telegram_alert(message: str) -> bool:
    """Send alert message to bot owner via Telegram API."""
    bot_token = os.getenv("BOT_TOKEN", "")
    owner_id = os.getenv("OWNER_USER_ID", "")
    if not bot_token or not owner_id:
        logger.warning("Cannot send alert: BOT_TOKEN or OWNER_USER_ID not configured")
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": owner_id, "text": message}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                return True
            logger.warning(f"Alert send failed: {resp.status_code}")
            return False
    except Exception as e:
        logger.error(f"Failed to send telegram alert: {e}")
        return False
