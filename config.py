"""
Configuration settings for Medicine Reminder Bot
"""

import os
from typing import List
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Config:
    """Main configuration class"""

    # Bot Configuration
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    BOT_USERNAME: str = os.getenv("BOT_USERNAME", "medicine_reminder_bot")

    # Webhook Configuration (for Render deployment)
    WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "")  # e.g., "https://your-app.onrender.com"
    WEBHOOK_PATH: str = f"/webhook/{BOT_TOKEN}" if BOT_TOKEN else "/webhook"
    WEBHOOK_PORT: int = int(os.getenv("PORT", 10000))  # Render default port

    # Database Configuration
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./medicine_bot.db")
    DB_BACKEND: str = os.getenv("DB_BACKEND", "sqlite").lower()  # 'sqlite' or 'mongo'
    MONGODB_URI: str = os.getenv("MONGODB_URI", "")
    MONGODB_DB: str = os.getenv("MONGODB_DB", "medicine_bot")

    # Debug and Logging
    DEBUG: bool = os.getenv("DEBUG", "False").lower() == "true"
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # Timezone Settings
    DEFAULT_TIMEZONE: str = os.getenv("DEFAULT_TIMEZONE", "UTC")

    # Reminder Settings
    REMINDER_SNOOZE_MINUTES: int = int(os.getenv("REMINDER_SNOOZE_MINUTES", "5"))
    MAX_REMINDER_ATTEMPTS: int = int(os.getenv("MAX_REMINDER_ATTEMPTS", "3"))

    # Inventory Alerts
    DEFAULT_LOW_STOCK_THRESHOLD: float = float(os.getenv("DEFAULT_LOW_STOCK_THRESHOLD", "5.0"))
    INVENTORY_WARNING_DAYS: int = int(os.getenv("INVENTORY_WARNING_DAYS", "3"))

    # User Interface Settings
    MAX_MEDICINES_PER_PAGE: int = int(os.getenv("MAX_MEDICINES_PER_PAGE", "5"))
    KEYBOARD_TIMEOUT_SECONDS: int = int(os.getenv("KEYBOARD_TIMEOUT_SECONDS", "300"))

    # Report Settings
    WEEKLY_REPORT_DAY: int = int(os.getenv("WEEKLY_REPORT_DAY", "0"))  # 0=Monday, 6=Sunday
    WEEKLY_REPORT_TIME: str = os.getenv("WEEKLY_REPORT_TIME", "09:00")

    # Caregiver Settings
    MAX_CAREGIVERS_PER_USER: int = int(os.getenv("MAX_CAREGIVERS_PER_USER", "5"))
    CAREGIVER_DAILY_REPORT_TIME: str = os.getenv("CAREGIVER_DAILY_REPORT_TIME", "20:00")

    # Appointment Settings
    APPOINTMENT_ENABLE: bool = True
    APPOINTMENT_TIMEZONE: str = DEFAULT_TIMEZONE
    APPOINTMENT_ALLOW_CUSTOM: bool = True

    # Default reminders for appointments (booleans)
    APPOINTMENT_REMIND_DAY_BEFORE: bool = True
    APPOINTMENT_REMIND_3_DAYS_BEFORE: bool = False
    APPOINTMENT_REMIND_SAME_DAY: bool = True
    APPOINTMENT_SAME_DAY_REMINDER_HOUR: int = 8  # 08:00 בבוקר

    APPOINTMENTS_HELP: str = "קבעו תור לרופא, בדיקת דם, טיפול או בדיקה. ניתן גם להזין נושא חופשי."

    # Message Templates
    WELCOME_MESSAGE: str = """
🏥 *ברוכים הבאים לבוט תזכורת התרופות!*

אני כאן כדי לעזור לכם:
• 💊 לקבל תזכורות לנטילת תרופות
• 📊 לעקוב אחר המלאי
• 📝 לתעד תופעות לוואי
• 👥 לאפשר למטפלים לעקוב

להוספת הבוט למסך האפליקציות שלכם - לחצו למעלה על שם הבוט - לאחר מכן על 3 הנקודות למעלה בצד המסך - ולבסוף על "הוסף קיצור דרך"
    """

    HELP_MESSAGE: str = """
📋 <b>פקודות זמינות:</b>

<b>🏠 בסיסי:</b>
/start - התחלת השימוש
/help - הצגת עזרה זו
/settings - הגדרות אישיות

<b>💊 ניהול תרופות:</b>
/add_medicine - הוספת תרופה חדשה
/my_medicines - הצגת התרופות שלי
/update_inventory - עדכון מלאי

<b>⏰ תזכורות:</b>
/next_reminders - התזכורות הבאות
/snooze - דחיית תזכורת ב-5 דקות

<b>📊 מעקב:</b>
/log_symptoms - רישום תופעות לוואי
/weekly_report - דוח שבועי
/medicine_history - היסטוריית נטילה

<b>👥 מטפלים:</b>
/add_caregiver - הוספת מטפל
/caregiver_settings - הגדרות מטפלים

💡 <b>טיפ:</b> השתמשו בכפתורים למטה לניווט קל!
    """

    # Error Messages
    ERROR_MESSAGES = {
        "general": "אירעה שגיאה. אנא נסו שוב מאוחר יותר.",
        "invalid_time": "פורמט השעה שגוי. אנא השתמשו בפורמט HH:MM",
        "medicine_not_found": "התרופה לא נמצאה.",
        "unauthorized": "אין לכם הרשאה לפעולה זו.",
        "database_error": "שגיאה בבסיס הנתונים. אנא נסו שוב.",
        "invalid_input": "קלט לא תקין. אנא בדקו ונסו שוב.",
    }

    # Success Messages
    SUCCESS_MESSAGES = {
        "medicine_added": "✅ התרופה נוספה בהצלחה!",
        "dose_confirmed": "✅ נטילת התרופה אושרה!",
        "inventory_updated": "✅ המלאי עודכן בהצלחה!",
        "caregiver_added": "✅ המטפל נוסף בהצלחה!",
        "settings_saved": "✅ ההגדרות נשמרו!",
    }

    # Emojis for UI
    EMOJIS = {
        "medicine": "💊",
        "reminder": "⏰",
        "inventory": "📦",
        "warning": "⚠️",
        "success": "✅",
        "error": "❌",
        "info": "ℹ️",
        "report": "📊",
        "caregiver": "👥",
        "settings": "⚙️",
        "calendar": "📅",
        "back": "⬅️",
        "next": "➡️",
        "doctor": "👨‍⚕️",
        "symptoms": "🤒",
        "clock": "🕒",
        "home": "🏠",
    }

    # Backward-compat alias for occasional typos
    EMOJES = EMOJIS

    @classmethod
    def validate_config(cls) -> List[str]:
        """Validate configuration and return list of errors"""
        errors = []

        if not cls.BOT_TOKEN:
            errors.append("BOT_TOKEN is required")

        if not cls.WEBHOOK_URL and os.getenv("RENDER"):
            errors.append("WEBHOOK_URL is required for Render deployment")

        if cls.WEBHOOK_PORT < 1 or cls.WEBHOOK_PORT > 65535:
            errors.append("WEBHOOK_PORT must be between 1 and 65535")

        if cls.REMINDER_SNOOZE_MINUTES < 1:
            errors.append("REMINDER_SNOOZE_MINUTES must be positive")

        if cls.MAX_REMINDER_ATTEMPTS < 1:
            errors.append("MAX_REMINDER_ATTEMPTS must be positive")
        # Mongo validation
        if cls.DB_BACKEND == "mongo" and not cls.MONGODB_URI:
            errors.append("MONGODB_URI is required when DB_BACKEND=mongo")

        return errors

    @classmethod
    def is_production(cls) -> bool:
        """Check if running in production environment"""
        return bool(os.getenv("RENDER") or os.getenv("PRODUCTION"))

    @classmethod
    def get_webhook_url(cls) -> str:
        """Get full webhook URL"""
        if cls.WEBHOOK_URL:
            return f"{cls.WEBHOOK_URL.rstrip('/')}{cls.WEBHOOK_PATH}"
        return ""


# Global config instance
config = Config()

# Validate configuration on import
config_errors = config.validate_config()
if config_errors:
    error_msg = "\n".join([f"- {error}" for error in config_errors])
    raise ValueError(f"Configuration errors:\n{error_msg}")

# Development settings
if config.DEBUG:
    import logging

    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL), format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
