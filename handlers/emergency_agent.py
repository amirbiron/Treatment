"""
Israeli Emergency Guide Agent - answers emergency questions from a vetted guide.

Unlike the pharmacy agent, the data here is static and already reviewed: it lives
in docs/israeli-emergency-guide/. So the grounding strategy is different. The
whole guide is given to the model as context and the model is told to answer only
from it - but a prompt is not an enforcement mechanism, so three things are done
in code instead:

1. Life-threatening phrasings never reach the model at all. They get 101 back
   immediately, with no API latency and nothing to hallucinate.
2. Scenarios the guide's own coverage contract marks NOT COVERED are refused and
   routed to Home Front Command rather than answered from model knowledge.
3. Every phone number in a generated answer must appear verbatim in the guide.
   An invented emergency number is the failure mode that matters most here, and
   this is the only check that actually prevents it.
"""

# `str | None` in a signature is evaluated at import time and raises TypeError on
# Python 3.9, which the CI matrix still covers.
from __future__ import annotations

import logging
import os
import re
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

EMERGENCY_STATE = 400

# The whole history is resent on every request, so without a cap a long session
# grows what each message costs. Ten exchanges is far more than these
# conversations run, and the guide itself carries the context that matters.
DEFAULT_HISTORY_TURNS = 10
# An upper bound on the knob itself. Someone tuning for "more memory" should not
# be able to make a single message cost twenty times what it should.
MAX_HISTORY_TURNS = 50
HISTORY_TURNS_ENV = "EMERGENCY_HISTORY_TURNS"


def history_turns_from_env(environ=None) -> int:
    """Read the configured number of exchanges to keep.

    A bad value here must not take the bot down: this is a tuning knob typed
    into a hosting dashboard, and the only sane response to a typo is to log it
    and carry on with the default. Zero is a legitimate setting - it makes every
    question independent, which is defensible when each answer is grounded in
    the guide anyway.
    """
    raw = (environ if environ is not None else os.environ).get(HISTORY_TURNS_ENV)
    if raw is None or not raw.strip():
        return DEFAULT_HISTORY_TURNS

    try:
        turns = int(raw.strip())
    except ValueError:
        logger.warning(
            f"{HISTORY_TURNS_ENV}={raw!r} is not a number, using {DEFAULT_HISTORY_TURNS}"
        )
        return DEFAULT_HISTORY_TURNS

    if turns < 0:
        logger.warning(f"{HISTORY_TURNS_ENV}={turns} is negative, using {DEFAULT_HISTORY_TURNS}")
        return DEFAULT_HISTORY_TURNS
    if turns > MAX_HISTORY_TURNS:
        logger.warning(f"{HISTORY_TURNS_ENV}={turns} exceeds the cap, using {MAX_HISTORY_TURNS}")
        return MAX_HISTORY_TURNS
    return turns


# One turn is a user message plus a model reply, so trimming never leaves a
# question without its answer.
MAX_HISTORY_MESSAGES = history_turns_from_env() * 2

GUIDE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "docs", "israeli-emergency-guide"
)
# domain-checklist.md is deliberately excluded: it is the skill's own coverage
# contract, written for reviewers, not answer material for a user.
GUIDE_FILES = (
    "SKILL_HE.md",
    os.path.join("references", "hospital-directory.md"),
    os.path.join("references", "first-aid-basics.md"),
)


# ═══ The guide is the only source of truth ═══


def _load_guide() -> str:
    """Read the guide once. An empty string means the agent must not answer."""
    parts = []
    for name in GUIDE_FILES:
        path = os.path.join(GUIDE_DIR, name)
        try:
            with open(path, encoding="utf-8") as handle:
                parts.append(f"### {name}\n\n{handle.read()}")
        except OSError as exc:
            logger.error(f"Emergency guide file missing: {path} ({exc})")
    return "\n\n".join(parts)


GUIDE_TEXT = _load_guide()


def is_guide_available() -> bool:
    return bool(GUIDE_TEXT.strip())


# ═══ Answers that must never depend on a model ═══

