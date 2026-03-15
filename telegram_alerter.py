"""
Telegram alerter - sends notifications to bot owner.
Used for usage alerts and system notifications.
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_USER_ID = os.getenv("OWNER_USER_ID", "")


async def send_telegram_alert(message: str) -> bool:
    """Send alert message to bot owner via Telegram API."""
    if not BOT_TOKEN or not OWNER_USER_ID:
        logger.warning("Cannot send alert: BOT_TOKEN or OWNER_USER_ID not configured")
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": OWNER_USER_ID, "text": message}
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
