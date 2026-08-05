"""The emergency numbers card.

Kept in its own module, with nothing imported beyond the standard library, so
that the one screen a person might open in a hurry cannot be taken down by an
import failure somewhere in the AI stack. handlers/__init__.py already treats
the agent as optional; this makes the deterministic part actually live up to
that.
"""

# Straight from Step 1 of docs/israeli-emergency-guide/SKILL_HE.md. The test
# suite asserts every one of these still appears in the guide, so the card and
# the guide cannot drift apart silently.
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
