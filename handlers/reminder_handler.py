"""
Reminder Handler
Handles all reminder-related operations: dose confirmations, snoozing, missed doses
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, CommandHandler

from config import config
from database import DatabaseManager, DoseLog
from scheduler import medicine_scheduler
from utils.keyboards import get_reminder_keyboard, get_main_menu_keyboard, get_confirmation_keyboard, get_cancel_keyboard

logger = logging.getLogger(__name__)


class ReminderHandler:
    """Handler for all reminder-related operations"""

    def __init__(self):
        self.pending_confirmations: Dict[int, Dict] = {}

    def get_handlers(self) -> List:
        """Get all reminder-related handlers"""
        return [
            # Dose confirmation handlers
            CallbackQueryHandler(self.handle_dose_taken, pattern="^dose_taken_"),
            CallbackQueryHandler(self.handle_dose_snooze, pattern="^dose_snooze_"),
            CallbackQueryHandler(self.handle_dose_skip, pattern="^dose_skip_"),
            # Command handlers
            CommandHandler("snooze", self.snooze_latest_reminder),
            CommandHandler("next_reminders", self.show_next_reminders),
            CommandHandler("missed_doses", self.show_missed_doses),
            # Confirmation handlers
            CallbackQueryHandler(self.confirm_dose_skip, pattern="^skip_.*_confirm$"),
            CallbackQueryHandler(self.cancel_dose_skip, pattern="^skip_.*_cancel$"),
            # Quick symptoms logging tied to a medicine
            CallbackQueryHandler(self.handle_quick_symptoms, pattern="^symptoms_quick_"),
        ]

    async def handle_dose_taken(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle dose taken confirmation"""
        try:
            query = update.callback_query
            await query.answer()

            # Parse medicine ID from callback data
            medicine_id = int(query.data.split("_")[2])
            user_id = query.from_user.id

            # Get medicine and user info
            medicine = await DatabaseManager.get_medicine_by_id(medicine_id)
            user = await DatabaseManager.get_user_by_telegram_id(user_id)

            if not medicine or not user:
                await query.edit_message_text(f"{config.EMOJIS['error']} התרופה או המשתמש לא נמצא")
                return

            # Verify user owns this medicine
            if medicine.user_id != user.id:
                await query.edit_message_text(f"{config.EMOJIS['error']} אין לכם הרשאה לתרופה זו")
                return

            # Log dose as taken
            now = datetime.now()
            dose_log = await DatabaseManager.log_dose_taken(medicine_id=medicine_id, scheduled_time=now, taken_at=now)

            # Update inventory (reduce by 1)
            if medicine.inventory_count > 0:
                new_count = medicine.inventory_count - 1
                await DatabaseManager.update_inventory(medicine_id, new_count)

                # Check for low stock
                low_stock_warning = ""
                if new_count <= medicine.low_stock_threshold:
                    low_stock_warning = (
                        f"\n\n{config.EMOJIS['warning']} <b>מלאי נמוך!</b>\nנותרו {new_count} כדורים. כדאי להזמין עוד."
                    )

            else:
                new_count = 0
                low_stock_warning = f"\n\n{config.EMOJIS['error']} <b>המלאי אפס!</b> אנא עדכנו את המלאי."

            # Reset reminder attempts for this medicine
            reminder_key = f"{user_id}_{medicine_id}"
            if reminder_key in medicine_scheduler.reminder_attempts:
                medicine_scheduler.reminder_attempts[reminder_key] = 0

            # Create success message
            message = f"""
{config.EMOJIS['success']} <b>מעולה! נטילת התרופה אושרה</b>

{config.EMOJIS['medicine']} <b>{medicine.name}</b>
💊 מינון: {medicine.dosage}
⏰ זמן נטילה: {now.strftime('%H:%M')}
📦 מלאי נותר: {new_count} כדורים{low_stock_warning}

{config.EMOJIS['info']} התרופה תירשם ביומן הטיפולים שלכם.
            """

            # Send confirmation to caregivers if any
            await self._notify_caregivers_dose_taken(user_id, medicine, now)

            await query.edit_message_text(message, parse_mode="HTML", reply_markup=self._get_post_dose_keyboard(medicine_id))

            logger.info(f"User {user_id} confirmed taking medicine {medicine_id}")

        except Exception as e:
            logger.error(f"Error handling dose taken: {e}")
            await query.edit_message_text(f"{config.EMOJIS['error']} שגיאה באישור נטילת התרופה")

    async def handle_dose_snooze(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle dose snooze request"""
        try:
            query = update.callback_query
            await query.answer()

            medicine_id = int(query.data.split("_")[2])
            user_id = query.from_user.id

            # Get medicine info
            medicine = await DatabaseManager.get_medicine_by_id(medicine_id)
            if not medicine:
                await query.edit_message_text(f"{config.EMOJIS['error']} התרופה לא נמצאה")
                return

            # Schedule snooze reminder
            job_id = await medicine_scheduler.schedule_snooze_reminder(
                user_id=user_id, medicine_id=medicine_id, snooze_minutes=config.REMINDER_SNOOZE_MINUTES
            )

            snooze_time = datetime.now() + timedelta(minutes=config.REMINDER_SNOOZE_MINUTES)

            message = f"""
{config.EMOJIS['clock']} <b>תזכורת נדחתה</b>

{config.EMOJIS['medicine']} <b>{medicine.name}</b>
💊 מינון: {medicine.dosage}

⏰ תזכורת חוזרת: {snooze_time.strftime('%H:%M')}
({config.REMINDER_SNOOZE_MINUTES} דקות)

{config.EMOJIS['info']} תקבלו תזכורת נוספת בזמן שנקבע.
            """

            await query.edit_message_text(message, parse_mode="HTML", reply_markup=self._get_snooze_keyboard(medicine_id))

            logger.info(f"User {user_id} snoozed medicine {medicine_id} for {config.REMINDER_SNOOZE_MINUTES} minutes")

        except Exception as e:
            logger.error(f"Error handling dose snooze: {e}")
            await query.edit_message_text(f"{config.EMOJIS['error']} שגיאה בדחיית התזכורת")

    async def handle_dose_skip(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle dose skip request with confirmation"""
        try:
            query = update.callback_query
            await query.answer()

            medicine_id = int(query.data.split("_")[2])
            medicine = await DatabaseManager.get_medicine_by_id(medicine_id)

            if not medicine:
                await query.edit_message_text(f"{config.EMOJIS['error']} התרופה לא נמצאה")
                return

            message = f"""
{config.EMOJIS['warning']} <b>אישור דילוג על תרופה</b>

{config.EMOJIS['medicine']} <b>{medicine.name}</b>
💊 מינון: {medicine.dosage}

האם אתם בטוחים שברצונכם לדלג על התרופה?

⚠️ דילוג על תרופות עלול להשפיע על הטיפול
            """

            await query.edit_message_text(
                message, parse_mode="HTML", reply_markup=get_confirmation_keyboard("skip", medicine_id)
            )

        except Exception as e:
            logger.error(f"Error handling dose skip: {e}")
            await query.edit_message_text(f"{config.EMOJIS['error']} שגיאה בטיפול בדילוג")

    async def confirm_dose_skip(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Confirm dose skip and log it"""
        try:
            query = update.callback_query
            await query.answer()

            # Parse medicine ID from callback data
            data_parts = query.data.split("_")
            medicine_id = int(data_parts[1])
            user_id = query.from_user.id

            # Get medicine and user info
            medicine = await DatabaseManager.get_medicine_by_id(medicine_id)
            user = await DatabaseManager.get_user_by_telegram_id(user_id)

            if not medicine or not user:
                await query.edit_message_text(f"{config.EMOJIS['error']} התרופה או המשתמש לא נמצא")
                return

            # Verify user owns this medicine
            if medicine.user_id != user.id:
                await query.edit_message_text(f"{config.EMOJIS['error']} אין לכם הרשאה לתרופה זו")
                return

            # Log dose as skipped
            now = datetime.now()
            await DatabaseManager.log_dose_skipped(medicine_id=medicine_id, scheduled_time=now)

            # Reset reminder attempts
            reminder_key = f"{user_id}_{medicine_id}"
            if reminder_key in medicine_scheduler.reminder_attempts:
                medicine_scheduler.reminder_attempts[reminder_key] = 0

            # Notify caregivers
            await self._notify_caregivers_dose_skipped(user_id, medicine, now)

            message = f"""
{config.EMOJIS['info']} <b>תרופה דולגה</b>

{config.EMOJIS['medicine']} <b>{medicine.name}</b>
💊 מינון: {medicine.dosage}
⏰ זמן: {now.strftime('%H:%M')}

הדילוג נרשם ביומן הטיפולים.

{config.EMOJIS['warning']} אנא התייעצו עם הרופא לגבי דילוג על תרופות.
            """

            await query.edit_message_text(message, parse_mode="HTML")
            await context.bot.send_message(
                chat_id=update.effective_chat.id, text="תפריט ראשי:", reply_markup=get_main_menu_keyboard()
            )

            logger.info(f"User {user_id} skipped medicine {medicine_id}")

        except Exception as e:
            logger.error(f"Error confirming dose skip: {e}")
            await query.edit_message_text(f"{config.EMOJIS['error']} שגיאה באישור הדילוג")

    async def cancel_dose_skip(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel dose skip and return to reminder"""
        try:
            query = update.callback_query
            await query.answer()

            data_parts = query.data.split("_")
            medicine_id = int(data_parts[1])

            medicine = await DatabaseManager.get_medicine_by_id(medicine_id)
            if not medicine:
                await query.edit_message_text(f"{config.EMOJIS['error']} התרופה לא נמצאה")
                return

            # Return to original reminder
            message = f"""
{config.EMOJIS['reminder']} <b>זמן לקחת תרופה!</b>

{config.EMOJIS['medicine']} <b>{medicine.name}</b>
💊 מינון: {medicine.dosage}

{config.EMOJIS['inventory']} מלאי נותר: {medicine.inventory_count} כדורים
            """

            if medicine.inventory_count <= medicine.low_stock_threshold:
                message += f"\n{config.EMOJIS['warning']} <b>מלאי נמוך! כדאי להזמין עוד</b>"

            await query.edit_message_text(message, parse_mode="HTML", reply_markup=get_reminder_keyboard(medicine_id))

        except Exception as e:
            logger.error(f"Error canceling dose skip: {e}")
            await query.edit_message_text(f"{config.EMOJIS['error']} שגיאה בביטול הדילוג")

    async def snooze_latest_reminder(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Snooze the latest reminder (command handler)"""
        try:
            user_id = update.effective_user.id

            # Get latest pending reminder for this user
            latest_reminder = await self._get_latest_pending_reminder(user_id)

            if not latest_reminder:
                await update.message.reply_text(
                    f"{config.EMOJIS['info']} אין תזכורות פעילות לדחייה", reply_markup=get_main_menu_keyboard()
                )
                return

            # Schedule snooze
            job_id = await medicine_scheduler.schedule_snooze_reminder(
                user_id=user_id, medicine_id=latest_reminder["medicine_id"], snooze_minutes=config.REMINDER_SNOOZE_MINUTES
            )

            snooze_time = datetime.now() + timedelta(minutes=config.REMINDER_SNOOZE_MINUTES)

            message = f"""
{config.EMOJIS['clock']} <b>התזכורת האחרונה נדחתה</b>

{config.EMOJIS['medicine']} {latest_reminder['medicine_name']}
⏰ תזכורת חוזרת: {snooze_time.strftime('%H:%M')}
            """

            await update.message.reply_text(message, parse_mode="Markdown", reply_markup=get_main_menu_keyboard())

        except Exception as e:
            logger.error(f"Error in snooze command: {e}")
            await update.message.reply_text(f"{config.EMOJIS['error']} שגיאה בדחיית התזכורת")

    async def show_next_reminders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show next scheduled reminders"""
        try:
            user_id = update.effective_user.id

            # Get scheduled jobs for this user
            jobs = medicine_scheduler.get_scheduled_jobs(user_id)

            if not jobs:
                message = f"""
{config.EMOJIS['info']} **אין תזכורות מתוזמנות**

הוסיפו שעה לנטילת תרופה קיימת.
                """
                from telegram import InlineKeyboardMarkup, InlineKeyboardButton

                # Build quick actions
                user = await DatabaseManager.get_user_by_telegram_id(user_id)
                meds = await DatabaseManager.get_user_medicines(user.id) if user else []
                rows = []
                if meds:
                    rows.append([InlineKeyboardButton("הוסף שעה לתרופה", callback_data="rem_pick_medicine_for_time")])
                rows.append(
                    [InlineKeyboardButton(f"{config.EMOJIS['reminder']} הגדרות תזכורות", callback_data="settings_reminders")]
                )
                rows.append([InlineKeyboardButton(f"{config.EMOJIS['back']} חזור", callback_data="main_menu")])
                kb = InlineKeyboardMarkup(rows)
            else:
                message = f"{config.EMOJIS['clock']} **התזכורות הבאות:**\n\n"
                from telegram import InlineKeyboardMarkup, InlineKeyboardButton

                kb_rows = []
                # Sort jobs by next run time
                sorted_jobs = sorted([job for job in jobs if job["next_run"]], key=lambda x: x["next_run"])
                shown = 0
                for job in sorted_jobs:
                    if shown >= 6:
                        break
                    next_run = job["next_run"]
                    time_str = next_run.strftime("%H:%M")
                    date_str = next_run.strftime("%d/%m")
                    medicine_id = job.get("medicine_id") or 0
                    medicine_name = job["name"].split(" for user ")[0].replace("Medicine reminder", "").strip()
                    if next_run.date() == datetime.now().date():
                        message += f"⏰ **היום {time_str}** - {medicine_name}\n"
                    else:
                        message += f"📅 **{date_str} {time_str}** - {medicine_name}\n"
                    if medicine_id:
                        kb_rows.append(
                            [
                                InlineKeyboardButton("שנה שעה", callback_data=f"rem_edit_{medicine_id}"),
                                InlineKeyboardButton("בטל תזכורת", callback_data=f"rem_disable_{medicine_id}"),
                            ]
                        )
                    shown += 1
                if len(jobs) > shown:
                    message += f"\n{config.EMOJIS['info']} ועוד {len(jobs) - shown} תזכורות..."
                kb_rows.append([InlineKeyboardButton(f"{config.EMOJIS['back']} חזור לתפריט", callback_data="main_menu")])
                kb = InlineKeyboardMarkup(kb_rows)
            await update.message.reply_text(message, parse_mode="Markdown", reply_markup=kb)

        except Exception as e:
            logger.error(f"Error showing next reminders: {e}")
            await update.message.reply_text(f"{config.EMOJIS['error']} שגיאה בהצגת התזכורות")

    async def show_missed_doses(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show missed doses from the last 7 days"""
        try:
            user_id = update.effective_user.id
            user = await DatabaseManager.get_user_by_telegram_id(user_id)

            if not user:
                await update.message.reply_text(f"{config.EMOJIS['error']} משתמש לא נמצא")
                return

            # Get missed doses from last 7 days
            missed_doses = await DatabaseManager.get_missed_doses(user.id, days=7)

            if not missed_doses:
                message = f"""
{config.EMOJIS['success']} **מעולה! אין תרופות שדולגו**

בשבוע האחרון לקחתם את כל התרופות בזמן.
                """
            else:
                message = f"{config.EMOJIS['warning']} **תרופות שדולגו בשבוע האחרון:**\n\n"

                for dose in missed_doses[-10:]:  # Show last 10 missed doses
                    medicine = await DatabaseManager.get_medicine_by_id(dose.medicine_id)
                    if medicine:
                        date_str = dose.scheduled_time.strftime("%d/%m")
                        time_str = dose.scheduled_time.strftime("%H:%M")
                        status_emoji = config.EMOJIS["error"] if dose.status == "missed" else config.EMOJIS["info"]

                        message += f"{status_emoji} **{medicine.name}**\n"
                        message += f"   📅 {date_str} בשעה {time_str}\n"
                        message += f"   סטטוס: {'לא נלקח' if dose.status == 'missed' else 'דולג'}\n\n"

                if len(missed_doses) > 10:
                    message += f"{config.EMOJIS['info']} ועוד {len(missed_doses) - 10} תרופות שדולגו..."

                message += f"\n{config.EMOJIS['doctor']} מומלץ להתייעץ עם הרופא על דילוגים."

            await update.message.reply_text(message, parse_mode="HTML", reply_markup=get_main_menu_keyboard())

        except Exception as e:
            logger.error(f"Error showing missed doses: {e}")
            await update.message.reply_text(f"{config.EMOJIS['error']} שגיאה בהצגת התרופות שדולגו")

    def _get_post_dose_keyboard(self, medicine_id: int) -> InlineKeyboardMarkup:
        """Get keyboard shown after dose confirmation"""
        keyboard = [
            [
                InlineKeyboardButton(
                    f"{config.EMOJIS['symptoms']} רשום תופעות לוואי", callback_data=f"symptoms_quick_{medicine_id}"
                )
            ],
            [InlineKeyboardButton(f"{config.EMOJIS['medicine']} פרטי התרופה", callback_data=f"medicine_view_{medicine_id}")],
            [InlineKeyboardButton(f"{config.EMOJIS['home']} תפריט ראשי", callback_data="main_menu")],
        ]

        return InlineKeyboardMarkup(keyboard)

    def _get_snooze_keyboard(self, medicine_id: int) -> InlineKeyboardMarkup:
        """Get keyboard shown after snoozing"""
        keyboard = [
            [InlineKeyboardButton(f"{config.EMOJIS['success']} לקחתי עכשיו", callback_data=f"dose_taken_{medicine_id}")],
            [InlineKeyboardButton(f"{config.EMOJIS['clock']} דחה שוב", callback_data=f"dose_snooze_{medicine_id}")],
            [InlineKeyboardButton(f"{config.EMOJIS['home']} תפריט ראשי", callback_data="main_menu")],
        ]

        return InlineKeyboardMarkup(keyboard)

    async def _get_latest_pending_reminder(self, user_id: int) -> Optional[Dict]:
        """Get the latest pending reminder for a user"""
        try:
            # Get user's active medicines
            user = await DatabaseManager.get_user_by_telegram_id(user_id)
            if not user:
                return None

            medicines = await DatabaseManager.get_user_medicines(user.id)

            # Find latest scheduled reminder
            latest_reminder = None
            latest_time = None

            for medicine in medicines:
                schedules = await DatabaseManager.get_medicine_schedules(medicine.id)
                for schedule in schedules:
                    # Check if there's a recent dose log for this schedule
                    recent_doses = await DatabaseManager.get_recent_doses(medicine.id, hours=1)

                    # If no recent dose, this might be a pending reminder
                    if not recent_doses:
                        schedule_time = datetime.combine(datetime.now().date(), schedule.time_to_take)

                        if not latest_time or schedule_time > latest_time:
                            latest_time = schedule_time
                            latest_reminder = {
                                "medicine_id": medicine.id,
                                "medicine_name": medicine.name,
                                "scheduled_time": schedule_time,
                            }

            return latest_reminder

        except Exception as e:
            logger.error(f"Error getting latest pending reminder: {e}")
            return None

    async def handle_quick_symptoms(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Prompt user to log side-effects for a specific medicine."""
        try:
            query = update.callback_query
            await query.answer()
            parts = (query.data or "").split("_")
            medicine_id = int(parts[-1]) if parts and parts[-1].isdigit() else None
            if not medicine_id:
                await query.edit_message_text(f"{config.EMOJIS['error']} התרופה לא נמצאה")
                await context.bot.send_message(
                    chat_id=update.effective_chat.id, text="תפריט ראשי:", reply_markup=get_main_menu_keyboard()
                )
                return
            med = await DatabaseManager.get_medicine_by_id(medicine_id)
            if not med:
                await query.edit_message_text(f"{config.EMOJIS['error']} התרופה לא נמצאה")
                await context.bot.send_message(
                    chat_id=update.effective_chat.id, text="תפריט ראשי:", reply_markup=get_main_menu_keyboard()
                )
                return
            # Set context to capture next text as symptoms for this medicine (store name in prefix)
            context.user_data["awaiting_symptom_text"] = True
            context.user_data["symptoms_for_medicine"] = medicine_id
            await query.edit_message_text(f"{config.EMOJIS['symptoms']} רשמו תופעות לוואי עבור {med.name}:")
        except Exception as e:
            logger.error(f"Error in handle_quick_symptoms: {e}")
            try:
                await update.callback_query.edit_message_text(config.ERROR_MESSAGES["general"])
            except Exception:
                pass

    async def _notify_caregivers_dose_taken(self, user_id: int, medicine, taken_at: datetime):
        """Notify caregivers that dose was taken"""
        try:
            caregivers = await DatabaseManager.get_user_caregivers(user_id, active_only=True)
            user = await DatabaseManager.get_user_by_id(user_id)

            if not caregivers or not user:
                return

            message = f"""
{config.EMOJIS['success']} **תרופה נלקחה**

{config.EMOJIS['medicine']} **תרופה:** {medicine.name}
{config.EMOJIS['clock']} **שעה:** {taken_at.strftime('%H:%M')}
            """

            # Send to caregivers who have permission to receive updates
            for caregiver in caregivers:
                if (
                    ("view" in caregiver.permissions or "manage" in caregiver.permissions)
                    and caregiver.caregiver_telegram_id
                    and caregiver.caregiver_telegram_id > 0
                ):
                    try:
                        await medicine_scheduler.bot.send_message(
                            chat_id=caregiver.caregiver_telegram_id, text=message, parse_mode="Markdown"
                        )
                    except Exception as e:
                        logger.error(f"Failed to notify caregiver {caregiver.id}: {e}")
        except Exception as e:
            logger.error(f"Error notifying caregivers about dose taken: {e}")

    async def _notify_caregivers_dose_skipped(self, user_id: int, medicine, skipped_at: datetime):
        """Notify caregivers that dose was skipped"""
        try:
            caregivers = await DatabaseManager.get_user_caregivers(user_id, active_only=True)
            user = await DatabaseManager.get_user_by_id(user_id)

            if not caregivers or not user:
                return

            message = f"""
{config.EMOJIS['warning']} **תרופה דולגה**

{config.EMOJIS['medicine']} **תרופה:** {medicine.name}
{config.EMOJIS['clock']} **שעה:** {skipped_at.strftime('%H:%M')}
⚠️ **המטופל בחר לדלג על התרופה**
            """

            # Send to caregivers who have permission to receive updates
            for caregiver in caregivers:
                if (
                    ("view" in caregiver.permissions or "manage" in caregiver.permissions)
                    and caregiver.caregiver_telegram_id
                    and caregiver.caregiver_telegram_id > 0
                ):
                    try:
                        await medicine_scheduler.bot.send_message(
                            chat_id=caregiver.caregiver_telegram_id, text=message, parse_mode="Markdown"
                        )
                    except Exception as e:
                        logger.error(f"Failed to notify caregiver {caregiver.id}: {e}")
        except Exception as e:
            logger.error(f"Error notifying caregivers about dose skipped: {e}")


# Global instance
reminder_handler = ReminderHandler()
