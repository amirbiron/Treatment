"""
Pharmacy Inventory Agent - AI-powered Clalit pharmacy stock checker.
Uses Gemini AI to understand user queries about medication availability
and executes pharmacy-search.js (from agent-skill-clalit-pharm-search) to get real data.
"""

import asyncio
import logging
import os
import re
from datetime import timedelta

import google.generativeai as genai
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from usage_tracker import ALERT_THRESHOLD, increment_and_check_usage, is_limit_reached
from telegram_alerter import send_telegram_alert

logger = logging.getLogger(__name__)

# ═══ Layer 1: Configuration ═══

PHARMACY_STATE = 300

# Path to the pharmacy search skill
SKILL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "skills", "clalit-pharm-search")
SEARCH_SCRIPT = os.path.join(SKILL_DIR, "scripts", "pharmacy-search.js")

SYSTEM_PROMPT = """אתה סוכן AI מומחה בבדיקת זמינות תרופות בבתי מרקחת של כללית בישראל.

התפקיד שלך:
- לעזור למשתמשים לבדוק האם תרופה מסוימת זמינה במלאי בבית מרקחת כללית
- לחפש תרופות לפי שם (בעברית או באנגלית)
- למצוא בתי מרקחת לפי עיר או שם סניף
- לבדוק מלאי בזמן אמת

יש לך גישה לכלי חיפוש שמחזיר תוצאות ממערכת כללית. כשתקבל תוצאות מהכלי, הסבר אותן למשתמש בצורה ברורה ופשוטה.

סטטוסי מלאי:
- "במלאי" = התרופה זמינה
- "מלאי מוגבל" = כמות מוגבלת, כדאי למהר
- "אין במלאי" = לא זמין כרגע
- "אין מידע" = אין נתונים זמינים

הנחיות:
- ענה תמיד בעברית
- היה קצר וענייני
- אם המשתמש מבקש תרופה, חפש אותה קודם ואז בדוק מלאי
- הצע למשתמש לציין עיר או סניף ספציפי לבדיקת מלאי
- הדגש שהמידע הוא לא רשמי ויש לאמת ישירות מול בית המרקחת
- אל תיתן ייעוץ רפואי - הפנה לרופא או לרוקח

כשאתה מקבל תוצאות מהכלי, עצב אותן בצורה נוחה לקריאה עם אימוג'ים מתאימים.
"""

# ═══ Layer 2: Topic Shortcuts ═══

TOPIC_SHORTCUTS = {
    "pharm_search_med": "אני רוצה לחפש תרופה",
    "pharm_find_pharmacy": "אני רוצה למצוא בית מרקחת כללית",
    "pharm_check_stock": "אני רוצה לבדוק מלאי של תרופה",
}

# ═══ Layer 3: Constants ═══

TELEGRAM_MSG_LIMIT = 4096

OPENING_MESSAGE = (
    "🏥 *סוכן מלאי בית מרקחת כללית*\n\n"
    "אני יכול לעזור לך לבדוק זמינות תרופות בבתי מרקחת כללית בכל הארץ.\n\n"
    "מה תרצה לעשות?\n"
    "• חפש תרופה לפי שם\n"
    "• מצא בית מרקחת לפי עיר\n"
    "• בדוק מלאי תרופה בסניף ספציפי\n\n"
    "פשוט כתוב את שאלתך, למשל:\n"
    '_"האם יש אמוקסיצילין בתל אביב?"_\n\n'
    "לסיום: /end\\_pharm"
)


# ═══ Layer 4: Pharmacy Search Tool ═══


async def _run_pharmacy_command(command: str, *args: str) -> str:
    """Run pharmacy-search.js with given command and arguments."""
    if not os.path.isfile(SEARCH_SCRIPT):
        return "שגיאה: כלי חיפוש בית מרקחת לא מותקן. יש להתקין את agent-skill-clalit-pharm-search."

    cmd = ["node", SEARCH_SCRIPT, command, *args]
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=SKILL_DIR,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        output = stdout.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace").strip()
            logger.warning(f"pharmacy-search.js {command} failed: {err}")
            if not output:
                return f"שגיאה בחיפוש: {err[:200]}"
        return output or "לא נמצאו תוצאות."
    except asyncio.TimeoutError:
        if proc:
            proc.kill()
            await proc.wait()
        return "החיפוש ארך יותר מדי זמן. נסה שוב."
    except FileNotFoundError:
        return "שגיאה: Node.js לא מותקן במערכת."
    except Exception as e:
        logger.error(f"Pharmacy search error: {e}")
        return f"שגיאה בחיפוש: {e}"


