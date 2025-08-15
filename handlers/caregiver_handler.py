"""
Caregiver Handler
Handles caregiver management: adding, removing, permissions, daily reports
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, 
    ConversationHandler, 
    CommandHandler, 
    MessageHandler, 
    CallbackQueryHandler,
    filters
)

from config import config
from database import DatabaseManager, Caregiver
from utils.keyboards import (
    get_caregiver_keyboard,
    get_main_menu_keyboard,
    get_cancel_keyboard,
    get_confirmation_keyboard
)
from utils.helpers import validate_telegram_id, format_datetime_hebrew

logger = logging.getLogger(__name__)

# Conversation states
CAREGIVER_NAME, CAREGIVER_PHONE, CAREGIVER_EMAIL, CAREGIVER_PERMISSIONS = range(4)
EDIT_CAREGIVER_NAME, EDIT_CAREGIVER_PHONE, EDIT_CAREGIVER_EMAIL, EDIT_CAREGIVER_PERMISSIONS = range(4, 8)
EDIT_ALL_NAME, EDIT_ALL_PHONE, EDIT_ALL_EMAIL, EDIT_ALL_PERMS = range(8, 12)


class CaregiverHandler:
    """Handler for caregiver management and communication"""
    
    def __init__(self):
        self.user_caregiver_data: Dict[int, Dict] = {}
        
        # Permission levels
        self.permission_levels = {
            "view": "צפייה בלבד",
            "manage": "ניהול תרופות", 
            "admin": "מנהל מלא"
        }
        
        # Relationship types
        self.relationship_types = [
            "בן/בת משפחה", "בני זוג", "הורה", "ילד/ה", "אח/אחות",
            "רופא", "אחות", "מטפל/ת", "סיעוד", "חבר/ה", "אחר"
        ]
    
    def get_conversation_handler(self) -> ConversationHandler:
        """Get the conversation handler for caregiver management"""
        return ConversationHandler(
            entry_points=[
                CommandHandler("add_caregiver", self.start_add_caregiver),
                CallbackQueryHandler(self.start_add_caregiver, pattern="^caregiver_add$"),
                CallbackQueryHandler(self.view_caregivers, pattern="^caregiver_manage$"),
                CallbackQueryHandler(self.edit_caregiver, pattern="^caregiver_edit_"),
            ],
            states={
                CAREGIVER_NAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_caregiver_name)
                ],
                CAREGIVER_PHONE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_caregiver_phone)
                ],
                CAREGIVER_EMAIL: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_caregiver_email)
                ],
                CAREGIVER_PERMISSIONS: [
                    CallbackQueryHandler(self.handle_permissions_selection, pattern="^perm_")
                ],
                EDIT_ALL_NAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self._edit_all_set_name)
                ],
                EDIT_ALL_PHONE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self._edit_all_set_phone)
                ],
                EDIT_ALL_EMAIL: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self._edit_all_set_email)
                ],
                EDIT_ALL_PERMS: [
                    CallbackQueryHandler(self._edit_all_set_perms, pattern="^perm_")
                ],
            },
            fallbacks=[
                CommandHandler("cancel", self.cancel_operation),
                CallbackQueryHandler(self.cancel_operation, pattern="^cancel$")
            ],
            per_message=False
        )
    
    def get_handlers(self) -> List:
        """Get additional command handlers"""
        return [
            CommandHandler("caregiver_settings", self.caregiver_settings),
            CommandHandler("send_report", self.send_manual_report),
            CallbackQueryHandler(self.handle_caregiver_actions, pattern="^caregiver_"),
            CallbackQueryHandler(self.confirm_remove_caregiver, pattern="^remove_caregiver_"),
            CallbackQueryHandler(self.toggle_caregiver_status, pattern="^toggle_caregiver_"),
        ]
    
    async def start_add_caregiver(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start adding a new caregiver"""
        try:
            user_id = update.effective_user.id
            user = await DatabaseManager.get_user_by_telegram_id(user_id)
            
            if not user:
                await self._send_error_message(update, "משתמש לא נמצא")
                return ConversationHandler.END
            
            # Caregiver limit disabled per request
            # (previous limit check removed)
            
            # Initialize caregiver data
            self.user_caregiver_data[user_id] = {
                'user_id': user.id,
                'step': 'name',
                'email': None,
                'phone': None
            }
            
            message = f"""
  {config.EMOJIS['caregiver']} <b>הוספת מטפל חדש</b>
  
  🔹 <b>שלב 1/4:</b> שם המטפל
  
  אנא הזינו את שם המטפל:
  (לדוגמה: ד"ר כהן, אמא, אחות שרה)
            """
            
            if update.callback_query:
                await update.callback_query.answer()
                await update.callback_query.edit_message_text(
                    message,
                    parse_mode='HTML',
                    reply_markup=get_cancel_keyboard()
                )
            else:
                await update.message.reply_text(
                    message,
                    parse_mode='HTML',
                    reply_markup=get_cancel_keyboard()
                )
            
            return CAREGIVER_NAME
            
        except Exception as e:
            logger.error(f"Error starting add caregiver: {e}")
            await self._send_error_message(update, "שגיאה בתחילת הוספת המטפל")
            return ConversationHandler.END
    
    async def get_caregiver_telegram_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Get caregiver Telegram ID"""
        try:
            user_id = update.effective_user.id
            telegram_id_str = update.message.text.strip()
            
            # Allow skipping Telegram ID
            if telegram_id_str in ("דלג", "skip", "אין"):
                # Proceed to name step without telegram id
                self.user_caregiver_data[user_id] = self.user_caregiver_data.get(user_id, {})
                self.user_caregiver_data[user_id]['caregiver_telegram_id'] = None
                message = f"""
{config.EMOJIS['caregiver']} <b>הוספת מטפל חדש</b>

