"""
Pharmacy Inventory Agent - AI-powered Clalit pharmacy stock checker.
Uses Gemini AI to understand user queries about medication availability
and executes pharmacy-search.js (from agent-skill-clalit-pharm-search) to get real data.
"""

# `str | None` in a signature is evaluated at import time and raises TypeError on
# Python 3.9, which the CI matrix still covers. Deferring annotations keeps them
# as strings so the module imports everywhere.
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
from dataclasses import dataclass
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

יש לך כלים שמחזירים נתונים אמיתיים ממערכת כללית. כשתקבל תוצאות מהכלי, הסבר אותן למשתמש בצורה ברורה ופשוטה.

חוק מוחלט - אסור להמציא נתונים:
- שמות סניפים, כתובות, קודים וסטטוסי מלאי מגיעים אך ורק מהכלים. לעולם אל תכתוב אותם מהידע שלך.
- אם אין לך תוצאה מהכלי, אמור זאת במפורש. אל תדגים, אל תסמלץ ואל תציג דוגמה שנראית כמו תוצאה אמיתית.
- אם חסר לך מידע כדי לקרוא לכלי (למשל עיר או שם תרופה), בקש אותו מהמשתמש.

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


@dataclass(frozen=True)
class ToolResult:
    """Outcome of a pharmacy tool call.

    ok=False means no data was retrieved. The distinction is load bearing: an
    error must reach the user verbatim rather than being handed to the model,
    which would otherwise narrate around it or invent a plausible answer.
    """

    ok: bool
    text: str


SETUP_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "setup_pharmacy_skill.sh")
SKILL_INSTALL_TIMEOUT = 300

# One install at a time; the result is remembered so a failure is not retried
# on every message.
_install_lock = asyncio.Lock()
_install_failed_reason: str | None = None


def is_skill_installed() -> bool:
    return os.path.isfile(SEARCH_SCRIPT)


