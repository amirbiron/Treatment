"""
Pharmacy Inventory Agent
AI-powered agent for checking medication availability at Clalit pharmacies in Israel.
Uses Gemini for natural language understanding and the Clalit Pharmacy API for data.

Architecture follows the 6-layer agent pattern:
  Layer 1 - Configuration (AGENT_STATE, SYSTEM_PROMPT)
  Layer 2 - Topic Shortcuts
  Layer 3 - Safety Keywords
  Layer 4 - Core AI (Gemini + message splitting)
  Layer 5 - Telegram Handlers
  Layer 6 - ConversationHandler
"""

import json
import logging
import os
from typing import List, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from config import config

logger = logging.getLogger(__name__)

# ── Layer 1: Configuration ────────────────────────────────────────────────────

AGENT_STATE = 10  # Unique state number (0-9 used by medicine_handler)
AGENT_CHATTING = AGENT_STATE  # Alias for clarity

SYSTEM_PROMPT = """\
אתה עוזר ידידותי ומקצועי שעוזר למשתמשים למצוא תרופות ולבדוק זמינות מלאי \
בבתי מרקחת של כללית בישראל.

היכולות שלך:
1. חיפוש תרופות לפי שם (עברית או אנגלית) - מחזיר קוד קטלוגי (catCode) ושם מלא
2. חיפוש ערים שבהן יש בתי מרקחת כללית
3. חיפוש סניפי בתי מרקחת כללית לפי שם
4. בדיקת זמינות מלאי תרופה בעיר מסוימת או סניף מסוים

כללים חשובים:
- ענה תמיד בעברית
- כשמשתמש מבקש לחפש תרופה, השתמש בפונקציה search_medications
- כשמשתמש שואל על עיר, השתמש בפונקציה search_cities
- כשמשתמש שואל על סניף בית מרקחת, השתמש בפונקציה search_pharmacies
- הסבר את התוצאות בצורה ברורה ופשוטה
- אם לא נמצאו תוצאות, הצע חיפוש חלופי
- אל תמציא מידע - ענה רק לפי נתוני המערכת
- היה קצר ותכליתי

פורמט תשובה:
- השתמש באימוג'ים כדי להפוך את התשובה לקריאה יותר
- הצג תוצאות ברשימה מסודרת
- אם יש יותר מ-10 תוצאות, הצג את 10 הראשונות והזכר שיש עוד
"""

GEMINI_MODEL = "gemini-2.0-flash"
MAX_TELEGRAM_MESSAGE_LENGTH = 4096
CONVERSATION_TIMEOUT_SECONDS = 30 * 60  # 30 minutes

# ── Layer 2: Topic Shortcuts ──────────────────────────────────────────────────

TOPIC_SHORTCUTS = {
    "אקמול": "חפש בבקשה את התרופה אקמול",
    "אדויל": "חפש בבקשה את התרופה אדויל",
    "אופטלגין": "חפש בבקשה את התרופה אופטלגין",
    "נורופן": "חפש בבקשה את התרופה נורופן",
}

# ── Layer 3: Safety Keywords ──────────────────────────────────────────────────

SAFETY_OVERRIDES = {
    "מקרה חירום רפואי": "במקרה חירום רפואי אנא פנו למד\"א 101 או לחדר מיון הקרוב. "
                         "אני יכול לעזור רק עם מידע על זמינות תרופות בבתי מרקחת.",
    "תרופה ללא מרשם": "אני יכול לעזור לבדוק זמינות של תרופות בבתי מרקחת כללית. "
                       "לגבי שאלות על מרשמים, אנא פנו לרופא או לרוקח.",
}

# ── Layer 4: Core AI ──────────────────────────────────────────────────────────

_gemini_model_instance = None


