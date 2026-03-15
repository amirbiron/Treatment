"""
Gemini API wrapper with usage monitoring.
Wraps single-prompt calls and handles rate limiting.
"""

import logging
import os

import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted

from usage_tracker import ALERT_THRESHOLD, increment_and_check_usage, is_limit_reached
from telegram_alerter import send_telegram_alert

logger = logging.getLogger(__name__)

# Configure Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)


async def generate_content_with_monitoring(prompt: str, system_instruction: str = None) -> str | None:
    """Single prompt to Gemini with usage tracking. Returns response text or None."""
    if is_limit_reached():
        logger.warning("Daily API limit reached")
        return None

    current_count = increment_and_check_usage()
    if current_count == ALERT_THRESHOLD:
        await send_telegram_alert(f"Gemini usage alert: {current_count} calls today")

    try:
        model = genai.GenerativeModel(
            "gemini-2.5-flash",
            system_instruction=system_instruction,
        )
        response = await model.generate_content_async(prompt)
        return response.text
    except ResourceExhausted:
        logger.warning("Gemini API rate limit (429)")
        await send_telegram_alert("Gemini API rate limited (429)")
        return None
    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        return None
