"""
Main entrypoint and bot bootstrap for Medicine Reminder Bot.

This module exposes MedicineReminderBot for import checks and provides a
script entry to run the bot in polling (dev) or webhook (prod) modes.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional


class MedicineReminderBot:
    """Lightweight facade used by tests/CI to validate availability.

    The heavy initialization is done lazily via initialize().
    """

    def __init__(self) -> None:
        self.application = None  # telegram.ext.Application, assigned in initialize()

    async def initialize(self) -> None:
        """Initialize database, build Application and register handlers.

        Lazy-imports are used so importing this module remains cheap and safe.
        """
        # Lazy imports to avoid side effects at import time
        from config import config
        from database import init_database
        from telegram.ext import Application
        from handlers import get_all_conversation_handlers, get_all_callback_handlers
        from scheduler import medicine_scheduler

        # Initialize database
        await init_database()

        # Build Application
        application = Application.builder().token(config.BOT_TOKEN).build()

        # Register conversation handlers
        for conv in get_all_conversation_handlers():
            application.add_handler(conv)

        # Register callback handlers
        for cb in get_all_callback_handlers():
            application.add_handler(cb)

        # Provide bot reference to the scheduler utilities
        medicine_scheduler.bot = application.bot

        self.application = application

    def run_polling(self) -> None:
        """Run the bot using polling (development mode)."""
        if self.application is None:
            raise RuntimeError("Bot is not initialized. Call initialize() first.")

        # Delete webhook if was set previously and start polling
        self.application.run_polling(allowed_updates=["message", "callback_query"], drop_pending_updates=True)

    def run_webhook(self) -> None:
        """Run the bot in webhook mode (production)."""
        if self.application is None:
            raise RuntimeError("Bot is not initialized. Call initialize() first.")

        from config import config

        webhook_url = config.get_webhook_url() or None
        url_path = config.WEBHOOK_PATH.lstrip("/")

        self.application.run_webhook(
            listen="0.0.0.0",
            port=config.WEBHOOK_PORT,
            url_path=url_path,
            webhook_url=webhook_url,
            drop_pending_updates=True,
        )


if __name__ == "__main__":
    # Basic logging setup
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    # Build bot
    bot = MedicineReminderBot()
    # Initialize asynchronously, then run in chosen mode synchronously
    asyncio.run(bot.initialize())

    from config import config

    if config.is_production():
        bot.run_webhook()
    else:
        bot.run_polling()