def _get_gemini_model():
    """Lazy-initialize Gemini model."""
    global _gemini_model_instance
    if _gemini_model_instance is not None:
        return _gemini_model_instance

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        logger.error("GEMINI_API_KEY not set")
        return None

    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key)

        # Define the tools (functions) the model can call
        search_medications_tool = genai.protos.Tool(
            function_declarations=[
                genai.protos.FunctionDeclaration(
                    name="search_medications",
                    description="חיפוש תרופות לפי שם. מחזיר רשימת תרופות עם קוד קטלוגי (catCode) ושם מלא (omryName).",
                    parameters=genai.protos.Schema(
                        type=genai.protos.Type.OBJECT,
                        properties={
                            "query": genai.protos.Schema(
                                type=genai.protos.Type.STRING,
                                description="שם התרופה לחיפוש (עברית או אנגלית)",
                            ),
                        },
                        required=["query"],
                    ),
                ),
                genai.protos.FunctionDeclaration(
                    name="search_cities",
                    description="חיפוש ערים שבהן יש בתי מרקחת כללית. מחזיר שם עיר וקוד עיר (cityCode).",
                    parameters=genai.protos.Schema(
                        type=genai.protos.Type.OBJECT,
                        properties={
                            "query": genai.protos.Schema(
                                type=genai.protos.Type.STRING,
                                description="שם העיר או חלק ממנו",
                            ),
                        },
                        required=["query"],
                    ),
                ),
                genai.protos.FunctionDeclaration(
                    name="search_pharmacies",
                    description="חיפוש סניפי בתי מרקחת כללית לפי שם. מחזיר שם סניף וקוד מחלקה (deptCode).",
                    parameters=genai.protos.Schema(
                        type=genai.protos.Type.OBJECT,
                        properties={
                            "query": genai.protos.Schema(
                                type=genai.protos.Type.STRING,
                                description="שם בית המרקחת או חלק ממנו",
                            ),
                        },
                        required=["query"],
                    ),
                ),
            ]
        )

        _gemini_model_instance = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            system_instruction=SYSTEM_PROMPT,
            tools=[search_medications_tool],
        )
        return _gemini_model_instance
    except Exception as e:
        logger.error(f"Failed to initialize Gemini: {e}")
        return None


