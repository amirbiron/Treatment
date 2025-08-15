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
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler, 
    CallbackQueryHandler,
    ConversationHandler,
    filters
)
from telegram.error import TelegramError
from aiohttp import web
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config import config
from database import init_database, DatabaseManager
from scheduler import medicine_scheduler
from handlers.reports_handler import reports_handler
from utils.keyboards import get_reminders_settings_keyboard, get_inventory_main_keyboard

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, config.LOG_LEVEL)
)
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
            telegram_id = user.id
            
            # Get or create user in database
            db_user = await DatabaseManager.get_user_by_telegram_id(telegram_id)
            if not db_user:
                db_user = await DatabaseManager.create_user(
                    telegram_id=telegram_id,
                    username=user.username,
                    first_name=user.first_name,
                    last_name=user.last_name
                )
                logger.info(f"Created new user: {telegram_id}")
            
            # Send welcome message with main menu
            from utils.keyboards import get_main_menu_keyboard
            
            await update.message.reply_text(
                config.WELCOME_MESSAGE,
                reply_markup=get_main_menu_keyboard()
            )
            
        except Exception as e:
            logger.error(f"Error in start command: {e}")
            await update.message.reply_text(config.ERROR_MESSAGES["general"])
    
    async def help_command(self, update: Update, context):
        """Handle /help command"""
        try:
            await update.message.reply_text(
                config.HELP_MESSAGE,
                parse_mode='Markdown'
            )
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
            
            await update.message.reply_text(
                message,
                parse_mode='Markdown',
                reply_markup=get_settings_keyboard()
            )
            
        except Exception as e:
            logger.error(f"Error in settings command: {e}")
            await update.message.reply_text(config.ERROR_MESSAGES["general"])
    
    async def add_medicine_command(self, update: Update, context):
        """Handle /add_medicine command"""
        try:
            from utils.keyboards import get_cancel_keyboard
            
            message = f"""
{config.EMOJIS['medicine']} *הוספת תרופה חדשה*

אנא שלחו את שם התרופה:
            """
            
            await update.message.reply_text(
                message,
                parse_mode='Markdown',
                reply_markup=get_cancel_keyboard()
            )
            
            # Store conversation state (in real implementation, use ConversationHandler)
            context.user_data['adding_medicine'] = {'step': 'name'}
            
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
{config.EMOJIS['info']} <b>אין תרופות רשומות</b>

