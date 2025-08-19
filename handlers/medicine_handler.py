"""
Medicine Management Handler
Handles all medicine-related operations: add, edit, view, schedule, inventory
"""

import logging
import re
from datetime import time, datetime
from typing import Dict, List
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters

from config import config
from database import DatabaseManager, Medicine, MedicineSchedule
from scheduler import medicine_scheduler
from utils.keyboards import (
    get_medicine_detail_keyboard,
    get_time_selection_keyboard,
    get_cancel_keyboard,
    get_main_menu_keyboard,
)


logger = logging.getLogger(__name__)

# Conversation states
MEDICINE_NAME, MEDICINE_DOSAGE, MEDICINE_SCHEDULE, MEDICINE_INVENTORY = range(4)
EDIT_NAME, EDIT_DOSAGE, EDIT_SCHEDULE, EDIT_INVENTORY = range(4, 8)
CUSTOM_TIME_INPUT, CUSTOM_INVENTORY_INPUT = range(8, 10)


class MedicineHandler:
    """Handler for all medicine-related operations"""

    def __init__(self):
        self.user_medicine_data: Dict[int, Dict] = {}

    def get_conversation_handler(self) -> ConversationHandler:
        """Get the conversation handler for medicine management"""
        return ConversationHandler(
            entry_points=[
                CommandHandler("add_medicine", self.start_add_medicine),
                CallbackQueryHandler(self.start_add_medicine, pattern="^medicine_add$"),
                CallbackQueryHandler(self.view_medicine, pattern="^medicine_view_"),
                CallbackQueryHandler(self.edit_medicine, pattern="^medicine_edit_"),
                # Inventory per-medicine actions (only those with an ID)
                CallbackQueryHandler(self.handle_inventory_update, pattern=r"^inventory_\d+_"),
            ],
            states={
                MEDICINE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_medicine_name)],
                MEDICINE_DOSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_medicine_dosage)],
                MEDICINE_SCHEDULE: [
                    CallbackQueryHandler(self.cancel_operation, pattern="^time_cancel$"),
                    CallbackQueryHandler(self.handle_time_selection, pattern="^time_"),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_custom_time),
                ],
                MEDICINE_INVENTORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_medicine_inventory)],
                CUSTOM_TIME_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_custom_time)],
                CUSTOM_INVENTORY_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_custom_inventory)],
                # Always-on callbacks inside this conversation
                0: [
                    CallbackQueryHandler(self.handle_edit_callbacks, pattern=r"^(mededit_|medicine_schedule_)"),
                ],
                # Edit flows
                EDIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_edit_text)],
                EDIT_DOSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_edit_text)],
                EDIT_INVENTORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_edit_text)],
                EDIT_SCHEDULE: [
                    CallbackQueryHandler(self.handle_schedule_edit, pattern=r"^(time_|time_custom|sched_save_)"),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_edit_text),
                ],
            },
            fallbacks=[
                CommandHandler("cancel", self.cancel_operation),
                CallbackQueryHandler(self.cancel_operation, pattern="^cancel$"),
                CallbackQueryHandler(self.cancel_operation, pattern="^time_cancel$"),
            ],
        )

    async def start_add_medicine(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.effective_user.id
            self.user_medicine_data[user_id] = {"step": "name", "medicine_data": {}}
            message = f"""
{config.EMOJIS['medicine']} <b>הוספת תרופה חדשה</b>

🔹 <b>שלב 1/3:</b> שם התרופה

אנא שלחו את שם התרופה:
(לדוגמה: אקמול, ויטמין D, לבופה וכו')
            """
            if update.callback_query:
                await update.callback_query.answer()
                await update.callback_query.edit_message_text(message, parse_mode="HTML", reply_markup=get_cancel_keyboard())
            else:
                await update.message.reply_text(message, parse_mode="HTML", reply_markup=get_cancel_keyboard())
            return MEDICINE_NAME
        except Exception as e:
            logger.error(f"Error starting add medicine: {e}")
            await self._send_error_message(update, "שגיאה בתחילת הוספת התרופה")
            return ConversationHandler.END

    async def get_medicine_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.effective_user.id
            medicine_name = update.message.text.strip()
            if len(medicine_name) < 2:
                await update.message.reply_text(f"{config.EMOJIS['error']} שם התרופה קצר מדי. אנא הזינו שם בן לפחות 2 תווים.")
                return MEDICINE_NAME
            if len(medicine_name) > 200:
                await update.message.reply_text(f"{config.EMOJIS['error']} שם התרופה ארוך מדי. אנא הזינו שם קצר יותר.")
                return MEDICINE_NAME
            user = await DatabaseManager.get_user_by_telegram_id(user_id)
            existing_medicines = await DatabaseManager.get_user_medicines(user.id, active_only=False)
            for med in existing_medicines:
                if med.name.lower() == medicine_name.lower():
                    await update.message.reply_text(
                        f"{config.EMOJIS['warning']} תרופה בשם זה כבר קיימת. אנא בחרו שם אחר או עדכנו את התרופה הקיימת."
                    )
                    return MEDICINE_NAME
            self.user_medicine_data[user_id]["medicine_data"]["name"] = medicine_name
            message = f"""
{config.EMOJIS['medicine']} <b>הוספת תרופה: {medicine_name}</b>

🔹 <b>שלב 2/3:</b> מינון

אנא הזינו את המינון:
(לדוגמה: 500 מ"ג, 1 כדור, כפית, 2 טיפות וכו')
            """
            await update.message.reply_text(message, parse_mode="HTML", reply_markup=get_cancel_keyboard())
            return MEDICINE_DOSAGE
        except Exception as e:
            logger.error(f"Error getting medicine name: {e}")
            await self._send_error_message(update, "שגיאה בקבלת שם התרופה")
            return ConversationHandler.END

    async def get_medicine_dosage(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.effective_user.id
            dosage = update.message.text.strip()
            if len(dosage) < 1:
                await update.message.reply_text(f"{config.EMOJIS['error']} אנא הזינו מינון.")
                return MEDICINE_DOSAGE
            if len(dosage) > 100:
                await update.message.reply_text(f"{config.EMOJIS['error']} המינון ארוך מדי. אנא הזינו מינון קצר יותר.")
                return MEDICINE_DOSAGE
            self.user_medicine_data[user_id]["medicine_data"]["dosage"] = dosage
            medicine_name = self.user_medicine_data[user_id]["medicine_data"]["name"]
            message = f"""
{config.EMOJIS['medicine']} <b>הוספת תרופה: {medicine_name}</b>
⚖️ <b>מינון:</b> {dosage}

🔹 <b>שלב 3/3:</b> שעות נטילה

בחרו את השעה הראשונה לנטילת התרופה:
(תוכלו להוסיף שעות נוספות אחר כך)
            """
            await update.message.reply_text(message, parse_mode="HTML", reply_markup=get_time_selection_keyboard())
            return MEDICINE_SCHEDULE
        except Exception as e:
            logger.error(f"Error getting medicine dosage: {e}")
            await self._send_error_message(update, "שגיאה בקבלת המינון")
            return ConversationHandler.END

    async def handle_time_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            query = update.callback_query
            await query.answer()
            user_id = update.effective_user.id
            data = query.data
            if data == "time_custom":
                message = f"""
{config.EMOJIS['clock']} <b>הזנת שעה מותאמת אישית</b>

אנא הזינו שעה בפורמט HH:MM
(לדוגמה: 08:30, 14:15, 21:00)
                """
                await query.edit_message_text(message, parse_mode="HTML", reply_markup=get_cancel_keyboard())
                return CUSTOM_TIME_INPUT
            elif data.startswith("time_"):
                time_parts = data.replace("time_", "").split("_")
                hour = int(time_parts[0])
                minute = int(time_parts[1])
                selected_time = time(hour, minute)
                if "schedules" not in self.user_medicine_data[user_id]["medicine_data"]:
                    self.user_medicine_data[user_id]["medicine_data"]["schedules"] = []
                self.user_medicine_data[user_id]["medicine_data"]["schedules"].append(selected_time)
                medicine_name = self.user_medicine_data[user_id]["medicine_data"]["name"]
                dosage = self.user_medicine_data[user_id]["medicine_data"]["dosage"]
                self.user_medicine_data[user_id]["medicine_data"]["inventory_count"] = 0.0
                success = await self._create_medicine_in_db(user_id)
                if success:
                    schedules_text = ", ".join(
                        [t.strftime("%H:%M") for t in self.user_medicine_data[user_id]["medicine_data"]["schedules"]]
                    )
                    message = f"""
{config.EMOJIS['success']} <b>התרופה נוספה בהצלחה!</b>

{config.EMOJIS['medicine']} <b>{medicine_name}</b>
⚖️ מינון: {dosage}
⏰ שעות נטילה: {schedules_text}
📦 מלאי התחלתי: 0 כדורים (ניתן לעדכן דרך "עדכן מלאי")

התזכורות הופעלו אוטומטית!
                    """
                    await query.edit_message_text(message, parse_mode="HTML")
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id, text="תפריט ראשי:", reply_markup=get_main_menu_keyboard()
                    )
                else:
                    await query.edit_message_text(f"{config.EMOJIS['error']} שגיאה בשמירת התרופה. אנא נסו שוב.")
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id, text="תפריט ראשי:", reply_markup=get_main_menu_keyboard()
                    )
                if user_id in self.user_medicine_data:
                    del self.user_medicine_data[user_id]
                return ConversationHandler.END
        except Exception as e:
            logger.error(f"Error handling time selection: {e}")
            await self._send_error_message(update, "שגיאה בבחירת השעה")
            return ConversationHandler.END

    async def get_custom_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.effective_user.id
            time_str = update.message.text.strip()
            match = re.match(r"^([0-1]?[0-9]|2[0-3]):([0-5][0-9])$", time_str)
            if not match:
                await update.message.reply_text(
                    f"{config.EMOJIS['error']} פורמט שעה שגוי. אנא השתמשו בפורמט HH:MM (לדוגמה: 08:30)"
                )
                return CUSTOM_TIME_INPUT
            hour = int(match.group(1))
            minute = int(match.group(2))
            selected_time = time(hour, minute)
            if "schedules" not in self.user_medicine_data[user_id]["medicine_data"]:
                self.user_medicine_data[user_id]["medicine_data"]["schedules"] = []
            self.user_medicine_data[user_id]["medicine_data"]["schedules"].append(selected_time)
            medicine_name = self.user_medicine_data[user_id]["medicine_data"]["name"]
            dosage = self.user_medicine_data[user_id]["medicine_data"]["dosage"]
            self.user_medicine_data[user_id]["medicine_data"]["inventory_count"] = 0.0
            success = await self._create_medicine_in_db(user_id)
            if success:
                schedules_text = ", ".join(
                    [t.strftime("%H:%M") for t in self.user_medicine_data[user_id]["medicine_data"]["schedules"]]
                )
                message = f"""
{config.EMOJIS['success']} <b>התרופה נוספה בהצלחה!</b>

{config.EMOJIS['medicine']} <b>{medicine_name}</b>
⚖️ מינון: {dosage}
⏰ שעות נטילה: {schedules_text}
📦 מלאי התחלתי: 0 כדורים (ניתן לעדכן דרך "עדכן מלאי")

התזכורות הופעלו אוטומטית!
                """
                await update.message.reply_text(message, parse_mode="HTML", reply_markup=get_main_menu_keyboard())
            else:
                await update.message.reply_text(
                    f"{config.EMOJIS['error']} שגיאה בשמירת התרופה. אנא נסו שוב.", reply_markup=get_main_menu_keyboard()
                )
            if user_id in self.user_medicine_data:
                del self.user_medicine_data[user_id]
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Error getting custom time: {e}")
            await self._send_error_message(update, "שגיאה בקבלת השעה")
            return ConversationHandler.END

    async def get_medicine_inventory(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.effective_user.id
            inventory_str = update.message.text.strip()
            try:
                inventory_count = float(inventory_str)
                if inventory_count < 0:
                    raise ValueError("Negative inventory")
                if inventory_count > 9999:
                    raise ValueError("Too large inventory")
            except ValueError:
                await update.message.reply_text(f"{config.EMOJIS['error']} אנא הזינו מספר תקין (0-9999)")
                return MEDICINE_INVENTORY
            self.user_medicine_data[user_id]["medicine_data"]["inventory_count"] = inventory_count
            success = await self._create_medicine_in_db(user_id)
            if success:
                medicine_data = self.user_medicine_data[user_id]["medicine_data"]
                message = f"""
{config.EMOJIS['success']} <b>התרופה נוספה בהצלחה!</b>

{config.EMOJIS['medicine']} <b>{medicine_data['name']}</b>
⚖️ מינון: {medicine_data['dosage']}
⏰ שעות נטילה: {', '.join([t.strftime('%H:%M') for t in medicine_data['schedules']])}
📦 מלאי: {inventory_count} יחידות

התזכורות הופעלו אוטומטית!
                """
                await update.message.reply_text(message, parse_mode="HTML", reply_markup=get_main_menu_keyboard())
            else:
                await update.message.reply_text(f"{config.EMOJIS['error']} שגיאה בשמירת התרופה. אנא נסו שוב.")
            if user_id in self.user_medicine_data:
                del self.user_medicine_data[user_id]
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Error getting medicine inventory: {e}")
            await self._send_error_message(update, "שגיאה בקבלת כמות המלאי")
            return ConversationHandler.END

    async def _create_medicine_in_db(self, user_id: int) -> bool:
        try:
            user = await DatabaseManager.get_user_by_telegram_id(user_id)
            if not user:
                return False
            medicine_data = self.user_medicine_data[user_id]["medicine_data"]
            medicine = await DatabaseManager.create_medicine(
                user_id=user.id,
                name=medicine_data["name"],
                dosage=medicine_data["dosage"],
                inventory_count=medicine_data.get("inventory_count", 0.0),
            )
            for schedule_time in medicine_data["schedules"]:
                await DatabaseManager.create_medicine_schedule(medicine_id=medicine.id, time_to_take=schedule_time)
                await medicine_scheduler.schedule_medicine_reminder(
                    user_id=user_id,
                    medicine_id=medicine.id,
                    reminder_time=schedule_time,
                    timezone=user.timezone or config.DEFAULT_TIMEZONE,
                )
            return True
        except Exception as e:
            logger.error(f"Error creating medicine in database: {e}")
            return False

    async def view_medicine(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            query = update.callback_query
            await query.answer()
            medicine_id = int(query.data.split("_")[2])
            medicine = await DatabaseManager.get_medicine_by_id(medicine_id)
            if not medicine:
                await query.edit_message_text(f"{config.EMOJIS['error']} התרופה לא נמצאה")
                return
            schedules = await DatabaseManager.get_medicine_schedules(medicine_id)
            schedule_times = [s.time_to_take.strftime("%H:%M") for s in schedules]
            recent_doses = await DatabaseManager.get_recent_doses(medicine_id, days=7)
            taken_count = len([d for d in recent_doses if d.status == "taken"])
            total_count = len(recent_doses)
            inventory_status = ""
            if medicine.inventory_count <= medicine.low_stock_threshold:
                inventory_status = f"\n{config.EMOJIS['warning']} <b>מלאי נמוך! כדאי להזמין עוד</b>"
            message = f"""
{config.EMOJIS['medicine']} <b>{medicine.name}</b>

⚖️ <b>מינון:</b> {medicine.dosage}
⏰ <b>שעות נטילה:</b> {', '.join(schedule_times) if schedule_times else 'לא מוגדר'}
📦 <b>מלאי:</b> {medicine.inventory_count} כדורים
📊 <b>השבוע:</b> נלקח {taken_count}/{total_count} פעמים
📅 <b>נוצר:</b> {medicine.created_at.strftime('%d/%m/%Y')}

{medicine.notes or ''}{inventory_status}
            """
            await query.edit_message_text(message, parse_mode="HTML", reply_markup=get_medicine_detail_keyboard(medicine_id))
        except Exception as e:
            logger.error(f"Error viewing medicine: {e}")
            await query.edit_message_text(f"{config.EMOJIS['error']} שגיאה בהצגת פרטי התרופה")

    async def cancel_operation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.effective_user.id
            if user_id in self.user_medicine_data:
                del self.user_medicine_data[user_id]
            message = f"{config.EMOJIS['info']} הפעולה בוטלה"
            if update.callback_query:
                await update.callback_query.answer()
                await update.callback_query.edit_message_text(message)
                await context.bot.send_message(
                    chat_id=update.effective_chat.id, text="בחרו פעולה:", reply_markup=get_main_menu_keyboard()
                )
            else:
                await update.message.reply_text(message, reply_markup=get_main_menu_keyboard())
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Error canceling operation: {e}")
            return ConversationHandler.END

    async def _send_error_message(self, update: Update, error_text: str):
        try:
            if update.callback_query:
                await update.callback_query.edit_message_text(f"{config.EMOJIS['error']} {error_text}")
                await update.effective_message.reply_text("תפריט ראשי:", reply_markup=get_main_menu_keyboard())
            else:
                await update.message.reply_text(
                    f"{config.EMOJIS['error']} {error_text}", reply_markup=get_main_menu_keyboard()
                )
        except Exception as e:
            logger.error(f"Error sending error message: {e}")

    async def handle_inventory_update(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            query = update.callback_query
            await query.answer()
            context.user_data.pop("editing_medicine_for", None)
            context.user_data.pop("editing_field_for", None)
            data_parts = query.data.split("_")
            medicine_id = int(data_parts[1])
            operation = data_parts[2]
            medicine = await DatabaseManager.get_medicine_by_id(medicine_id)
            if not medicine:
                await query.edit_message_text(f"{config.EMOJIS['error']} התרופה לא נמצאה")
                return
            if operation == "custom":
                message = f"""
{config.EMOJIS['inventory']} <b>עדכון מלאי: {medicine.name}</b>

מלאי נוכחי: {medicine.inventory_count} כדורים
 
אנא הזן את סך המלאי העדכני הכולל שברשותך (במספר כדורים):
                """
                await query.edit_message_text(message, parse_mode="HTML", reply_markup=get_cancel_keyboard())
                context.user_data["updating_inventory_for"] = medicine_id
                return CUSTOM_INVENTORY_INPUT
            elif operation == "add" or operation == "add_dialog":
                message = f"""
{config.EMOJIS['inventory']} <b>הוספת כמות למלאי: {medicine.name}</b>

מלאי נוכחי: {medicine.inventory_count} כדורים

אנא הזינו את מספר הכדורים שברצונך להוסיף למלאי הקיים:
                """
                await query.edit_message_text(message, parse_mode="HTML", reply_markup=get_cancel_keyboard())
                context.user_data["adding_inventory_for"] = medicine_id
                context.user_data["awaiting_add_quantity"] = True
                return CUSTOM_INVENTORY_INPUT
            else:
                if operation.startswith("+"):
                    change = float(operation[1:])
                    new_count = medicine.inventory_count + change
                elif operation.startswith("-"):
                    change = float(operation[1:])
                    new_count = max(0, medicine.inventory_count - change)
                else:
                    await query.edit_message_text(f"{config.EMOJIS['error']} פעולה לא מזוהה")
                    return
                await DatabaseManager.update_inventory(medicine_id, new_count)
                status_msg = ""
                if new_count <= medicine.low_stock_threshold:
                    status_msg = f"\n{config.EMOJIS['warning']} מלאי נמוך!"
                message = f"""
{config.EMOJIS['success']} <b>מלאי עודכן!</b>

{config.EMOJIS['medicine']} {medicine.name}
{config.EMOJIS['inventory']} מלאי חדש: {int(new_count)} כדורים{status_msg}
                """
                await query.edit_message_text(
                    message, parse_mode="HTML", reply_markup=get_medicine_detail_keyboard(medicine_id)
                )
        except Exception as e:
            logger.error(f"Error handling inventory update: {e}")
            await query.edit_message_text(f"{config.EMOJIS['error']} שגיאה בעדכון המלאי")

    async def handle_custom_inventory(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            medicine_id = context.user_data.get("updating_inventory_for") or context.user_data.get("adding_inventory_for")
            if not medicine_id:
                await update.message.reply_text(f"{config.EMOJIS['error']} שגיאה: לא נמצא מזהה התרופה")
                return ConversationHandler.END
            inventory_str = update.message.text.strip()
            try:
                new_count = float(inventory_str)
                if new_count < 0:
                    raise ValueError("Negative inventory")
                if new_count > 9999:
                    raise ValueError("Too large inventory")
            except ValueError:
                await update.message.reply_text(f"{config.EMOJIS['error']} אנא הזינו מספר תקין (0-9999)")
                return CUSTOM_INVENTORY_INPUT
            if context.user_data.get("awaiting_add_quantity"):
                med = await DatabaseManager.get_medicine_by_id(medicine_id)
                final_count = float(med.inventory_count) + new_count
                await DatabaseManager.update_inventory(medicine_id, final_count)
            else:
                final_count = new_count
                await DatabaseManager.update_inventory(medicine_id, final_count)
            medicine = await DatabaseManager.get_medicine_by_id(medicine_id)
            status_msg = ""
            if final_count <= medicine.low_stock_threshold:
                status_msg = f"\n{config.EMOJIS['warning']} מלאי נמוך!"
            message = f"""
{config.EMOJIS['success']} <b>מלאי עודכן בהצלחה!</b>

{config.EMOJIS['medicine']} {medicine.name}
{config.EMOJIS['inventory']} מלאי חדש: {int(final_count)} כדורים{status_msg}
            """
            await update.message.reply_text(message, parse_mode="HTML", reply_markup=get_medicine_detail_keyboard(medicine_id))
            context.user_data.pop("updating_inventory_for", None)
            context.user_data.pop("adding_inventory_for", None)
            context.user_data.pop("awaiting_add_quantity", None)
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Error handling custom inventory: {e}")
            await update.message.reply_text(f"{config.EMOJIS['error']} שגיאה בעדכון המלאי")
            return ConversationHandler.END

    async def edit_medicine(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            query = update.callback_query
            await query.answer()
            parts = query.data.split("_")
            medicine_id = int(parts[2]) if len(parts) > 2 else None
            if not medicine_id:
                await query.edit_message_text(f"{config.EMOJIS['error']} שגיאה: לא נמצא מזהה התרופה")
                return ConversationHandler.END
            medicine = await DatabaseManager.get_medicine_by_id(medicine_id)
            if not medicine:
                await query.edit_message_text(f"{config.EMOJIS['error']} התרופה לא נמצאה")
                return ConversationHandler.END
            context.user_data["editing_medicine_for"] = medicine_id
            buttons = [
                [
                    InlineKeyboardButton("שנה שם", callback_data=f"mededit_name_{medicine_id}"),
                    InlineKeyboardButton("שנה מינון", callback_data=f"mededit_dosage_{medicine_id}"),
                ],
                [
                    InlineKeyboardButton("עדכן הערות", callback_data=f"mededit_notes_{medicine_id}"),
                    InlineKeyboardButton("שנה שעות", callback_data=f"medicine_schedule_{medicine_id}"),
                ],
                [InlineKeyboardButton("שנה גודל חבילה", callback_data=f"mededit_packsize_{medicine_id}")],
                [InlineKeyboardButton(f"{'🔴 השבת' if medicine.is_active else '🟢 הפעל'}", callback_data=f"mededit_toggle_{medicine_id}")],
                [InlineKeyboardButton(f"{config.EMOJIS['back']} חזור", callback_data=f"medicine_view_{medicine_id}")],
            ]
            await query.edit_message_text(
                f"עריכת תרופה: {medicine.name}\nבחרו פעולה:", reply_markup=InlineKeyboardMarkup(buttons)
            )
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Error handling edit medicine: {e}")
            try:
                await update.callback_query.edit_message_text(f"{config.EMOJIS['error']} שגיאה בעריכת התרופה")
            except Exception:
                pass
            return ConversationHandler.END

    async def handle_edit_callbacks(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            query = update.callback_query
            await query.answer()
            data = query.data
            if data.startswith("mededit_name_"):
                medicine_id = int(data.split("_")[-1])
                context.user_data["editing_medicine_for"] = medicine_id
                context.user_data["editing_field_for"] = "name"
                await query.edit_message_text("הקלידו שם חדש כדי לשנות שם:", reply_markup=get_cancel_keyboard())
                return EDIT_NAME
            if data.startswith("mededit_dosage_"):
                medicine_id = int(data.split("_")[-1])
                context.user_data["editing_medicine_for"] = medicine_id
                context.user_data["editing_field_for"] = "dosage"
                await query.edit_message_text("הקלידו: מינון <טקסט> כדי לשנות מינון:\nאו פשוט שלחו את המינון החדש:", reply_markup=get_cancel_keyboard())
                return EDIT_DOSAGE
            if data.startswith("mededit_notes_"):
                medicine_id = int(data.split("_")[-1])
                context.user_data["editing_medicine_for"] = medicine_id
                context.user_data["editing_field_for"] = "notes"
                await query.edit_message_text("הקלידו: הערות <טקסט> כדי לעדכן הערות:\nאו שלחו את ההערות החדשות:", reply_markup=get_cancel_keyboard())
                return EDIT_NAME
            if data.startswith("mededit_packsize_"):
                medicine_id = int(data.split("_")[-1])
                context.user_data["editing_medicine_for"] = medicine_id
                context.user_data["editing_field_for"] = "packsize"
                await query.edit_message_text("הקלידו גודל חבילה (מספר כדורים בחבילה):", reply_markup=get_cancel_keyboard())
                return EDIT_INVENTORY
            if data.startswith("mededit_toggle_"):
                medicine_id = int(data.split("_")[-1])
                med = await DatabaseManager.get_medicine_by_id(medicine_id)
                if not med:
                    await query.edit_message_text(config.ERROR_MESSAGES["medicine_not_found"])
                    return ConversationHandler.END
                await DatabaseManager.update_medicine(medicine_id, is_active=not bool(med.is_active))
                await self.edit_medicine(update, context)
                return ConversationHandler.END
            if data.startswith("medicine_schedule_"):
                medicine_id = int(data.split("_")[-1])
                context.user_data["scheduling_for"] = medicine_id
                context.user_data["new_schedule_times"] = []
                await query.edit_message_text(
                    "בחרו שעה ראשונה או הזינו בפורמט HH:MM. אפשר לבחור כמה ואז לשמור:",
                    reply_markup=self._get_schedule_edit_keyboard(medicine_id),
                )
                return EDIT_SCHEDULE
        except Exception as e:
            logger.error(f"Error in handle_edit_callbacks: {e}")
            await update.callback_query.edit_message_text(config.ERROR_MESSAGES["general"])
            return ConversationHandler.END

    def _get_schedule_edit_keyboard(self, medicine_id: int) -> InlineKeyboardMarkup:
        base = get_time_selection_keyboard()
        rows = []
        if isinstance(base.inline_keyboard, list):
            for r in base.inline_keyboard:
                rows.append(list(r))
        rows.append([InlineKeyboardButton(f"{config.EMOJIS['success']} שמור שעות", callback_data=f"sched_save_{medicine_id}")])
        rows.append([InlineKeyboardButton(f"{config.EMOJIS['back']} ביטול", callback_data=f"medicine_view_{medicine_id}")])
        return InlineKeyboardMarkup(rows)

    async def handle_schedule_edit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            query = update.callback_query
            await query.answer()
            data = query.data
            ud = context.user_data
            if data == "time_custom":
                await query.edit_message_text("הקלידו שעה בפורמט HH:MM (למשל 09:30)", reply_markup=get_cancel_keyboard())
                ud["awaiting_custom_sched_time"] = True
                return EDIT_SCHEDULE
            if data.startswith("time_"):
                parts = data.replace("time_", "").split("_")
                hour = int(parts[0])
                minute = int(parts[1])
                lst: List[time] = ud.get("new_schedule_times", [])
                lst.append(time(hour, minute))
                ud["new_schedule_times"] = lst
                await query.edit_message_reply_markup(self._get_schedule_edit_keyboard(int(ud.get("scheduling_for"))))
                return EDIT_SCHEDULE
            if data.startswith("sched_save_"):
                medicine_id = int(data.split("_")[-1])
                times: List[time] = ud.get("new_schedule_times", [])
                uniq = {t.strftime("%H:%M"): t for t in times}
                ordered = [uniq[k] for k in sorted(uniq.keys())]
                await DatabaseManager.replace_medicine_schedules(medicine_id, ordered)
                user = await DatabaseManager.get_user_by_telegram_id(update.effective_user.id)
                await medicine_scheduler.cancel_medicine_reminders(user.id, medicine_id)
                for t in ordered:
                    await medicine_scheduler.schedule_medicine_reminder(
                        user.id, medicine_id, t, timezone=user.timezone or config.DEFAULT_TIMEZONE
                    )
                await query.edit_message_text(
                    f"⏰ עודכנו {len(ordered)} שעות לנטילת התרופה.",
                    reply_markup=get_medicine_detail_keyboard(medicine_id),
                )
                ud.pop("scheduling_for", None)
                ud.pop("new_schedule_times", None)
                ud.pop("awaiting_custom_sched_time", None)
                return ConversationHandler.END
        except Exception as e:
            logger.error(f"Error in handle_schedule_edit: {e}")
            await update.callback_query.edit_message_text(config.ERROR_MESSAGES["general"])
            return ConversationHandler.END

    async def handle_edit_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            ud = context.user_data
            medicine_id = ud.get("editing_medicine_for") or ud.get("scheduling_for")
            if not medicine_id:
                await update.message.reply_text(config.ERROR_MESSAGES["general"])
                return ConversationHandler.END
            text = update.message.text.strip()
            if ud.get("awaiting_custom_sched_time"):
                match = re.match(r"^([0-1]?[0-9]|2[0-3]):([0-5][0-9])$", text)
                if not match:
                    await update.message.reply_text(config.ERROR_MESSAGES["invalid_time"])
                    return EDIT_SCHEDULE
                hour = int(match.group(1))
                minute = int(match.group(2))
                lst: List[time] = ud.get("new_schedule_times", [])
                lst.append(time(hour, minute))
                ud["new_schedule_times"] = lst
                ud.pop("awaiting_custom_sched_time", None)
                await update.message.reply_text("נוספה שעה. בחרו עוד שעות או שמרו:")
                return EDIT_SCHEDULE
            field = ud.get("editing_field_for")
            if field == "name":
                if len(text) < 2:
                    await update.message.reply_text(f"{config.EMOJIS['error']} שם קצר מדי")
                    return EDIT_NAME
                await DatabaseManager.update_medicine(int(medicine_id), name=text)
            elif field == "dosage":
                await DatabaseManager.update_medicine(int(medicine_id), dosage=text)
            elif field == "notes":
                await DatabaseManager.update_medicine(int(medicine_id), notes=text)
            elif field == "packsize":
                try:
                    pack = float(text)
                    await DatabaseManager.update_medicine(int(medicine_id), low_stock_threshold=pack)
                except Exception:
                    await update.message.reply_text(f"{config.EMOJIS['error']} אנא הזינו מספר תקין")
                    return EDIT_INVENTORY
            ud.pop("editing_medicine_for", None)
            ud.pop("editing_field_for", None)
            await update.message.reply_text("עודכן.", reply_markup=get_medicine_detail_keyboard(int(medicine_id)))
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Error in handle_edit_text: {e}")
            await update.message.reply_text(config.ERROR_MESSAGES["general"])
            return ConversationHandler.END


# Global instance
medicine_handler = MedicineHandler()