async def _search_medication(query: str) -> str:
    """Search for a medication by name."""
    return await _run_pharmacy_command("search", query)


async def _list_cities(query: str = "") -> str:
    """List cities or filter by name."""
    if query:
        return await _run_pharmacy_command("cities", query)
    return await _run_pharmacy_command("cities")


async def _find_pharmacies(query: str) -> str:
    """Find pharmacy branches by name/city."""
    return await _run_pharmacy_command("pharmacies", query)


async def _check_stock(cat_code: str, city_code: str = "", dept_code: str = "") -> str:
    """Check stock for a medication at a location."""
    args = [cat_code]
    if city_code:
        args.extend(["--city", city_code])
    elif dept_code:
        args.extend(["--pharmacy", dept_code])
    return await _run_pharmacy_command("stock", *args)


# ═══ Layer 5: AI Core ═══


def _split_message(text: str, limit: int = TELEGRAM_MSG_LIMIT) -> list[str]:
    """Split long messages to fit Telegram's limit."""
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        split_at = text.rfind("\n\n", 0, limit)
        if split_at <= 0:
            split_at = text.rfind("\n", 0, limit)
        if split_at <= 0:
            split_at = limit
        chunk = text[:split_at].strip()
        if chunk:
            chunks.append(chunk)
        text = text[split_at:].lstrip("\n")
    return chunks or [text]


async def _send_to_ai(context, user_message: str) -> str | None:
    """Send message to Gemini and get response. Does not update history."""
    model = context.user_data.get("pharm_model")
    if not model:
        return None

    if is_limit_reached():
        return "מצטער, הגעתי למגבלת השימוש היומית. נסה שוב מחר."

    current_count = increment_and_check_usage()
    if current_count == ALERT_THRESHOLD:
        await send_telegram_alert(f"Pharmacy agent usage alert: {current_count} calls today")

    history = context.user_data.get("pharm_chat_history", [])
    try:
        chat = model.start_chat(history=history)
        response = await chat.send_message_async(user_message)
        return response.text
    except Exception as e:
        logger.error(f"Gemini API error in pharmacy agent: {e}")
        return "מצטער, אירעה שגיאה בתקשורת עם ה-AI. נסה שוב."


def _commit_to_history(context, user_message: str, bot_response: str):
    """Save to chat history - only after successful Telegram delivery."""
    history = context.user_data.get("pharm_chat_history", [])
    history.append({"role": "user", "parts": [user_message]})
    history.append({"role": "model", "parts": [bot_response]})
    context.user_data["pharm_chat_history"] = history


_NO_API_KEY_MESSAGE = (
    "🏥 *סוכן מלאי בית מרקחת כללית*\n\n"
    "לא ניתן להפעיל את הסוכן - מפתח Gemini API לא מוגדר.\n"
    "יש להגדיר GEMINI\\_API\\_KEY במשתני הסביבה."
)


def _init_ai_session(context) -> tuple[str, bool]:
    """Initialize a new AI session with system instruction.

    Returns (opening_message, success) so the caller knows whether the
    session is functional.
    """
    gemini_api_key = os.getenv("GEMINI_API_KEY", "")
    if not gemini_api_key:
        logger.error("GEMINI_API_KEY not set - pharmacy agent cannot start")
        context.user_data.pop("pharm_model", None)
        context.user_data["pharm_chat_history"] = []
        return _NO_API_KEY_MESSAGE, False

    genai.configure(api_key=gemini_api_key)
    context.user_data["pharm_model"] = genai.GenerativeModel(
        "gemini-2.5-flash",
        system_instruction=SYSTEM_PROMPT,
    )
    context.user_data["pharm_chat_history"] = []
    return OPENING_MESSAGE, True