# Straight from the guide's Step 1. The test suite asserts every one of these
# still appears in the guide, so the two cannot drift apart silently.
EMERGENCY_NUMBERS = (
    ("101", 'מד"א', "חירום רפואי, אמבולנס"),
    ("100", "משטרה", "פשע, איום ביטחוני, תאונה"),
    ("102", "כיבוי אש והצלה", "שריפה, חומרים מסוכנים, חילוץ"),
    ("104", "פיקוד העורף", "אזעקות, מקלוט, מידע בזמן מלחמה"),
    ("105", "הגנה על ילדים ברשת", "פגיעה מקוונת בקטין, סחיטה"),
    ("118", "מוקד הרווחה", "אלימות במשפחה, ילד או קשיש בסיכון"),
    ("1201", 'ער"ן', "מצוקה נפשית, מחשבות אובדניות"),
    ("1202 / 1203", "סיוע לנפגעות ונפגעי תקיפה מינית", "1202 לנשים, 1203 לגברים"),
    ("04-7771900", "מכון מידע בהרעלות", "הרעלה, מנת יתר, נשיכת נחש או עקרב"),
)

_CALL_101 = "☎️ חייגו *101* (מד\"א) עכשיו."

# Phrasings that describe someone who may be dying. These skip the model
# entirely: a round trip to Gemini adds seconds and adds nothing.
#
# Hebrew final letters are a trap here: "נושם" ends in ם, so a pattern written
# as "נושמ" silently matches nothing. Every stem that can end a word carries the
# final form in a character class.
RED_FLAG_PATTERNS = (
    r"לא\s*נוש[םמ]",
    r"לא\s*מגיב",
    r"מחוסר\s*הכרה",
    r"איבד\s*הכרה",
    r"התעלף",
    r"דימום\s*(חמור|כבד|מסיבי)",
    r"כאב(ים)?\s*ב?חזה",
    r"קוצר\s*נשימה",
    r"קושי\s*לנשום",
    r"חשד\s*ל?שבץ",
    r"החייא",
    r"נחנק",
    r"פרכוס",
    r"טובע",
)

# The guide covers suicidal distress separately, and routing it to 101 by
# default is the wrong answer unless there is an active attempt.
#
# The error costs are lopsided: catching a message that turned out not to be a
# crisis just shows someone a helpline, while missing one hands a person in
# distress a generic answer. So these lean broad on purpose.
MENTAL_HEALTH_PATTERNS = (
    r"אובדנ",
    r"להתאבד",
    r"התאבדות",
    r"לשים\s*סוף",
    r"לגמור\s*עם\s*הכל",
    r"רוצה\s*למות",
    r"לא\s*רוצה\s*לחיות",
    r"נמאס\s*לי\s*לחיות",
    r"אין\s*טעם\s*לחיות",
    r"לפגוע\s*בעצמי",
    r"לשרוט\s*את\s*עצמי",
)

# references/domain-checklist.md records these as known, deliberate gaps. The
# guide says nothing about them, so the model would be answering from its own
# knowledge - which is exactly what must not happen for life-safety guidance.
UNCOVERED_PATTERNS = (
    (r"מחבל|חדיר[הת]\s*מחבל|פיגוע\s*חדירה", "חדירת מחבלים"),
    (r"חומר(ים)?\s*מסוכ[ןנ]|דליפ[הת]\s*(גז|כימיק)|אירוע\s*כימי", "אירוע חומרים מסוכנים"),
    (r"רדיולוג|קרינה|גרעינ", "אירוע רדיולוגי"),
    (r"צונאמי", "חשש לצונאמי"),
)

_UNCOVERED_REPLY = (
    "אין לי מידע מאומת על *{topic}* במדריך, ולא אמציא הנחיות בנושא שעלול לעלות בחיים.\n\n"
    "ההנחיות הרשמיות נמצאות אצל פיקוד העורף:\n"
    "☎️ מוקד *104*\n"
    "📱 אפליקציית פיקוד העורף\n"
    "🌐 oref.org.il\n\n"
    "אם יש כרגע נפגעים — חייגו *101* (מד\"א) ו-*100* (משטרה)."
)

_MENTAL_HEALTH_REPLY = (
    "אני מצטער שאתה עובר את זה. אתה לא לבד ויש קווים שזמינים עכשיו:\n\n"
    "☎️ *ער\"ן 1201* — 24/7, חינם ואנונימי\n"
    "💬 *סה\"ר* — צ'אט אנונימי 24/7 באתר sahar.org.il\n"
    "📱 וואטסאפ ער\"ן: 052-8451201\n"
    "☎️ *נט\"ל 3362\\** — טראומה, מלחמה, 7 באוקטובר\n\n"
    "אם יש סכנה מיידית או ניסיון פעיל — חייגו *100* (משטרה) ו-*101* (מד\"א) יחד."
)

