from datetime import datetime
from typing import Dict

from telegram import Update
from telegram.ext import ContextTypes

from config import config
from database import DatabaseManager
from utils.keyboards import (
    get_main_menu_keyboard,
    get_appointments_menu_keyboard,
    get_calendar_keyboard,
    get_time_selection_keyboard,
    get_appointment_reminder_keyboard,
    get_appointments_list_keyboard,
    get_appointment_detail_keyboard,
)
from scheduler import medicine_scheduler


class AppointmentsHandler:
    """Handle appointment creation flow"""

    def __init__(self):
        self.valid_types = {
            "doctor": "רופא",
            "blood": "בדיקת דם",
            "treatment": "טיפול",
            "checkup": "בדיקה",
            "custom": "אחר",
        }

    async def show_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            f"{config.EMOJIS['calendar']} הוספת תור\n\n{config.APPOINTMENTS_HELP}",
            reply_markup=get_appointments_menu_keyboard(),
        )

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data
        ud: Dict = context.user_data.setdefault("appt_state", {})

        if data == "appt_cancel" or data == "time_cancel":
            context.user_data.pop("appt_state", None)
            await query.edit_message_text("בוטל")
            await context.bot.send_message(
                chat_id=query.message.chat_id, text="תפריט ראשי:", reply_markup=get_main_menu_keyboard()
            )
            return

        if data == "appt_back_to_menu":
            context.user_data.pop("appt_state", None)
            await query.edit_message_text(
                f"{config.EMOJIS['calendar']} הוספת תור\n\n{config.APPOINTMENTS_HELP}",
                reply_markup=get_appointments_menu_keyboard(),
            )
            return

        if data == "appt_list":
            user = await DatabaseManager.get_user_by_telegram_id(query.from_user.id)
            items = await DatabaseManager.get_user_appointments(user.id, offset=0, limit=10)
            if not items:
                await query.edit_message_text("אין תורים קרובים", reply_markup=get_appointments_menu_keyboard())
                return
            await query.edit_message_text(
                "התורים הקרובים:", reply_markup=get_appointments_list_keyboard(items, offset=0, page_size=10)
            )
            return

        if data.startswith("appt_page_"):
            offset = int(data.split("_")[2])
            user = await DatabaseManager.get_user_by_telegram_id(query.from_user.id)
            items = await DatabaseManager.get_user_appointments(user.id, offset=offset, limit=10)
            await query.edit_message_text(
                "התורים הקרובים:", reply_markup=get_appointments_list_keyboard(items, offset=offset, page_size=10)
            )
            return

        if data == "appt_pick_month":
            now = datetime.utcnow()
            await query.edit_message_text("בחרו חודש:", reply_markup=get_calendar_keyboard(now.year, now.month))
            ud["pick_month"] = True
            return

        if data.startswith("appt_view_"):
            appt_id = int(data.split("_")[2])
            appt = await DatabaseManager.get_appointment_by_id(appt_id)
            if not appt:
                await query.edit_message_text("התור לא נמצא", reply_markup=get_appointments_menu_keyboard())
                return
            msg = (
                f"{config.EMOJIS['calendar']} תור\n"
                f"כותרת: {appt.title}\n"
                f"סוג: {appt.category}\n"
                f"מתי: {appt.when_at.strftime('%d/%m/%Y %H:%M')}\n"
                f"תזכורות: {'יום לפני' if appt.remind_day_before else ''} {'ו-3 ימים לפני' if appt.remind_3days_before else ''}"
            )
            await query.edit_message_text(msg, reply_markup=get_appointment_detail_keyboard(appt.id))
            return

        if data.startswith("appt_delete_"):
            appt_id = int(data.split("_")[2])
            user = await DatabaseManager.get_user_by_telegram_id(query.from_user.id)
            await medicine_scheduler.cancel_appointment_reminders(user.id, appt_id)
            ok = await DatabaseManager.delete_appointment(appt_id)
            if ok:
                await query.edit_message_text(f"{config.EMOJIS['success']} התור נמחק")
            else:
                await query.edit_message_text(config.ERROR_MESSAGES["general"])
            return

        if data.startswith("appt_edit_time_"):
            appt_id = int(data.split("_")[3])
            ud["edit_appt_id"] = appt_id
            ud["step"] = "edit_time_date"
            now = datetime.utcnow()
            await query.edit_message_text("בחרו תאריך חדש:", reply_markup=get_calendar_keyboard(now.year, now.month))
            return

        if data.startswith("appt_date_") and ud.get("step") == "edit_time_date":
            _, _, y, m, d = data.split("_")
            year, month, day = int(y), int(m), int(d)
            ud["new_date"] = f"{year:04d}-{month:02d}-{day:02d}"
            ud["step"] = "edit_time_time"
            await query.edit_message_text("בחרו שעה חדשה:", reply_markup=get_time_selection_keyboard())
            return

        # handle pick month flow for listing
        if data.startswith("appt_date_") and ud.get("pick_month"):
            _, _, y, m, _ = data.split("_")
            year, month = int(y), int(m)
            from calendar import monthrange

            start = datetime(year, month, 1).date()
            end = datetime(year, month, monthrange(year, month)[1]).date()
            user = await DatabaseManager.get_user_by_telegram_id(query.from_user.id)
            items = await DatabaseManager.get_user_appointments(user.id, start_date=start, end_date=end, offset=0, limit=10)
            ud.pop("pick_month", None)
            await query.edit_message_text(
                f"תורים לחודש {month:02d}/{year}:", reply_markup=get_appointments_list_keyboard(items, offset=0, page_size=10)
            )
            return

        if data.startswith("time_") and ud.get("step") == "edit_time_time":
            parts = data.split("_")
            if len(parts) >= 3 and parts[1].isdigit() and parts[2].isdigit():
                hour = int(parts[1])
                minute = int(parts[2])
                ud["new_time"] = f"{hour:02d}:{minute:02d}"
                appt_id = int(ud.get("edit_appt_id"))
                date_str = ud.get("new_date")
                when = datetime.strptime(f"{date_str} {ud['new_time']}", "%Y-%m-%d %H:%M")
                appt = await DatabaseManager.update_appointment(appt_id, when_at=when)
                user = await DatabaseManager.get_user_by_telegram_id(query.from_user.id)
                await medicine_scheduler.schedule_appointment_reminders(
                    user.id,
                    appt_id,
                    when,
                    appt.remind_day_before,
                    appt.remind_3days_before,
                    user.timezone or config.DEFAULT_TIMEZONE,
                )
                context.user_data.pop("appt_state", None)
                await query.edit_message_text(
                    f"{config.EMOJIS['success']} עודכן התאריך/שעה", reply_markup=get_appointment_detail_keyboard(appt_id)
                )
                return

        if data.startswith("appt_type_"):
            appt_type = data.split("_", 2)[2]
            ud.clear()
            ud["type"] = appt_type
            ud["step"] = "details"
            prompt = {
                "doctor": "הזינו את התמחות הרופא",
                "blood": "הקלידו את סוג בדיקת הדם",
                "treatment": "הקלידו את סוג הטיפול",
                "checkup": "הקלידו את סוג הבדיקה",
                "custom": "הקלידו את נושא התור",
            }.get(appt_type, "הקלידו פרטי תור")
            await query.edit_message_text(prompt)
            return

        if data.startswith("appt_cal_nav_"):
            parts = data.split("_")
            year = int(parts[3])
            month = int(parts[4])
            dirn = parts[5]
            if dirn == "prev":
                month -= 1
                if month == 0:
                    month = 12
                    year -= 1
            else:
                month += 1
                if month == 13:
                    month = 1
                    year += 1
            await query.edit_message_text("בחרו תאריך:", reply_markup=get_calendar_keyboard(year, month))
            return

        if data.startswith("appt_date_"):
            _, _, y, m, d = data.split("_")
            year, month, day = int(y), int(m), int(d)
            ud["date"] = f"{year:04d}-{month:02d}-{day:02d}"
            ud["step"] = "time"
            await query.edit_message_text("בחרו שעה לְתור או הזינו בפורמט HH:MM:", reply_markup=get_time_selection_keyboard())
            return

        if data == "time_custom":
            ud["awaiting_time_text"] = True
            await query.edit_message_text("הקלידו שעה בפורמט HH:MM (למשל 09:30)")
            return

        if data.startswith("time_"):
            parts = data.split("_")
            if len(parts) >= 3 and parts[1].isdigit() and parts[2].isdigit():
                hour = int(parts[1])
                minute = int(parts[2])
                ud["time"] = f"{hour:02d}:{minute:02d}"
                ud["step"] = "reminders"
                # Defaults: all off until user selects
                rem1 = False
                rem3 = False
                rem0 = False
                ud["rem1"] = rem1
                ud["rem3"] = rem3
                ud["rem0"] = rem0
                await query.edit_message_text(
                    "בחרו תזכורות ללפני התור ו/או ביום התור (לחיצה על הכפתור מפעילה/מכבה)",
                    reply_markup=get_appointment_reminder_keyboard(rem1, rem3, rem0),
                )
                return

        if data == "appt_rem1_toggle":
            ud["rem1"] = not bool(ud.get("rem1", False))
            await query.edit_message_reply_markup(
                reply_markup=get_appointment_reminder_keyboard(
                    ud.get("rem1", False), ud.get("rem3", False), ud.get("rem0", False)
                )
            )
            return

        if data == "appt_rem3_toggle":
            ud["rem3"] = not bool(ud.get("rem3", False))
            await query.edit_message_reply_markup(
                reply_markup=get_appointment_reminder_keyboard(
                    ud.get("rem1", False), ud.get("rem3", False), ud.get("rem0", False)
                )
            )
            return

        if data == "appt_rem0_toggle":
            ud["rem0"] = not bool(ud.get("rem0", False))
            await query.edit_message_reply_markup(
                reply_markup=get_appointment_reminder_keyboard(
                    ud.get("rem1", False), ud.get("rem3", False), ud.get("rem0", False)
                )
            )
            return

        if data == "appt_rem0_time":
            ud["awaiting_same_day_time"] = True
            await query.edit_message_text("הקלידו שעה ליום התור בפורמט HH:MM (למשל 08:00)")
            return

        if data == "appt_back":
            # Go back to time selection
            ud["step"] = "time"
            await query.edit_message_text("בחרו שעה לְתור או הזינו בפורמט HH:MM:", reply_markup=get_time_selection_keyboard())
            return

        if data == "appt_save":
            # Validate and save
            user = await DatabaseManager.get_user_by_telegram_id(query.from_user.id)
            if not user:
                await query.edit_message_text("נדרש /start קודם")
                return
            try:
                appt_type = ud.get("type", "custom")
                title = ud.get("title", "תור")
                date_str = ud.get("date")
                time_str = ud.get("time", "09:00")
                rem1 = bool(ud.get("rem1", False))
                rem3 = bool(ud.get("rem3", False))
                rem0 = bool(ud.get("rem0", False))
                if not date_str or not time_str:
                    await query.edit_message_text("אנא בחרו תאריך ושעה")
                    return
                # Validate time string strictly
                try:
                    when = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
                except Exception:
                    await query.edit_message_text("אנא בחרו שעה תקינה לתור")
                    return
                appt = await DatabaseManager.create_appointment(
                    user_id=user.id,
                    category=appt_type,
                    title=title,
                    when_at=when,
                    remind_day_before=rem1,
                    remind_3days_before=rem3,
                    remind_same_day=rem0,
                    same_day_reminder_time=(
                        datetime.strptime(
                            ud.get("rem0_time", f"{config.APPOINTMENT_SAME_DAY_REMINDER_HOUR:02d}:00"), "%H:%M"
                        ).time()
                        if rem0
                        else None
                    ),
                )
                # Schedule reminders
                await medicine_scheduler.schedule_appointment_reminders(
                    user.id, appt.id, when, rem1, rem3, user.timezone or config.DEFAULT_TIMEZONE, same_day=rem0
                )
                context.user_data.pop("appt_state", None)
                await query.edit_message_text(f"{config.EMOJIS['success']} התור נשמר!")
                await context.bot.send_message(
                    chat_id=query.message.chat_id, text="תפריט ראשי:", reply_markup=get_main_menu_keyboard()
                )
                return
            except Exception:
                await query.edit_message_text(config.ERROR_MESSAGES["general"])
                return

        # Default: ignore
        await query.edit_message_text(config.ERROR_MESSAGES["general"])

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = (update.message.text or "").strip()
        ud: Dict = context.user_data.setdefault("appt_state", {})
        if ud.get("step") == "details":
            ud["title"] = text
            ud["step"] = "date"
            # Show calendar starting current month
            now = datetime.utcnow()
            await update.message.reply_text("בחרו תאריך:", reply_markup=get_calendar_keyboard(now.year, now.month))
            return
        if ud.get("awaiting_time_text"):
            ud.pop("awaiting_time_text", None)
            # Validate HH:MM
            try:
                h, m = text.split(":")
                hour = int(h)
                minute = int(m)
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValueError()
                ud["time"] = f"{hour:02d}:{minute:02d}"
                ud["step"] = "reminders"
                # Defaults: all off until user selects
                rem1 = False
                rem3 = False
                ud["rem1"] = rem1
                ud["rem3"] = rem3
                await update.message.reply_text(
                    "בחרו תזכורות ללפני התור ו/או ביום התור (לחיצה על הכפתור מפעילה/מכבה)",
                    reply_markup=get_appointment_reminder_keyboard(rem1, rem3, False),
                )
                return
            except Exception:
                await update.message.reply_text("פורמט שגוי. הזינו שעה כמו 09:30")
                return

        if ud.get("awaiting_same_day_time"):
            ud.pop("awaiting_same_day_time", None)
            try:
                h, m = text.split(":")
                hour = int(h)
                minute = int(m)
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValueError()
                ud["rem0_time"] = f"{hour:02d}:{minute:02d}"
                await update.message.reply_text(
                    f"נקבעה שעה {ud['rem0_time']} לתזכורת ביום התור",
                    reply_markup=get_appointment_reminder_keyboard(
                        ud.get("rem1", False), ud.get("rem3", False), ud.get("rem0", False)
                    ),
                )
                return
            except Exception:
                await update.message.reply_text("פורמט שגוי. הזינו שעה כמו 08:00")
                return


appointments_handler = AppointmentsHandler()