# ═══ Layer 6: Tool-calling logic ═══

# Patterns to detect user intent for automatic tool use
_SEARCH_PATTERN = re.compile(
    r"(?:חפש|חיפוש|מצא|search|find)\s+(?:תרופה\s+)?(.+)", re.IGNORECASE
)
_STOCK_PATTERN = re.compile(
    r"(?:מלאי של|בדוק מלאי|זמינות של|stock of|availability of|האם יש במלאי|יש במלאי)\s+(.+)",
    re.IGNORECASE,
)
_CITY_PATTERN = re.compile(
    r"(?:עיר|ערים|city|cities|סניפים?\s+ב)(.+)?", re.IGNORECASE
)
_PHARMACY_PATTERN = re.compile(
    r"(?:בית מרקחת|בתי מרקחת|סניפים?|pharmacy|pharmacies)\s*(?:ב|in)?\s*(.+)?", re.IGNORECASE
)


async def _process_with_tools(context, user_message: str) -> tuple[str | None, str]:
    """Process user message, potentially calling pharmacy tools and then AI.

    Returns (ai_response, message_sent_to_ai) so callers can store the actual
    message in chat history for consistent multi-turn context.
    """
    tool_results = []

    # Try to auto-detect intent and run tools.
    # Check patterns in priority order; only one primary intent fires.
    msg_lower = user_message.strip()

    # Check pharmacy/city patterns first (more specific location queries)
    pharm_match = _PHARMACY_PATTERN.search(msg_lower)
    city_match = _CITY_PATTERN.search(msg_lower)

    if pharm_match and pharm_match.group(1):
        query = pharm_match.group(1).strip()
        result = await _find_pharmacies(query)
        tool_results.append(f"בתי מרקחת - '{query}':\n{result}")
    elif city_match:
        query = (city_match.group(1) or "").strip()
        result = await _list_cities(query)
        tool_results.append(f"ערים:\n{result}")
    else:
        # Medication-related patterns (search or stock)
        stock_match = _STOCK_PATTERN.search(msg_lower)
        search_match = _SEARCH_PATTERN.search(msg_lower)

        if stock_match:
            query = stock_match.group(1).strip()
            search_result = await _search_medication(query)
            tool_results.append(f"תוצאות חיפוש תרופה '{query}':\n{search_result}")
            # Try to extract catCode from search results and check stock
            cat_code_match = re.search(r"catCode[:\s]+(\d+)", search_result)
            if cat_code_match:
                cat_code = cat_code_match.group(1)
                stock_result = await _check_stock(cat_code)
                tool_results.append(f"בדיקת מלאי (catCode {cat_code}):\n{stock_result}")
        elif search_match:
            query = search_match.group(1).strip()
            result = await _search_medication(query)
            tool_results.append(f"תוצאות חיפוש תרופה '{query}':\n{result}")

    # Build the prompt for AI
    if tool_results:
        tool_context = "\n\n---\n".join(tool_results)
        ai_message = (
            f"השאלה של המשתמש: {user_message}\n\n"
            f"תוצאות מכלי החיפוש:\n{tool_context}\n\n"
            f"אנא ענה למשתמש בהתבסס על התוצאות. "
            f"אם התוצאות כוללות קודים (catCode, cityCode, deptCode), "
            f"הסבר למשתמש מה הצעד הבא."
        )
        return await _send_to_ai(context, ai_message), ai_message
    else:
        # No tool match - just send to AI directly
        return await _send_to_ai(context, user_message), user_message


# ═══ Layer 7: Telegram Handlers ═══