לחצו על /add_medicine כדי להוסיף תרופה ראשונה.
                """
            else:
                message = f"{config.EMOJIS['medicine']} <b>התרופות שלכם:</b>\n\n"
                for medicine in medicines:
                    status_emoji = config.EMOJIS['success'] if medicine.is_active else config.EMOJIS['error']
                    inventory_warning = ""
                    
                    if medicine.inventory_count <= medicine.low_stock_threshold:
                        inventory_warning = f" {config.EMOJIS['warning']}"
                    
                    message += f"{status_emoji} <b>{medicine.name}</b>\n"
                    message += f"   💊 {medicine.dosage}\n"
                    message += f"   📦 מלאי: {medicine.inventory_count}{inventory_warning}\n\n"
            
            from utils.keyboards import get_medicines_keyboard
            
            await update.message.reply_text(
                message,
                parse_mode='HTML',
                reply_markup=get_medicines_keyboard(medicines if medicines else [])
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
            
            args = context.args if hasattr(context, 'args') else []
            if len(args) < 2:
                await update.message.reply_text(
                    "שימוש: /update_inventory <שם_תרופה> <כמות_חדשה>"
                )
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
            await update.message.reply_text(
                f"{config.EMOJIS['success']} עודכן מלאי לתרופה {selected.name}: {new_count}"
            )
        
        except Exception as e:
            logger.error(f"Error in update_inventory command: {e}")
            await update.message.reply_text(config.ERROR_MESSAGES["general"])
    
    async def snooze_command(self, update: Update, context):
        """Handle /snooze command (generic)"""
        try:
            await update.message.reply_text(
                "להשהיית תזכורת, השתמשו בכפתור דחייה שמופיע בהתראה."
            )
        except Exception as e:
            logger.error(f"Error in snooze command: {e}")
            await update.message.reply_text(config.ERROR_MESSAGES["general"])
    
    async def log_symptoms_command(self, update: Update, context):
        """Open symptoms tracking menu"""
        try:
            from utils.keyboards import get_symptoms_keyboard, get_symptoms_medicine_picker
            user = await DatabaseManager.get_user_by_telegram_id(update.effective_user.id)
            meds = await DatabaseManager.get_user_medicines(user.id) if user else []
            await update.message.reply_text(
                "מעקב סימפטומים:",
                reply_markup=get_symptoms_keyboard()
            )
            # Offer picking a medicine as well
            if meds:
                await update.message.reply_text(
                    "בחרו תרופה לשיוך דיווח התופעות:",
                    reply_markup=get_symptoms_medicine_picker(meds)
                )
        except Exception as e:
            logger.error(f"Error in log_symptoms command: {e}")
            await update.message.reply_text(config.ERROR_MESSAGES["general"])
    
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
            
            # Time selection buttons: handle preset hour and custom entry
            if data in ("cancel", "time_cancel"):
                from utils.keyboards import get_main_menu_keyboard
                context.user_data.pop('editing_schedule_for', None)
                await query.edit_message_text(
                    f"{config.EMOJIS['info']} הפעולה בוטלה",
                    reply_markup=get_main_menu_keyboard()
                )
                return
            if data == "time_custom":
                await query.edit_message_text("הקלידו שעה בפורמט HH:MM (למשל 08:30)")
                return
            if data.startswith("time_"):
                parts = data.split("_")
                if len(parts) >= 3 and parts[1].isdigit() and parts[2].isdigit():
                    try:
                        if not context.user_data.get('editing_schedule_for'):
                            await query.edit_message_text("שגיאה: אין תרופה נבחרת. חזרו ל'שנה שעות' ונסו שוב.")
                            return
                        h = int(parts[1]); m = int(parts[2])
                        from datetime import time as dtime
                        new_time = dtime(hour=h, minute=m)
                        medicine_id = int(context.user_data.get('editing_schedule_for'))
                        # Replace schedules
                        await DatabaseManager.replace_medicine_schedules(medicine_id, [new_time])
                        # Reschedule reminders
                        user = await DatabaseManager.get_user_by_telegram_id(query.from_user.id)
                        await medicine_scheduler.cancel_medicine_reminders(user.id, medicine_id)
                        await medicine_scheduler.schedule_medicine_reminder(
                            user_id=user.id,
                            medicine_id=medicine_id,
                            reminder_time=new_time,
                            timezone=user.timezone or config.DEFAULT_TIMEZONE
                        )
                        context.user_data.pop('editing_schedule_for', None)
                        # Show success and medicine details
                        from utils.keyboards import get_medicine_detail_keyboard
                        med = await DatabaseManager.get_medicine_by_id(medicine_id)
                        await query.edit_message_text(
                            f"{config.EMOJIS['success']} השעה עודכנה ל- {new_time.strftime('%H:%M')}\n{config.EMOJIS['medicine']} {med.name}",
                            reply_markup=get_medicine_detail_keyboard(medicine_id)
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
                await query.edit_message_text(
                    config.WELCOME_MESSAGE,
                    parse_mode='Markdown',
                    reply_markup=get_main_menu_keyboard()
                )
            elif data.startswith("medicine_") or data.startswith("medicines_"):
                # Route to internal medicine action handler which covers all medicine flows
                await self._handle_medicine_action(query, context)
                return
            elif data.startswith("mededit_"):
                # mededit_name_<id>, mededit_dosage_<id>, mededit_notes_<id>, mededit_toggle_<id>
                parts = data.split("_")
                action = parts[1] if len(parts) > 1 else ""
                mid = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
                if not mid:
                    await query.edit_message_text(config.ERROR_MESSAGES["general"])
                    return
                if action == "toggle":
                    # Toggle active state
                    med = await DatabaseManager.get_medicine_by_id(mid)
                    await DatabaseManager.set_medicine_active(mid, not med.is_active)
                    from utils.keyboards import get_medicine_detail_keyboard
                    med2 = await DatabaseManager.get_medicine_by_id(mid)
                    await query.edit_message_text(
                        f"{config.EMOJIS['success']} הסטטוס עודכן ל{'פעילה' if med2.is_active else 'מושבתת'}",
                        reply_markup=get_medicine_detail_keyboard(mid)
                    )
                    return
                if action == "packsize":
                    context.user_data['editing_field_for'] = {"id": mid, "field": "packsize"}
                    await query.edit_message_text("הקלידו גודל חבילה (למשל 30):")
                    return
                # For name/dosage/notes, prompt text input
                context.user_data['editing_field_for'] = {"id": mid, "field": action}
                prompt = {
                    "name": "הקלידו שם חדש לתרופה:",
                    "dosage": "הקלידו מינון חדש:",
                    "notes": "הקלידו הערות (טקסט חופשי):",
                }.get(action, "הקלידו ערך חדש:")
                await query.edit_message_text(prompt)
                return
            elif data.startswith("settings_"):
                await self._handle_settings_action(query, context)
            elif data.startswith("report_") or data.startswith("report_action_") or data.startswith("export_report_"):
                # Routed by reports handler; do nothing here (already registered)
                return
            # Reminders settings controls
            elif data.startswith("rsnoop_") or data.startswith("rattempts_") or data == "rsilent_toggle" or data == "settings_menu":
                await self._handle_reminders_settings_controls(query)
                return
            # Inventory main controls
            elif data in ("inventory_add", "inventory_report"):
                await self._handle_inventory_controls(query, context)
                return
            elif data.startswith("inventory_"):
                from handlers.medicine_handler import medicine_handler
                await medicine_handler.handle_inventory_update(update, context)
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
                    context.user_data['awaiting_symptom_text'] = True
                    context.user_data['symptoms_for_medicine'] = med_id
                    await query.edit_message_text(
                        f"{config.EMOJIS['symptoms']} רשמו תופעות לוואי עבור {med.name}:",
                        reply_markup=get_main_menu_keyboard()
                    )
                    return
                if data == "symptoms_log":
                    await query.edit_message_text(
                        "שלחו עכשיו הודעה עם תיאור תופעות הלוואי שברצונכם לרשום.",
                    )
                    context.user_data['awaiting_symptom_text'] = True
                    return
                if data == "symptoms_history":
                    from utils.keyboards import get_symptoms_history_picker
                    user = await DatabaseManager.get_user_by_telegram_id(user_id)
                    meds = await DatabaseManager.get_user_medicines(user.id) if user else []
                    await query.edit_message_text(
                        "בחרו סינון להיסטוריית תופעות לוואי:",
                        reply_markup=get_symptoms_history_picker(meds)
                    )
                    return
                if data == "symptoms_history_all" or data.startswith("symptoms_history_med_"):
                    from datetime import date, timedelta
                    user = await DatabaseManager.get_user_by_telegram_id(user_id)
                    end_date = date.today(); start_date = end_date - timedelta(days=30)
                    med_filter = None
                    if data.startswith("symptoms_history_med_"):
                        try:
                            med_filter = int(data.split("_")[-1])
                        except Exception:
                            med_filter = None
                    logs = await DatabaseManager.get_symptom_logs_in_range(user.id, start_date, end_date, med_filter)
                    if not logs:
                        await query.edit_message_text("אין רישומי תופעות לוואי ב-30 הימים האחרונים")
                        return
                    preview = []
                    for log in logs[-10:]:
                        ts = log.log_date.strftime('%d/%m %H:%M')
                        med_name = None
                        if getattr(log, 'medicine_id', None):
                            m = await DatabaseManager.get_medicine_by_id(int(log.medicine_id))
                            med_name = m.name if m else None
                        body = (log.symptoms or log.side_effects or '—')
                        row = f"{ts} - {med_name}: {body}" if med_name else f"{ts} - {body}"
                        preview.append(row)
                    await query.edit_message_text("\n".join(preview))
                    return
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
            f"{config.EMOJIS['success']} נטילת התרופה אושרה!\n"
            f"מלאי נותר: {new_count if medicine else 'לא ידוע'} כדורים"
        )
    
    async def _handle_dose_snooze(self, query, context):
        """Handle dose snooze request"""
        medicine_id = int(query.data.split("_")[2])
        user_id = query.from_user.id
        
        # Schedule snooze reminder
        job_id = await medicine_scheduler.schedule_snooze_reminder(user_id, medicine_id)
        
        await query.edit_message_text(
            f"{config.EMOJIS['clock']} תזכורת נדחתה ל-{config.REMINDER_SNOOZE_MINUTES} דקות"
        )
    
    async def _handle_add_medicine_flow(self, update: Update, context):
        """Very simple add-medicine text flow: name -> dosage -> create"""
        try:
            user = update.effective_user
            db_user = await DatabaseManager.get_user_by_telegram_id(user.id)
            if not db_user:
                await update.message.reply_text("אנא התחילו עם /start")
                context.user_data.pop('adding_medicine', None)
                return
            state = context.user_data.get('adding_medicine', {})
            step = state.get('step')
            text = (update.message.text or "").strip()
            
            if step == 'name':
                state['name'] = text
                state['step'] = 'dosage'
                context.user_data['adding_medicine'] = state
                await update.message.reply_text("מה המינון? למשל: 10mg פעמיים ביום")
                return
            
            if step == 'dosage':
                name = state.get('name')
                dosage = text
                # Create medicine with defaults
                await DatabaseManager.create_medicine(
                    user_id=db_user.id,
                    name=name,
                    dosage=dosage,
                )
                context.user_data.pop('adding_medicine', None)
                await update.message.reply_text(
                    f"{config.EMOJIS['success']} התרופה נוספה בהצלחה!",
                )
                await self.my_medicines_command(update, context)
                return
            
            # Unknown step -> reset
            context.user_data.pop('adding_medicine', None)
            await update.message.reply_text(config.ERROR_MESSAGES['invalid_input'])
        except Exception as exc:
            logger.error(f"Error in _handle_add_medicine_flow: {exc}")
            context.user_data.pop('adding_medicine', None)
            await update.message.reply_text(config.ERROR_MESSAGES['general'])
    
    async def _handle_medicine_action(self, query, context):
        """Handle medicine-related inline actions"""
        from utils.keyboards import (
            get_medicines_keyboard,
            get_medicine_detail_keyboard,
        )
        try:
            data = query.data
            user = query.from_user
            
            # Back to medicines list
            if data == "medicines_list" or data == "medicine_manage":
                db_user = await DatabaseManager.get_user_by_telegram_id(user.id)
                medicines = await DatabaseManager.get_user_medicines(db_user.id) if db_user else []
                if not medicines:
                    message = f"{config.EMOJIS['info']} <b>אין תרופות רשומות</b>\n\nלחצו על /add_medicine כדי להוסיף תרופה ראשונה."
                else:
                    message = f"{config.EMOJIS['medicine']} <b>התרופות שלכם:</b>\n\n"
                    for medicine in medicines:
                        status_emoji = config.EMOJIS['success'] if medicine.is_active else config.EMOJIS['error']
                        inventory_warning = ""
                        if medicine.inventory_count <= medicine.low_stock_threshold:
                            inventory_warning = f" {config.EMOJIS['warning']}"
                        message += f"{status_emoji} <b>{medicine.name}</b>\n"
                        message += f"   💊 {medicine.dosage}\n"
                        message += f"   📦 מלאי: {medicine.inventory_count}{inventory_warning}\n\n"
                await query.edit_message_text(
                    message,
                    parse_mode='HTML',
                    reply_markup=get_medicines_keyboard(medicines if medicines else [])
                )
                return
            
            # Add medicine flow entry point (prompt via inline)
            if data == "medicine_add":
                from utils.keyboards import get_cancel_keyboard
                message = f"""
{config.EMOJIS['medicine']} <b>הוספת תרופה חדשה</b>

