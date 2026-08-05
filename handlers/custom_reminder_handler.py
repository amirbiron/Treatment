"""
Custom (free-form) Reminder Handler

A reminder with its own text, not tied to any medicine: "לקחת מרשם מהרופא",
"למדוד לחץ דם". Either one-off at a date and time, or repeating daily or
weekly.

Menu driven rather than a ConversationHandler, matching the reminders menu it
hangs off. The only text step is the reminder body, flagged on user_data and
picked up by main.handle_text_message.
"""

import logging
from datetime import datetime, time, timedelta
from typing import List, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from config import config
from database import DatabaseManager
from scheduler import medicine_scheduler
from utils.time import get_timezone, get_user_timezone_name, now_in_timezone

logger = logging.getLogger(__name__)

MAX_TEXT_LENGTH = 300

# user_data keys for the in-progress reminder
AWAITING_TEXT = "awaiting_custom_reminder_text"
DRAFT = "custom_reminder_draft"

WEEKDAY_NAMES = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
# APScheduler's day_of_week is 0=Monday..6=Sunday, matching WEEKDAY_NAMES above.


def describe_reminder(reminder) -> str:
    """Human-readable schedule for a reminder row."""
    if reminder.repeat == "once":
        when = reminder.remind_at.strftime("%d/%m/%Y %H:%M") if reminder.remind_at else "?"
        return f"פעם אחת, {when}"
    hhmm = reminder.remind_time.strftime("%H:%M") if reminder.remind_time else "?"
    if reminder.repeat == "daily":
        return f"כל יום ב-{hhmm}"
    if reminder.repeat == "weekly":
        day = WEEKDAY_NAMES[reminder.weekday] if reminder.weekday is not None else "?"
        return f"כל יום {day} ב-{hhmm}"
    return hhmm