def _get_chat_keyboard() -> InlineKeyboardMarkup:
    """Keyboard shown during chat."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("חפש תרופה", callback_data="pharm_search_med"),
                InlineKeyboardButton("מצא בית מרקחת", callback_data="pharm_find_pharmacy"),
            ],
            [
                InlineKeyboardButton("בדוק מלאי", callback_data="pharm_check_stock"),
            ],
            [InlineKeyboardButton("סיום שיחה", callback_data="pharm_end")],
        ]
    )


async def entry_from_callback(update: Update, context):
    """Entry point from inline button."""
    query = update.callback_query
    await query.answer()
    opening, success = _init_ai_session(context)
    if not success:
        await query.edit_message_text(text=opening, parse_mode="Markdown")
        return ConversationHandler.END
    await query.edit_message_text(
        text=opening,
        parse_mode="Markdown",
        reply_markup=_get_chat_keyboard(),
    )
    return PHARMACY_STATE


async def handle_shortcut(update: Update, context):
    """Handle topic shortcut buttons."""
    query = update.callback_query
    await query.answer()
    data = query.data

    shortcut_text = TOPIC_SHORTCUTS.get(data)
    if not shortcut_text:
        return PHARMACY_STATE

    # Send the shortcut as if the user typed it
    bot_response, ai_message = await _process_with_tools(context, shortcut_text)
    if bot_response:
        chunks = _split_message(bot_response)
        for chunk in chunks[:-1]:
            await query.message.reply_text(chunk)
        await query.message.reply_text(
            chunks[-1], reply_markup=_get_chat_keyboard()
        )
        _commit_to_history(context, ai_message, bot_response)
    else:
        await query.message.reply_text(
            "מצטער, לא הצלחתי לעבד את הבקשה. נסה שוב.",
            reply_markup=_get_chat_keyboard(),
        )
    return PHARMACY_STATE


async def handle_message(update: Update, context):
    """Handle free text message from user."""
    user_message = update.message.text
    if not user_message:
        return PHARMACY_STATE

    bot_response, ai_message = await _process_with_tools(context, user_message)
    if bot_response:
        chunks = _split_message(bot_response)
        for chunk in chunks[:-1]:
            await update.message.reply_text(chunk)
        await update.message.reply_text(
            chunks[-1], reply_markup=_get_chat_keyboard()
        )
        _commit_to_history(context, ai_message, bot_response)
    else:
        await update.message.reply_text(
            "מצטער, לא הצלחתי לעבד את הבקשה. נסה שוב.",
            reply_markup=_get_chat_keyboard(),
        )
    return PHARMACY_STATE


async def end_chat(update: Update, context):
    """End pharmacy chat session."""
    context.user_data.pop("pharm_model", None)
    context.user_data.pop("pharm_chat_history", None)

    from utils.keyboards import get_main_menu_keyboard

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("תודה! אם תצטרך עזרה נוספת עם מלאי תרופות, אני כאן.")
        await update.callback_query.message.reply_text(
            "בחרו פעולה:", reply_markup=get_main_menu_keyboard()
        )
    elif update.message:
        await update.message.reply_text(
            "תודה! אם תצטרך עזרה נוספת עם מלאי תרופות, אני כאן.",
            reply_markup=get_main_menu_keyboard(),
        )
    return ConversationHandler.END


async def end_chat_command(update: Update, context):
    """End chat via /end_pharm command."""
    return await end_chat(update, context)


async def fallback_start(update: Update, context):
    """Clean up and return to /start."""
    context.user_data.pop("pharm_model", None)
    context.user_data.pop("pharm_chat_history", None)

    from utils.keyboards import get_main_menu_keyboard
    from config import config

    await update.message.reply_text(
        config.WELCOME_MESSAGE, parse_mode="Markdown", reply_markup=get_main_menu_keyboard()
    )
    return ConversationHandler.END


# ═══ Layer 8: ConversationHandler ═══


def create_pharmacy_conversation() -> ConversationHandler:
    """Create the pharmacy agent ConversationHandler."""
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(entry_from_callback, pattern=r"^pharm_start$"),
        ],
        states={
            PHARMACY_STATE: [
                CommandHandler("end_pharm", end_chat_command),
                CallbackQueryHandler(end_chat, pattern=r"^pharm_end$"),
                CallbackQueryHandler(
                    handle_shortcut,
                    pattern=r"^pharm_(search_med|find_pharmacy|check_stock)$",
                ),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    handle_message,
                ),
            ],
        },
        fallbacks=[
            CommandHandler("end_pharm", end_chat_command),
            CommandHandler("start", fallback_start),
        ],
        conversation_timeout=timedelta(minutes=30).total_seconds(),
    )