_ERR_AI_COMM = "מצטער, אירעה שגיאה בתקשורת עם ה-AI. נסה שוב."
_ERR_NO_GUIDE = (
    "מדריך החירום לא נטען, ולכן אני לא יכול לענות על שאלות בנושא.\n\n"
    "במקרה חירום רפואי חייגו *101*, משטרה *100*, כיבוי אש *102*."
)
_ERR_UNVERIFIED = (
    "לא הצלחתי לאמת את התשובה מול המדריך, ולכן אני לא מציג אותה.\n\n"
    "נסו לנסח את השאלה אחרת, או פנו ישירות:\n"
    "☎️ חירום רפואי *101* • משטרה *100* • כיבוי אש *102* • פיקוד העורף *104*"
)

DISCLAIMER = "\n\n_מידע כללי מתוך מדריך חירום, לא ייעוץ רפואי. בספק — חייגו 101._"


def format_emergency_numbers() -> str:
    """The quick-reference card. No model involved, so it cannot be wrong."""
    lines = ["🚨 *מספרי חירום בישראל*\n"]
    for number, service, when in EMERGENCY_NUMBERS:
        lines.append(f"*{number}* — {service}\n_{when}_")
    lines.append(
        "\n⚠️ 112 אינו מוקד חירום מאוחד בישראל. הוא מגיע למשטרה בלבד "
        "ולא מנתב למד\"א. בחירום רפואי תמיד 101."
    )
    return "\n".join(lines)


# ═══ Verifying a generated answer against the guide ═══

# Only phone-shaped tokens are checked, so shekel amounts, minutes and years do
# not trip the validator: star codes, hyphenated runs, and bare numbers in the
# 1xx/1xxx service range where an invented digit is most dangerous.
_PHONE_TOKEN = re.compile(r"\*\d{3,5}|\d{3,5}\*|\+?\d{1,4}(?:-\d{3,7}){1,3}|\b1\d{2,3}\b")


def _normalize_number(token: str) -> str:
    return re.sub(r"[^\d]", "", token)


def _guide_numbers() -> frozenset:
    return frozenset(
        _normalize_number(match) for match in _PHONE_TOKEN.findall(GUIDE_TEXT)
    )


GUIDE_NUMBERS = _guide_numbers()


@dataclass(frozen=True)
class Verdict:
    """Outcome of checking an answer. `bad` names the first invented number."""

    ok: bool
    bad: str = ""


def verify_answer(text: str) -> Verdict:
    """Reject an answer containing a phone number that is not in the guide.

    A wrong emergency number is worse than no answer, and the model has no way
    of knowing it invented one.
    """
    for token in _PHONE_TOKEN.findall(text):
        digits = _normalize_number(token)
        if digits and digits not in GUIDE_NUMBERS:
            return Verdict(False, token)
    return Verdict(True)


# ═══ Deterministic routing, before any model call ═══


def _matches(patterns, text: str) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def classify(text: str) -> str:
    """Decide whether the message can be answered without the model at all."""
    if _matches(RED_FLAG_PATTERNS, text):
        return "critical"
    if _matches(MENTAL_HEALTH_PATTERNS, text):
        return "mental_health"
    for pattern, _topic in UNCOVERED_PATTERNS:
        if re.search(pattern, text):
            return "uncovered"
    return "ask_model"


def uncovered_topic(text: str) -> str:
    for pattern, topic in UNCOVERED_PATTERNS:
        if re.search(pattern, text):
            return topic
    return ""


def critical_reply() -> str:
    return (
        "🚨 *זה נשמע כמו מצב חירום רפואי.*\n\n"
        f"{_CALL_101}\n\n"
        "המוקדן ידריך אתכם עד שהאמבולנס מגיע — אל תנתקו.\n"
        "אם אי אפשר לדבר: מסרון או וואטסאפ למד\"א 052-7000101."
    )


# ═══ The model, with the guide as its only material ═══

