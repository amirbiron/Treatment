"""Whether a user wants inventory numbers shown.

The reminder scheduler and the menu both need this, and both need the same
answer. It lives here rather than in either of them so the default cannot drift:
inventory is shown unless the user explicitly turned it off, including when the
setting cannot be read at all. Hiding a count someone relies on is worse than
showing one they do not care about.
"""

import logging

logger = logging.getLogger(__name__)


def shows_inventory(settings) -> bool:
    """Read the flag off a settings object, defaulting to on."""
    return bool(getattr(settings, "track_inventory", True))


async def shows_inventory_for_user(db_user) -> bool:
    """Look the setting up for a resolved user row."""
    from database import DatabaseManager

    if not db_user:
        return True
    try:
        return shows_inventory(await DatabaseManager.get_user_settings(db_user.id))
    except Exception:
        logger.exception("Could not read the inventory setting; showing inventory")
        return True


def stock_line(count, low_threshold=None, prefix="📦 מלאי נותר: ") -> str:
    """The stock line plus its warning, or nothing at all.

    Callers pass an already-resolved decision so they do not each repeat the
    lookup. Returning "" rather than a blank line keeps the message tidy when
    the line is dropped.
    """
    line = f"{prefix}{count} כדורים"
    if low_threshold is not None and count <= low_threshold:
        line += (
            "\n\n❌ <b>המלאי אפס!</b> אנא עדכנו את המלאי."
            if count == 0
            else f"\n\n⚠️ <b>מלאי נמוך!</b>\nנותרו {count} כדורים. כדאי להזמין עוד."
        )
    return line


async def shows_inventory_for_telegram_id(telegram_user_id) -> bool:
    """Look the setting up from a Telegram id."""
    from database import DatabaseManager

    try:
        return await shows_inventory_for_user(
            await DatabaseManager.get_user_by_telegram_id(telegram_user_id)
        )
    except Exception:
        logger.exception("Could not resolve the user; showing inventory")
        return True
