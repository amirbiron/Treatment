"""
Usage Admin Handler
Provides an admin-only command to show weekly active users.
"""

import logging
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

from config import config
from database import DatabaseManager

logger = logging.getLogger(__name__)


class UsageAdminHandler:
    """Admin-only usage insights commands"""

    def get_handlers(self):
        return [CommandHandler("admin_usage", self.admin_usage)]

    async def admin_usage(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.effective_user.id
            # Authorize admin by Telegram ID
            if user_id not in getattr(config, "ADMIN_TELEGRAM_IDS", []):
                return

            since = datetime.utcnow() - timedelta(days=7)
            count = await DatabaseManager.count_users_active_since(since)  # SQL or Mongo implementation

            await update.message.reply_text(
                f"משתמשים פעילים ב-7 ימים האחרונים: {count}"
            )
        except Exception as e:
            logger.error(f"Error in admin_usage: {e}")
            try:
                await update.message.reply_text("❌ שגיאה בשליפת הנתונים")
            except Exception:
                pass


usage_admin_handler = UsageAdminHandler()