class CustomReminderHandler:
    """Standalone reminders: list, create, delete."""

    def get_handlers(self) -> List:
        return [
            CallbackQueryHandler(self.show_menu, pattern="^crem_menu$"),
            CallbackQueryHandler(self.start_add, pattern="^crem_add$"),
            CallbackQueryHandler(self.pick_repeat, pattern=r"^crem_rep_(once|daily|weekly)$"),
            CallbackQueryHandler(self.pick_weekday, pattern=r"^crem_wd_\d$"),
            CallbackQueryHandler(self.pick_day, pattern=r"^crem_day_\d+$"),
            CallbackQueryHandler(self.pick_time, pattern=r"^crem_time_\d{2}_\d{2}$"),
            CallbackQueryHandler(self.ask_delete, pattern=r"^crem_del_\d+$"),
            CallbackQueryHandler(self.confirm_delete, pattern=r"^cremdel_\d+_confirm$"),
            CallbackQueryHandler(self.cancel_delete, pattern=r"^cremdel_\d+_cancel$"),
        ]

    # --- listing ---

    async def show_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List the user's standalone reminders."""
        try:
            self._clear_draft(context)
            user = await DatabaseManager.get_user_by_telegram_id(update.effective_user.id)
            if not user:
                await self._reply(update, config.ERROR_MESSAGES["unauthorized"])
                return

            reminders = await DatabaseManager.get_user_custom_reminders(user.id)
            rows = [
                [
                    InlineKeyboardButton(
                        f"⏰ {r.text} — {describe_reminder(r)}", callback_data=f"crem_del_{r.id}"
                    )
                ]
                for r in reminders
            ]
            rows.append([InlineKeyboardButton("➕ תזכורת חדשה", callback_data="crem_add")])
            rows.append([InlineKeyboardButton(f"{config.EMOJIS['back']} חזור", callback_data="reminders_menu")])

            if reminders:
                message = (
                    f"{config.EMOJIS['reminder']} <b>תזכורות אישיות</b>\n\n"
                    "אלו תזכורות שאינן קשורות לתרופה. הקישו על תזכורת כדי למחוק אותה."
                )
            else:
                message = (
                    f"{config.EMOJIS['reminder']} <b>תזכורות אישיות</b>\n\n"
                    "אין עדיין תזכורות אישיות.\n"
                    'לדוגמה: "לקחת מרשם מהרופא", "למדוד לחץ דם".'
                )

            await self._reply(update, message, reply_markup=InlineKeyboardMarkup(rows), parse_mode="HTML")

        except Exception as exc:
            logger.error(f"Error showing custom reminders: {exc}")
            await self._reply(update, config.ERROR_MESSAGES["general"])

    # --- creation ---

    async def start_add(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        self._clear_draft(context)
        context.user_data[AWAITING_TEXT] = True
        await query.edit_message_text(
            f"{config.EMOJIS['reminder']} על מה להזכיר?\nכתבו את תוכן התזכורת:",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(f"{config.EMOJIS['back']} ביטול", callback_data="crem_menu")]]
            ),
        )

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Consume the pending reminder text. Returns True if the text was ours."""
        if not context.user_data.get(AWAITING_TEXT):
            return False

        text = (update.message.text or "").strip()
        context.user_data.pop(AWAITING_TEXT, None)

        if not text:
            await update.message.reply_text(f"{config.EMOJIS['error']} התזכורת ריקה, לא נשמרה.")
            return True
        if len(text) > MAX_TEXT_LENGTH:
            text = text[:MAX_TEXT_LENGTH]

        context.user_data[DRAFT] = {"text": text}
        await update.message.reply_text(
            f'{config.EMOJIS["reminder"]} <b>{text}</b>\n\nמתי להזכיר?',
            parse_mode="HTML",
            reply_markup=self._repeat_keyboard(),
        )
        return True

    async def pick_repeat(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        draft = context.user_data.get(DRAFT)
        if not draft:
            await query.edit_message_text("התזכורת פגה. התחילו מחדש.", reply_markup=self._back_keyboard())
            return

        repeat = query.data.rsplit("_", 1)[1]
        draft["repeat"] = repeat

        if repeat == "once":
            await query.edit_message_text("באיזה יום?", reply_markup=await self._day_keyboard(update))
        elif repeat == "weekly":
            await query.edit_message_text("באיזה יום בשבוע?", reply_markup=self._weekday_keyboard())
        else:
            await query.edit_message_text("באיזו שעה?", reply_markup=self._time_keyboard())

    async def pick_day(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Days ahead from today, so the buttons never go stale."""
        query = update.callback_query
        await query.answer()
        draft = context.user_data.get(DRAFT)
        if not draft:
            await query.edit_message_text("התזכורת פגה. התחילו מחדש.", reply_markup=self._back_keyboard())
            return

        draft["days_ahead"] = int(query.data.rsplit("_", 1)[1])
        await query.edit_message_text("באיזו שעה?", reply_markup=self._time_keyboard())

    async def pick_weekday(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        draft = context.user_data.get(DRAFT)
        if not draft:
            await query.edit_message_text("התזכורת פגה. התחילו מחדש.", reply_markup=self._back_keyboard())
            return

        draft["weekday"] = int(query.data.rsplit("_", 1)[1])
        await query.edit_message_text("באיזו שעה?", reply_markup=self._time_keyboard())

    async def pick_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Final step: persist the reminder and arm it."""
        query = update.callback_query
        await query.answer()
        draft = context.user_data.get(DRAFT)
        if not draft:
            await query.edit_message_text("התזכורת פגה. התחילו מחדש.", reply_markup=self._back_keyboard())
            return

        _, _, hour, minute = query.data.split("_")
        at = time(int(hour), int(minute))

        try:
            user = await DatabaseManager.get_user_by_telegram_id(query.from_user.id)
            if not user:
                await query.edit_message_text(config.ERROR_MESSAGES["unauthorized"])
                return

            repeat = draft.get("repeat", "once")
            remind_at = None
            if repeat == "once":
                remind_at = self._resolve_datetime(user, draft.get("days_ahead", 0), at)

            reminder = await DatabaseManager.create_custom_reminder(
                user_id=user.id,
                text=draft["text"],
                repeat=repeat,
                remind_at=remind_at,
                remind_time=None if repeat == "once" else at,
                weekday=draft.get("weekday") if repeat == "weekly" else None,
            )

            job_id = await medicine_scheduler.schedule_custom_reminder(reminder)
            self._clear_draft(context)

            if job_id:
                confirmation = (
                    f"{config.EMOJIS['success']} התזכורת נוצרה\n\n"
                    f"{config.EMOJIS['reminder']} <b>{reminder.text}</b>\n"
                    f"🗓 {describe_reminder(reminder)}"
                )
            else:
                # Only reachable for a one-off whose moment already passed
                await DatabaseManager.set_custom_reminder_active(reminder.id, False)
                confirmation = f"{config.EMOJIS['warning']} המועד שנבחר כבר עבר. נסו שוב עם מועד עתידי."

            await query.edit_message_text(confirmation, parse_mode="HTML", reply_markup=self._back_keyboard())

        except Exception as exc:
            logger.error(f"Failed to create custom reminder: {exc}")
            await query.edit_message_text(config.ERROR_MESSAGES["general"])

    # --- deletion ---

    async def ask_delete(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        reminder_id = int(query.data.rsplit("_", 1)[1])
        reminder = await DatabaseManager.get_custom_reminder_by_id(reminder_id)
        if not reminder:
            await self.show_menu(update, context)
            return

        await query.edit_message_text(
            f"{config.EMOJIS['reminder']} <b>{reminder.text}</b>\n🗓 {describe_reminder(reminder)}\n\nלמחוק את התזכורת?",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("כן, מחק", callback_data=f"cremdel_{reminder_id}_confirm"),
                        InlineKeyboardButton("ביטול", callback_data=f"cremdel_{reminder_id}_cancel"),
                    ]
                ]
            ),
        )

    async def confirm_delete(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        reminder_id = int(query.data.split("_")[1])

        reminder = await DatabaseManager.get_custom_reminder_by_id(reminder_id)
        if reminder:
            # Drop the job first: a deleted row with a live job would fire into nothing
            await medicine_scheduler.cancel_custom_reminder(reminder.user_id, reminder_id)
        await DatabaseManager.delete_custom_reminder(reminder_id)
        await self.show_menu(update, context)

    async def cancel_delete(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.show_menu(update, context)

    # --- keyboards ---

    @staticmethod
    def _repeat_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("📅 פעם אחת", callback_data="crem_rep_once")],
                [InlineKeyboardButton("🔁 כל יום", callback_data="crem_rep_daily")],
                [InlineKeyboardButton("🗓 כל שבוע", callback_data="crem_rep_weekly")],
                [InlineKeyboardButton(f"{config.EMOJIS['back']} ביטול", callback_data="crem_menu")],
            ]
        )

    @staticmethod
    async def _day_keyboard(update: Update) -> InlineKeyboardMarkup:
        """Next seven days, labelled by date in the user's timezone."""
        user = await DatabaseManager.get_user_by_telegram_id(update.effective_user.id)
        tz = get_timezone(get_user_timezone_name(user) if user else config.DEFAULT_TIMEZONE)
        today = now_in_timezone(tz).date()

        rows, row = [], []
        for days_ahead in range(7):
            day = today + timedelta(days=days_ahead)
            if days_ahead == 0:
                label = f"היום {day.strftime('%d/%m')}"
            elif days_ahead == 1:
                label = f"מחר {day.strftime('%d/%m')}"
            else:
                label = f"{WEEKDAY_NAMES[day.weekday()]} {day.strftime('%d/%m')}"
            row.append(InlineKeyboardButton(label, callback_data=f"crem_day_{days_ahead}"))
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)

        rows.append([InlineKeyboardButton(f"{config.EMOJIS['back']} ביטול", callback_data="crem_menu")])
        return InlineKeyboardMarkup(rows)

    @staticmethod
    def _weekday_keyboard() -> InlineKeyboardMarkup:
        rows, row = [], []
        for index, name in enumerate(WEEKDAY_NAMES):
            row.append(InlineKeyboardButton(name, callback_data=f"crem_wd_{index}"))
            if len(row) == 3:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([InlineKeyboardButton(f"{config.EMOJIS['back']} ביטול", callback_data="crem_menu")])
        return InlineKeyboardMarkup(rows)

    @staticmethod
    def _time_keyboard() -> InlineKeyboardMarkup:
        rows, row = [], []
        for hour in range(6, 24):
            row.append(InlineKeyboardButton(f"{hour:02d}:00", callback_data=f"crem_time_{hour:02d}_00"))
            if len(row) == 4:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([InlineKeyboardButton(f"{config.EMOJIS['back']} ביטול", callback_data="crem_menu")])
        return InlineKeyboardMarkup(rows)

    @staticmethod
    def _back_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton(f"{config.EMOJIS['back']} לתזכורות האישיות", callback_data="crem_menu")]]
        )

    # --- helpers ---

    @staticmethod
    def _resolve_datetime(user, days_ahead: int, at: time) -> datetime:
        """Turn 'N days from today at HH:MM' into a naive datetime in the user's timezone.

        Naive on purpose: the column is naive, and the scheduler re-attaches the
        user's timezone when it arms the job.
        """
        tz = get_timezone(get_user_timezone_name(user) if user else config.DEFAULT_TIMEZONE)
        target_date = (now_in_timezone(tz) + timedelta(days=int(days_ahead))).date()
        return datetime.combine(target_date, at)

    @staticmethod
    def _clear_draft(context: ContextTypes.DEFAULT_TYPE):
        context.user_data.pop(AWAITING_TEXT, None)
        context.user_data.pop(DRAFT, None)

    @staticmethod
    async def _reply(update: Update, text: str, **kwargs):
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(text, **kwargs)
        else:
            await update.message.reply_text(text, **kwargs)


custom_reminder_handler = CustomReminderHandler()