async def ensure_skill_installed() -> ToolResult:
    """Install the search skill on demand.

    Render's disk is ephemeral and setup_pharmacy_skill.sh is not part of the
    boot sequence, so after any restart the skill is simply gone. Installing it
    here means the agent recovers by itself instead of reporting a broken tool.
    """
    global _install_failed_reason

    if is_skill_installed():
        return ToolResult(True, "")

    async with _install_lock:
        if is_skill_installed():
            return ToolResult(True, "")
        if _install_failed_reason:
            return ToolResult(False, _install_failed_reason)

        for binary in ("git", "node", "npm"):
            if not shutil.which(binary):
                _install_failed_reason = f"שגיאה: {binary} אינו מותקן בסביבה, ולכן לא ניתן להתקין את כלי החיפוש."
                logger.error(f"Cannot install pharmacy skill: {binary} not found on PATH")
                return ToolResult(False, _install_failed_reason)

        if not os.path.isfile(SETUP_SCRIPT):
            _install_failed_reason = "שגיאה: סקריפט ההתקנה של כלי החיפוש חסר."
            logger.error(f"Pharmacy setup script missing at {SETUP_SCRIPT}")
            return ToolResult(False, _install_failed_reason)

        logger.info("Pharmacy skill missing, installing it now")
        try:
            proc = await asyncio.create_subprocess_exec(
                "bash",
                SETUP_SCRIPT,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=os.path.dirname(SETUP_SCRIPT),
            )
            output, _ = await asyncio.wait_for(proc.communicate(), timeout=SKILL_INSTALL_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            _install_failed_reason = "שגיאה: התקנת כלי החיפוש ארכה זמן רב מדי."
            logger.error("Pharmacy skill install timed out")
            return ToolResult(False, _install_failed_reason)
        except Exception as exc:
            _install_failed_reason = "שגיאה: התקנת כלי החיפוש נכשלה."
            logger.exception(f"Pharmacy skill install raised: {exc}")
            return ToolResult(False, _install_failed_reason)

        if proc.returncode != 0 or not is_skill_installed():
            tail = output.decode("utf-8", errors="replace").strip()[-400:]
            _install_failed_reason = "שגיאה: התקנת כלי החיפוש נכשלה."
            logger.error(f"Pharmacy skill install failed (rc={proc.returncode}): {tail}")
            return ToolResult(False, _install_failed_reason)

        logger.info("Pharmacy skill installed successfully")
        return ToolResult(True, "")


async def _run_pharmacy_command(command: str, *args: str, _retries: int = 2) -> ToolResult:
    """Run pharmacy-search.js with given command and arguments.

    Retries on transient 403/5xx errors with exponential backoff.
    """
    ready = await ensure_skill_installed()
    if not ready.ok:
        return ready

    cmd = ["node", SEARCH_SCRIPT, command, *args]
    for attempt in range(_retries + 1):
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
                # Match HTTP status codes in error messages (e.g. "403 Forbidden", "status: 503")
                is_transient = bool(re.search(r'\b(403|500|502|503)\b', err))
                # Retry on transient HTTP errors (403, 5xx)
                if is_transient and attempt < _retries:
                    delay = 2 ** (attempt + 1)
                    logger.info(f"pharmacy-search.js {command} got transient error, retrying in {delay}s: {err[:100]}")
                    await asyncio.sleep(delay)
                    continue
                logger.warning(f"pharmacy-search.js {command} failed: {err}")
                if not output:
                    if is_transient and attempt > 0:
                        msg = f"שגיאה בחיפוש לאחר {attempt + 1} ניסיונות: {err[:200]}"
                        if re.search(r'\b403\b', err):
                            msg += "\nייתכן שיש צורך להריץ מחדש את setup_pharmacy_skill.sh."
                        return ToolResult(False, msg)
                    if re.search(r'\b403\b', err):
                        return ToolResult(False, "שגיאה: שירות החיפוש של כללית חסם את הבקשה (403). ייתכן שיש צורך להריץ מחדש את setup_pharmacy_skill.sh.")
                    return ToolResult(False, f"שגיאה בחיפוש: {err[:200]}")
            return ToolResult(True, output or "לא נמצאו תוצאות.")
        except asyncio.TimeoutError:
            if proc:
                proc.kill()
                await proc.wait()
            return ToolResult(False, "החיפוש ארך יותר מדי זמן. נסה שוב.")
        except FileNotFoundError:
            return ToolResult(False, "שגיאה: Node.js לא מותקן במערכת.")
        except Exception as e:
            logger.error(f"Pharmacy search error: {e}")
            return ToolResult(False, f"שגיאה בחיפוש: {e}")
    return ToolResult(False, "שגיאה בחיפוש: כל הניסיונות נכשלו.")


async def _search_medication(query: str) -> ToolResult:
    """Search for a medication by name."""
    return await _run_pharmacy_command("search", query)


async def _list_cities(query: str = "") -> ToolResult:
    """List cities or filter by name."""
    if query:
        return await _run_pharmacy_command("cities", query)
    return await _run_pharmacy_command("cities")


async def _find_pharmacies(query: str) -> ToolResult:
    """Find pharmacy branches by name/city."""
    return await _run_pharmacy_command("pharmacies", query)


async def _check_stock(cat_code: str, city_code: str = "", dept_code: str = "") -> ToolResult:
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


_ERR_RATE_LIMIT = "מצטער, הגעתי למגבלת השימוש היומית. נסה שוב מחר."
_ERR_AI_COMM = "מצטער, אירעה שגיאה בתקשורת עם ה-AI. נסה שוב."


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
        tools=[{"function_declarations": FUNCTION_DECLARATIONS}],
    )
    context.user_data["pharm_chat_history"] = []
    return OPENING_MESSAGE, True


# ═══ Layer 6: Tool-calling logic ═══

# Declared to Gemini so the model itself decides when data is needed. The
# previous design guessed intent with Hebrew regexes; anything they missed went
# straight to the model with no data attached, and it answered from imagination.
FUNCTION_DECLARATIONS = [
    {
        "name": "search_medication",
        "description": "חיפוש תרופה לפי שם בעברית או באנגלית. מחזיר גם catCode הדרוש לבדיקת מלאי.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "שם התרופה"}},
            "required": ["query"],
        },
    },
    {
        "name": "find_pharmacies",
        "description": "מציאת סניפי בית מרקחת של כללית לפי עיר או שם סניף. מחזיר deptCode.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "עיר או שם סניף"}},
            "required": ["query"],
        },
    },
    {
        "name": "list_cities",
        "description": "רשימת ערים שבהן יש בתי מרקחת כללית. מחזיר cityCode.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "סינון לפי שם עיר, אופציונלי"}},
        },
    },
    {
        "name": "check_stock",
        "description": "בדיקת מלאי בפועל. דורש catCode מ-search_medication, ועיר או סניף.",
        "parameters": {
            "type": "object",
            "properties": {
                "cat_code": {"type": "string", "description": "קוד התרופה מ-search_medication"},
                "city_code": {"type": "string", "description": "cityCode מ-list_cities"},
                "dept_code": {"type": "string", "description": "deptCode מ-find_pharmacies"},
            },
            "required": ["cat_code"],
        },
    },
]

_TOOL_DISPATCH = {
    "search_medication": lambda a: _search_medication(a.get("query", "")),
    "find_pharmacies": lambda a: _find_pharmacies(a.get("query", "")),
    "list_cities": lambda a: _list_cities(a.get("query", "")),
    "check_stock": lambda a: _check_stock(
        a.get("cat_code", ""), a.get("city_code", ""), a.get("dept_code", "")
    ),
}