SYSTEM_PROMPT_TEMPLATE = """אתה עוזר שעונה על שאלות בנושא חירום בישראל, על סמך מדריך מאומת בלבד.

חוקים מוחלטים:
- ענה אך ורק ממה שכתוב במדריך שלמטה. אל תשלים ממה שאתה "יודע".
- מספרי טלפון, שמות בתי חולים, סכומים ושעות פעילות — רק אם הם מופיעים במדריך מילה במילה.
- אם המדריך לא מכסה את השאלה, אמור זאת במפורש והפנה למוקד 104 או למד"א 101. אל תנחש.
- אל תאבחן ואל תמליץ על טיפול. אתה מפנה לשירות הנכון, לא מחליף רופא.
- אם המצב נשמע מסכן חיים, פתח בהנחיה לחייג 101.

סגנון: עברית פשוטה, משפטים קצרים, בלי ז'רגון. הבוט משמש גם אנשים מבוגרים.
ענה בקצרה — עד כ-8 שורות — ותן את הפעולה המעשית קודם.

=== המדריך ===

{guide}
"""


def _init_ai_session(context) -> None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        "gemini-2.5-flash",
        system_instruction=SYSTEM_PROMPT_TEMPLATE.format(guide=GUIDE_TEXT),
    )
    context.user_data["emerg_model"] = model
    context.user_data["emerg_chat_history"] = []


async def ask_guide(context, user_message: str):
    """Return (reply, is_real). is_real=False keeps it out of chat history."""
    model = context.user_data.get("emerg_model")
    if model is None:
        _init_ai_session(context)
        model = context.user_data["emerg_model"]

    current_count = increment_and_check_usage()
    if current_count == ALERT_THRESHOLD:
        await send_telegram_alert(f"Emergency agent usage alert: {current_count} calls today")

    history = context.user_data.get("emerg_chat_history", [])
    try:
        chat = model.start_chat(history=history)
        response = await chat.send_message_async(user_message)
        answer = response.text
    except Exception as exc:
        logger.exception(f"Emergency agent Gemini call failed: {exc}")
        return _ERR_AI_COMM, False

    verdict = verify_answer(answer)
    if not verdict.ok:
        # The number is not in the guide, so the model produced it on its own.
        logger.error(f"Emergency answer rejected, invented number {verdict.bad!r}")
        return _ERR_UNVERIFIED, False

    return answer + DISCLAIMER, True


# ═══ Telegram wiring ═══


def get_emergency_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🚨 מספרי חירום", callback_data="emerg_numbers")],
            [
                InlineKeyboardButton("🏥 לאן לפנות?", callback_data="emerg_triage"),
                InlineKeyboardButton("🛡️ אזעקה", callback_data="emerg_siren"),
            ],
            [InlineKeyboardButton("❌ סיום", callback_data="emerg_end")],
        ]
    )


TOPIC_SHORTCUTS = {
    "emerg_triage": "מתי מחייגים למד\"א, מתי הולכים לטרם ומתי לחדר מיון?",
    "emerg_siren": "מה עושים כשנשמעת אזעקה, וכמה זמן נשארים במרחב המוגן?",
}

INTRO = (
    "🚑 *מדריך חירום ישראלי*\n\n"
    "שאלו אותי כל שאלה על שירותי חירום בארץ — מספרי חירום, לאן לפנות, "
    "חדר מיון וזכויות, אזעקות ומרחב מוגן, קווי סיוע נפשי.\n\n"
    "⚠️ *במצב חירום ממשי אל תתכתבו איתי — חייגו 101.*"
)


async def entry_from_callback(update: Update, context):
    query = update.callback_query
    await query.answer()

    if not is_guide_available():
        await query.message.reply_text(_ERR_NO_GUIDE, parse_mode="Markdown")
        return ConversationHandler.END

    _init_ai_session(context)
    await query.message.reply_text(
        INTRO, parse_mode="Markdown", reply_markup=get_emergency_keyboard()
    )
    return EMERGENCY_STATE


