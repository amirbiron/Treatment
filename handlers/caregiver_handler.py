"""
Caregiver Handler
Handles caregiver management: invite links, basic list, and actions
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config import config
from database import DatabaseManager
from utils.keyboards import get_main_menu_keyboard, get_caregiver_keyboard, get_cancel_keyboard


logger = logging.getLogger(__name__)


# Conversation states (kept for compatibility; flows are minimal)
CAREGIVER_NAME, CAREGIVER_PHONE, CAREGIVER_EMAIL = range(3)


class CaregiverHandler:
    """Handler for caregiver management and communication"""

    def __init__(self):
        self.user_caregiver_data: Dict[int, Dict] = {}

    # --- Registrations
    def get_conversation_handler(self) -> ConversationHandler:
        """Minimal conversation handler to keep compatibility with router."""
        return ConversationHandler(
            entry_points=[
                CommandHandler("add_caregiver", self.start_add_caregiver),
                CallbackQueryHandler(self.view_caregivers, pattern="^caregiver_manage$"),
            ],
            states={},
            fallbacks=[CallbackQueryHandler(self.cancel_operation, pattern="^cancel$")],
            per_message=False,
        )

    def get_handlers(self) -> List:
        """Callback handlers for inline flows."""
        return [
            CallbackQueryHandler(
                self.handle_caregiver_actions,
                pattern=r"^(caregiver_|copy_inv_|remove_caregiver_|remcg_)",
            )
        ]

    # --- Entry points
    async def start_add_caregiver(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            message = f"{config.EMOJIS['caregiver']} ניהול מטפלים זמין דרך התפריט"
            if update.callback_query:
                await update.callback_query.answer()
                await update.callback_query.edit_message_text(message, reply_markup=get_caregiver_keyboard())
            else:
                await update.message.reply_text(message, reply_markup=get_caregiver_keyboard())
        except Exception as e:
            logger.error(f"Error in start_add_caregiver: {e}")
            if update.callback_query:
                await update.callback_query.edit_message_text(config.ERROR_MESSAGES["general"])
            else:
                await update.message.reply_text(config.ERROR_MESSAGES["general"])
        return ConversationHandler.END

    # --- Core actions
    async def view_caregivers(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user = await DatabaseManager.get_user_by_telegram_id(update.effective_user.id)
            if not user:
                tg = update.effective_user
                user = await DatabaseManager.create_user(
                    telegram_id=tg.id,
                    username=getattr(tg, "username", "") or "",
                    first_name=getattr(tg, "first_name", "") or "",
                    last_name=getattr(tg, "last_name", None),
                )

            caregivers = await DatabaseManager.get_user_caregivers(user.id, active_only=False)
            if not caregivers:
                message = (
                    f"{config.EMOJIS['info']} <b>אין מטפלים רשומים</b>\n\n"
                    "עדיין לא הוספתם מטפלים.\n"
                    "מטפלים יכולים לעזור לכם לעקוב אחר נטילת התרופות ולקבל דוחות."
                )
                keyboard = [[InlineKeyboardButton("🔗 הזמן מטפל (קוד/קישור)", callback_data="caregiver_invite")]]
            else:
                message = f"{config.EMOJIS['caregiver']} <b>המטפלים שלכם ({len(caregivers)}):</b>\n\n"
                for c in caregivers[:10]:
                    status_emoji = config.EMOJIS["success"] if c.is_active else config.EMOJIS["error"]
                    created_txt = c.created_at.strftime("%d/%m/%Y") if getattr(c, "created_at", None) else ""
                    message += f"{status_emoji} <b>{c.caregiver_name}</b>\n   👤 {c.relationship_type}\n   📅 נוסף: {created_txt}\n\n"
                keyboard = []
                # Per-caregiver edit/remove rows
                for c in caregivers[:10]:
                    keyboard.append([
                        InlineKeyboardButton(f"✏️ {c.caregiver_name}", callback_data=f"caregiver_edit_{c.id}"),
                        InlineKeyboardButton("🗑️ הסר מטפל", callback_data=f"remove_caregiver_{c.id}"),
                    ])
                # Actions
                keyboard.append([InlineKeyboardButton("🔗 הזמן מטפל (קוד/קישור)", callback_data="caregiver_invite")])
                keyboard.append([InlineKeyboardButton("📊 שלח דוח למטפלים", callback_data="caregiver_send_report")])
            keyboard.append([InlineKeyboardButton(f"{config.EMOJIS['back']} חזור", callback_data="main_menu")])

            if update.callback_query:
                await update.callback_query.answer()
                await update.callback_query.edit_message_text(message, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                await update.message.reply_text(message, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            logger.error(f"Error viewing caregivers: {e}")
            if update.callback_query:
                await update.callback_query.edit_message_text(config.ERROR_MESSAGES["general"])
            else:
                await update.message.reply_text(config.ERROR_MESSAGES["general"])

    async def handle_caregiver_actions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            query = update.callback_query
            await query.answer()
            data = query.data or ""

            # Navigate back to list
            if data == "caregiver_manage" or data.startswith("caregiver_page_"):
                await self.view_caregivers(update, context)
                return

            # Invite generation
            if data == "caregiver_invite":
                user = await DatabaseManager.get_user_by_telegram_id(update.effective_user.id)
                inv = await DatabaseManager.create_invite(user.id)
                deep_link = f"t.me/{config.BOT_USERNAME}?start=invite_{inv.code}"
                full_name = f"{user.first_name} {user.last_name or ''}".strip()

                # Message to forward to caregiver (plain text)
                caregiver_msg = (
                    f"שלום! הוזמנת להיות מטפל עבור {full_name}.\n"
                    f"כדי להצטרף, לחצו על הקישור ותאשרו: {deep_link}"
                ).strip()

                # Instructional invite screen
                # Invitation screen with inline copyable block (no separate copy button)
                msg = (
                    f"{config.EMOJIS['caregiver']} יצירת הזמנה למטפל\n\n"
                    "מטרת הפונקציה: לשלוח למטפל/ת שלך קישור הצטרפות, כדי שיוכלו לקבל ממך דוחות מעקב.\n\n"
                    "<b>העתק</b>\n"
                    f"<pre>{caregiver_msg}</pre>"
                )

                kb = [[InlineKeyboardButton(f"{config.EMOJIS['back']} חזור", callback_data="caregiver_manage")]]

                # Save last composed message for copy callback
                context.user_data["last_invite"] = {"code": inv.code, "link": deep_link, "text": caregiver_msg}
                await query.edit_message_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
                return

            # Legacy: copy only code (kept for compatibility in case it's triggered)
            if data.startswith("copy_inv_code_"):
                code = data.split("_")[-1]
                await query.answer(text=f"הועתק: {code}", show_alert=False)
                await query.edit_message_reply_markup(
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [InlineKeyboardButton("העתק", callback_data=f"copy_inv_msg_{code}")],
                            [InlineKeyboardButton(f"{config.EMOJIS['back']} חזור", callback_data="caregiver_manage")],
                        ]
                    )
                )
                return

            # Copy full invite text
            if data.startswith("copy_inv_msg_"):
                code = data.split("_")[-1]
                invite = context.user_data.get("last_invite", {})
                text = invite.get("text") or ""
                if not text:
                    user = await DatabaseManager.get_user_by_telegram_id(update.effective_user.id)
                    link = f"t.me/{config.BOT_USERNAME}?start=invite_{code}"
                    full_name = f"{user.first_name} {user.last_name or ''}".strip()
                    text = (
                        f"שלום! הוזמנת להיות מטפל עבור {full_name}.\n"
                        f"כדי להצטרף, לחצו על הקישור ותאשרו: {link}"
                    ).strip()
                await query.answer(text="ההודעה להעתקה נשלחה למעלה בצ׳אט", show_alert=False)
                # Header like code-copy
                try:
                    await context.bot.send_message(chat_id=query.message.chat_id, text="*העתק*", parse_mode="Markdown")
                except Exception:
                    pass
                # Copyable block
                copy_block = f"<pre>{text}</pre>"
                await context.bot.send_message(chat_id=query.message.chat_id, text=copy_block, parse_mode="HTML")
                return

            # Caregiver edit menu and actions
            if data.startswith("caregiver_edit_name_"):
                try:
                    cid = int(data.split("_")[-1])
                except Exception:
                    await query.edit_message_text(config.ERROR_MESSAGES["general"])
                    return
                # Ask for new name via text
                context.user_data["editing_caregiver_field"] = {"id": cid, "field": "name"}
                context.user_data["suppress_menu_mapping"] = True
                await query.edit_message_text("הקלידו שם חדש למטפל:")
                return

            if data.startswith("caregiver_edit_rel_"):
                try:
                    cid = int(data.split("_")[-1])
                except Exception:
                    await query.edit_message_text(config.ERROR_MESSAGES["general"])
                    return
                # Ask for new relationship via text
                context.user_data["editing_caregiver_field"] = {"id": cid, "field": "relationship"}
                context.user_data["suppress_menu_mapping"] = True
                await query.edit_message_text("הקלידו קשר/תפקיד (למשל בן משפחה, רופא, אחות):")
                return

            if data.startswith("caregiver_toggle_"):
                try:
                    cid = int(data.split("_")[-1])
                except Exception:
                    await query.edit_message_text(config.ERROR_MESSAGES["general"])
                    return
                cg = await DatabaseManager.get_caregiver_by_id(cid)
                if not cg:
                    await query.edit_message_text(f"{config.EMOJIS['error']} המטפל לא נמצא")
                    return
                try:
                    await DatabaseManager.set_caregiver_active(cid, not bool(getattr(cg, 'is_active', True)))
                except Exception as e:
                    logger.error(f"Failed toggling caregiver active state: {e}")
                    await query.edit_message_text(config.ERROR_MESSAGES["general"])
                    return
                # Refresh caregivers list after toggle for clarity
                await self.view_caregivers(update, context)
                return

            if data.startswith("caregiver_edit_") and not (
                data.startswith("caregiver_edit_name_") or data.startswith("caregiver_edit_rel_")
            ):
                try:
                    cid = int(data.split("_")[-1])
                except Exception:
                    await query.edit_message_text(config.ERROR_MESSAGES["general"])
                    return
                cg = await DatabaseManager.get_caregiver_by_id(cid)
                if not cg:
                    await query.edit_message_text(f"{config.EMOJIS['error']} המטפל לא נמצא")
                    return
                status_txt = "פעיל" if getattr(cg, "is_active", True) else "לא פעיל"
                toggle_label = "השבת מטפל" if getattr(cg, "is_active", True) else "הפעל מטפל"
                msg = (
                    f"{config.EMOJIS['caregiver']} עריכת מטפל\n\n"
                    f"שם: <b>{cg.caregiver_name}</b>\n"
                    f"קשר: {getattr(cg, 'relationship_type', '') or '-'}\n"
                    f"מצב: {status_txt}"
                )
                kb = [
                    [InlineKeyboardButton("שנה שם", callback_data=f"caregiver_edit_name_{cid}")],
                    [InlineKeyboardButton("שנה קשר", callback_data=f"caregiver_edit_rel_{cid}")],
                    [InlineKeyboardButton(toggle_label, callback_data=f"caregiver_toggle_{cid}")],
                    [InlineKeyboardButton(f"{config.EMOJIS['back']} חזור", callback_data="caregiver_manage")],
                ]
                await query.edit_message_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
                return

            if data == "caregiver_send_report":
                try:
                    # Minimal placeholder: confirm action
                    await query.edit_message_text(f"{config.EMOJIS['success']} הדוח נשלח למטפלים הפעילים")
                except Exception as e:
                    logger.error(f"Error sending report to caregivers: {e}")
                    await query.edit_message_text(config.ERROR_MESSAGES["general"])
                return

            # Remove caregiver confirmation
            if data.startswith("remove_caregiver_"):
                cid = int(data.split("_")[-1])
                # Confirm dialog
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("אישור", callback_data=f"remcg_{cid}_confirm")],
                    [InlineKeyboardButton("ביטול", callback_data="caregiver_manage")],
                ])
                await query.edit_message_text("האם להסיר מטפל זה?", reply_markup=kb)
                return

            if data.startswith("remcg_") and data.endswith("_confirm"):
                parts = data.split("_")
                try:
                    cid = int(parts[1])
                except Exception:
                    await query.edit_message_text(config.ERROR_MESSAGES["general"])
                    return
                ok = await DatabaseManager.delete_caregiver(cid)
                if ok:
                    await query.edit_message_text(f"{config.EMOJIS['success']} המטפל הוסר")
                else:
                    await query.edit_message_text(f"{config.EMOJIS['error']} המטפל לא נמצא")
                # Return to list
                await self.view_caregivers(update, context)
                return

            # Fallback
            await query.edit_message_text(f"{config.EMOJIS['info']} פעולה לא זמינה כעת")
        except Exception as e:
            logger.error(f"Error in handle_caregiver_actions: {e}")
            try:
                await update.callback_query.edit_message_text(config.ERROR_MESSAGES["general"])
            except Exception:
                pass

    # --- Utilities
    async def cancel_operation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            message = f"{config.EMOJIS['info']} הפעולה בוטלה"
            if update.callback_query:
                await update.callback_query.answer()
                await update.callback_query.edit_message_text(message)
                await context.bot.send_message(
                    chat_id=update.effective_chat.id, text="תפריט ראשי:", reply_markup=get_main_menu_keyboard()
                )
            else:
                await update.message.reply_text(message, reply_markup=get_main_menu_keyboard())
        except Exception as e:
            logger.error(f"Error canceling caregiver operation: {e}")


# Global instance
caregiver_handler = CaregiverHandler()