# Bounds the search/stock back-and-forth so a confused model cannot loop forever.
MAX_TOOL_ROUNDS = 5


def _function_calls(response):
    """Function calls Gemini asked for in this turn."""
    calls = []
    for candidate in getattr(response, "candidates", []) or []:
        for part in getattr(candidate.content, "parts", []) or []:
            call = getattr(part, "function_call", None)
            if call and call.name:
                calls.append(call)
    return calls


async def _process_with_tools(context, user_message: str) -> tuple[str | None, str, bool]:
    """Run one user turn, letting Gemini call the pharmacy tools it needs.

    Returns (response, message_for_history, is_real_response). A tool failure is
    returned to the user as-is and marked not-real, so the model never gets the
    chance to dress a failure up as an answer.
    """
    model = context.user_data.get("pharm_model")
    if not model:
        return None, user_message, False

    if is_limit_reached():
        return _ERR_RATE_LIMIT, user_message, False

    current_count = increment_and_check_usage()
    if current_count == ALERT_THRESHOLD:
        await send_telegram_alert(f"Pharmacy agent usage alert: {current_count} calls today")

    history = context.user_data.get("pharm_chat_history", [])
    try:
        chat = model.start_chat(history=history)
        response = await chat.send_message_async(user_message)

        for _ in range(MAX_TOOL_ROUNDS):
            calls = _function_calls(response)
            if not calls:
                break

            parts = []
            for call in calls:
                handler = _TOOL_DISPATCH.get(call.name)
                if not handler:
                    logger.warning(f"Gemini asked for unknown tool {call.name!r}")
                    parts.append(
                        genai.protos.Part(
                            function_response=genai.protos.FunctionResponse(
                                name=call.name, response={"error": "unknown tool"}
                            )
                        )
                    )
                    continue

                result = await handler(dict(call.args))
                if not result.ok:
                    # Hand the failure straight to the user. Passing it to the
                    # model invites a confident answer built on nothing.
                    logger.warning(f"Pharmacy tool {call.name} failed: {result.text[:120]}")
                    return result.text, user_message, False

                parts.append(
                    genai.protos.Part(
                        function_response=genai.protos.FunctionResponse(
                            name=call.name, response={"result": result.text}
                        )
                    )
                )

            response = await chat.send_message_async(
                genai.protos.Content(role="user", parts=parts)
            )

        return response.text, user_message, True

    except Exception as e:
        logger.error(f"Gemini API error in pharmacy agent: {e}")
        return _ERR_AI_COMM, user_message, False


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

    # Routed like any other turn so the model can call tools if it decides to.
    # Sending straight to the model left an unguarded path to an invented answer.
    bot_response, _, is_real = await _process_with_tools(context, shortcut_text)
    if bot_response:
        chunks = _split_message(bot_response)
        for chunk in chunks[:-1]:
            await query.message.reply_text(chunk)
        await query.message.reply_text(
            chunks[-1], reply_markup=_get_chat_keyboard()
        )
        if is_real:
            _commit_to_history(context, shortcut_text, bot_response)
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

    bot_response, ai_message, is_real = await _process_with_tools(context, user_message)
    if bot_response:
        chunks = _split_message(bot_response)
        for chunk in chunks[:-1]:
            await update.message.reply_text(chunk)
        await update.message.reply_text(
            chunks[-1], reply_markup=_get_chat_keyboard()
        )
        if is_real:
            _commit_to_history(context, ai_message, bot_response)
    else:
        await update.message.reply_text(
            "מצטער, לא הצלחתי לעבד את הבקשה. נסה שוב.",
            reply_markup=_get_chat_keyboard(),
        )
    return PHARMACY_STATE


async def end_chat(update: Update, context):
    """End pharmacy chat session."""
    _cleanup_session(context)

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
    _cleanup_session(context)

    from utils.keyboards import get_main_menu_keyboard
    from config import config

    await update.message.reply_text(
        config.WELCOME_MESSAGE, parse_mode="Markdown", reply_markup=get_main_menu_keyboard()
    )
    return ConversationHandler.END


def _cleanup_session(context):
    """Remove pharmacy session data from user_data."""
    context.user_data.pop("pharm_model", None)
    context.user_data.pop("pharm_chat_history", None)


async def timeout_handler(update: Update, context):
    """Clean up session data when conversation times out."""
    _cleanup_session(context)
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
            ConversationHandler.TIMEOUT: [
                MessageHandler(filters.ALL, timeout_handler),
                CallbackQueryHandler(timeout_handler),
            ],
        },
        fallbacks=[
            CommandHandler("end_pharm", end_chat_command),
            CommandHandler("start", fallback_start),
        ],
        conversation_timeout=timedelta(minutes=30).total_seconds(),
    )
