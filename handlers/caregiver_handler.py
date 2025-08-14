"""
Caregiver Handler
Handles caregiver management: adding, removing, permissions, daily reports
"""

import logging
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
CAREGIVER_TELEGRAM_ID, CAREGIVER_NAME, CAREGIVER_RELATIONSHIP, CAREGIVER_PERMISSIONS = range(4)
EDIT_CAREGIVER_NAME, EDIT_CAREGIVER_RELATIONSHIP, EDIT_CAREGIVER_PERMISSIONS = range(4, 7)


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
                CAREGIVER_TELEGRAM_ID: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_caregiver_telegram_id)
                ],
                CAREGIVER_NAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_caregiver_name)
                ],
                CAREGIVER_RELATIONSHIP: [
                    CallbackQueryHandler(self.handle_relationship_selection, pattern="^rel_"),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_custom_relationship)
                ],
                CAREGIVER_PERMISSIONS: [
                    CallbackQueryHandler(self.handle_permissions_selection, pattern="^perm_")
                ]
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
            
            # Check caregiver limit
            existing_caregivers = await DatabaseManager.get_user_caregivers(user.id, active_only=False)
            if len(existing_caregivers) >= config.MAX_CAREGIVERS_PER_USER:
                message = f"""
{config.EMOJIS['error']} <b>הגעתם למגבלת המטפלים</b>

אתם יכולים להוסיף עד {config.MAX_CAREGIVERS_PER_USER} מטפלים.
אנא הסירו מטפל קיים לפני הוספת מטפל חדש.
                """
                
                if update.callback_query:
                    await update.callback_query.answer()
                    await update.callback_query.edit_message_text(
                        message,
                        parse_mode='HTML',
                        reply_markup=get_caregiver_keyboard()
                    )
                else:
                    await update.message.reply_text(
                        message,
                        parse_mode='HTML',
                        reply_markup=get_caregiver_keyboard()
                    )
                
                return ConversationHandler.END
            
            # Initialize caregiver data
            self.user_caregiver_data[user_id] = {
                'user_id': user.id,
                'step': 'telegram_id'
            }
            
            message = f"""
{config.EMOJIS['caregiver']} <b>הוספת מטפל חדש</b>

🔹 <b>שלב 1/4:</b> מזהה טלגרם

אנא שלחו את מזהה הטלגרם של המטפל:
• ניתן לקבל את המזהה ממטפל
• או לשלוח @username (אם קיים)

דוגמה: 123456789
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
            
            return CAREGIVER_TELEGRAM_ID
            
        except Exception as e:
            logger.error(f"Error starting add caregiver: {e}")
            await self._send_error_message(update, "שגיאה בתחילת הוספת המטפל")
            return ConversationHandler.END
    
    async def get_caregiver_telegram_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Get caregiver Telegram ID"""
        try:
            user_id = update.effective_user.id
            telegram_id_str = update.message.text.strip()
            
            # Handle @username format
            if telegram_id_str.startswith('@'):
                await update.message.reply_text(
                    f"{config.EMOJIS['info']} שלוח מזהה מספרי של המטפל (לא @username)"
                )
                return CAREGIVER_TELEGRAM_ID
            
            # Validate Telegram ID
            is_valid, error_msg = validate_telegram_id(telegram_id_str)
            if not is_valid:
                await update.message.reply_text(
                    f"{config.EMOJIS['error']} {error_msg}"
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
                if caregiver.caregiver_telegram_id == caregiver_telegram_id:
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
            
            # Create relationship selection keyboard
            keyboard = []
            for i, relationship in enumerate(self.relationship_types):
                keyboard.append([
                    InlineKeyboardButton(
                        relationship,
                        callback_data=f"rel_{i}"
                    )
                ])
            
            keyboard.append([
                InlineKeyboardButton(
                    "אחר (הזן ידנית)",
                    callback_data="rel_custom"
                )
            ])
            
            message = f"""
{config.EMOJIS['caregiver']} <b>הוספת מטפל חדש</b>

✅ <b>שם המטפל:</b> {caregiver_name}

🔹 <b>שלב 3/4:</b> קשר למטופל

בחרו את סוג הקשר של המטפל אליכם:
            """
            
            await update.message.reply_text(
                message,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            return CAREGIVER_RELATIONSHIP
            
        except Exception as e:
            logger.error(f"Error getting caregiver name: {e}")
            await self._send_error_message(update, "שגיאה בקבלת שם המטפל")
            return ConversationHandler.END
    
    async def handle_relationship_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle relationship selection"""
        try:
            query = update.callback_query
            await query.answer()
            
            user_id = query.from_user.id
            data = query.data
            
            if data == "rel_custom":
                message = f"""
{config.EMOJIS['caregiver']} <b>הוספת מטפל חדש</b>

🔹 <b>הזנת קשר מותאם אישית:</b>

אנא הזינו את סוג הקשר של המטפל אליכם:
                """
                
                await query.edit_message_text(
                    message,
                    parse_mode='HTML',
                    reply_markup=get_cancel_keyboard()
                )
                
                return CAREGIVER_RELATIONSHIP
            
            # Parse relationship index
            rel_index = int(data.split("_")[1])
            relationship = self.relationship_types[rel_index]
            
            # Store relationship
            self.user_caregiver_data[user_id]['relationship_type'] = relationship
            
            # Create permissions keyboard
            keyboard = []
            for perm_key, perm_desc in self.permission_levels.items():
                keyboard.append([
                    InlineKeyboardButton(
                        f"{perm_desc}",
                        callback_data=f"perm_{perm_key}"
                    )
                ])
            
            caregiver_name = self.user_caregiver_data[user_id]['caregiver_name']
            
            message = f"""
{config.EMOJIS['caregiver']} <b>הוספת מטפל חדש</b>

✅ <b>שם המטפל:</b> {caregiver_name}
✅ <b>קשר:</b> {relationship}

🔹 <b>שלב 4/4:</b> הרשאות

בחרו את רמת ההרשאות של המטפל:

• <b>צפייה בלבד</b> - יכול לראות דוחות בלבד
• <b>ניהול תרופות</b> - יכול להוסיף ולערוך תרופות
• <b>מנהל מלא</b> - גישה מלאה לכל הפונקציות
            """
            
            await query.edit_message_text(
                message,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            return CAREGIVER_PERMISSIONS
            
        except Exception as e:
            logger.error(f"Error handling relationship selection: {e}")
            await query.edit_message_text(
                f"{config.EMOJIS['error']} שגיאה בבחירת הקשר"
            )
            return ConversationHandler.END
    
    async def get_custom_relationship(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Get custom relationship text"""
        try:
            user_id = update.effective_user.id
            relationship = update.message.text.strip()
            
            if len(relationship) < 2:
                await update.message.reply_text(
                    f"{config.EMOJIS['error']} הקשר קצר מדי"
                )
                return CAREGIVER_RELATIONSHIP
            
            if len(relationship) > 50:
                await update.message.reply_text(
                    f"{config.EMOJIS['error']} הקשר ארוך מדי"
                )
                return CAREGIVER_RELATIONSHIP
            
            # Store relationship
            self.user_caregiver_data[user_id]['relationship_type'] = relationship
            
            # Create permissions keyboard
            keyboard = []
            for perm_key, perm_desc in self.permission_levels.items():
                keyboard.append([
                    InlineKeyboardButton(
                        f"{perm_desc}",
                        callback_data=f"perm_{perm_key}"
                    )
                ])
            
            caregiver_name = self.user_caregiver_data[user_id]['caregiver_name']
            
            message = f"""
{config.EMOJIS['caregiver']} <b>הוספת מטפל חדש</b>

✅ <b>שם המטפל:</b> {caregiver_name}
✅ <b>קשר:</b> {relationship}

🔹 <b>שלב 4/4:</b> הרשאות

בחרו את רמת ההרשאות של המטפל:
            """
            
            await update.message.reply_text(
                message,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            return CAREGIVER_PERMISSIONS
            
        except Exception as e:
            logger.error(f"Error getting custom relationship: {e}")
            await self._send_error_message(update, "שגיאה בקבלת הקשר")
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
            
            success = await self._save_caregiver(user_id)
            
            if success:
                data = self.user_caregiver_data[user_id]
                perm_desc = self.permission_levels.get(permissions, permissions)
                
                message = f"""
{config.EMOJIS['success']} <b>מטפל נוסף בהצלחה!</b>

{config.EMOJIS['caregiver']} <b>פרטי המטפל:</b>
• שם: {data['caregiver_name']}
• קשר: {data['relationship_type']}
• הרשאות: {perm_desc}
• מזהה טלגרם: {data['caregiver_telegram_id']}

המטפל יקבל הודעה על ההצטרפות ויוכל לראות דוחות מיד.
                """
                
                # Send notification to caregiver
                await self._notify_new_caregiver(user_id, data)
                
                keyboard = [
                    [
                        InlineKeyboardButton(
                            f"{config.EMOJIS['caregiver']} נהל מטפלים",
                            callback_data="caregiver_manage"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            f"{config.EMOJIS['home']} תפריט ראשי",
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
        """View and manage caregivers"""
        try:
            user_id = update.effective_user.id
            user = await DatabaseManager.get_user_by_telegram_id(user_id)
            
            if not user:
                await self._send_error_message(update, "משתמש לא נמצא")
                return
            
            caregivers = await DatabaseManager.get_user_caregivers(user.id, active_only=False)
            
            if not caregivers:
                message = f"""
{config.EMOJIS['info']} <b>אין מטפלים רשומים</b>

עדיין לא הוספתם מטפלים.
מטפלים יכולים לעזור לכם לעקוב אחר נטילת התרופות ולקבל דוחות.
                """
                
                keyboard = [
                    [
                        InlineKeyboardButton(
                            f"{config.EMOJIS['caregiver']} הוסף מטפל ראשון",
                            callback_data="caregiver_add"
                        )
                    ]
                ]
            else:
                message = f"{config.EMOJIS['caregiver']} <b>המטפלים שלכם ({len(caregivers)}):</b>\n\n"
                
                for caregiver in caregivers:
                    status_emoji = config.EMOJIS['success'] if caregiver.is_active else config.EMOJIS['error']
                    perm_desc = self.permission_levels.get(caregiver.permissions, caregiver.permissions)
                    
                    message += f"{status_emoji} <b>{caregiver.caregiver_name}</b>\n"
                    message += f"   👤 {caregiver.relationship_type}\n"
                    message += f"   🔐 {perm_desc}\n"
                    message += f"   📅 נוסף: {caregiver.created_at.strftime('%d/%m/%Y')}\n\n"
                
                keyboard = []
                
                # Add management buttons for each caregiver
                for caregiver in caregivers[:5]:  # Limit to 5 for space
                    keyboard.append([
                        InlineKeyboardButton(
                            f"✏️ {caregiver.caregiver_name}",
                            callback_data=f"caregiver_edit_{caregiver.id}"
                        )
                    ])
                
                # Action buttons
                keyboard.append([
                    InlineKeyboardButton(
                        f"{config.EMOJIS['caregiver']} הוסף מטפל",
                        callback_data="caregiver_add"
                    )
                ])
                
                if caregivers:
                    keyboard.append([
                        InlineKeyboardButton(
                            f"📊 שלח דוח למטפלים",
                            callback_data="caregiver_send_report"
                        )
                    ])
            
            keyboard.append([
                InlineKeyboardButton(
                    f"{config.EMOJIS['back']} חזור",
                    callback_data="main_menu"
                )
            ])
            
            if update.callback_query:
                await update.callback_query.answer()
                await update.callback_query.edit_message_text(
                    message,
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                await update.message.reply_text(
                    message,
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            
        except Exception as e:
            logger.error(f"Error viewing caregivers: {e}")
            await self._send_error_message(update, "שגיאה בהצגת המטפלים")
    
    async def _save_caregiver(self, user_id: int) -> bool:
        """Save caregiver to database"""
        try:
            data = self.user_caregiver_data[user_id]
            
            caregiver = await DatabaseManager.create_caregiver(
                user_id=data['user_id'],
                caregiver_telegram_id=data['caregiver_telegram_id'],
                caregiver_name=data['caregiver_name'],
                relationship=data['relationship_type'],
                permissions=data['permissions']
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
            if bot:
                await bot.send_message(
                    chat_id=caregiver_data['caregiver_telegram_id'],
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
                await update.callback_query.edit_message_text(
                    message,
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
                    f"{config.EMOJIS['error']} {error_text}",
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
        """Handle generic caregiver-related callback actions (routing only)."""
        try:
            query = update.callback_query
            await query.answer()
            data = query.data
            
            if data == 'caregiver_manage':
                await self.view_caregivers(update, context)
                return
            if data == 'caregiver_add':
                await self.start_add_caregiver(update, context)
                return
            if data == 'caregiver_send_report':
                await self.send_manual_report(update, context)
                return
            if data.startswith('caregiver_edit_'):
                await self.edit_caregiver(update, context)
                return
            if data.startswith('remove_caregiver_'):
                await self.confirm_remove_caregiver(update, context)
                return
            if data.startswith('toggle_caregiver_'):
                await self.toggle_caregiver_status(update, context)
                return
            
            # Fallback
            await query.edit_message_text(f"{config.EMOJIS['info']} פעולה לא זמינה כעת")
        except Exception as e:
            logger.error(f"Error in handle_caregiver_actions: {e}")
            await update.callback_query.edit_message_text(config.ERROR_MESSAGES['general'])

    async def edit_caregiver(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start caregiver edit flow (minimal placeholder)."""
        try:
            query = update.callback_query
            await query.answer()
            data = query.data
            caregiver_id = None
            try:
                caregiver_id = int(data.split('_')[-1])
            except Exception:
                pass
            
            message = f"{config.EMOJIS['info']} עריכת מטפל תתווסף בקרוב"
            if caregiver_id is not None:
                message += f"\n(ID: {caregiver_id})"
                
            from utils.keyboards import get_caregiver_keyboard
            await query.edit_message_text(
                message,
                reply_markup=get_caregiver_keyboard()
            )
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


# Global instance
caregiver_handler = CaregiverHandler()
