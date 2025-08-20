"""
Medicine Reminder Bot - Main Entry Point
Modern Telegram Bot using python-telegram-bot v22.3 with async/await
Designed for deployment on Render platform with webhook support
"""

import asyncio
import logging
import signal
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters
from telegram.error import TelegramError
from aiohttp import web
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config import config
from database import init_database, DatabaseManager
from scheduler import medicine_scheduler
from handlers.reports_handler import reports_handler
from handlers.appointments_handler import appointments_handler
from utils.keyboards import get_reminders_settings_keyboard, get_inventory_main_keyboard

# Configure logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=getattr(logging, config.LOG_LEVEL))
logger = logging.getLogger(__name__)


class MedicineReminderBot:
    """Main bot class with all handlers and lifecycle management"""

    def __init__(self):
        self.application = None
        self.is_running = False
        # Handler instances
        from handlers import (
            medicine_handler as _medicine_handler,
            reminder_handler as _reminder_handler,
            reports_handler as _reports_handler,
            caregiver_handler as _caregiver_handler,
        )

        self._medicine_handler = _medicine_handler
        self._reminder_handler = _reminder_handler
        self._reports_handler = _reports_handler
        self._caregiver_handler = _caregiver_handler
        # Internal shutdown coordination
        self._serve_forever_event = None
        self._shutdown_started = False
        self._runner = None

    async def initialize(self):
        """Initialize the bot application and all components"""
        try:
            logger.info("Initializing Medicine Reminder Bot...")

            # Initialize database
            await init_database()
            logger.info("Database initialized")

            # Create application
            builder = Application.builder()
            builder.token(config.BOT_TOKEN)

            # Note: Keep Updater enabled to support run_webhook
            self.application = builder.build()

            # Set up bot reference for scheduler
            medicine_scheduler.bot = self.application.bot

            # Register all handlers
            await self._register_handlers()

            # Start scheduler
            await medicine_scheduler.start()

            logger.info("Bot initialization completed")

        except Exception as e:
            logger.error(f"Failed to initialize bot: {e}")
            raise

    async def _register_handlers(self):
        """Register all command and callback handlers"""
        app = self.application

        # Basic Commands
        app.add_handler(CommandHandler("start", self.start_command))
        app.add_handler(CommandHandler("help", self.help_command))
        app.add_handler(CommandHandler("settings", self.settings_command))

        # Medicine Management Commands
        app.add_handler(CommandHandler("add_medicine", self.add_medicine_command))
        app.add_handler(CommandHandler("my_medicines", self.my_medicines_command))
        app.add_handler(CommandHandler("update_inventory", self.update_inventory_command))

        # Reminder Commands
        app.add_handler(CommandHandler("next_reminders", self.next_reminders_command))
        app.add_handler(CommandHandler("snooze", self.snooze_command))

        # Tracking Commands
        app.add_handler(CommandHandler("log_symptoms", self.log_symptoms_command))
        app.add_handler(CommandHandler("weekly_report", self.weekly_report_command))
        app.add_handler(CommandHandler("medicine_history", self.medicine_history_command))

        # Caregiver Commands
        app.add_handler(CommandHandler("add_caregiver", self.add_caregiver_command))
        app.add_handler(CommandHandler("caregiver_settings", self.caregiver_settings_command))

        # Conversation and callback handlers from packages
        from handlers import get_all_conversation_handlers, get_all_callback_handlers

        for conv in get_all_conversation_handlers():
            app.add_handler(conv)
        for cb in get_all_callback_handlers():
            app.add_handler(cb)

        # Reports handler already included above

        # Callback Query Handler for inline keyboards
        app.add_handler(CallbackQueryHandler(self.button_callback))

        # Message handler for text input
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text_message))

        # Error handler
        app.add_error_handler(self.error_handler)

        logger.info("All handlers registered successfully")

    async def start_command(self, update: Update, context):
        """Handle /start command"""
        try:
            user = update.effective_user
            # Deep-link args: /start invite_CODE
            text = (update.message.text or "").strip()
            if text.startswith("/start ") and "invite_" in text:
                code = text.split("invite_", 1)[-1].strip()
                inv = await DatabaseManager.get_invite_by_code(code)
                if (
                    not inv
                    or getattr(inv, "status", "active") != "active"
                    or (getattr(inv, "expires_at", None) and getattr(inv, "expires_at") < datetime.utcnow())
                ):
                    await update.message.reply_text("קוד הזמנה לא תקין או פג תוקף.")
                else:
                    # Ask confirmation
                    from telegram import InlineKeyboardMarkup, InlineKeyboardButton

                    context.user_data["pending_invite_code"] = code
                    await update.message.reply_text(
                        f"התבקשת להצטרף כמטפל עבור משתמש {inv.user_id}. לאשר?",
                        reply_markup=InlineKeyboardMarkup(
                            [
                                [InlineKeyboardButton("אישור", callback_data="invite_accept")],
                                [InlineKeyboardButton("ביטול", callback_data="invite_reject")],
                            ]
                        ),
                    )
                return
            # Show main menu immediately for faster UX
            from utils.keyboards import get_main_menu_keyboard

            await update.message.reply_text(
                config.WELCOME_MESSAGE, parse_mode="Markdown", reply_markup=get_main_menu_keyboard()
            )
            telegram_id = user.id

            # Get or create user in database (after showing UI)
            db_user = await DatabaseManager.get_user_by_telegram_id(telegram_id)
            if not db_user:
                db_user = await DatabaseManager.create_user(
                    telegram_id=telegram_id, username=user.username, first_name=user.first_name, last_name=user.last_name
                )
                logger.info(f"Created new user: {telegram_id}")

        except Exception as e:
            logger.error(f"Error in start command: {e}")
            await update.message.reply_text(config.ERROR_MESSAGES["general"])

    async def help_command(self, update: Update, context):
        """Handle /help command"""
        try:
            await update.message.reply_text(config.HELP_MESSAGE, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error in help command: {e}")
            await update.message.reply_text(config.ERROR_MESSAGES["general"])

    async def settings_command(self, update: Update, context):
        """Handle /settings command"""
        try:
            from utils.keyboards import get_settings_keyboard

            message = f"""
{config.EMOJIS['settings']} *הגדרות אישיות*

בחרו את ההגדרה שתרצו לשנות:
            """

            await update.message.reply_text(message, parse_mode="Markdown", reply_markup=get_settings_keyboard())

        except Exception as e:
            logger.error(f"Error in settings command: {e}")
            await update.message.reply_text(config.ERROR_MESSAGES["general"])

    async def add_medicine_command(self, update: Update, context):
        """Handle /add_medicine command"""
        try:
            from utils.keyboards import get_cancel_keyboard

            message = f"""
{config.EMOJES['medicine']} <b>הוספת תרופה חדשה</b>

אנא שלחו את שם התרופה:
            """

            await update.message.reply_text(message, parse_mode="HTML")

            # Store conversation state (in real implementation, use ConversationHandler)
            context.user_data["adding_medicine"] = {"step": "name"}

        except Exception as e:
            logger.error(f"Error in add_medicine command: {e}")
            await update.message.reply_text(config.ERROR_MESSAGES["general"])

    async def my_medicines_command(self, update: Update, context):
        """Handle /my_medicines command"""
        try:
            user = update.effective_user
            db_user = await DatabaseManager.get_user_by_telegram_id(user.id)

            if not db_user:
                await update.message.reply_text("אנא התחילו עם /start")
                return

            medicines = await DatabaseManager.get_user_medicines(db_user.id)

            if not medicines:
                message = f"""
{config.EMOJES['info']} <b>אין תרופות רשומות</b>

לחצו על /add_medicine כדי להוסיף תרופה ראשונה.
                """
            else:
                message = f"{config.EMOJES['medicine']} <b>התרופות שלכם:</b>\n\n"
                for medicine in medicines:
                    status_emoji = config.EMOJES["success"] if medicine.is_active else config.EMOJES["error"]
                    inventory_warning = ""

                    if medicine.inventory_count <= medicine.low_stock_threshold:
                        inventory_warning = f" {config.EMOJES['warning']}"

                    message += f"{status_emoji} <b>{medicine.name}</b>\n"
                    message += f"   💊 {medicine.dosage}\n"
                    message += f"   📦 מלאי: {medicine.inventory_count}{inventory_warning}\n\n"

            from utils.keyboards import get_medicines_keyboard

            await update.message.reply_text(
                message, parse_mode="HTML", reply_markup=get_medicines_keyboard(medicines if medicines else [])
            )

        except Exception as e:
            logger.error(f"Error in my_medicines command: {e}")
            await update.message.reply_text(config.ERROR_MESSAGES["general"])

    async def update_inventory_command(self, update: Update, context):
        """Handle /update_inventory <medicine_name> <new_count>"""
        try:
            user = update.effective_user
            db_user = await DatabaseManager.get_user_by_telegram_id(user.id)
            if not db_user:
                await update.message.reply_text("אנא התחילו עם /start")
                return

            args = context.args if hasattr(context, "args") else []
            if len(args) < 2:
                await update.message.reply_text("שימוש: /update_inventory <שם_תרופה> <כמות_חדשה>")
                return

            medicine_name = args[0]
            try:
                new_count = int(args[1])
            except ValueError:
                await update.message.reply_text("כמות חייבת להיות מספר שלם")
                return

            medicines = await DatabaseManager.get_user_medicines(db_user.id)
            if not medicines:
                await update.message.reply_text("לא נמצאו תרופות בעבורכם")
                return

            selected = None
            for m in medicines:
                if m.name.lower() == medicine_name.lower():
                    selected = m
                    break

            if not selected:
                await update.message.reply_text("לא נמצאה תרופה בשם הזה")
                return

            await DatabaseManager.update_inventory(selected.id, new_count)
            await update.message.reply_text(f"{config.EMOJES['success']} עודכן מלאי לתרופה {selected.name}: {new_count}")

        except Exception as e:
            logger.error(f"Error in update_inventory command: {e}")
            await update.message.reply_text(config.ERROR_MESSAGES["general"])

    async def snooze_command(self, update: Update, context):
        """Handle /snooze command (generic)"""
        try:
            await update.message.reply_text("להשהיית תזכורת, השתמשו בכפתור דחייה שמופיע בהתראה.")
        except Exception as e:
            logger.error(f"Error in snooze command: {e}")
            await update.message.reply_text(config.ERROR_MESSAGES["general"])

    async def log_symptoms_command(self, update: Update, context):
        """Open symptoms tracking menu"""
        try:
            user = update.effective_user
            db_user = await DatabaseManager.get_user_by_telegram_id(user.id) if user else None
            meds = await DatabaseManager.get_user_medicines(db_user.id) if db_user else []
            # Support both message command and callback button
            if getattr(update, "callback_query", None):
                await update.callback_query.answer()
                if meds:
                    from utils.keyboards import get_symptoms_medicine_picker

                    await update.callback_query.edit_message_text(
                        "בחרו תרופה לשיוך מעקב תופעות:", reply_markup=get_symptoms_medicine_picker(meds)
                    )
                else:
                    await update.callback_query.edit_message_text("אין תרופות במערכת. הוסיפו תרופה דרך 'התרופות שלי'.")
                return
            # Fallback to classic message reply
            if meds:
                from utils.keyboards import get_symptoms_medicine_picker

                await update.message.reply_text(
                    "בחרו תרופה לשיוך מעקב תופעות:", reply_markup=get_symptoms_medicine_picker(meds)
                )
            else:
                await update.message.reply_text("אין תרופות במערכת. הוסיפו תרופה דרך 'התרופות שלי'.")
        except Exception as e:
            logger.error(f"Error in log_symptoms command: {e}")
            try:
                if getattr(update, "callback_query", None):
                    await update.callback_query.edit_message_text(config.ERROR_MESSAGES["general"])
                else:
                    await update.message.reply_text(config.ERROR_MESSAGES["general"])
            except Exception:
                pass

    async def weekly_report_command(self, update: Update, context):
        """Handle /weekly_report command (stub)"""
        try:
            await update.message.reply_text("דוח שבועי יתווסף בקרוב.")
        except Exception as e:
            logger.error(f"Error in weekly_report command: {e}")
            await update.message.reply_text(config.ERROR_MESSAGES["general"])

    async def medicine_history_command(self, update: Update, context):
        """Handle /medicine_history command (stub)"""
        try:
            await update.message.reply_text("היסטוריית תרופות תתווסף בקרוב.")
        except Exception as e:
            logger.error(f"Error in medicine_history command: {e}")
            await update.message.reply_text(config.ERROR_MESSAGES["general"])

    async def add_caregiver_command(self, update: Update, context):
        """Handle /add_caregiver command (stub)"""
        try:
            await update.message.reply_text("ניהול מטפל יתווסף בקרוב.")
        except Exception as e:
            logger.error(f"Error in add_caregiver command: {e}")
            await update.message.reply_text(config.ERROR_MESSAGES["general"])

    async def caregiver_settings_command(self, update: Update, context):
        """Handle /caregiver_settings command (stub)"""
        try:
            await update.message.reply_text("הגדרות מטפל יתווסף בקרוב.")
        except Exception as e:
            logger.error(f"Error in caregiver_settings command: {e}")
            await update.message.reply_text(config.ERROR_MESSAGES["general"])

    async def next_reminders_command(self, update: Update, context):
        """Handle /next_reminders command"""
        try:
            # Delegate to reminder handler rich view
            from handlers import reminder_handler

            await reminder_handler.show_next_reminders(update, context)

        except Exception as e:
            logger.error(f"Error in next_reminders command: {e}")
            await update.message.reply_text(config.ERROR_MESSAGES["general"])

    async def button_callback(self, update: Update, context):
        """Handle inline keyboard button callbacks"""
        try:
            query = update.callback_query
            await query.answer()

            data = query.data
            user_id = query.from_user.id

            if data.startswith("appt_") or (
                data.startswith("time_")
                and (
                    context.user_data.get("appt_state")
                    and isinstance(context.user_data.get("appt_state"), dict)
                    and context.user_data.get("appt_state").get("step") in ("edit_time_time", "time")
                )
                and not context.user_data.get("editing_schedule_for")
            ):
                await appointments_handler.handle_callback(update, context)
                return

            # Time selection buttons: handle preset hour and custom entry
            if data in ("cancel", "time_cancel"):
                from utils.keyboards import get_main_menu_keyboard

                context.user_data.pop("editing_schedule_for", None)
                # Telegram edit_message_text cannot attach ReplyKeyboardMarkup. Send a new message instead.
                await query.edit_message_text(f"{config.EMOJES['info']} הפעולה בוטלה")
                await self.application.bot.send_message(
                    chat_id=query.message.chat_id, text="בחרו פעולה:", reply_markup=get_main_menu_keyboard()
                )
                return
            if data == "time_custom":
                await query.edit_message_text("הקלידו שעה בפורמט HH:MM (למשל 08:30)")
                context.user_data["awaiting_schedule_text"] = True
                return
            if data.startswith("time_"):
                parts = data.split("_")
                if len(parts) >= 3 and parts[1].isdigit() and parts[2].isdigit():
                    try:
                        if not context.user_data.get("editing_schedule_for"):
                            await query.edit_message_text("שגיאה: אין תרופה נבחרת. חזרו ל'שנה שעות' ונסו שוב.")
                            return
                        h = int(parts[1])
                        m = int(parts[2])
                        from datetime import time as dtime

                        new_time = dtime(hour=h, minute=m)
                        medicine_id = int(context.user_data.get("editing_schedule_for"))
                        # Replace schedules
                        await DatabaseManager.replace_medicine_schedules(medicine_id, [new_time])
                        # Reschedule reminders
                        user = await DatabaseManager.get_user_by_telegram_id(query.from_user.id)
                        await medicine_scheduler.cancel_medicine_reminders(user.id, medicine_id)
                        await medicine_scheduler.schedule_medicine_reminder(
                            user_id=user.id,
                            medicine_id=medicine_id,
                            reminder_time=new_time,
                            timezone=user.timezone or config.DEFAULT_TIMEZONE,
                        )
                        context.user_data.pop("editing_schedule_for", None)
                        # Show success and medicine details
                        from utils.keyboards import get_medicine_detail_keyboard

                        med = await DatabaseManager.get_medicine_by_id(medicine_id)
                        await query.edit_message_text(
                            f"{config.EMOJES['success']} השעה עודכנה ל- {new_time.strftime('%H:%M')}\n{config.EMOJES['medicine']} {med.name}",
                            reply_markup=get_medicine_detail_keyboard(medicine_id),
                        )
                        return
                    except Exception as ex:
                        logger.error(f"Failed to update schedule via time buttons: {ex}")
                        await query.edit_message_text(config.ERROR_MESSAGES["general"])
                        return
                else:
                    await query.edit_message_text("שעה לא תקינה")
                    return

            # Handle different callback types
            if data.startswith("dose_taken_") or data.startswith("dose_snooze_") or data.startswith("dose_skip_"):
                # Handled by reminder handler callbacks (already registered)
                return
            elif data == "main_menu":
                from utils.keyboards import get_main_menu_keyboard

                await query.edit_message_text(config.WELCOME_MESSAGE, parse_mode="Markdown")
                # Clear transient edit flags to avoid stray state
                context.user_data.pop("editing_field_for", None)
                context.user_data.pop("editing_schedule_for", None)
                context.user_data.pop("awaiting_symptom_text", None)
                context.user_data.pop("editing_symptom_log", None)
                context.user_data.pop("suppress_menu_mapping", None)
                await self.application.bot.send_message(
                    chat_id=query.message.chat_id, text="בחרו פעולה:", reply_markup=get_main_menu_keyboard()
                )
            elif data.startswith("medicine_") or data.startswith("medicines_"):
                # Route to internal medicine action handler which covers all medicine flows
                await self._handle_medicine_action(update, query, context)
                return
            elif data == "medicine_next_page":
                # TODO: implement paging; for now just re-render list (simple UX)
                await self._handle_medicine_action(update, query, context)
                return
            elif data.startswith("rem_edit_"):
                # Open time selection for a medicine
                try:
                    medicine_id = int(data.split("_")[-1])
                except Exception:
                    await query.edit_message_text(config.ERROR_MESSAGES["general"])
                    return
                from utils.keyboards import get_time_selection_keyboard

                context.user_data["editing_schedule_for"] = medicine_id
                await query.edit_message_text(
                    "בחרו שעה חדשה לנטילת התרופה או הזינו שעה (לדוגמה 08:30)", reply_markup=get_time_selection_keyboard()
                )
                return
            elif data == "rem_pick_medicine_for_time":
                # From empty reminders screen: pick medicine then choose hour
                user = await DatabaseManager.get_user_by_telegram_id(user_id)
                meds = await DatabaseManager.get_user_medicines(user.id) if user else []
                if not meds:
                    await query.edit_message_text("אין תרופות זמינות להוספת שעות.")
                    return
                from utils.keyboards import get_medicines_keyboard

                # Reuse medicines list; user clicks a medicine and then can choose שעות
                await query.edit_message_text("בחרו תרופה להוספת שעה:", reply_markup=get_medicines_keyboard(meds))
                return
            elif data.startswith("rem_disable_"):
                # Disable reminder by deactivating medicine
                try:
                    medicine_id = int(data.split("_")[-1])
                except Exception:
                    await query.edit_message_text(config.ERROR_MESSAGES["general"])
                    return
                med = await DatabaseManager.get_medicine_by_id(medicine_id)
                if not med:
                    await query.edit_message_text(config.ERROR_MESSAGES["medicine_not_found"])
                    return
                await DatabaseManager.set_medicine_active(medicine_id, False)
                await query.edit_message_text(f"{config.EMOJES['success']} התזכורת בוטלה לתרופה {med.name}")
                return
            elif data == "symptoms_menu":
                await self.log_symptoms_command(update, context)
                return
            elif data.startswith("mededit_"):
                # mededit_name_<id>, mededit_dosage_<id>, mededit_notes_<id>, mededit_packsize_<id>
                parts = data.split("_")
                action = parts[1] if len(parts) > 1 else ""
                mid = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
                if not mid:
                    await query.edit_message_text(config.ERROR_MESSAGES["general"])
                    return
                if action == "packsize":
                    context.user_data["editing_field_for"] = {"id": mid, "field": "packsize"}
                    await query.edit_message_text("הקלידו גודל חבילה (למשל 30):")
                    context.user_data["suppress_menu_mapping"] = True
                    return
                # For name/dosage/notes, prompt text input
                context.user_data["editing_field_for"] = {"id": mid, "field": action}
                prompt = {
                    "name": "הקלידו שם חדש לתרופה:",
                    "dosage": "הקלידו מינון חדש:",
                    "notes": "הקלידו הערות (טקסט חופשי):",
                }.get(action, "הקלידו ערך חדש:")
                await query.edit_message_text(prompt)
                # Avoid main-menu text mapping hijacking next text
                context.user_data["suppress_menu_mapping"] = True
                return
            elif data == "reminders_menu":
                from handlers import reminder_handler

                await reminder_handler.show_next_reminders(update, context)
                return
            elif data.startswith("settings_") or data.startswith("tz_"):
                await self._handle_settings_action(update, context)
            elif data.startswith("report_") or data.startswith("report_action_") or data.startswith("export_report_"):
                # Routed by reports handler; do nothing here (already registered)
                return
            # Confirmation dialogs (generic)
            elif data.startswith("symdel_"):
                parts = data.split("_")
                if parts[-1] == "confirm":
                    log_id = int(parts[-2])
                    ok = await DatabaseManager.delete_symptom_log(log_id)
                    await query.edit_message_text(
                        f"{config.EMOJES['success']} הרישום נמחק" if ok else f"{config.EMOJES['error']} הרישום לא נמצא"
                    )
                    return
                elif parts[-1] == "cancel":
                    await query.edit_message_text("בוטל")
                    return
            elif data.startswith("meddel_"):
                parts = data.split("_")
                if parts[-1] == "confirm":
                    medicine_id = int(parts[-2])
                    user = await DatabaseManager.get_user_by_telegram_id(query.from_user.id)
                    await medicine_scheduler.cancel_medicine_reminders(user.id, medicine_id)
                    ok = await DatabaseManager.delete_medicine(medicine_id)
                    # After deletion, show the medicines list page at current offset (if any in context)
                    offset = context.user_data.get("med_list_offset", 0)
                    db_user = await DatabaseManager.get_user_by_telegram_id(user.id)
                    meds = await DatabaseManager.get_user_medicines(db_user.id) if db_user else []
                    message = (
                        f"{config.EMOJES['success']} התרופה נמחקה" if ok else f"{config.EMOJES['error']} התרופה לא נמצאה"
                    ) + "\n\n"
                    if not meds:
                        message += f"{config.EMOJES['info']} אין תרופות רשומות"
                    else:
                        message += f"{config.EMOJES['medicine']} <b>התרופות שלכם:</b>\n\n"
                        slice_start = max(0, int(offset))
                        slice_end = slice_start + config.MAX_MEDICINES_PER_PAGE
                        for med in meds[slice_start:slice_end]:
                            status_emoji = config.EMOJES["success"] if med.is_active else config.EMOJES["error"]
                            inv_warn = f" {config.EMOJES['warning']}" if med.inventory_count <= med.low_stock_threshold else ""
                            message += f"{status_emoji} <b>{med.name}</b>\n   💊 {med.dosage}\n   📦 מלאי: {med.inventory_count}{inv_warn}\n\n"
                    from utils.keyboards import get_medicines_keyboard

                    await query.edit_message_text(
                        message, parse_mode="HTML", reply_markup=get_medicines_keyboard(meds if meds else [], offset=offset)
                    )
                    return
                elif parts[-1] == "cancel":
                    await query.edit_message_text("בוטל")
                    return
            # Reminders settings controls
            elif (
                data.startswith("rsnoop_")
                or data.startswith("rattempts_")
                or data == "rsilent_toggle"
                or data == "settings_menu"
            ):
                await self._handle_reminders_settings_controls(query)
                return
            # Inventory main controls
            elif data in ("inventory_add", "inventory_report"):
                await self._handle_inventory_controls(query, context)
                return
            elif data.startswith("inventory_"):
                # Handled by medicine handler conversation entry points
                return
            elif data.startswith("caregiver_"):
                # Routed by caregiver handler; do nothing here
                return
            elif data.startswith("symptoms_"):
                # Minimal inline handling for symptoms
                if data.startswith("symptoms_log_med_"):
                    # bind next text to a specific medicine id
                    try:
                        med_id = int(data.split("_")[-1])
                    except Exception:
                        await query.edit_message_text(config.ERROR_MESSAGES["general"])
                        return
                    med = await DatabaseManager.get_medicine_by_id(med_id)
                    if not med:
                        await query.edit_message_text(config.ERROR_MESSAGES["medicine_not_found"])
                        return
                    context.user_data["symptoms_for_medicine"] = med_id
                    from utils.keyboards import get_symptoms_keyboard

                    await query.edit_message_text(f"מעקב תופעות עבור {med.name}:", reply_markup=get_symptoms_keyboard())
                    return
                if data == "symptoms_log":
                    # Require medicine selection first; if not selected, show picker
                    user = await DatabaseManager.get_user_by_telegram_id(user_id)
                    meds = await DatabaseManager.get_user_medicines(user.id) if user else []
                    if not context.user_data.get("symptoms_for_medicine") and meds:
                        from utils.keyboards import get_symptoms_medicine_picker

                        await query.edit_message_text(
                            "בחרו תרופה לפני רישום תופעות:", reply_markup=get_symptoms_medicine_picker(meds)
                        )
                        return
                    await query.edit_message_text(
                        "שלחו עכשיו הודעה עם תיאור תופעות הלוואי שברצונכם לרשום.",
                    )
                    context.user_data["awaiting_symptom_text"] = True
                    return
                if data == "symptoms_history":
                    from utils.keyboards import get_symptoms_history_picker, get_symptom_logs_list_keyboard

                    user = await DatabaseManager.get_user_by_telegram_id(user_id)
                    # If a medicine was selected earlier for symptoms, show its history directly
                    med_selected = context.user_data.get("symptoms_for_medicine")
                    if med_selected:
                        from datetime import date, timedelta

                        end_date = date.today()
                        start_date = end_date - timedelta(days=30)
                        logs = await DatabaseManager.get_symptom_logs_in_range(
                            user.id, start_date, end_date, medicine_id=int(med_selected)
                        )
                        if not logs:
                            await query.edit_message_text("אין רישומי תופעות לוואי ב-30 הימים האחרונים")
                            return
                        await query.edit_message_text(
                            "רישומי 30 הימים האחרונים:", reply_markup=get_symptom_logs_list_keyboard(logs[-10:])
                        )
                        return
                    # Otherwise, show the history filter picker
                    meds = await DatabaseManager.get_user_medicines(user.id) if user else []
                    await query.edit_message_text(
                        "בחרו סינון להיסטוריית תופעות לוואי:", reply_markup=get_symptoms_history_picker(meds)
                    )
                    return
                if data == "symptoms_history_all" or data.startswith("symptoms_history_med_"):
                    from datetime import date, timedelta

                    user = await DatabaseManager.get_user_by_telegram_id(user_id)
                    end_date = date.today()
                    start_date = end_date - timedelta(days=30)
                    med_filter = None
                    if data.startswith("symptoms_history_med_"):
                        try:
                            med_filter = int(data.split("_")[-1])
                        except Exception:
                            med_filter = None
                    logs = await DatabaseManager.get_symptom_logs_in_range(
                        user.id, start_date, end_date, medicine_id=med_filter
                    )
                    if not logs:
                        await query.edit_message_text("אין רישומי תופעות לוואי ב-30 הימים האחרונים")
                        return
                    # Show list with per-item actions
                    from utils.keyboards import get_symptom_logs_list_keyboard

                    await query.edit_message_text(
                        "רישומי 30 הימים האחרונים:", reply_markup=get_symptom_logs_list_keyboard(logs[-10:])
                    )
                    return
                if data.startswith("symptoms_delete_"):
                    log_id = int(data.split("_")[-1])
                    from utils.keyboards import get_confirmation_keyboard

                    await query.edit_message_text(
                        "האם למחוק את הרישום?", reply_markup=get_confirmation_keyboard("symdel", log_id)
                    )
                    return
                if data.startswith("symptoms_edit_"):
                    log_id = int(data.split("_")[-1])
                    context.user_data["editing_symptom_log"] = log_id
                    await query.edit_message_text("שלחו את הטקסט המעודכן לרישום זה:")
                    return
                return
            elif data in ("invite_accept", "invite_reject"):
                code = context.user_data.get("pending_invite_code")
                if not code:
                    await query.edit_message_text("אין הזמנה ממתינה.")
                    return
                inv = await DatabaseManager.get_invite_by_code(code)
                if not inv or getattr(inv, "status", "active") != "active":
                    await query.edit_message_text("קוד לא תקף.")
                    return
                if data == "invite_reject":
                    await DatabaseManager.cancel_invite(code)
                    context.user_data.pop("pending_invite_code", None)
                    await query.edit_message_text("הזמנה בוטלה.")
                    return
                # accept: create caregiver linked to inv.user_id and set telegram id
                try:
                    # fetch or create caregiver with provided name
                    name = getattr(inv, "caregiver_name", None) or (query.from_user.full_name or "מטפל")
                    cg = await DatabaseManager.create_caregiver(
                        user_id=int(getattr(inv, "user_id")),
                        caregiver_telegram_id=query.from_user.id,
                        caregiver_name=name,
                        relationship="מטפל",
                        permissions="view",
                    )
                    await DatabaseManager.mark_invite_used(code)
                    context.user_data.pop("pending_invite_code", None)
                    await query.edit_message_text(f"{config.EMOJES['success']} הצטרפת כמטפל")
                except Exception:
                    await query.edit_message_text(config.ERROR_MESSAGES["general"])
                return
            else:
                # Ignore unknown callbacks silently to reduce confusion
                try:
                    await query.answer()
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Error in button callback: {e}")
            await query.edit_message_text(config.ERROR_MESSAGES["general"])

    async def _handle_dose_taken(self, query, context):
        """Handle dose taken confirmation"""
        medicine_id = int(query.data.split("_")[2])
        user = query.from_user

        # Log dose taken
        await DatabaseManager.log_dose_taken(medicine_id, datetime.now())

        # Update inventory
        medicine = await DatabaseManager.get_medicine_by_id(medicine_id)
        if medicine and medicine.inventory_count > 0:
            new_count = medicine.inventory_count - 1
            await DatabaseManager.update_inventory(medicine_id, new_count)

        # Reset reminder attempts
        reminder_key = f"{user.id}_{medicine_id}"
        medicine_scheduler.reminder_attempts[reminder_key] = 0

        await query.edit_message_text(
            f"{config.EMOJES['success']} נטילת התרופה אושרה!\n" f"מלאי נותר: {new_count if medicine else 'לא ידוע'} כדורים"
        )

    async def _handle_dose_snooze(self, query, context):
        """Handle dose snooze request"""
        medicine_id = int(query.data.split("_")[2])
        user_id = query.from_user.id

        # Schedule snooze reminder
        job_id = await medicine_scheduler.schedule_snooze_reminder(user_id, medicine_id)

        await query.edit_message_text(f"{config.EMOJES['clock']} תזכורת נדחתה ל-{config.REMINDER_SNOOZE_MINUTES} דקות")

    async def _handle_add_medicine_flow(self, update: Update, context):
        """Very simple add-medicine text flow: name -> dosage -> create"""
        try:
            user = update.effective_user
            db_user = await DatabaseManager.get_user_by_telegram_id(user.id)
            if not db_user:
                await update.message.reply_text("אנא התחילו עם /start")
                context.user_data.pop("adding_medicine", None)
                return
            state = context.user_data.get("adding_medicine", {})
            step = state.get("step")
            text = (update.message.text or "").strip()

            if step == "name":
                state["name"] = text
                state["step"] = "dosage"
                context.user_data["adding_medicine"] = state
                await update.message.reply_text("מה המינון? למשל: 10mg פעמיים ביום")
                return

            if step == "dosage":
                name = state.get("name")
                dosage = text
                # Create medicine with defaults
                await DatabaseManager.create_medicine(
                    user_id=db_user.id,
                    name=name,
                    dosage=dosage,
                )
                context.user_data.pop("adding_medicine", None)
                await update.message.reply_text(
                    f"{config.EMOJES['success']} התרופה נוספה בהצלחה!",
                )
                await self.my_medicines_command(update, context)
                return

            # Unknown step -> reset
            context.user_data.pop("adding_medicine", None)
            await update.message.reply_text(config.ERROR_MESSAGES["invalid_input"])
        except Exception as exc:
            logger.error(f"Error in _handle_add_medicine_flow: {exc}")
            context.user_data.pop("adding_medicine", None)
            await update.message.reply_text(config.ERROR_MESSAGES["general"])

    async def _handle_medicine_action(self, update: Update, query, context):
        """Handle medicine-related inline actions"""
        from utils.keyboards import (
            get_medicines_keyboard,
            get_medicine_detail_keyboard,
        )

        try:
            data = query.data
            user = query.from_user

            # Back to medicines list
            if data == "medicines_list" or data == "medicine_manage" or data.startswith("medicines_page_"):
                db_user = await DatabaseManager.get_user_by_telegram_id(user.id)
                medicines = await DatabaseManager.get_user_medicines(db_user.id) if db_user else []
                offset = 0
                if data.startswith("medicines_page_"):
                    try:
                        offset = int(data.split("_")[-1])
                    except Exception:
                        offset = 0
                header = ""
                if data == "medicine_manage":
                    header = f"{config.EMOJES['settings']} <b>מצב עריכת תרופות</b>\n\n"
                if not medicines:
                    message = (
                        header
                        + f"{config.EMOJES['info']} <b>אין תרופות רשומות</b>\n\nלחצו על /add_medicine כדי להוסיף תרופה ראשונה."
                    )
                else:
                    message = header + f"{config.EMOJES['medicine']} <b>התרופות שלכם:</b>\n\n"
                    slice_start = max(0, offset)
                    slice_end = slice_start + config.MAX_MEDICINES_PER_PAGE
                    for medicine in medicines[slice_start:slice_end]:
                        status_emoji = config.EMOJES["success"] if medicine.is_active else config.EMOJES["error"]
                        inventory_warning = ""
                        if medicine.inventory_count <= medicine.low_stock_threshold:
                            inventory_warning = f" {config.EMOJES['warning']}"
                        message += f"{status_emoji} <b>{medicine.name}</b>\n"
                        message += f"   💊 {medicine.dosage}\n"
                        message += f"   📦 מלאי: {medicine.inventory_count}{inventory_warning}\n\n"
                try:
                    await query.edit_message_text(
                        message,
                        parse_mode="HTML",
                        reply_markup=get_medicines_keyboard(medicines if medicines else [], offset=offset),
                    )
                except Exception as exc:
                    # Always send a fresh message if edit fails so user sees a change
                    await self.application.bot.send_message(
                        chat_id=query.message.chat_id,
                        text=message,
                        parse_mode="HTML",
                        reply_markup=get_medicines_keyboard(medicines if medicines else [], offset=offset),
                    )
                # Persist current offset for returns after actions
                context.user_data["med_list_offset"] = offset
                return

            # Add medicine flow entry point (prompt via inline)
            if data == "medicine_add":
                from utils.keyboards import get_cancel_keyboard

                message = f"""
{config.EMOJES['medicine']} <b>הוספת תרופה חדשה</b>

אנא שלחו את שם התרופה:
                """
                # Switch to conversation-like state
                context.user_data["adding_medicine"] = {"step": "name"}
                await query.edit_message_text(message, parse_mode="HTML")
                return

            # View one medicine details
            if data.startswith("medicine_view_"):
                medicine_id = int(data.split("_")[2])
                medicine = await DatabaseManager.get_medicine_by_id(medicine_id)
                if not medicine:
                    await query.edit_message_text(config.ERROR_MESSAGES["medicine_not_found"])
                    return
                details = [
                    f"{config.EMOJES['medicine']} <b>{medicine.name}</b>",
                    f"💊 מינון: {medicine.dosage}",
                    f"📦 מלאי: {medicine.inventory_count}",
                    f"⚙️ סטטוס: {'פעילה' if medicine.is_active else 'מושבתת'}",
                ]
                await query.edit_message_text(
                    "\n".join(details), parse_mode="HTML", reply_markup=get_medicine_detail_keyboard(medicine.id)
                )
                return

            # Inventory/schedule/edit/history/toggle actions - improved
            if data.startswith("medicine_inventory_"):
                # delegate detailed inventory handling (including +1/-1/custom) to handler
                if re := __import__("re"):
                    pass
                # If user clicked entry button, show keyboard
                parts = data.split("_")
                if len(parts) == 3:
                    medicine_id = int(parts[2])
                    from utils.keyboards import get_inventory_update_keyboard

                    med = await DatabaseManager.get_medicine_by_id(medicine_id)
                    pack = med.pack_size if med and med.pack_size else 28
                    await query.edit_message_text(
                        f"{config.EMOJES['inventory']} עדכון מלאי: {med.name}\nמלאי נוכחי: {med.inventory_count} כדורים\n\nבחרו הוספת כמות או הזינו סך מלאי מדויק:",
                        reply_markup=get_inventory_update_keyboard(medicine_id, pack),
                    )
                    return
                # Otherwise, forward inventory_* callbacks to handler
                from handlers.medicine_handler import medicine_handler

                await medicine_handler.handle_inventory_update(update=update, context=context)
                return

            if data.startswith("medicine_schedule_"):
                # Start schedule edit flow: show time selection keyboard
                from utils.keyboards import get_time_selection_keyboard

                context.user_data["editing_schedule_for"] = int(data.split("_")[2])
                await query.edit_message_text(
                    "בחרו שעה חדשה לנטילת התרופה או הזינו שעה (לדוגמה 08:30)", reply_markup=get_time_selection_keyboard()
                )
                return
            if data.startswith("medicine_delete_"):
                medicine_id = int(data.split("_")[2])
                from utils.keyboards import get_confirmation_keyboard

                await query.edit_message_text(
                    "האם למחוק את התרופה?", reply_markup=get_confirmation_keyboard("meddel", medicine_id)
                )
                return

            if data.startswith("medicine_edit_"):
                medicine_id = int(data.split("_")[2])
                message = (
                    "עריכת פרטי תרופה:\n"
                    "• שלחו שם חדש כדי לשנות שם\n"
                    "• הקלידו: מינון <טקסט> כדי לשנות מינון\n"
                    "• הקלידו: הערות <טקסט> כדי לעדכן הערות\n"
                    "• הקלידו: שעות HH:MM,HH:MM,.. כדי להחליף את כל השעות\n"
                    "• הקלידו: השבת או הפעל כדי לשנות סטטוס"
                )
                context.user_data["editing_medicine_for"] = medicine_id
                await query.edit_message_text(message)
                return

            if data.startswith("medicine_history_"):
                # Show last 30 days history for this specific medicine
                try:
                    medicine_id = int(data.split("_")[-1])
                except Exception:
                    await query.edit_message_text(config.ERROR_MESSAGES["general"])
                    return
                from datetime import date, timedelta

                end_date = date.today()
                start_date = end_date - timedelta(days=30)
                user = await DatabaseManager.get_user_by_telegram_id(query.from_user.id)
                if not user:
                    await query.edit_message_text(config.ERROR_MESSAGES["general"])
                    return
                logs = await DatabaseManager.get_symptom_logs_in_range(user.id, start_date, end_date, medicine_id=medicine_id)
                if not logs:
                    await query.edit_message_text("אין היסטוריה 30 ימים לתרופה זו")
                    return
                from utils.keyboards import get_symptom_logs_list_keyboard

                await query.edit_message_text(
                    f"היסטוריה (30 ימים) לתרופה {medicine_id}:", reply_markup=get_symptom_logs_list_keyboard(logs[-10:])
                )
                return
            # Add manage schedules and delete actions (via simple keywords)

            # Fallback
            await query.edit_message_text("פעולת תרופות לא נתמכת")
        except Exception as exc:
            logger.error(f"Error in _handle_medicine_action: {exc}")
            await query.edit_message_text(config.ERROR_MESSAGES["general"])

    async def _handle_settings_action(self, update: Update, context):
        """Handle settings-related inline actions (works with CallbackQuery or Message)."""
        try:
            query = update.callback_query
            data = query.data if query else ""
            if data == "settings_timezone":
                # Minimal timezone selector
                zones = ["UTC", "Asia/Jerusalem", "Europe/London", "America/New_York"]
                rows = []
                for z in zones:
                    rows.append([InlineKeyboardButton(z, callback_data=f"tz_{z}")])
                rows.append([InlineKeyboardButton("הקלד אזור זמן", callback_data="tz_custom")])
                rows.append([InlineKeyboardButton(f"{config.EMOJES['back']} חזור", callback_data="main_menu")])
                if query:
                    await query.edit_message_text("בחרו אזור זמן:", reply_markup=InlineKeyboardMarkup(rows))
            elif data == "tz_custom":
                context.user_data["awaiting_timezone_text"] = True
                await query.edit_message_text("הקלידו את אזור הזמן (למשל Asia/Jerusalem, Europe/Berlin או GMT+3)")
            elif data.startswith("tz_"):
                # Apply selected timezone only for recognized values
                tz = data[3:]
                allowed = {"UTC", "Asia/Jerusalem", "Europe/London", "America/New_York"}
                if tz not in allowed:
                    await query.edit_message_text("אזור זמן לא נתמך.")
                    return
                user = await DatabaseManager.get_user_by_telegram_id(query.from_user.id)
                await DatabaseManager.update_user_timezone(user.id, tz)
                await query.edit_message_text(f"{config.EMOJES['success']} עודכן אזור הזמן ל- {tz}")
            elif data == "settings_reminders":
                # Show full reminders settings UI
                user = await DatabaseManager.get_user_by_telegram_id(query.from_user.id)
                settings = await DatabaseManager.get_user_settings(user.id)
                msg = (
                    f"{config.EMOJES['reminder']} הגדרות תזכורות\n\n"
                    f"דחיית תזכורת: {settings.snooze_minutes} דקות\n"
                    f"מספר ניסיונות תזכורת: {settings.max_attempts}\n"
                    f"מצב שקט: {'מופעל' if settings.silent_mode else 'כבוי'}\n"
                )
                await query.edit_message_text(
                    msg,
                    parse_mode="Markdown",
                    reply_markup=get_reminders_settings_keyboard(
                        settings.snooze_minutes, settings.max_attempts, settings.silent_mode
                    ),
                )

            elif data == "settings_inventory":
                await query.edit_message_text("הגדרות מלאי בסיסיות: התראות מלאי נמוכים מופעלות.")
            elif data == "settings_caregivers":
                await query.edit_message_text("ניהול מטפלים זמין דרך תפריט 'מטפלים'.")
            elif data == "settings_reports":
                # Show report settings placeholder rather than opening reports center
                await query.edit_message_text(
                    f"{config.EMOJES['report']} הגדרות דוחות יתווספו בקרוב (בחירת תדירות, ערוצים)",
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton(f"{config.EMOJES['back']} חזור", callback_data="settings_menu")]]
                    ),
                )
                return
            elif data == "settings_appointments":
                await appointments_handler.show_menu(query, context)
                return
            elif data == "settings_menu":
                from utils.keyboards import get_settings_keyboard

                await query.edit_message_text(
                    f"{config.EMOJES['settings']} *הגדרות אישיות*", parse_mode="Markdown", reply_markup=get_settings_keyboard()
                )
                return
            else:
                await query.edit_message_text("הגדרות לא נתמכות")
        except Exception as exc:
            logger.error(f"Error in _handle_settings_action: {exc}")
            await query.edit_message_text(config.ERROR_MESSAGES["general"])

    async def handle_text_message(self, update: Update, context):
        """Handle regular text messages (for conversation flows)"""
        try:
            # Route appointment flow text first if active
            if context.user_data.get("appt_state"):
                try:
                    await appointments_handler.handle_text(update, context)
                    return
                except Exception:
                    pass

            # This would handle conversation states for adding medicines, etc.
            # For now, just acknowledge
            user_data = context.user_data

            text = (update.message.text or "").strip()

            # Route main menu buttons by text
            from utils.keyboards import (
                get_main_menu_keyboard,
                get_medicines_keyboard,
                get_medicine_detail_keyboard,
                get_settings_keyboard,
                get_caregiver_keyboard,
                get_symptoms_keyboard,
                get_reports_keyboard,
            )

            mapping = {
                f"{config.EMOJES['medicine']} התרופות שלי": "my_medicines",
                f"{config.EMOJES['reminder']} תזכורות": "reminders",
                f"{config.EMOJES['inventory']} מלאי": "inventory",
                f"{config.EMOJES['symptoms']} תופעות לוואי": "symptoms",
                f"{config.EMOJES['report']} דוחות": "reports",
                f"{config.EMOJES['caregiver']} מטפלים": "caregivers",
                f"{config.EMOJES['calendar']} הוספת תור": "appointments",
                f"{config.EMOJES['settings']} הגדרות": "settings",
                f"{config.EMOJES['info']} עזרה": "help",
            }

            # If user pressed a main menu button, navigate immediately and clear edit states
            if text in mapping:
                # Clear transient edit states to avoid misinterpreting navigation as edits
                for k in (
                    "editing_medicine_for",
                    "editing_field_for",
                    "editing_schedule_for",
                    "updating_inventory_for",
                    "awaiting_symptom_text",
                    "editing_symptom_log",
                    "suppress_menu_mapping",
                ):
                    user_data.pop(k, None)
                action = mapping[text]
                if action == "my_medicines" or action == "inventory":
                    if action == "inventory":
                        await self._open_inventory_center(update)
                    else:
                        await self.my_medicines_command(update, context)
                    return
                if action == "reminders":
                    from handlers import reminder_handler

                    await reminder_handler.show_next_reminders(update, context)
                    return
                if action == "settings":
                    await self.settings_command(update, context)
                    return
                if action == "caregivers":
                    from utils.keyboards import get_caregiver_keyboard

                    await update.message.reply_text("ניהול מטפלים:", reply_markup=get_caregiver_keyboard())
                    return
                if action == "symptoms":
                    await self.log_symptoms_command(update, context)
                    return
                if action == "reports":
                    from handlers import reports_handler

                    await reports_handler.show_reports_menu(update, context)
                    return
                if action == "appointments":
                    await appointments_handler.show_menu(update, context)
                    return
                if action == "help":
                    await self.help_command(update, context)
                    return

            # Handle mededit text inputs
            if "editing_field_for" in user_data:
                info = user_data.pop("editing_field_for")
                user_data.pop("suppress_menu_mapping", None)
                mid = int(info.get("id"))
                field = info.get("field")
                if field == "name" and len(text) >= 2:
                    await DatabaseManager.update_medicine(mid, name=text)
                    await update.message.reply_text(f"{config.EMOJES['success']} שם התרופה עודכן")
                    await self.my_medicines_command(update, context)
                    return
                if field == "dosage" and len(text) >= 1:
                    await DatabaseManager.update_medicine(mid, dosage=text)
                    await update.message.reply_text(f"{config.EMOJES['success']} המינון עודכן")
                    await self.my_medicines_command(update, context)
                    return
                if field == "notes":
                    await DatabaseManager.update_medicine(mid, notes=text)
                    await update.message.reply_text(f"{config.EMOJES['success']} ההערות עודכנו")
                    await self.my_medicines_command(update, context)
                    return
                if field == "packsize" and text.isdigit():
                    await DatabaseManager.update_medicine(mid, pack_size=int(text))
                    await update.message.reply_text(f"{config.EMOJES['success']} גודל החבילה עודכן")
                    await self.my_medicines_command(update, context)
                    return
                # Fallback
                await update.message.reply_text(config.ERROR_MESSAGES["invalid_input"])
                return

            # Inventory update inline flow via text (fallback if conversation isn't active)
            if "updating_inventory_for" in user_data or "adding_inventory_for" in user_data:
                medicine_id = user_data.get("updating_inventory_for") or user_data.get("adding_inventory_for")
                try:
                    delta_or_total = float(text)
                    if delta_or_total < 0:
                        raise ValueError("Negative inventory")
                except ValueError:
                    await update.message.reply_text("אנא הזינו מספר תקין לכמות המלאי")
                    return
                # Compute final count
                med = await DatabaseManager.get_medicine_by_id(int(medicine_id))
                if not med:
                    await update.message.reply_text(config.ERROR_MESSAGES["medicine_not_found"])
                    user_data.pop("updating_inventory_for", None)
                    user_data.pop("adding_inventory_for", None)
                    user_data.pop("awaiting_add_quantity", None)
                    return
                if user_data.get("awaiting_add_quantity"):
                    final_count = float(med.inventory_count) + delta_or_total
                else:
                    final_count = delta_or_total
                await DatabaseManager.update_inventory(int(medicine_id), final_count)
                # Success message similar to conversation handler
                status_msg = ""
                if final_count <= med.low_stock_threshold:
                    status_msg = f"\n{config.EMOJES['warning']} מלאי נמוך!"
                from utils.keyboards import get_medicine_detail_keyboard

                message = f"""
{config.EMOJES['success']} <b>מלאי עודכן בהצלחה!</b>

{config.EMOJES['medicine']} {med.name}
📦 מלאי חדש: {int(final_count)} כדורים{status_msg}
                """
                await update.message.reply_text(
                    message, parse_mode="HTML", reply_markup=get_medicine_detail_keyboard(int(medicine_id))
                )
                # Clean flags
                user_data.pop("updating_inventory_for", None)
                user_data.pop("adding_inventory_for", None)
                user_data.pop("awaiting_add_quantity", None)
                return
            # Schedule edit flow via text (time input HH:MM)
            if "editing_schedule_for" in user_data:
                medicine_id = int(user_data.get("editing_schedule_for"))
                # Validate HH:MM
                import re

                if not re.match(r"^\d{1,2}:\d{2}$", text):
                    await update.message.reply_text("אנא הזינו שעה בפורמט HH:MM, למשל 08:30")
                    return
                hours, minutes = text.split(":")
                try:
                    h = int(hours)
                    m = int(minutes)
                    from datetime import time as dtime

                    new_time = dtime(hour=h, minute=m)
                except Exception:
                    await update.message.reply_text("שעה לא תקינה")
                    return
                # Replace or add a schedule time (avoid duplicates)
                times = [new_time]
                await DatabaseManager.replace_medicine_schedules(medicine_id, times)
                # Re-schedule reminders for this time
                user = await DatabaseManager.get_user_by_telegram_id(update.effective_user.id)
                await medicine_scheduler.cancel_medicine_reminders(user.id, medicine_id)
                await medicine_scheduler.schedule_medicine_reminder(
                    user_id=user.id,
                    medicine_id=medicine_id,
                    reminder_time=new_time,
                    timezone=user.timezone or config.DEFAULT_TIMEZONE,
                )
                user_data.pop("editing_schedule_for", None)
                await update.message.reply_text(f"{config.EMOJES['success']} השעה עודכנה ל- {new_time.strftime('%H:%M')}")
                # Show medicine details
                med = await DatabaseManager.get_medicine_by_id(medicine_id)
                from utils.keyboards import get_medicine_detail_keyboard

                await update.message.reply_text(
                    f"{config.EMOJES['medicine']} {med.name}", reply_markup=get_medicine_detail_keyboard(medicine_id)
                )
                return
            # Edit medicine free-text commands
            if "editing_medicine_for" in user_data:
                mid = int(user_data.get("editing_medicine_for"))
                lower = text.strip()
                # Replace all schedule times: הקלד: שעות HH:MM,HH:MM
                if lower.startswith("שעות "):
                    parts = lower.split(" ", 1)[1].split(",")
                    from datetime import time as dtime

                    new_times = []
                    for p in parts:
                        p = p.strip()
                        if not p:
                            continue
                        if ":" not in p:
                            await update.message.reply_text("פורמט שעה לא תקין. דוגמה: שעות 08:00,14:30")
                            return
                        hh, mm = p.split(":", 1)
                        new_times.append(dtime(hour=int(hh), minute=int(mm)))
                    # Replace in DB
                    await DatabaseManager.replace_medicine_schedules(mid, new_times)
                    # Unschedule then reschedule
                    user = await DatabaseManager.get_user_by_telegram_id(update.effective_user.id)
                    await medicine_scheduler.cancel_medicine_reminders(user.id, mid)
                    for t in new_times:
                        await medicine_scheduler.schedule_medicine_reminder(
                            user.id, mid, t, user.timezone or config.DEFAULT_TIMEZONE
                        )
                    await update.message.reply_text(f"{config.EMOJES['success']} שעות הוחלפו")
                    user_data.pop("editing_medicine_for", None)
                    await self.my_medicines_command(update, context)
                    return
                # Delete medicine: הקלד: מחק
                if lower == "מחק":
                    user = await DatabaseManager.get_user_by_telegram_id(update.effective_user.id)
                    await medicine_scheduler.cancel_medicine_reminders(user.id, mid)
                    ok = await DatabaseManager.delete_medicine(mid)
                    if ok:
                        await update.message.reply_text(f"{config.EMOJES['success']} התרופה נמחקה")
                    else:
                        await update.message.reply_text(f"{config.EMOJES['error']} שגיאה במחיקה")
                    user_data.pop("editing_medicine_for", None)
                    await self.my_medicines_command(update, context)
                    return
                if lower.startswith("מינון "):
                    new_dosage = text.split(" ", 1)[1].strip()
                    await DatabaseManager.update_medicine(mid, dosage=new_dosage)
                    await update.message.reply_text(f"{config.EMOJES['success']} המינון עודכן")
                    user_data.pop("editing_medicine_for", None)
                    await self.my_medicines_command(update, context)
                    return
                if lower.startswith("הערות "):
                    new_notes = text.split(" ", 1)[1].strip()
                    await DatabaseManager.update_medicine(mid, notes=new_notes)
                    await update.message.reply_text(f"{config.EMOJES['success']} ההערות עודכנו")
                    user_data.pop("editing_medicine_for", None)
                    await self.my_medicines_command(update, context)
                    return

                # Otherwise treat as rename
                if len(text.strip()) >= 2:
                    await DatabaseManager.update_medicine(mid, name=text.strip())
                    await update.message.reply_text(f"{config.EMOJES['success']} שם התרופה עודכן")
                    user_data.pop("editing_medicine_for", None)
                    await self.my_medicines_command(update, context)
                    return

            if user_data.get("suppress_menu_mapping"):
                # ignore one-time menu mapping after edit prompt
                user_data.pop("suppress_menu_mapping", None)
            elif text in mapping:
                action = mapping[text]
                if action == "my_medicines" or action == "inventory":
                    # Inventory from main menu goes to a simple inventory center
                    if action == "inventory":
                        await self._open_inventory_center(update)
                    else:
                        await self.my_medicines_command(update, context)
                    return
                if action == "reminders":
                    # Rich reminders menu
                    from handlers import reminder_handler

                    await reminder_handler.show_next_reminders(update, context)
                    return
                if action == "settings":
                    await self.settings_command(update, context)
                    return
                if action == "caregivers":
                    from utils.keyboards import get_caregiver_keyboard

                    await update.message.reply_text("ניהול מטפלים:", reply_markup=get_caregiver_keyboard())
                    return
                if action == "symptoms":
                    await self.log_symptoms_command(update, context)
                    return
                if action == "reports":
                    from handlers import reports_handler

                    await reports_handler.show_reports_menu(update, context)
                    return
                if action == "appointments":
                    await appointments_handler.show_menu(update, context)
                    return
                if action == "help":
                    await self.help_command(update, context)
                    return

            if "adding_medicine" in user_data:
                await self._handle_add_medicine_flow(update, context)
            else:
                # Save symptom text if awaiting
                if user_data.get("awaiting_symptom_text"):
                    try:
                        user = await DatabaseManager.get_user_by_telegram_id(update.effective_user.id)
                        from datetime import datetime as dt

                        # If tied to a specific medicine from quick action, include name prefix
                        med_prefix = None
                        med_id = user_data.get("symptoms_for_medicine")
                        entry_text = text
                        if med_id:
                            med = await DatabaseManager.get_medicine_by_id(int(med_id))
                            med_prefix = med.name if med else None
                        if med_prefix:
                            entry_text = f"[{med_prefix}] {entry_text}"
                        await DatabaseManager.create_symptom_log(
                            user_id=user.id,
                            log_date=dt.utcnow(),
                            symptoms=entry_text,
                            medicine_id=int(med_id) if med_id else None,
                        )
                        user_data.pop("awaiting_symptom_text", None)
                        user_data.pop("symptoms_for_medicine", None)
                        from utils.keyboards import get_main_menu_keyboard

                        await update.message.reply_text(
                            f"{config.EMOJES['success']} נרשם. תודה!", reply_markup=get_main_menu_keyboard()
                        )
                        return
                    except Exception as exc:
                        logger.error(f"Error saving symptom: {exc}")
                        await update.message.reply_text(config.ERROR_MESSAGES["general"])
                        user_data.pop("awaiting_symptom_text", None)
                        return
                # Save timezone if awaiting text
                if user_data.get("awaiting_timezone_text"):
                    from utils.helpers import normalize_timezone

                    zone = (text or "").strip()
                    ok, normalized, display = normalize_timezone(zone)
                    if not ok or not normalized:
                        await update.message.reply_text(
                            "אנא הזינו אזור זמן תקין (למשל Asia/Jerusalem, Europe/Berlin או GMT+3)"
                        )
                        return
                    user = await DatabaseManager.get_user_by_telegram_id(update.effective_user.id)
                    await DatabaseManager.update_user_timezone(user.id, normalized)
                    user_data.pop("awaiting_timezone_text", None)
                    await update.message.reply_text(f"{config.EMOJES['success']} עודכן אזור הזמן ל- {display}")
                    return
                # Edit symptom log text if awaiting
                if user_data.get("editing_symptom_log"):
                    log_id = int(user_data.get("editing_symptom_log"))
                    await DatabaseManager.update_symptom_log(log_id, symptoms=text)
                    user_data.pop("editing_symptom_log", None)
                    await update.message.reply_text(f"{config.EMOJES['success']} הרישום עודכן")
                    return
                await update.message.reply_text("השתמשו בתפריט או בפקודות. /help לעזרה")

        except Exception as e:
            logger.error(f"Error handling text message: {e}")
            await update.message.reply_text(config.ERROR_MESSAGES["general"])

    async def error_handler(self, update: Update, context):
        """Handle errors"""
        logger.error(f"Exception while handling update {update}: {context.error}")

        if update and update.effective_message:
            await update.effective_message.reply_text(config.ERROR_MESSAGES["general"])

    async def _handle_reminders_settings_controls(self, query):
        try:
            data = query.data
            user = await DatabaseManager.get_user_by_telegram_id(query.from_user.id)
            settings = await DatabaseManager.get_user_settings(user.id)
            if data.startswith("rsnoop_"):
                delta = 1 if data.endswith("+1") else -1
                new_val = max(1, min(120, settings.snooze_minutes + delta))
                settings = await DatabaseManager.update_user_settings(user.id, snooze_minutes=new_val)
            elif data.startswith("rattempts_"):
                delta = 1 if data.endswith("+1") else -1
                new_val = max(1, min(10, settings.max_attempts + delta))
                settings = await DatabaseManager.update_user_settings(user.id, max_attempts=new_val)
            elif data == "rsilent_toggle":
                settings = await DatabaseManager.update_user_settings(user.id, silent_mode=not settings.silent_mode)
            elif data == "settings_menu":
                from utils.keyboards import get_settings_keyboard

                await query.edit_message_text(
                    f"{config.EMOJES['settings']} *הגדרות אישיות*", parse_mode="Markdown", reply_markup=get_settings_keyboard()
                )
                return
            # Refresh UI
            msg = (
                f"{config.EMOJES['reminder']} הגדרות תזכורות\n\n"
                f"דחיית תזכורת: {settings.snooze_minutes} דקות\n"
                f"מספר ניסיונות תזכורת: {settings.max_attempts}\n"
                f"מצב שקט: {'מופעל' if settings.silent_mode else 'כבוי'}\n"
            )
            await query.edit_message_text(
                msg,
                parse_mode="Markdown",
                reply_markup=get_reminders_settings_keyboard(
                    settings.snooze_minutes, settings.max_attempts, settings.silent_mode
                ),
            )
        except Exception as exc:
            logger.error(f"Error in _handle_reminders_settings_controls: {exc}")
            await query.edit_message_text(config.ERROR_MESSAGES["general"])

    async def _open_inventory_center(self, update):
        try:
            # Show inventory overview with actions
            from database import DatabaseManager

            user = await DatabaseManager.get_user_by_telegram_id(update.effective_user.id)
            meds = await DatabaseManager.get_user_medicines(user.id)
            low = [m for m in meds if m.inventory_count <= m.low_stock_threshold]
            msg = f"{config.EMOJES['inventory']} מרכז המלאי\n\n"
            if not meds:
                msg += "אין תרופות במערכת. הוסיפו תרופה דרך 'התרופות שלי'."
            else:
                msg += f'סה"כ תרופות: {len(meds)} | נמוך: {len(low)}\n'
                for m in meds[:10]:
                    warn = f" {config.EMOJES['warning']}" if m.inventory_count <= m.low_stock_threshold else ""
                    msg += f"• {m.name} — {m.inventory_count} {warn}\n"
                if len(meds) > 10:
                    msg += f"ועוד {len(meds)-10}...\n"
            await update.message.reply_text(msg, reply_markup=get_inventory_main_keyboard())
        except Exception as exc:
            logger.error(f"Error in _open_inventory_center: {exc}")
            await update.message.reply_text(config.ERROR_MESSAGES["general"])

    async def _handle_inventory_controls(self, query, context):
        try:
            data = query.data
            if data == "inventory_report":
                from handlers import reports_handler

                # Use existing inventory report generator
                await reports_handler.start_custom_report(query, context)
                return
            if data == "inventory_add":
                # Reuse medicines list and then per-medicine inventory keyboard
                user = await DatabaseManager.get_user_by_telegram_id(query.from_user.id)
                meds = await DatabaseManager.get_user_medicines(user.id)
                if not meds:
                    await query.edit_message_text("אין תרופות להוספת מלאי.")
                    return
                from utils.keyboards import get_medicines_keyboard

                await query.edit_message_text("בחרו תרופה לעדכון מלאי:", reply_markup=get_medicines_keyboard(meds))
                return
        except Exception as exc:
            logger.error(f"Error in _handle_inventory_controls: {exc}")
            await query.edit_message_text(config.ERROR_MESSAGES["general"])

    async def run_webhook(self):
        """Run bot in webhook mode (for production) with health endpoint."""
        try:
            webhook_url = config.get_webhook_url()
            if not webhook_url:
                raise ValueError("Webhook URL not configured")

            logger.info(f"Starting webhook server on port {config.WEBHOOK_PORT}")
            logger.info(f"Webhook URL: {webhook_url}")

            # Initialize and start application
            await self.application.initialize()
            await self.application.start()

            # Configure webhook at Telegram side with secret token
            secret_token = config.BOT_TOKEN[-32:] if len(config.BOT_TOKEN) >= 32 else None
            await self.application.bot.set_webhook(
                url=webhook_url, allowed_updates=["message", "callback_query"], secret_token=secret_token
            )

            # Build aiohttp app with /health and webhook handlers
            app = web.Application()

            async def health_handler(request):
                return web.Response(text="OK", content_type="text/plain")

            async def root_handler(request):
                return web.Response(text="OK", content_type="text/plain")

            async def telegram_webhook_handler(request):
                # Optional secret token validation
                if secret_token:
                    received = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
                    if received != secret_token:
                        return web.Response(status=401, text="Invalid secret token")
                try:
                    data = await request.json()
                except Exception:
                    return web.Response(status=400, text="Invalid JSON")
                try:
                    update = Update.de_json(data, self.application.bot)
                    await self.application.process_update(update)
                except Exception as exc:
                    logger.error(f"Failed to process update: {exc}")
                    return web.Response(status=500, text="Failed to process update")
                return web.Response(text="OK")

            # Routes
            app.router.add_get("/health", health_handler)
            app.router.add_get("/", root_handler)
            app.router.add_post(config.WEBHOOK_PATH, telegram_webhook_handler)

            runner = web.AppRunner(app)
            self._runner = runner
            await runner.setup()
            site = web.TCPSite(runner, host="0.0.0.0", port=config.WEBHOOK_PORT)
            await site.start()

            logger.info("Webhook server is up")

            # Wait until shutdown is requested
            self._serve_forever_event = asyncio.Event()
            try:
                await self._serve_forever_event.wait()
            except asyncio.CancelledError:
                logger.debug("Webhook run cancelled - shutting down")
            finally:
                try:
                    await runner.cleanup()
                except Exception as cleanup_exc:
                    logger.warning(f"Error during webhook server cleanup: {cleanup_exc}")

        except Exception as e:
            logger.error(f"Failed to run webhook: {e}")
            raise

    # Removed sync webhook runner to avoid Python 3.13 event loop issues

    async def run_polling(self):
        """Run bot in polling mode (for development)"""
        try:
            logger.info("Starting bot in polling mode...")

            await self.application.initialize()
            await self.application.start()

            # Delete webhook (in case it was set before)
            await self.application.bot.delete_webhook()

            # Start polling
            await self.application.run_polling(allowed_updates=["message", "callback_query"], drop_pending_updates=True)

        except Exception as e:
            logger.error(f"Failed to run polling: {e}")
            raise

    async def shutdown(self):
        """Graceful shutdown"""
        logger.info("Shutting down bot...")

        # Prevent duplicate shutdowns
        if self._shutdown_started:
            return
        self._shutdown_started = True

        # Signal the webhook runner (if any) to stop blocking
        try:
            if self._serve_forever_event and not self._serve_forever_event.is_set():
                self._serve_forever_event.set()
        except Exception:
            pass

        try:
            # Stop scheduler
            await medicine_scheduler.stop()

            # Stop application
            if self.application:
                await self.application.stop()
                await self.application.shutdown()

            logger.info("Bot shutdown completed")

        except asyncio.CancelledError:
            logger.debug("Shutdown cancelled by event loop")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")


async def main():
    """Main entry point"""
    bot = MedicineReminderBot()

    # Use event-based signal handling to reduce CancelledError noise on shutdown
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGINT, stop_event.set)
        loop.add_signal_handler(signal.SIGTERM, stop_event.set)
    except NotImplementedError:
        # Fallback for environments without add_signal_handler
        signal.signal(signal.SIGINT, lambda *_: asyncio.create_task(bot.shutdown()))
        signal.signal(signal.SIGTERM, lambda *_: asyncio.create_task(bot.shutdown()))

    try:
        # Initialize bot
        await bot.initialize()

        # Start run task according to environment
        if config.is_production():
            run_task = asyncio.create_task(bot.run_webhook())
        else:
            run_task = asyncio.create_task(bot.run_polling())

        # Wait for either stop signal or task completion
        stop_task = asyncio.create_task(stop_event.wait())
        await asyncio.wait({run_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)

    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Critical error: {e}")
        raise
    finally:
        await bot.shutdown()
        # Ensure run task is finished/cleaned
        try:
            await asyncio.wait_for(run_task, timeout=10)
        except Exception:
            pass


if __name__ == "__main__":
    # Entry point for the application
    asyncio.run(main())