async def _execute_function_call(function_name: str, args: dict) -> str:
    """Execute a function call from Gemini and return JSON result."""
    from clalit_pharmacy_api import search_medications, search_cities, search_pharmacies

    try:
        if function_name == "search_medications":
            results = await search_medications(args.get("query", ""))
            if not results:
                return json.dumps({"results": [], "message": "לא נמצאו תרופות"}, ensure_ascii=False)
            # Limit to 15 results
            return json.dumps({"results": results[:15], "total": len(results)}, ensure_ascii=False)

        elif function_name == "search_cities":
            results = await search_cities(args.get("query", ""))
            if not results:
                return json.dumps({"results": [], "message": "לא נמצאו ערים"}, ensure_ascii=False)
            return json.dumps({"results": results[:15], "total": len(results)}, ensure_ascii=False)

        elif function_name == "search_pharmacies":
            results = await search_pharmacies(args.get("query", ""))
            if not results:
                return json.dumps({"results": [], "message": "לא נמצאו בתי מרקחת"}, ensure_ascii=False)
            return json.dumps({"results": results[:15], "total": len(results)}, ensure_ascii=False)

        else:
            return json.dumps({"error": f"Unknown function: {function_name}"}, ensure_ascii=False)

    except Exception as e:
        logger.error(f"Function call {function_name} failed: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


async def _chat_with_gemini(user_message: str, history: list) -> str:
    """Send a message to Gemini with function calling support."""
    import google.generativeai as genai

    model = _get_gemini_model()
    if not model:
        return "שירות ה-AI אינו זמין כרגע. אנא נסו שוב מאוחר יותר."

    try:
        chat = model.start_chat(history=history)
        response = chat.send_message(user_message)

        # Handle function calls in a loop (Gemini may chain multiple calls)
        max_iterations = 5
        iteration = 0
        while iteration < max_iterations:
            iteration += 1

            # Check if there's a function call in the response
            candidate = response.candidates[0] if response.candidates else None
            if not candidate:
                break

            function_call = None
            for part in candidate.content.parts:
                if hasattr(part, "function_call") and part.function_call.name:
                    function_call = part.function_call
                    break

            if not function_call:
                break

            # Execute the function call
            fn_name = function_call.name
            fn_args = dict(function_call.args) if function_call.args else {}
            logger.info(f"Gemini function call: {fn_name}({fn_args})")

            result = await _execute_function_call(fn_name, fn_args)

            # Send function result back to Gemini
            response = chat.send_message(
                genai.protos.Content(
                    parts=[
                        genai.protos.Part(
                            function_response=genai.protos.FunctionResponse(
                                name=fn_name,
                                response={"result": result},
                            )
                        )
                    ]
                )
            )

        # Extract final text response
        text = response.text if response.text else "לא הצלחתי לעבד את הבקשה. אנא נסו שוב."

        # Update history with the full conversation
        history.clear()
        history.extend(chat.history)

        return text

    except Exception as e:
        logger.error(f"Gemini chat error: {e}")
        return "אירעה שגיאה בעיבוד הבקשה. אנא נסו שוב."


def _split_message(text: str) -> list[str]:
    """Split long messages to fit Telegram's 4096-char limit."""
    if len(text) <= MAX_TELEGRAM_MESSAGE_LENGTH:
        return [text]
    chunks = []
    while text:
        if len(text) <= MAX_TELEGRAM_MESSAGE_LENGTH:
            chunks.append(text)
            break
        # Find last newline before limit
        cut = text.rfind("\n", 0, MAX_TELEGRAM_MESSAGE_LENGTH)
        if cut <= 0:
            cut = MAX_TELEGRAM_MESSAGE_LENGTH
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return chunks


# ── Layer 5: Telegram Handlers ────────────────────────────────────────────────


class PharmacyAgent:
    """AI agent for checking Clalit pharmacy medication availability."""

    def get_conversation_handler(self) -> ConversationHandler:
        """Layer 6: ConversationHandler orchestration."""
        return ConversationHandler(
            entry_points=[
                CallbackQueryHandler(self.start_agent, pattern="^pharmacy_agent_start$"),
            ],
            states={
                AGENT_CHATTING: [
                    CallbackQueryHandler(self.end_agent, pattern="^pharmacy_agent_end$"),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message),
                ],
            },
            fallbacks=[
                CommandHandler("cancel", self.end_agent),
                CallbackQueryHandler(self.end_agent, pattern="^pharmacy_agent_end$"),
                CommandHandler("start", self.force_end),
            ],
            per_message=False,
            conversation_timeout=CONVERSATION_TIMEOUT_SECONDS,
        )

    def get_handlers(self) -> list:
        """Additional callback handlers outside conversation."""
        return []

    async def start_agent(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Entry point: start pharmacy agent conversation."""
        query = update.callback_query
        if query:
            await query.answer()

        # Initialize conversation history
        context.user_data["pharmacy_agent_history"] = []

        welcome = (
            "🏥 *בדיקת זמינות תרופות בכללית*\n\n"
            "אני יכול לעזור לכם:\n"
            "• 🔍 לחפש תרופות לפי שם\n"
            "• 🏙️ למצוא ערים עם בתי מרקחת כללית\n"
            "• 🏪 לחפש סניפי בית מרקחת\n\n"
            "שלחו שם תרופה, עיר או שאלה.\n"
            "לסיום לחצו על *יציאה* או שלחו /cancel"
        )

        end_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ יציאה", callback_data="pharmacy_agent_end")],
        ])

        if query:
            await query.edit_message_text(welcome, parse_mode="Markdown", reply_markup=end_keyboard)
        else:
            await update.message.reply_text(welcome, parse_mode="Markdown", reply_markup=end_keyboard)

        return AGENT_CHATTING

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle user messages during agent conversation."""
        text = (update.message.text or "").strip()
        if not text:
            return AGENT_CHATTING

        # Layer 3: Safety keyword overrides
        for keyword, override_response in SAFETY_OVERRIDES.items():
            if keyword in text:
                await update.message.reply_text(override_response)
                return AGENT_CHATTING

        # Layer 2: Topic shortcuts
        for shortcut, expanded in TOPIC_SHORTCUTS.items():
            if text == shortcut:
                text = expanded
                break

        # Layer 4: Send to Gemini
        history = context.user_data.get("pharmacy_agent_history", [])

        # Show typing indicator
        await update.message.chat.send_action("typing")

        response_text = await _chat_with_gemini(text, history)

        # Update history reference (list was modified in place)
        context.user_data["pharmacy_agent_history"] = history

        # Split and send response
        end_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ יציאה", callback_data="pharmacy_agent_end")],
        ])

        chunks = _split_message(response_text)
        for i, chunk in enumerate(chunks):
            # Only add keyboard to last chunk
            reply_markup = end_keyboard if i == len(chunks) - 1 else None
            await update.message.reply_text(chunk, reply_markup=reply_markup)

        return AGENT_CHATTING

    async def end_agent(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """End the agent conversation."""
        # Clean up
        context.user_data.pop("pharmacy_agent_history", None)

        goodbye = "👋 תודה שהשתמשתם בשירות בדיקת מלאי תרופות!"

        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(goodbye)
        else:
            await update.message.reply_text(goodbye)

        # Re-show main menu
        from utils.keyboards import get_main_menu_keyboard
        chat_id = update.effective_chat.id
        await context.bot.send_message(
            chat_id=chat_id,
            text="בחרו פעולה:",
            reply_markup=get_main_menu_keyboard(),
        )

        return ConversationHandler.END

    async def force_end(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Force-end conversation (e.g., on /start)."""
        context.user_data.pop("pharmacy_agent_history", None)
        return ConversationHandler.END


# Singleton instance
pharmacy_agent = PharmacyAgent()
