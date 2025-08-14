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

from config import config
from database import init_database, DatabaseManager
from scheduler import medicine_scheduler

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
                parse_mode='Markdown',
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
{config.EMOJIS['info']} *אין תרופות רשומות*

לחצו על /add_medicine כדי להוסיף תרופה ראשונה.
                """
            else:
                message = f"{config.EMOJIS['medicine']} *התרופות שלכם:*\n\n"
                for medicine in medicines:
                    status_emoji = config.EMOJIS['success'] if medicine.is_active else config.EMOJIS['error']
                    inventory_warning = ""
                    
                    if medicine.inventory_count <= medicine.low_stock_threshold:
                        inventory_warning = f" {config.EMOJIS['warning']}"
                    
                    message += f"{status_emoji} *{medicine.name}*\n"
                    message += f"   💊 {medicine.dosage}\n"
                    message += f"   📦 מלאי: {medicine.inventory_count}{inventory_warning}\n\n"
            
            from utils.keyboards import get_medicines_keyboard
            
            await update.message.reply_text(
                message,
                parse_mode='Markdown',
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
                f"{config.EMOJES['success']} עודכן מלאי לתרופה {selected.name}: {new_count}"
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
        """Handle /log_symptoms command (stub)"""
        try:
            await update.message.reply_text(
                "תארו את הסימפטומים בהודעה חוזרת, ואשמור זאת בהמשך הגרסה."
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
            user = update.effective_user
            jobs = medicine_scheduler.get_scheduled_jobs(user.id)
            
            if not jobs:
                message = f"{config.EMOJES['info']} אין תזכורות מתוזמנות"
            else:
                message = f"{config.EMOJES['clock']} *התזכורות הבאות:*\n\n"
                for job in sorted(jobs, key=lambda x: x['next_run']):
                    if job['next_run']:
                        time_str = job['next_run'].strftime('%H:%M')
                        message += f"⏰ {time_str} - {job['name']}\n"
            
            await update.message.reply_text(
                message,
                parse_mode='Markdown'
            )
            
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
            
            # Handle different callback types
            if data.startswith("dose_taken_"):
                await self._handle_dose_taken(query, context)
            elif data.startswith("dose_snooze_"):
                await self._handle_dose_snooze(query, context)
            elif data.startswith("medicine_"):
                await self._handle_medicine_action(query, context)
            elif data.startswith("settings_"):
                await self._handle_settings_action(query, context)
            else:
                await query.edit_message_text("פעולה לא מזוהה")
                
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
            f"{config.EMOJES['success']} נטילת התרופה אושרה!\n"
            f"מלאי נותר: {new_count if medicine else 'לא ידוע'} כדורים"
        )
    
    async def _handle_dose_snooze(self, query, context):
        """Handle dose snooze request"""
        medicine_id = int(query.data.split("_")[2])
        user_id = query.from_user.id
        
        # Schedule snooze reminder
        job_id = await medicine_scheduler.schedule_snooze_reminder(user_id, medicine_id)
        
        await query.edit_message_text(
            f"{config.EMOJES['clock']} תזכורת נדחתה ל-{config.REMINDER_SNOOZE_MINUTES} דקות"
        )
    
    async def handle_text_message(self, update: Update, context):
        """Handle regular text messages (for conversation flows)"""
        try:
            # This would handle conversation states for adding medicines, etc.
            # For now, just acknowledge
            user_data = context.user_data
            
            if 'adding_medicine' in user_data:
                await self._handle_add_medicine_flow(update, context)
            else:
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