async def handle_message(update: Update, context):
    text = (update.message.text or "").strip()
    if not text:
        return EMERGENCY_STATE

    kind = classify(text)
    if kind == "critical":
        # No API call: a person who is not breathing cannot wait for Gemini.
        await update.message.reply_text(
            critical_reply(), parse_mode="Markdown", reply_markup=get_emergency_keyboard()
        )
        return EMERGENCY_STATE
    if kind == "mental_health":
        await update.message.reply_text(
            _MENTAL_HEALTH_REPLY, parse_mode="Markdown", reply_markup=get_emergency_keyboard()
        )
        return EMERGENCY_STATE
    if kind == "uncovered":
        await update.message.reply_text(
            _UNCOVERED_REPLY.format(topic=uncovered_topic(text)),
            parse_mode="Markdown",
            reply_markup=get_emergency_keyboard(),
        )
        return EMERGENCY_STATE

    if is_limit_reached():
        await update.message.reply_text(
            "הגעתי למכסת השאלות היומית. מספרי החירום עדיין כאן:\n\n"
            + format_emergency_numbers(),
            parse_mode="Markdown",
        )
        return EMERGENCY_STATE

    await update.message.chat.send_action("typing")
    reply, is_real = await ask_guide(context, text)

    if is_real:
        remember(context, text, reply)

    await update.message.reply_text(
        reply, parse_mode="Markdown", reply_markup=get_emergency_keyboard()
    )
    return EMERGENCY_STATE


async def handle_numbers(update: Update, context):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        format_emergency_numbers(), parse_mode="Markdown", reply_markup=get_emergency_keyboard()
    )
    return EMERGENCY_STATE


async def handle_shortcut(update: Update, context):
    query = update.callback_query
    await query.answer()

    prompt = TOPIC_SHORTCUTS[query.data]
    reply, is_real = await ask_guide(context, prompt)

    if is_real:
        remember(context, prompt, reply)

    await query.message.reply_text(
        reply, parse_mode="Markdown", reply_markup=get_emergency_keyboard()
    )
    return EMERGENCY_STATE


def remember(context, user_message: str, reply: str) -> None:
    """Append one exchange, keeping only the most recent turns."""
    history = context.user_data.setdefault("emerg_chat_history", [])
    if MAX_HISTORY_MESSAGES <= 0:
        history.clear()
        return

    history.append({"role": "user", "parts": [user_message]})
    history.append({"role": "model", "parts": [reply]})
    if len(history) > MAX_HISTORY_MESSAGES:
        del history[:-MAX_HISTORY_MESSAGES]


def _cleanup_session(context):
    context.user_data.pop("emerg_model", None)
    context.user_data.pop("emerg_chat_history", None)


async def end_chat(update: Update, context):
    _cleanup_session(context)

    from utils.keyboards import get_main_menu_keyboard

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            "בחרו פעולה:", reply_markup=get_main_menu_keyboard()
        )
    elif update.message:
        await update.message.reply_text(
            "שמרו על עצמכם. בחירום — 101.", reply_markup=get_main_menu_keyboard()
        )
    return ConversationHandler.END


async def end_chat_command(update: Update, context):
    return await end_chat(update, context)


async def fallback_start(update: Update, context):
    _cleanup_session(context)

    from utils.keyboards import get_main_menu_keyboard
    from config import config

    await update.message.reply_text(
        config.WELCOME_MESSAGE, parse_mode="Markdown", reply_markup=get_main_menu_keyboard()
    )
    return ConversationHandler.END


async def timeout_handler(update: Update, context):
    _cleanup_session(context)
    return ConversationHandler.END


def create_emergency_conversation() -> ConversationHandler:
    """Create the emergency guide agent ConversationHandler."""
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(entry_from_callback, pattern=r"^emerg_start$"),
        ],
        states={
            EMERGENCY_STATE: [
                CommandHandler("end_emerg", end_chat_command),
                CallbackQueryHandler(end_chat, pattern=r"^emerg_end$"),
                CallbackQueryHandler(handle_numbers, pattern=r"^emerg_numbers$"),
                CallbackQueryHandler(handle_shortcut, pattern=r"^emerg_(triage|siren)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message),
            ],
            ConversationHandler.TIMEOUT: [
                MessageHandler(filters.ALL, timeout_handler),
                CallbackQueryHandler(timeout_handler),
            ],
        },
        fallbacks=[
            CommandHandler("end_emerg", end_chat_command),
            CommandHandler("start", fallback_start),
        ],
        conversation_timeout=timedelta(minutes=30).total_seconds(),
    )
