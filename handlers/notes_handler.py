"""
Notes Handler

A free-form notepad, not attached to any particular medicine. Medicines already
carry a single `notes` field that is overwritten on every edit; this is the
place for things that accumulate - questions for the doctor, what a pharmacist
said, how a dose felt.

Menu driven rather than a ConversationHandler: the only text step is the note
body, which is flagged on user_data and picked up by main.handle_text_message.
"""

import logging
from typing import List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from config import config
from database import DatabaseManager

logger = logging.getLogger(__name__)

# How much of a note to show in the list before truncating
PREVIEW_LENGTH = 40

# user_data flags
AWAITING_NEW_NOTE = "awaiting_note_text"
EDITING_NOTE = "editing_note_id"


def _preview(content: str) -> str:
    """One-line label for the list button."""
    first_line = (content or "").strip().splitlines()[0] if (content or "").strip() else ""
    if len(first_line) > PREVIEW_LENGTH:
        return first_line[: PREVIEW_LENGTH - 1] + "…"
    return first_line or "(פתק ריק)"


def _notes_list_keyboard(notes: List) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(f"📄 {_preview(n.content)}", callback_data=f"note_view_{n.id}")]
        for n in notes
    ]
    rows.append([InlineKeyboardButton("➕ פתק חדש", callback_data="note_add")])
    rows.append([InlineKeyboardButton(f"{config.EMOJIS['back']} חזור", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)


def _note_detail_keyboard(note_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(f"{config.EMOJIS['settings']} ערוך", callback_data=f"note_edit_{note_id}"),
                InlineKeyboardButton(f"{config.EMOJIS['error']} מחק", callback_data=f"note_del_{note_id}"),
            ],
            [InlineKeyboardButton(f"{config.EMOJIS['back']} חזור לפתקים", callback_data="notes_menu")],
        ]
    )


class NotesHandler:
    """Free-form notes: list, read, add, edit, delete."""

    def get_handlers(self) -> List:
        return [
            CallbackQueryHandler(self.show_notes, pattern="^notes_menu$"),
            CallbackQueryHandler(self.start_add_note, pattern="^note_add$"),
            CallbackQueryHandler(self.view_note, pattern=r"^note_view_\d+$"),
            CallbackQueryHandler(self.start_edit_note, pattern=r"^note_edit_\d+$"),
            CallbackQueryHandler(self.ask_delete_note, pattern=r"^note_del_\d+$"),
            CallbackQueryHandler(self.confirm_delete_note, pattern=r"^notedel_\d+_confirm$"),
            CallbackQueryHandler(self.cancel_delete_note, pattern=r"^notedel_\d+_cancel$"),
        ]

    async def show_notes(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List the user's notes. Works from a button or from the main menu text."""
        try:
            self._clear_flags(context)
            user = await DatabaseManager.get_user_by_telegram_id(update.effective_user.id)
            if not user:
                await self._reply(update, config.ERROR_MESSAGES["unauthorized"])
                return

            notes = await DatabaseManager.get_user_notes(user.id)
            if notes:
                message = f"📝 <b>הפתקים שלי</b>\n\nיש {len(notes)} פתקים. בחרו פתק לצפייה:"
            else:
                message = "📝 <b>הפתקים שלי</b>\n\nאין עדיין פתקים.\nכאן אפשר לרשום שאלות לרופא, מה אמר הרוקח, איך הרגשתם אחרי מנה."

            await self._reply(update, message, reply_markup=_notes_list_keyboard(notes), parse_mode="HTML")

        except Exception as exc:
            logger.error(f"Error showing notes: {exc}")
            await self._reply(update, config.ERROR_MESSAGES["general"])

    async def start_add_note(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        self._clear_flags(context)
        context.user_data[AWAITING_NEW_NOTE] = True
        await query.edit_message_text(
            "📝 כתבו את הפתק:",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(f"{config.EMOJIS['back']} ביטול", callback_data="notes_menu")]]
            ),
        )

    async def view_note(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        await self._render_note(query, int(query.data.rsplit("_", 1)[1]))

    @staticmethod
    async def _render_note(query, note_id: int):
        """Show one note. Kept separate because two callbacks land on this view."""
        note = await DatabaseManager.get_note_by_id(note_id)
        if not note:
            await query.edit_message_text("הפתק לא נמצא.")
            return

        created = note.created_at.strftime("%d/%m/%Y %H:%M") if note.created_at else ""
        await query.edit_message_text(
            f"📄 <b>פתק</b>\n<i>{created}</i>\n\n{note.content}",
            parse_mode="HTML",
            reply_markup=_note_detail_keyboard(note_id),
        )

    async def start_edit_note(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        note_id = int(query.data.rsplit("_", 1)[1])
        self._clear_flags(context)
        context.user_data[EDITING_NOTE] = note_id
        await query.edit_message_text(
            "📝 כתבו את התוכן החדש של הפתק:",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(f"{config.EMOJIS['back']} ביטול", callback_data=f"note_view_{note_id}")]]
            ),
        )

    async def ask_delete_note(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        note_id = int(query.data.rsplit("_", 1)[1])
        await query.edit_message_text(
            "למחוק את הפתק?",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("כן, מחק", callback_data=f"notedel_{note_id}_confirm"),
                        InlineKeyboardButton("ביטול", callback_data=f"notedel_{note_id}_cancel"),
                    ]
                ]
            ),
        )

    async def confirm_delete_note(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        note_id = int(query.data.split("_")[1])
        await DatabaseManager.delete_note(note_id)
        await self.show_notes(update, context)

    async def cancel_delete_note(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        # CallbackQuery is immutable, so re-render directly instead of rewriting query.data
        await self._render_note(query, int(query.data.split("_")[1]))

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Consume a pending note body. Returns True if the text was ours."""
        user_data = context.user_data
        adding = user_data.get(AWAITING_NEW_NOTE)
        editing = user_data.get(EDITING_NOTE)
        if not adding and not editing:
            return False

        content = (update.message.text or "").strip()
        self._clear_flags(context)

        if not content:
            await update.message.reply_text(f"{config.EMOJIS['error']} הפתק ריק, לא נשמר.")
            return True

        if editing:
            await DatabaseManager.update_note(int(editing), content)
            await update.message.reply_text(f"{config.EMOJIS['success']} הפתק עודכן")
        else:
            user = await DatabaseManager.get_user_by_telegram_id(update.effective_user.id)
            if not user:
                await update.message.reply_text(config.ERROR_MESSAGES["unauthorized"])
                return True
            await DatabaseManager.create_note(user.id, content)
            await update.message.reply_text(f"{config.EMOJIS['success']} הפתק נשמר")

        await self.show_notes(update, context)
        return True

    @staticmethod
    def _clear_flags(context: ContextTypes.DEFAULT_TYPE):
        context.user_data.pop(AWAITING_NEW_NOTE, None)
        context.user_data.pop(EDITING_NOTE, None)

    @staticmethod
    async def _reply(update: Update, text: str, **kwargs):
        """Answer through whichever channel the user arrived on."""
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(text, **kwargs)
        else:
            await update.message.reply_text(text, **kwargs)


notes_handler = NotesHandler()
