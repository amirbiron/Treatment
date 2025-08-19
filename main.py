"""
Main entry for Medicine Reminder Bot
Exports MedicineReminderBot for external usage/tests.

This file intentionally keeps imports lazy to avoid heavy side-effects at import time.
"""

from typing import Any, List


class MedicineReminderBot:
    """Lightweight facade to build/run the Telegram bot.

    Importing this class does not trigger heavy imports. Call build()/run_polling() to initialize.
    """

    def __init__(self, token: str | None = None):
        self.token = token
        self.app: Any = None

    def build(self):
        """Build the Application and register handlers.
        Returns the constructed Application instance.
        """
        # Lazy imports to keep module import cheap/safe
        import os
        from telegram.ext import Application
        from config import config
        from handlers import get_all_conversation_handlers, get_all_callback_handlers
        from scheduler import medicine_scheduler

        bot_token = self.token or os.getenv("BOT_TOKEN") or config.BOT_TOKEN
        if not bot_token:
            raise ValueError("BOT_TOKEN is required")

        application = Application.builder().token(bot_token).build()

        # Register conversation handlers
        for conv in get_all_conversation_handlers():
            application.add_handler(conv)

        # Register plain callback/command handlers
        for cb in get_all_callback_handlers():
            application.add_handler(cb)

        # Provide bot instance to scheduler utilities
        medicine_scheduler.bot = application.bot

        self.app = application
        return application

    def run_polling(self):
        """Build (if needed) and run the bot with polling. Blocks until interrupted."""
        app = self.app or self.build()
        app.run_polling()


if __name__ == "__main__":
    # Run using polling when executed directly
    MedicineReminderBot().run_polling()