🔹 <b>שלב 2/4:</b> שם המטפל

אנא הזינו את שם המטפל:
(לדוגמה: ד"ר כהן, אמא, אחות שרה)
                """
                await update.message.reply_text(
                    message,
                    parse_mode='HTML',
                    reply_markup=get_cancel_keyboard()
                )
                return CAREGIVER_NAME
            # Handle @username format – ask for numeric ID or skip
            if telegram_id_str.startswith('@'):
                await update.message.reply_text(
                    f"{config.EMOJIS['info']} אם אין מזהה מספרי ניתן לכתוב 'דלג' ולהמשיך ללא טלגרם"
                )
                return CAREGIVER_TELEGRAM_ID
            
            # Validate Telegram ID
            is_valid, error_msg = validate_telegram_id(telegram_id_str)
            if not is_valid:
                await update.message.reply_text(
                    f"{config.EMOJIS['error']} {error_msg} | ניתן גם לכתוב 'דלג'"
                )
                return CAREGIVER_TELEGRAM_ID
            
            caregiver_telegram_id = int(telegram_id_str)
            
            # Check if not adding themselves
            if caregiver_telegram_id == user_id:
                await update.message.reply_text(
                    f"{config.EMOJIS['error']} לא ניתן להוסיף את עצמכם כמטפל"
                )
                return CAREGIVER_TELEGRAM_ID
            
            # Check if caregiver already exists
            user = await DatabaseManager.get_user_by_telegram_id(user_id)
            existing_caregivers = await DatabaseManager.get_user_caregivers(user.id)
            
            for caregiver in existing_caregivers:
                if caregiver.caregiver_telegram_id and caregiver.caregiver_telegram_id == caregiver_telegram_id:
                    await update.message.reply_text(
                        f"{config.EMOJIS['warning']} מטפל זה כבר קיים ברשימה"
                    )
                    return CAREGIVER_TELEGRAM_ID
             
            # Store Telegram ID
            self.user_caregiver_data[user_id]['caregiver_telegram_id'] = caregiver_telegram_id
            
            message = f"""
  {config.EMOJIS['caregiver']} <b>הוספת מטפל חדש</b>
 
 ✅ <b>מזהה טלגרם:</b> {caregiver_telegram_id}
 
 🔹 <b>שלב 2/4:</b> שם המטפל
 
 אנא הזינו את שם המטפל:
 (לדוגמה: ד"ר כהן, אמא, אחות שרה)
             """

            await update.message.reply_text(
                message,
                parse_mode='HTML',
                reply_markup=get_cancel_keyboard()
            )
            
            return CAREGIVER_NAME

        except Exception as e:
            logger.error(f"Error getting caregiver telegram ID: {e}")
            await self._send_error_message(update, "שגיאה בקבלת מזהה הטלגרם")
            return ConversationHandler.END
    
    async def get_caregiver_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Get caregiver name"""
        try:
            user_id = update.effective_user.id
            caregiver_name = update.message.text.strip()

            # If we're in edit mode and expecting a new name
            editing = context.user_data.get('editing_caregiver')
            if editing and editing.get('field') == 'name':
                caregiver_id = editing['id']
                # Validate
                if len(caregiver_name) < 2:
                    await update.message.reply_text(
                        f"{config.EMOJIS['error']} שם המטפל קצר מדי (מינימום 2 תווים)"
                    )
                    return ConversationHandler.END
                if len(caregiver_name) > 100:
                    await update.message.reply_text(
                        f"{config.EMOJIS['error']} שם המטפל ארוך מדי (מקסימום 100 תווים)"
                    )
                    return ConversationHandler.END
                await DatabaseManager.update_caregiver(caregiver_id, caregiver_name=caregiver_name)
                context.user_data.pop('editing_caregiver', None)
                await update.message.reply_text(f"{config.EMOJIS['success']} שם המטפל עודכן ל- {caregiver_name}")
                return ConversationHandler.END

            # Validate name
            if len(caregiver_name) < 2:
                await update.message.reply_text(
                    f"{config.EMOJIS['error']} שם המטפל קצר מדי (מינימום 2 תווים)"
                )
                return CAREGIVER_NAME

            if len(caregiver_name) > 100:
                await update.message.reply_text(
                    f"{config.EMOJIS['error']} שם המטפל ארוך מדי (מקסימום 100 תווים)"
                )
                return CAREGIVER_NAME

            # Store name
            self.user_caregiver_data[user_id]['caregiver_name'] = caregiver_name

            message = f"""
{config.EMOJIS['caregiver']} <b>הוספת מטפל חדש</b>

✅ <b>שם המטפל:</b> {caregiver_name}

🔹 <b>שלב 2/4:</b> מספר טלפון (חובה)

אנא הזינו מספר טלפון של המטפל:
            """

            await update.message.reply_text(
                message,
                parse_mode='HTML',
                reply_markup=get_cancel_keyboard()
            )

            return CAREGIVER_PHONE

        except Exception as e:
            logger.error(f"Error getting caregiver name: {e}")
            await self._send_error_message(update, "שגיאה בקבלת שם המטפל")
            return ConversationHandler.END
    
    async def get_caregiver_phone(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Get caregiver phone (required)."""
        try:
            user_id = update.effective_user.id
            phone = update.message.text.strip()
            import re
            if not re.match(r"^[+\d][\d\-\s]{6,}$", phone):
                await update.message.reply_text(f"{config.EMOJIS['error']} אנא הזינו מספר טלפון תקין")
                return CAREGIVER_PHONE
            self.user_caregiver_data[user_id]['phone'] = phone
            message = f"""
{config.EMOJIS['caregiver']} <b>הוספת מטפל חדש</b>

✅ <b>טלפון:</b> {phone}

🔹 <b>שלב 3/4:</b> אימייל (לא חובה)
(אפשר לכתוב דלג)
            """
            await update.message.reply_text(message, parse_mode='HTML', reply_markup=get_cancel_keyboard())
            return CAREGIVER_EMAIL
        except Exception as e:
            logger.error(f"Error getting caregiver phone: {e}")
            await self._send_error_message(update, "שגיאה בקבלת הטלפון")
            return ConversationHandler.END

    async def get_caregiver_email(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Get caregiver email (optional)."""
        try:
            user_id = update.effective_user.id
            email = update.message.text.strip()
            if email.lower() in ("דלג", "skip", "אין", "-"):
                email = None
            elif email:
                import re
                if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
                    await update.message.reply_text(f"{config.EMOJIS['error']} אימייל לא תקין או השאירו ריק וכתבו 'דלג'")
                    return CAREGIVER_EMAIL
            self.user_caregiver_data[user_id]['email'] = email
            # Permissions keyboard
            keyboard = [[InlineKeyboardButton(desc, callback_data=f"perm_{key}")] for key, desc in self.permission_levels.items()]
            email_line = f"✅ <b>אימייל:</b> {email}\n" if email else ""
            message = (
                f"{config.EMOJIS['caregiver']} <b>הוספת מטפל חדש</b>\n\n"
                f"✅ <b>טלפון:</b> {self.user_caregiver_data[user_id]['phone']}\n"
                f"{email_line}"
                f"🔹 <b>שלב 4/4:</b> הרשאות\n"
                f"בחרו את רמת ההרשאות של המטפל:"
            )
            await update.message.reply_text(message, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
            return CAREGIVER_PERMISSIONS
        except Exception as e:
            logger.error(f"Error getting caregiver email: {e}")
            await self._send_error_message(update, "שגיאה בקבלת האימייל")
            return ConversationHandler.END
    
    async def handle_permissions_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle permissions selection and save caregiver"""
        try:
            query = update.callback_query
            await query.answer()
            
            user_id = query.from_user.id
            permissions = query.data.split("_")[1]
            
            # Store permissions and save caregiver
            self.user_caregiver_data[user_id]['permissions'] = permissions
            
            # Save with phone/email fields
            success = await self._save_caregiver(user_id)
            
            if success:
                data = self.user_caregiver_data[user_id]
                perm_desc = self.permission_levels.get(permissions, permissions)
                
                caregiver_emoji = config.EMOJIS.get('caregiver', '👥')
                success_emoji = config.EMOJIS.get('success', '✅')
                phone_line = f"• מספר טלפון: {data.get('phone')}\n" if data.get('phone') else ""
                email_line = f"• דואר אלקטרוני: {data.get('email')}\n" if data.get('email') else ""
                message = (
                    f"{success_emoji} <b>מטפל נוסף בהצלחה!</b>\n\n"
                    f"{caregiver_emoji} <b>פרטי המטפל:</b>\n"
                    f"• שם: {data.get('caregiver_name','')}\n"
                    f"• קשר: {data.get('relationship_type','')}\n"
                    f"• הרשאות: {perm_desc}\n"
                    f"{phone_line}{email_line}"
                )
                
                # Send notification to caregiver
                await self._notify_new_caregiver(user_id, data)
                
                home_emoji = config.EMOJIS.get('home', '🏠')
                caregiver_emoji = config.EMOJIS.get('caregiver', '👥')
                keyboard = [
                    [
                        InlineKeyboardButton(
                            f"{caregiver_emoji} נהל מטפלים",
                            callback_data="caregiver_manage"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            f"{home_emoji} תפריט ראשי",
                            callback_data="main_menu"
                        )
                    ]
                ]
            else:
                message = f"{config.EMOJIS['error']} שגיאה בשמירת המטפל. אנא נסו שוב."
                keyboard = [[
                    InlineKeyboardButton(
                        f"{config.EMOJIS['back']} חזור",
                        callback_data="main_menu"
                    )
                ]]
            
            await query.edit_message_text(
                message,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            # Clean up
            if user_id in self.user_caregiver_data:
                del self.user_caregiver_data[user_id]
            
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"Error handling permissions selection: {e}")
            await query.edit_message_text(
                f"{config.EMOJIS['error']} שגיאה בשמירת המטפל"
            )
            return ConversationHandler.END
    
    async def view_caregivers(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """View and manage caregivers with pagination."""
        try:
            user_id = update.effective_user.id
            user = await DatabaseManager.get_user_by_telegram_id(user_id)
            if not user:
                await self._send_error_message(update, "משתמש לא נמצא")
                return ConversationHandler.END
            query = update.callback_query
            offset = 0
            if query and query.data.startswith('caregiver_page_'):
                try:
                    offset = int(query.data.split('_')[-1])
                except Exception:
                    offset = 0
            context.user_data['caregiver_list_offset'] = offset
            page_size = 10
            caregivers = await DatabaseManager.get_user_caregivers(user.id, active_only=False)
            if not caregivers:
                message = f"""
{config.EMOJIS['info']} <b>אין מטפלים רשומים</b>

עדיין לא הוספתם מטפלים.
מטפלים יכולים לעזור לכם לעקוב אחר נטילת התרופות ולקבל דוחות.
                """
                keyboard = [[[InlineKeyboardButton(f"{config.EMOJIS['caregiver']} הוסף מטפל ראשון", callback_data="caregiver_add")]]]
            else:
                message = f"{config.EMOJIS['caregiver']} <b>המטפלים שלכם ({len(caregivers)}):</b>\n\n"
                for c in caregivers[offset:offset+page_size]:
                    status_emoji = config.EMOJIS['success'] if c.is_active else config.EMOJIS['error']
                    perm_desc = self.permission_levels.get(c.permissions, c.permissions)
                    created_txt = c.created_at.strftime('%d/%m/%Y') if getattr(c, 'created_at', None) else ''
                    message += f"{status_emoji} <b>{c.caregiver_name}</b>\n   👤 {c.relationship_type}\n   🔐 {perm_desc}\n   📅 נוסף: {created_txt}\n\n"
                keyboard = []
                for c in caregivers[offset:offset+page_size]:
                    keyboard.append([InlineKeyboardButton(f"✏️ {c.caregiver_name}", callback_data=f"caregiver_edit_{c.id}")])
                # Nav row
                nav = []
                if offset > 0:
                    prev_off = max(0, offset - page_size)
                    nav.append(InlineKeyboardButton("‹ הקודם", callback_data=f"caregiver_page_{prev_off}"))
                if offset + page_size < len(caregivers):
                    next_off = offset + page_size
                    nav.append(InlineKeyboardButton("הבא ›", callback_data=f"caregiver_page_{next_off}"))
                if nav:
                    keyboard.append(nav)
                # Actions
                keyboard.append([InlineKeyboardButton(f"{config.EMOJIS['caregiver']} הוסף מטפל", callback_data="caregiver_add")])
                if caregivers:
                    keyboard.append([InlineKeyboardButton(f"📊 שלח דוח למטפלים", callback_data="caregiver_send_report")])
            keyboard.append([InlineKeyboardButton(f"{config.EMOJIS['back']} חזור", callback_data="main_menu")])
            if query:
                await query.answer()
                await query.edit_message_text(message, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                await update.message.reply_text(message, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            logger.error(f"Error viewing caregivers: {e}")
            await self._send_error_message(update, "שגיאה בהצגת המטפלים")
    
    async def _save_caregiver(self, user_id: int) -> bool:
        """Save caregiver to database"""
        try:
            data = self.user_caregiver_data[user_id]
            
            caregiver = await DatabaseManager.create_caregiver(
                user_id=data['user_id'],
                caregiver_name=data['caregiver_name'],
                phone=data.get('phone'),
                email=data.get('email')
            )
            
            return caregiver is not None
            
        except Exception as e:
            logger.error(f"Error saving caregiver: {e}")
            return False
    
    async def _notify_new_caregiver(self, user_id: int, caregiver_data: Dict):
        """Send notification to new caregiver"""
        try:
            user = await DatabaseManager.get_user_by_telegram_id(user_id)
            if not user:
                return
            
            message = f"""
{config.EMOJIS['caregiver']} <b>הוזמנתם כמטפל</b>

👤 <b>מטופל:</b> {user.first_name} {user.last_name or ''}
🏥 <b>קשר:</b> {caregiver_data['relationship_type']}
🔐 <b>הרשאות:</b> {self.permission_levels.get(caregiver_data['permissions'], caregiver_data['permissions'])}

אתם יכולים עכשיו לקבל דוחות על נטילת התרופות ולעזור במעקב.

להתחלת השימוש: /start
            """
            
            from main import bot  # Avoid circular import
            caregiver_chat_id = caregiver_data.get('caregiver_telegram_id')
            if bot and caregiver_chat_id:
                await bot.send_message(
                    chat_id=caregiver_chat_id,
                    text=message,
                    parse_mode='HTML'
                )
            
        except Exception as e:
            logger.error(f"Error notifying new caregiver: {e}")
    
    async def cancel_operation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel caregiver operation"""
        try:
            user_id = update.effective_user.id
            
            # Clean up user data
            if user_id in self.user_caregiver_data:
                del self.user_caregiver_data[user_id]
            
            message = f"{config.EMOJIS['info']} הפעולה בוטלה"
            
            if update.callback_query:
                await update.callback_query.answer()
                await update.callback_query.edit_message_text(message)
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="תפריט ראשי:",
                    reply_markup=get_main_menu_keyboard()
                )
            else:
                await update.message.reply_text(
                    message,
                    reply_markup=get_main_menu_keyboard()
                )
            
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"Error canceling caregiver operation: {e}")
            return ConversationHandler.END
    
    async def _send_error_message(self, update: Update, error_text: str):
        """Send error message to user"""
        try:
            if update.callback_query:
                await update.callback_query.edit_message_text(
                    f"{config.EMOJIS['error']} {error_text}"
                )
                await update.effective_message.reply_text(
                    "תפריט ראשי:",
                    reply_markup=get_main_menu_keyboard()
                )
            else:
                await update.message.reply_text(
                    f"{config.EMOJIS['error']} {error_text}",
                    reply_markup=get_main_menu_keyboard()
                )
        except Exception as e:
            logger.error(f"Error sending error message: {e}")


    # ===== Missing handlers (minimal implementations) =====
    async def caregiver_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show caregiver settings menu (minimal)."""
        try:
            from utils.keyboards import get_caregiver_keyboard
            message = f"{config.EMOJIS['caregiver']} ניהול מטפלים"
            if update.callback_query:
                await update.callback_query.answer()
                await update.callback_query.edit_message_text(
                    message,
                    reply_markup=get_caregiver_keyboard()
                )
            else:
                await update.message.reply_text(
                    message,
                    reply_markup=get_caregiver_keyboard()
                )
        except Exception as e:
            logger.error(f"Error in caregiver_settings: {e}")
            if update.callback_query:
                await update.callback_query.edit_message_text(config.ERROR_MESSAGES['general'])
            else:
                await update.message.reply_text(config.ERROR_MESSAGES['general'])

    async def send_manual_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Entry for manual report sending to caregivers (minimal)."""
        try:
            from handlers import reports_handler
            if reports_handler:
                # Reuse reports menu flow
                if update.callback_query:
                    await reports_handler.show_reports_menu(update, context)
                else:
                    await reports_handler.show_reports_menu(update, context)
            else:
                msg = f"{config.EMOJIS['info']} מודול הדוחות אינו זמין כעת"
                if update.callback_query:
                    await update.callback_query.edit_message_text(msg)
                else:
                    await update.message.reply_text(msg)
        except Exception as e:
            logger.error(f"Error in send_manual_report: {e}")
            if update.callback_query:
                await update.callback_query.edit_message_text(config.ERROR_MESSAGES['general'])
            else:
                await update.message.reply_text(config.ERROR_MESSAGES['general'])

    async def handle_caregiver_actions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle generic caregiver-related callback actions (routing and inline edit steps)."""
        try:
            query = update.callback_query
            await query.answer()
            data = query.data

            # Navigation
            if data == 'caregiver_manage':
                await self.view_caregivers(update, context)
                return
            if data == 'caregiver_add':
                await self.start_add_caregiver(update, context)
                return
            if data == 'caregiver_send_report':
                await self.send_manual_report(update, context)
                return

            # Enter edit view
            if data.startswith('caregiver_edit_') and data.count('_') == 2:
                await self.edit_caregiver(update, context)
                return

            # Edit name
            if data.startswith('caregiver_edit_name_'):
                caregiver_id = int(data.split('_')[-1])
                context.user_data['editing_caregiver'] = {'id': caregiver_id, 'field': 'name'}
                await query.edit_message_text(
                    f"{config.EMOJIS['caregiver']} הזינו שם חדש למטפל:",
                    reply_markup=get_cancel_keyboard()
                )
                return

            # Edit phone
            if data.startswith('caregiver_edit_phone_'):
                caregiver_id = int(data.split('_')[-1])
                context.user_data['editing_caregiver'] = {'id': caregiver_id, 'field': 'phone'}
                await query.edit_message_text(
                    f"{config.EMOJIS['caregiver']} הזינו מספר טלפון חדש:",
                    reply_markup=get_cancel_keyboard()
                )
                return

            # Edit email
            if data.startswith('caregiver_edit_email_'):
                caregiver_id = int(data.split('_')[-1])
                context.user_data['editing_caregiver'] = {'id': caregiver_id, 'field': 'email'}
                await query.edit_message_text(
                    f"{config.EMOJIS['caregiver']} הזינו אימייל חדש (או כתבו דלג כדי להסיר):",
                    reply_markup=get_cancel_keyboard()
                )
                return

            # Edit permissions: show options
            if data.startswith('caregiver_edit_perm_'):
                caregiver_id = int(data.split('_')[-1])
                keyboard = [[InlineKeyboardButton(desc, callback_data=f"caregiver_permset_{key}_{caregiver_id}")] for key, desc in self.permission_levels.items()]
                await query.edit_message_text(
                    f"{config.EMOJIS['caregiver']} בחרו הרשאות:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return

            # Permissions selection
            if data.startswith('caregiver_permset_'):
                parts = data.split('_')
                perm_key = parts[2]
                caregiver_id = int(parts[3])
                await DatabaseManager.update_caregiver(caregiver_id, permissions=perm_key)
                await query.edit_message_text(f"{config.EMOJIS['success']} ההרשאות עודכנו ל- {self.permission_levels.get(perm_key, perm_key)}")
                return

            # Confirm remove
            if data.startswith('remove_caregiver_') and data.endswith('_confirm'):
                caregiver_id = int(data.split('_')[-2])
                # Soft delete: set inactive
                success = await DatabaseManager.set_caregiver_active(caregiver_id, False)
                msg = f"{config.EMOJIS['success']} המטפל הוסר" if success else f"{config.EMOJIS['error']} לא ניתן להסיר מטפל"
                await query.edit_message_text(msg)
                return
            if data.startswith('remove_caregiver_') and data.endswith('_cancel'):
                await self.view_caregivers(update, context)
                return
            if data.startswith('remove_caregiver_'):
                caregiver_id = int(data.split('_')[-1])
                await query.edit_message_text(
                    f"{config.EMOJIS['warning']} להסיר מטפל זה?",
                    reply_markup=get_confirmation_keyboard("remove_caregiver", caregiver_id)
                )
                return

            # Toggle active state
            if data.startswith('toggle_caregiver_'):
                caregiver_id = int(data.split('_')[-1])
                caregiver = await DatabaseManager.get_caregiver_by_id(caregiver_id)
                if not caregiver:
                    await query.edit_message_text(f"{config.EMOJIS['error']} מטפל לא נמצא")
                    return
                success = await DatabaseManager.set_caregiver_active(caregiver_id, not caregiver.is_active)
                if success:
                    await self.edit_caregiver(update, context)
                else:
                    await query.edit_message_text(f"{config.EMOJIS['error']} שינוי סטטוס נכשל")
                return

            # Fallback
            await query.edit_message_text(f"{config.EMOJIS['info']} פעולה לא זמינה כעת")
        except Exception as e:
            logger.error(f"Error in handle_caregiver_actions: {e}")
            await update.callback_query.edit_message_text(config.ERROR_MESSAGES['general'])

    async def edit_caregiver(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start caregiver edit flow: show edit options for a selected caregiver."""
        try:
            query = update.callback_query
            await query.answer()
            data = query.data
            caregiver_id = int(data.split('_')[-1])
            caregiver = await DatabaseManager.get_caregiver_by_id(caregiver_id)
            if not caregiver:
                await query.edit_message_text(f"{config.EMOJIS['error']} מטפל לא נמצא")
                return
            perm_desc = self.permission_levels.get(caregiver.permissions, caregiver.permissions)
            status_emoji = config.EMOJIS['success'] if caregiver.is_active else config.EMOJIS['error']
            message = f"""
{config.EMOJIS['caregiver']} <b>עריכת מטפל</b>

<b>{caregiver.caregiver_name}</b> {status_emoji}
📞 {caregiver.phone or ''}
✉️ {caregiver.email or ''}
🔐 {perm_desc}
            """
            keyboard = [
                [InlineKeyboardButton("🧩 עריכה מרוכזת", callback_data=f"caregiver_edit_all_{caregiver_id}")],
                [InlineKeyboardButton("✏️ שנה שם", callback_data=f"caregiver_edit_name_{caregiver_id}"), InlineKeyboardButton("📞 שנה טלפון", callback_data=f"caregiver_edit_phone_{caregiver_id}")],
                [InlineKeyboardButton("✉️ שנה אימייל", callback_data=f"caregiver_edit_email_{caregiver_id}"), InlineKeyboardButton("🔐 שנה הרשאות", callback_data=f"caregiver_edit_perm_{caregiver_id}")],
                [InlineKeyboardButton(f"{'🟢 הפעל' if not caregiver.is_active else '🔴 השבת'}", callback_data=f"toggle_caregiver_{caregiver_id}")],
                [InlineKeyboardButton("🗑️ הסר מטפל", callback_data=f"remove_caregiver_{caregiver_id}")],
                [InlineKeyboardButton(f"{config.EMOJIS['back']} חזור", callback_data="caregiver_manage")]
            ]
            await query.edit_message_text(message, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            logger.error(f"Error in edit_caregiver: {e}")
            await update.callback_query.edit_message_text(config.ERROR_MESSAGES['general'])

    async def confirm_remove_caregiver(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Confirm caregiver removal (placeholder)."""
        try:
            query = update.callback_query
            await query.answer()
            await query.edit_message_text(f"{config.EMOJIS['warning']} הסרת מטפל תיתמך בהמשך")
        except Exception as e:
            logger.error(f"Error in confirm_remove_caregiver: {e}")
            await update.callback_query.edit_message_text(config.ERROR_MESSAGES['general'])

    async def toggle_caregiver_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Toggle caregiver active/inactive (placeholder)."""
        try:
            query = update.callback_query
            await query.answer()
            await query.edit_message_text(f"{config.EMOJIS['info']} שינוי סטטוס מטפל ייתמך בקרוב")
        except Exception as e:
            logger.error(f"Error in toggle_caregiver_status: {e}")
            await update.callback_query.edit_message_text(config.ERROR_MESSAGES['general'])

    async def _edit_all_set_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            data = context.user_data.get('edit_all', {})
            data['name'] = update.message.text.strip()
            context.user_data['edit_all'] = data
            await update.message.reply_text(f"{config.EMOJIS['caregiver']} הזינו מספר טלפון:", reply_markup=get_cancel_keyboard())
            return EDIT_ALL_PHONE
        except Exception as e:
            logger.error(f"Error in _edit_all_set_name: {e}")
            await self._send_error_message(update, "שגיאה בעדכון השם")
            return ConversationHandler.END

    async def _edit_all_set_phone(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            phone = update.message.text.strip()
            import re
            if not re.match(r"^[+\d][\d\-\s]{6,}$", phone):
                await update.message.reply_text(f"{config.EMOJIS['error']} מספר טלפון לא תקין")
                return EDIT_ALL_PHONE
            data = context.user_data.get('edit_all', {})
            data['phone'] = phone
            context.user_data['edit_all'] = data
            await update.message.reply_text(f"{config.EMOJIS['caregiver']} הזינו אימייל (או כתבו דלג):", reply_markup=get_cancel_keyboard())
            return EDIT_ALL_EMAIL
        except Exception as e:
            logger.error(f"Error in _edit_all_set_phone: {e}")
            await self._send_error_message(update, "שגיאה בעדכון הטלפון")
            return ConversationHandler.END

    async def _edit_all_set_email(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            email = update.message.text.strip()
            if email.lower() in ("דלג", "skip", "אין", "-"):
                email = None
            elif email:
                import re
                if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
                    await update.message.reply_text(f"{config.EMOJIS['error']} אימייל לא תקין או כתבו דלג")
                    return EDIT_ALL_EMAIL
            data = context.user_data.get('edit_all', {})
            data['email'] = email
            context.user_data['edit_all'] = data
            # permissions keyboard
            keyboard = [[InlineKeyboardButton(desc, callback_data=f"perm_{key}")] for key, desc in self.permission_levels.items()]
            await update.message.reply_text(f"{config.EMOJIS['caregiver']} בחרו הרשאות:", reply_markup=InlineKeyboardMarkup(keyboard))
            return EDIT_ALL_PERMS
        except Exception as e:
            logger.error(f"Error in _edit_all_set_email: {e}")
            await self._send_error_message(update, "שגיאה בעדכון האימייל")
            return ConversationHandler.END

    async def _edit_all_set_perms(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            query = update.callback_query
            await query.answer()
            perm_key = query.data.split('_')[1]
            data = context.user_data.get('edit_all', {})
            caregiver_id = int(data.get('id')) if data.get('id') else None
            if not caregiver_id:
                await query.edit_message_text(config.ERROR_MESSAGES['general'])
                return ConversationHandler.END
            # apply updates
            await DatabaseManager.update_caregiver(
                caregiver_id,
                caregiver_name=data.get('name'),
                permissions=perm_key,
                email=data.get('email'),
                phone=data.get('phone')
            )
            # Clear and go back to caregivers list at the current page
            context.user_data.pop('edit_all', None)
            await self.view_caregivers(update, context)
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Error in _edit_all_set_perms: {e}")
            await update.callback_query.edit_message_text(config.ERROR_MESSAGES['general'])
            return ConversationHandler.END


# Global instance
caregiver_handler = CaregiverHandler()