אנא שלחו את שם התרופה:
                """
                # Switch to conversation-like state
                context.user_data['adding_medicine'] = {'step': 'name'}
                await query.edit_message_text(
                    message,
                    parse_mode='HTML'
                )
                return
            
            # View one medicine details
            if data.startswith("medicine_view_"):
                medicine_id = int(data.split("_")[2])
                medicine = await DatabaseManager.get_medicine_by_id(medicine_id)
                if not medicine:
                    await query.edit_message_text(config.ERROR_MESSAGES["medicine_not_found"]) 
                    return
                details = [
                    f"{config.EMOJIS['medicine']} <b>{medicine.name}</b>",
                    f"💊 מינון: {medicine.dosage}",
                    f"📦 מלאי: {medicine.inventory_count}",
                    f"⚙️ סטטוס: {'פעילה' if medicine.is_active else 'מושבתת'}",
                ]
                await query.edit_message_text(
                    "\n".join(details),
                    parse_mode='HTML',
                    reply_markup=get_medicine_detail_keyboard(medicine.id)
                )
                return
            
            # Inventory/schedule/edit/history/toggle actions - improved
            if data.startswith("medicine_inventory_"):
                # delegate detailed inventory handling (including +1/-1/custom) to handler
                if re := __import__('re'):
                    pass
                # If user clicked entry button, show keyboard
                parts = data.split("_")
                if len(parts) == 3:
                    medicine_id = int(parts[2])
                    from utils.keyboards import get_inventory_update_keyboard
                    await query.edit_message_text(
                        f"בחרו עדכון מהיר למלאי או הזינו כמות מדויקת:",
                        reply_markup=get_inventory_update_keyboard(medicine_id, getattr(await DatabaseManager.get_medicine_by_id(medicine_id), 'pack_size', None) or 28)
                    )
                    return
                # Otherwise, forward inventory_* callbacks to handler
                from handlers.medicine_handler import medicine_handler
                await medicine_handler.handle_inventory_update(update, context)
                return
            
            if data.startswith("medicine_schedule_"):
                # Start schedule edit flow: show time selection keyboard
                from utils.keyboards import get_time_selection_keyboard
                await query.edit_message_text(
                    "בחרו שעה חדשה לנטילת התרופה או הזינו שעה (לדוגמה 08:30)",
                    reply_markup=get_time_selection_keyboard()
                )
                context.user_data['editing_schedule_for'] = int(data.split("_")[2])
                return
            
            if data.startswith("medicine_edit_"):
                medicine_id = int(data.split("_")[2])
                message = (
                    "עריכת פרטי תרופה:\n"
                    "• שלחו שם חדש כדי לשנות שם\n"
                    "• הקלידו: מינון <טקסט> כדי לשנות מינון\n"
                    "• הקלידו: הערות <טקסט> כדי לעדכן הערות\n"
                    "• הקלידו: השבת או הפעל כדי לשנות סטטוס"
                )
                context.user_data['editing_medicine_for'] = medicine_id
                await query.edit_message_text(message)
                return
            
            if data.startswith("medicine_history_"):
                from handlers.reports_handler import reports_handler
                await reports_handler.generate_weekly_report(update, context)
                return
            # Add manage schedules and delete actions (via simple keywords)
            if data.startswith("medicine_toggle_"):
                await query.edit_message_text("כיבוי/הפעלה מתקדמים יתווספו בהמשך. השתמשו ב'ערוך פרטים' > 'הפעל/השבת'.")
                return
 
            if data.startswith("medicine_toggle_"):
                await query.edit_message_text("הפעלת/השבתת תרופה תתווסף בקרוב")
                return
            
            # Fallback
            await query.edit_message_text("פעולת תרופות לא נתמכת")
        except Exception as exc:
            logger.error(f"Error in _handle_medicine_action: {exc}")
            await query.edit_message_text(config.ERROR_MESSAGES["general"])
    
    async def _handle_settings_action(self, query, context):
        """Handle settings-related inline actions"""
        try:
            data = query.data
            if data == "settings_timezone":
                # Minimal timezone selector
                zones = ["UTC", "Asia/Jerusalem", "Europe/London", "America/New_York"]
                rows = []
                for z in zones:
                    rows.append([InlineKeyboardButton(z, callback_data=f"tz_{z}")])
                rows.append([InlineKeyboardButton("הקלד אזור זמן", callback_data="tz_custom")])
                rows.append([InlineKeyboardButton(f"{config.EMOJIS['back']} חזור", callback_data="main_menu")])
                await query.edit_message_text(
                    "בחרו אזור זמן:",
                    reply_markup=InlineKeyboardMarkup(rows)
                )
            elif data.startswith("tz_"):
                # Apply selected timezone
                tz = data[3:]
                user = await DatabaseManager.get_user_by_telegram_id(query.from_user.id)
                await DatabaseManager.update_user_timezone(user.id, tz)
                await query.edit_message_text(f"{config.EMOJIS['success']} עודכן אזור הזמן ל- {tz}")
            elif data == "tz_custom":
                await query.edit_message_text("הקלידו את אזור הזמן (למשל Asia/Jerusalem)")
                context.user_data['awaiting_timezone_text'] = True
            elif data == "settings_reminders":
                # Show full reminders settings UI
                user = await DatabaseManager.get_user_by_telegram_id(query.from_user.id)
                settings = await DatabaseManager.get_user_settings(user.id)
                msg = (
                    f"{config.EMOJIS['reminder']} הגדרות תזכורות\n\n"
                    f"דחיית תזכורת: {settings.snooze_minutes} דקות\n"
                    f"מספר ניסיונות תזכורת: {settings.max_attempts}\n"
                    f"מצב שקט: {'מופעל' if settings.silent_mode else 'כבוי'}\n"
                )
                await query.edit_message_text(
                    msg,
                    parse_mode='Markdown',
                    reply_markup=get_reminders_settings_keyboard(settings.snooze_minutes, settings.max_attempts, settings.silent_mode)
                )
                 
            elif data == "settings_inventory":
                await query.edit_message_text("הגדרות מלאי בסיסיות: התראות מלאי נמוכים מופעלות.")
            elif data == "settings_caregivers":
                await query.edit_message_text("ניהול מטפלים זמין דרך תפריט 'מטפלים'.")
            elif data == "settings_reports":
                from handlers import reports_handler
                await reports_handler.show_reports_menu(query, context)
                return
            else:
                await query.edit_message_text("הגדרות לא נתמכות")
        except Exception as exc:
            logger.error(f"Error in _handle_settings_action: {exc}")
            await query.edit_message_text(config.ERROR_MESSAGES["general"])
        
    async def handle_text_message(self, update: Update, context):
        """Handle regular text messages (for conversation flows)"""
        try:
            # This would handle conversation states for adding medicines, etc.
            # For now, just acknowledge
            user_data = context.user_data
            
            text = (update.message.text or "").strip()
            
            # Route main menu buttons by text
            from utils.keyboards import (
                get_main_menu_keyboard,
                get_settings_keyboard,
                get_caregiver_keyboard,
                get_symptoms_keyboard,
            )
            
            buttons = {
                f"{config.EMOJIS['medicine']} התרופות שלי": "my_medicines",
                f"{config.EMOJIS['reminder']} תזכורות": "reminders",
                f"{config.EMOJIS['inventory']} מלאי": "inventory",
                f"{config.EMOJIS['symptoms']} תופעות לוואי": "symptoms",
                f"{config.EMOJIS['report']} דוחות": "reports",
                f"{config.EMOJIS['caregiver']} מטפלים": "caregivers",
                f"{config.EMOJIS['settings']} הגדרות": "settings",
                f"{config.EMOJIS['info']} עזרה": "help",
            }
            
            # Handle mededit text inputs
            if 'editing_field_for' in user_data:
                info = user_data.pop('editing_field_for')
                mid = int(info.get('id'))
                field = info.get('field')
                if field == 'name' and len(text) >= 2:
                    await DatabaseManager.update_medicine(mid, name=text)
                    await update.message.reply_text(f"{config.EMOJIS['success']} שם התרופה עודכן")
                    await self.my_medicines_command(update, context)
                    return
                if field == 'dosage' and len(text) >= 1:
                    await DatabaseManager.update_medicine(mid, dosage=text)
                    await update.message.reply_text(f"{config.EMOJIS['success']} המינון עודכן")
                    await self.my_medicines_command(update, context)
                    return
                if field == 'notes':
                    await DatabaseManager.update_medicine(mid, notes=text)
                    await update.message.reply_text(f"{config.EMOJIS['success']} ההערות עודכנו")
                    await self.my_medicines_command(update, context)
                    return
                if field == 'packsize' and text.isdigit():
                    await DatabaseManager.update_medicine(mid, pack_size=int(text))
                    await update.message.reply_text(f"{config.EMOJIS['success']} גודל החבילה עודכן")
                    await self.my_medicines_command(update, context)
                    return
                # Fallback
                await update.message.reply_text(config.ERROR_MESSAGES['invalid_input'])
                return

            # Inventory update inline flow via text
            if 'updating_inventory_for' in user_data:
                medicine_id = user_data.get('updating_inventory_for')
                try:
                    new_count = float(text)
                except ValueError:
                    await update.message.reply_text("אנא הזינו מספר תקין לכמות המלאי")
                    return
                await DatabaseManager.update_inventory(int(medicine_id), new_count)
                user_data.pop('updating_inventory_for', None)
                await update.message.reply_text(f"{config.EMOJIS['success']} המלאי עודכן")
                await self.my_medicines_command(update, context)
                return
            # Schedule edit flow via text (time input HH:MM)
            if 'editing_schedule_for' in user_data:
                medicine_id = int(user_data.get('editing_schedule_for'))
                # Validate HH:MM
                import re
                if not re.match(r"^\d{1,2}:\d{2}$", text):
                    await update.message.reply_text("אנא הזינו שעה בפורמט HH:MM, למשל 08:30")
                    return
                hours, minutes = text.split(":")
                try:
                    h = int(hours); m = int(minutes)
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
                    timezone=user.timezone or config.DEFAULT_TIMEZONE
                )
                user_data.pop('editing_schedule_for', None)
                await update.message.reply_text(f"{config.EMOJIS['success']} השעה עודכנה ל- {new_time.strftime('%H:%M')}")
                # Show medicine details
                med = await DatabaseManager.get_medicine_by_id(medicine_id)
                from utils.keyboards import get_medicine_detail_keyboard
                await update.message.reply_text(
                    f"{config.EMOJIS['medicine']} {med.name}",
                    reply_markup=get_medicine_detail_keyboard(medicine_id)
                )
                return
            # Edit medicine free-text commands
            if 'editing_medicine_for' in user_data:
                mid = int(user_data.get('editing_medicine_for'))
                lower = text.strip()
                # Replace all schedule times: הקלד: שעות HH:MM,HH:MM
                if lower.startswith('שעות '):
                    parts = lower.split(' ', 1)[1].split(',')
                    from datetime import time as dtime
                    new_times = []
                    for p in parts:
                        p = p.strip()
                        if not p:
                            continue
                        if ':' not in p:
                            await update.message.reply_text("פורמט שעה לא תקין. דוגמה: שעות 08:00,14:30")
                            return
                        hh, mm = p.split(':', 1)
                        new_times.append(dtime(hour=int(hh), minute=int(mm)))
                    # Replace in DB
                    await DatabaseManager.replace_medicine_schedules(mid, new_times)
                    # Unschedule then reschedule
                    user = await DatabaseManager.get_user_by_telegram_id(update.effective_user.id)
                    await medicine_scheduler.cancel_medicine_reminders(user.id, mid)
                    for t in new_times:
                        await medicine_scheduler.schedule_medicine_reminder(user.id, mid, t, user.timezone or config.DEFAULT_TIMEZONE)
                    await update.message.reply_text(f"{config.EMOJIS['success']} שעות הוחלפו")
                    user_data.pop('editing_medicine_for', None)
                    await self.my_medicines_command(update, context)
                    return
                # Delete medicine: הקלד: מחק
                if lower == 'מחק':
                    user = await DatabaseManager.get_user_by_telegram_id(update.effective_user.id)
                    await medicine_scheduler.cancel_medicine_reminders(user.id, mid)
                    ok = await DatabaseManager.delete_medicine(mid)
                    if ok:
                        await update.message.reply_text(f"{config.EMOJIS['success']} התרופה נמחקה")
                    else:
                        await update.message.reply_text(f"{config.EMOJIS['error']} שגיאה במחיקה")
                    user_data.pop('editing_medicine_for', None)
                    await self.my_medicines_command(update, context)
                    return
                if lower.startswith('מינון '):
                    new_dosage = text.split(' ', 1)[1].strip()
                    await DatabaseManager.update_medicine(mid, dosage=new_dosage)
                    await update.message.reply_text(f"{config.EMOJIS['success']} המינון עודכן")
                    user_data.pop('editing_medicine_for', None)
                    await self.my_medicines_command(update, context)
                    return
                if lower.startswith('הערות '):
                    new_notes = text.split(' ', 1)[1].strip()
                    await DatabaseManager.update_medicine(mid, notes=new_notes)
                    await update.message.reply_text(f"{config.EMOJIS['success']} ההערות עודכנו")
                    user_data.pop('editing_medicine_for', None)
                    await self.my_medicines_command(update, context)
                    return
                if lower in ('השבת', 'הפעל'):
                    is_active = (lower == 'הפעל')
                    await DatabaseManager.set_medicine_active(mid, is_active)
                    await update.message.reply_text(f"{config.EMOJIS['success']} הסטטוס עודכן")
                    user_data.pop('editing_medicine_for', None)
                    await self.my_medicines_command(update, context)
                    return
                # Otherwise treat as rename
                if len(text.strip()) >= 2:
                    await DatabaseManager.update_medicine(mid, name=text.strip())
                    await update.message.reply_text(f"{config.EMOJIS['success']} שם התרופה עודכן")
                    user_data.pop('editing_medicine_for', None)
                    await self.my_medicines_command(update, context)
                    return
            
            if text in buttons:
                action = buttons[text]
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
                    await update.message.reply_text(
                        "ניהול מטפלים:",
                        reply_markup=get_caregiver_keyboard()
                    )
                    return
                if action == "symptoms":
                    await self.log_symptoms_command(update, context)
                    return
                if action == "reports":
                    from handlers import reports_handler
                    await reports_handler.show_reports_menu(update, context)
                    return
                if action == "help":
                    await self.help_command(update, context)
                    return
            
            if 'adding_medicine' in user_data:
                await self._handle_add_medicine_flow(update, context)
            else:
                # Save symptom text if awaiting
                if user_data.get('awaiting_symptom_text'):
                    try:
                        user = await DatabaseManager.get_user_by_telegram_id(update.effective_user.id)
                        from datetime import datetime as dt
                        # If tied to a specific medicine from quick action, include name prefix
                        med_prefix = None
                        med_id = user_data.pop('symptoms_for_medicine', None)
                        if med_id:
                            med = await DatabaseManager.get_medicine_by_id(int(med_id))
                            med_prefix = med.name if med else None
                        entry_text = f"{med_prefix}: {text}" if med_prefix else text
                        await DatabaseManager.create_symptom_log(
                            user_id=user.id,
                            log_date=dt.utcnow(),
                            symptoms=entry_text,
                            medicine_id=int(med_id) if med_id else None
                        )
                        user_data.pop('awaiting_symptom_text', None)
                        from utils.keyboards import get_main_menu_keyboard
                        await update.message.reply_text(
                            f"{config.EMOJIS['success']} נרשם. תודה!",
                            reply_markup=get_main_menu_keyboard()
                        )
                        return
                    except Exception as exc:
                        logger.error(f"Error saving symptom: {exc}")
                        await update.message.reply_text(config.ERROR_MESSAGES['general'])
                        user_data.pop('awaiting_symptom_text', None)
                        return
                # Save timezone if awaiting text
                if user_data.get('awaiting_timezone_text'):
                    zone = text.strip()
                    if '/' not in zone or len(zone) < 3:
                        await update.message.reply_text("אנא הזינו אזור זמן תקין, למשל Asia/Jerusalem")
                        return
                    user = await DatabaseManager.get_user_by_telegram_id(update.effective_user.id)
                    await DatabaseManager.update_user_timezone(user.id, zone)
                    user_data.pop('awaiting_timezone_text', None)
                    await update.message.reply_text(f"{config.EMOJIS['success']} עודכן אזור הזמן ל- {zone}")
                    return
                await update.message.reply_text(
                    "השתמשו בתפריט או בפקודות. /help לעזרה"
                )
                
        except Exception as e:
            logger.error(f"Error handling text message: {e}")
            await update.message.reply_text(config.ERROR_MESSAGES["general"])
    
    async def error_handler(self, update: Update, context):
        """Handle errors"""
        logger.error(f"Exception while handling update {update}: {context.error}")
        
        if update and update.effective_message:
            await update.effective_message.reply_text(
                config.ERROR_MESSAGES["general"]
            )
    
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
                    f"{config.EMOJIS['settings']} *הגדרות אישיות*",
                    parse_mode='Markdown',
                    reply_markup=get_settings_keyboard()
                )
                return
            # Refresh UI
            msg = (
                f"{config.EMOJIS['reminder']} הגדרות תזכורות\n\n"
                f"דחיית תזכורת: {settings.snooze_minutes} דקות\n"
                f"מספר ניסיונות תזכורת: {settings.max_attempts}\n"
                f"מצב שקט: {'מופעל' if settings.silent_mode else 'כבוי'}\n"
            )
            await query.edit_message_text(
                msg,
                parse_mode='Markdown',
                reply_markup=get_reminders_settings_keyboard(settings.snooze_minutes, settings.max_attempts, settings.silent_mode)
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
            msg = f"{config.EMOJIS['inventory']} מרכז המלאי\n\n"
            if not meds:
                msg += "אין תרופות במערכת. הוסיפו תרופה דרך 'התרופות שלי'."
            else:
                msg += f"סה\"כ תרופות: {len(meds)} | נמוך: {len(low)}\n"
                for m in meds[:10]:
                    warn = f" {config.EMOJIS['warning']}" if m.inventory_count <= m.low_stock_threshold else ""
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
                await query.edit_message_text(
                    "בחרו תרופה לעדכון מלאי:",
                    reply_markup=get_medicines_keyboard(meds)
                )
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
            secret_token = (config.BOT_TOKEN[-32:] if len(config.BOT_TOKEN) >= 32 else None)
            await self.application.bot.set_webhook(
                url=webhook_url,
                allowed_updates=["message", "callback_query"],
                secret_token=secret_token
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
            await runner.setup()
            site = web.TCPSite(runner, host="0.0.0.0", port=config.WEBHOOK_PORT)
            await site.start()
            
            logger.info("Webhook server is up")
            
            # Block forever
            await asyncio.Event().wait()
            
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
            await self.application.run_polling(
                allowed_updates=["message", "callback_query"],
                drop_pending_updates=True
            )
            
        except Exception as e:
            logger.error(f"Failed to run polling: {e}")
            raise
    
    async def shutdown(self):
        """Graceful shutdown"""
        logger.info("Shutting down bot...")
        
        try:
            # Stop scheduler
            await medicine_scheduler.stop()
            
            # Stop application
            if self.application:
                await self.application.stop()
                await self.application.shutdown()
            
            logger.info("Bot shutdown completed")
            
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")


async def main():
    """Main entry point"""
    bot = MedicineReminderBot()
    
    # Setup signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}")
        asyncio.create_task(bot.shutdown())
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Initialize bot
        await bot.initialize()
        
        # Run bot based on environment
        if config.is_production():
            await bot.run_webhook()
        else:
            await bot.run_polling()
            
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Critical error: {e}")
        raise
    finally:
        await bot.shutdown()


if __name__ == "__main__":
    # Entry point for the application
    asyncio.run(main())
