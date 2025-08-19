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
        # Suppress noisy PTB warning about CallbackQueryHandler + per_message=False
        # This preserves mixed text/callback conversations while keeping logs clean.
        from warnings import filterwarnings
        try:
            from telegram.warnings import PTBUserWarning
            filterwarnings(
                action="ignore",
                message=r".*CallbackQueryHandler.*will not be tracked for every message.*",
                category=PTBUserWarning,
            )
        except Exception:
            # If telegram.warnings isn't available yet, continue without filtering
            pass

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

        # Set admin-only bot commands (side menu) if admin IDs configured
        try:
            from config import config
            if config.ADMIN_TELEGRAM_IDS:
                from telegram import BotCommand, BotCommandScopeChat
                async def _set_admin_commands(app):
                    for admin_id in config.ADMIN_TELEGRAM_IDS:
                        try:
                            await app.bot.set_my_commands(
                                commands=[BotCommand("admin_usage", "מספר משתמשים פעילים בשבוע האחרון")],
                                scope=BotCommandScopeChat(chat_id=admin_id),
                                language_code="he",
                            )
                        except Exception:
                            pass
                # schedule post init to set commands
                async def _post_init_set_commands(_: Any):
                    await _set_admin_commands(application)
                # chain with existing post_init if any
                prev_post_init = getattr(application, "post_init", None)
                async def _combined_post_init(app):
                    if prev_post_init:
                        await prev_post_init(app)
                    await _post_init_set_commands(app)
                # compose with startup hook if already set later in run_* methods
                application.post_init = _combined_post_init
        except Exception:
            pass

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
        # Lazy imports to avoid side effects at import time
        from scheduler import medicine_scheduler

        app = self.app or self.build()

        prev_post_init = getattr(app, "post_init", None)
        async def _on_startup(app_arg: Any):
            if prev_post_init:
                await prev_post_init(app_arg)
            await medicine_scheduler.start()

        prev_post_shutdown = getattr(app, "post_shutdown", None)
        async def _on_shutdown(app_arg: Any):
            if prev_post_shutdown:
                await prev_post_shutdown(app_arg)
            await medicine_scheduler.stop()

        app.post_init = _on_startup
        app.post_shutdown = _on_shutdown

        app.run_polling()

    def run_webhook(self):
        """Run the bot using a built-in webhook webserver (for Render)."""
        # Lazy imports to avoid side effects at import time
        import os
        from config import config
        from scheduler import medicine_scheduler

        app = self.app or self.build()

        prev_post_init = getattr(app, "post_init", None)
        async def _on_startup(app_arg: Any):
            if prev_post_init:
                await prev_post_init(app_arg)
            await medicine_scheduler.start()

        prev_post_shutdown = getattr(app, "post_shutdown", None)
        async def _on_shutdown(app_arg: Any):
            if prev_post_shutdown:
                await prev_post_shutdown(app_arg)
            await medicine_scheduler.stop()

        app.post_init = _on_startup
        app.post_shutdown = _on_shutdown

        webhook_url = config.get_webhook_url()
        url_path = config.WEBHOOK_PATH.lstrip("/")
        listen_host = "0.0.0.0"
        port = int(os.getenv("PORT", str(config.WEBHOOK_PORT)))

        app.run_webhook(
            listen=listen_host,
            port=port,
            url_path=url_path,
            webhook_url=(webhook_url or None),
            drop_pending_updates=True,
        )


if __name__ == "__main__":
    # Prefer webhook mode on Render (binds to PORT), fallback to polling locally
    import os
    from config import config

    bot = MedicineReminderBot()

    if os.getenv("RENDER") or config.get_webhook_url():
        bot.run_webhook()
    else:
        bot.run_polling()