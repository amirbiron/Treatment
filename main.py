import asyncio
import logging
import os
from typing import List

from telegram import Update, BotCommand
from telegram.ext import (
    Application, CommandHandler, ContextTypes
)

from config import config
from handlers import get_all_conversation_handlers, get_all_callback_handlers
from scheduler import medicine_scheduler


logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        config.WELCOME_MESSAGE,
        parse_mode='Markdown'
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        config.HELP_MESSAGE,
        parse_mode='Markdown'
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled exception in handler", exc_info=context.error)


async def post_init(application: Application) -> None:
    # Set bot commands
    commands: List[BotCommand] = [
        BotCommand("start", "התחלת השימוש"),
        BotCommand("help", "הצגת עזרה"),
        BotCommand("add_medicine", "הוספת תרופה"),
        BotCommand("weekly_report", "דוח שבועי"),
        BotCommand("monthly_report", "דוח חודשי"),
        BotCommand("snooze", "דחיית תזכורת"),
        BotCommand("next_reminders", "תזכורות קרובות"),
    ]
    try:
        await application.bot.set_my_commands(commands)
    except Exception:
        logger.warning("Failed setting bot commands", exc_info=True)

    # Wire scheduler to bot and start lightweight scheduler engine
    medicine_scheduler.bot = application.bot
    try:
        if not medicine_scheduler.scheduler.running:
            medicine_scheduler.scheduler.start()
            logger.info("APScheduler started")
    except Exception:
        logger.warning("Failed to start APScheduler", exc_info=True)


def build_application() -> Application:
    app = Application.builder() \
        .token(config.BOT_TOKEN) \
        .post_init(post_init) \
        .build()

    # Core commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))

    # Domain conversations and callbacks
    for conv in get_all_conversation_handlers():
        app.add_handler(conv)
    for h in get_all_callback_handlers():
        app.add_handler(h)

    # Errors
    app.add_error_handler(error_handler)

    return app


def main() -> None:
    application = build_application()

    if config.is_production() and config.get_webhook_url():
        # Webhook mode (Render)
        application.run_webhook(
            listen="0.0.0.0",
            port=config.WEBHOOK_PORT,
            url_path=config.WEBHOOK_PATH,
            webhook_url=config.get_webhook_url(),
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        # Polling mode (local/dev)
        application.run_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
        )


if __name__ == "__main__":
    main()