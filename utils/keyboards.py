"""
Keyboard layouts and inline buttons for Medicine Reminder Bot
Designed for elderly users with large, clear buttons and Hebrew text
"""

from typing import List, Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton

from config import config


def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Main menu keyboard with large, clear buttons"""
    keyboard = [
        [KeyboardButton(f"{config.EMOJIS['medicine']} התרופות שלי"), KeyboardButton(f"{config.EMOJIS['reminder']} תזכורות")],
        [KeyboardButton(f"{config.EMOJIS['inventory']} מלאי"), KeyboardButton(f"{config.EMOJIS['symptoms']} תופעות לוואי")],
        [KeyboardButton(f"{config.EMOJIS['report']} דוחות"), KeyboardButton(f"{config.EMOJIS['caregiver']} מטפלים")],
        [KeyboardButton(f"{config.EMOJIS['calendar']} הוספת תור")],
        [KeyboardButton(f"{config.EMOJIS['settings']} הגדרות"), KeyboardButton(f"{config.EMOJIS['info']} עזרה")],
    ]

    return ReplyKeyboardMarkup(
        keyboard, resize_keyboard=True, one_time_keyboard=False, input_field_placeholder="בחרו פעולה..."
    )


def get_appointments_menu_keyboard() -> InlineKeyboardMarkup:
    """Inline menu for creating an appointment"""
    keyboard = [
        [
            InlineKeyboardButton(f"{config.EMOJIS['doctor']} לרופא", callback_data="appt_type_doctor"),
            InlineKeyboardButton("🧪 לבדיקת דם", callback_data="appt_type_blood"),
        ],
        [
            InlineKeyboardButton("💆 לטיפול", callback_data="appt_type_treatment"),
            InlineKeyboardButton("🔎 לבדיקה", callback_data="appt_type_checkup"),
        ],
        [InlineKeyboardButton(f"{config.EMOJIS['info']} אחר...", callback_data="appt_type_custom")],
        [InlineKeyboardButton("📋 התורים שלי", callback_data="appt_list")],
        [InlineKeyboardButton(f"{config.EMOJIS['back']} חזור לתפריט", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_appointments_list_keyboard(items: list, offset: int = 0, page_size: int = 10) -> InlineKeyboardMarkup:
    """Show upcoming appointments list with select/delete buttons"""
    keyboard = []
    category_map = {
        "doctor": "רופא",
        "blood": "בדיקת דם",
        "treatment": "טיפול",
        "checkup": "בדיקה",
        "custom": "אחר",
    }
    for appt in items:
        title = getattr(appt, "title", None) or "תור"
        category_key = getattr(appt, "category", None)
        category_label = category_map.get(category_key, "תור")
        when_txt = appt.when_at.strftime("%d/%m %H:%M")
        keyboard.append(
            [InlineKeyboardButton(f"{when_txt} — {category_label} — {title}", callback_data=f"appt_view_{appt.id}")]
        )
    nav = []
    if offset > 0:
        nav.append(InlineKeyboardButton("‹ הקודם", callback_data=f"appt_page_{max(0, offset - page_size)}"))
    if len(items) == page_size:
        nav.append(InlineKeyboardButton("הבא ›", callback_data=f"appt_page_{offset + page_size}"))
    if nav:
        keyboard.append(nav)
    keyboard.append(
        [
            InlineKeyboardButton("בחר חודש", callback_data="appt_pick_month"),
            InlineKeyboardButton(f"{config.EMOJIS['back']} חזור", callback_data="appt_back_to_menu"),
        ]
    )
    return InlineKeyboardMarkup(keyboard)


def get_appointment_detail_keyboard(appt_id: int) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("שנה תאריך/שעה", callback_data=f"appt_edit_time_{appt_id}"),
            InlineKeyboardButton("מחק", callback_data=f"appt_delete_{appt_id}"),
        ],
        [InlineKeyboardButton(f"{config.EMOJIS['back']} חזור", callback_data="appt_list")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_calendar_keyboard(year: int, month: int) -> InlineKeyboardMarkup:
    """Simple inline calendar for date picking (Sunday-first)."""
    import calendar

    cal = calendar.Calendar(firstweekday=6)  # Sunday=6 in Python's calendar when firstweekday=6
    month_days = cal.monthdayscalendar(year, month)
    header = [
        InlineKeyboardButton("«", callback_data=f"appt_cal_nav_{year}_{month}_prev"),
        InlineKeyboardButton(f"{year}-{month:02d}", callback_data="noop"),
        InlineKeyboardButton("»", callback_data=f"appt_cal_nav_{year}_{month}_next"),
    ]
    keyboard = [header]
    # Weekday headers (S M T W T F S in Hebrew order might differ; keep generic)
    keyboard.append(
        [
            InlineKeyboardButton("א", callback_data="noop"),
            InlineKeyboardButton("ב", callback_data="noop"),
            InlineKeyboardButton("ג", callback_data="noop"),
            InlineKeyboardButton("ד", callback_data="noop"),
            InlineKeyboardButton("ה", callback_data="noop"),
            InlineKeyboardButton("ו", callback_data="noop"),
            InlineKeyboardButton("ש", callback_data="noop"),
        ]
    )
    for week in month_days:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(" ", callback_data="noop"))
            else:
                row.append(InlineKeyboardButton(str(day), callback_data=f"appt_date_{year}_{month:02d}_{day:02d}"))
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton(f"{config.EMOJIS['back']} ביטול", callback_data="appt_cancel")])
    return InlineKeyboardMarkup(keyboard)


def get_appointment_reminder_keyboard(rem1: bool, rem3: bool, rem0: bool = False) -> InlineKeyboardMarkup:
    """Toggle reminders and confirm. Tap to toggle each option on/off."""
    on = "✅"
    off = "⭕"
    keyboard = [
        [
            InlineKeyboardButton(f"{on if rem1 else off} יום לפני", callback_data="appt_rem1_toggle"),
            InlineKeyboardButton(f"{on if rem3 else off} 3 ימים לפני", callback_data="appt_rem3_toggle"),
        ],
        [
            InlineKeyboardButton(
                f"{on if rem0 else off} ביום התור (ב-{config.APPOINTMENT_SAME_DAY_REMINDER_HOUR:02d}:00)",
                callback_data="appt_rem0_toggle",
            ),
            InlineKeyboardButton("שנה שעה", callback_data="appt_rem0_time"),
        ],
        [InlineKeyboardButton(f"{config.EMOJIS['success']} שמור תור", callback_data="appt_save")],
        [InlineKeyboardButton(f"{config.EMOJIS['back']} חזור", callback_data="appt_back")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_reminder_keyboard(medicine_id: int) -> InlineKeyboardMarkup:
    """Keyboard for medicine reminder notifications"""
    keyboard = [
        [InlineKeyboardButton(f"{config.EMOJIS['success']} לקחתי!", callback_data=f"dose_taken_{medicine_id}")],
        [
            InlineKeyboardButton(
                f"{config.EMOJIS['clock']} דחה ל-{config.REMINDER_SNOOZE_MINUTES} דקות",
                callback_data=f"dose_snooze_{medicine_id}",
            )
        ],
        [InlineKeyboardButton(f"{config.EMOJIS['error']} לא אקח", callback_data=f"dose_skip_{medicine_id}")],
    ]

    return InlineKeyboardMarkup(keyboard)


def get_medicines_keyboard(medicines: List, offset: int = 0) -> InlineKeyboardMarkup:
    """Keyboard for displaying user's medicines"""
    keyboard = []

    # Add medicine buttons (max 5 per page)
    page_size = config.MAX_MEDICINES_PER_PAGE
    slice_start = max(0, int(offset))
    slice_end = slice_start + page_size
    page_items = medicines[slice_start:slice_end]
    for i, medicine in enumerate(page_items):
        status_emoji = config.EMOJIS["success"] if medicine.is_active else config.EMOJIS["error"]
        # Removed warning emoji from button label for clarity

        button_text = f"{status_emoji} {medicine.name}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"medicine_view_{medicine.id}")])
        # Quick actions row per medicine
        keyboard.append(
            [
                InlineKeyboardButton(f"{config.EMOJIS['clock']} שעות", callback_data=f"medicine_schedule_{medicine.id}"),
                InlineKeyboardButton(f"{config.EMOJIS['inventory']} מלאי", callback_data=f"medicine_inventory_{medicine.id}"),
                InlineKeyboardButton(f"{config.EMOJIS['settings']} פרטים", callback_data=f"medicine_view_{medicine.id}"),
                InlineKeyboardButton(f"{config.EMOJIS['report']} היסטוריה", callback_data=f"medicine_history_{medicine.id}"),
            ]
        )

    # Global action buttons
    action_row = [InlineKeyboardButton(f"{config.EMOJIS['medicine']} הוסף תרופה", callback_data="medicine_add")]
    keyboard.append(action_row)

    # Navigation buttons
    nav_row = []
    if slice_start > 0:
        prev_offset = max(0, slice_start - page_size)
        nav_row.append(InlineKeyboardButton("‹ הקודם", callback_data=f"medicines_page_{prev_offset}"))
    if slice_end < len(medicines):
        next_offset = slice_start + page_size
        nav_row.append(InlineKeyboardButton("עמוד הבא ›", callback_data=f"medicines_page_{next_offset}"))
    if nav_row:
        keyboard.append(nav_row)

    # Back to main menu
    keyboard.append(
        [
            InlineKeyboardButton(f"{config.EMOJIS['back']} חזור לתפריט", callback_data="main_menu"),
            InlineKeyboardButton(f"{config.EMOJIS['symptoms']} תופעות לוואי", callback_data="symptoms_menu"),
        ]
    )

    return InlineKeyboardMarkup(keyboard)


def get_medicine_detail_keyboard(medicine_id: int) -> InlineKeyboardMarkup:
    """Keyboard for individual medicine details"""
    keyboard = [
        [
            InlineKeyboardButton(f"{config.EMOJIS['clock']} שנה שעות", callback_data=f"medicine_schedule_{medicine_id}"),
            InlineKeyboardButton(f"{config.EMOJIS['inventory']} עדכן מלאי", callback_data=f"medicine_inventory_{medicine_id}"),
        ],
        [
            InlineKeyboardButton(f"{config.EMOJIS['settings']} ערוך פרטים", callback_data=f"medicine_edit_{medicine_id}"),
            InlineKeyboardButton(f"{config.EMOJIS['report']} היסטוריה", callback_data=f"medicine_history_{medicine_id}"),
        ],
        [InlineKeyboardButton(f"{config.EMOJIS['error']} מחק תרופה", callback_data=f"medicine_delete_{medicine_id}")],
        [InlineKeyboardButton(f"{config.EMOJIS['back']} חזור לרשימה", callback_data="medicines_list")],
    ]

    return InlineKeyboardMarkup(keyboard)


def get_settings_keyboard() -> InlineKeyboardMarkup:
    """Settings menu keyboard"""
    keyboard = [
        [
            InlineKeyboardButton(f"{config.EMOJIS['clock']} אזור זמן", callback_data="settings_timezone"),
            InlineKeyboardButton(f"{config.EMOJIS['reminder']} הגדרות תזכורות", callback_data="settings_reminders"),
        ],
        [
            InlineKeyboardButton(f"{config.EMOJIS['inventory']} הגדרות מלאי", callback_data="settings_inventory"),
            InlineKeyboardButton(f"{config.EMOJIS['caregiver']} הגדרות מטפלים", callback_data="settings_caregivers"),
        ],
        [InlineKeyboardButton(f"{config.EMOJIS['report']} הגדרות דוחות", callback_data="settings_reports")],
        [InlineKeyboardButton(f"{config.EMOJIS['back']} חזור לתפריט", callback_data="main_menu")],
    ]

    return InlineKeyboardMarkup(keyboard)


def get_reminders_settings_keyboard(current_snooze: int, current_attempts: int, silent: bool) -> InlineKeyboardMarkup:
    """Keyboard for reminders settings adjustments."""
    keyboard = [
        [
            InlineKeyboardButton(f"דחייה: {current_snooze} דק'", callback_data="rsnoop_info"),
            InlineKeyboardButton("-1", callback_data="rsnoop_-1"),
            InlineKeyboardButton("+1", callback_data="rsnoop_+1"),
        ],
        [
            InlineKeyboardButton(f"ניסיונות: {current_attempts}", callback_data="rattempts_info"),
            InlineKeyboardButton("-1", callback_data="rattempts_-1"),
            InlineKeyboardButton("+1", callback_data="rattempts_+1"),
        ],
        [InlineKeyboardButton(f"מצב שקט: {'מופעל' if silent else 'כבוי'}", callback_data="rsilent_toggle")],
        [InlineKeyboardButton(f"{config.EMOJIS['back']} חזור", callback_data="reminders_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_inventory_main_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for inventory main section."""
    keyboard = [
        [
            InlineKeyboardButton(f"{config.EMOJIS['inventory']} הוסף מלאי", callback_data="inventory_add"),
        ],
        [InlineKeyboardButton(f"{config.EMOJIS['report']} דוח מצב מלאי", callback_data="inventory_report")],
        [InlineKeyboardButton(f"{config.EMOJIS['back']} חזור לתפריט", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_caregiver_keyboard() -> InlineKeyboardMarkup:
    """Caregiver management keyboard"""
    keyboard = [
        [InlineKeyboardButton(f"{config.EMOJIS['caregiver']} הוסף מטפל", callback_data="caregiver_add")],
        [
            InlineKeyboardButton(f"{config.EMOJIS['settings']} נהל מטפלים", callback_data="caregiver_manage"),
            InlineKeyboardButton(f"{config.EMOJIS['report']} שלח דוח", callback_data="caregiver_send_report"),
        ],
        [InlineKeyboardButton(f"{config.EMOJIS['back']} חזור לתפריט", callback_data="main_menu")],
    ]

    return InlineKeyboardMarkup(keyboard)


def get_symptoms_keyboard() -> InlineKeyboardMarkup:
    """Symptoms tracking keyboard"""
    keyboard = [
        [InlineKeyboardButton(f"{config.EMOJIS['symptoms']} רשום תופעות לוואי", callback_data="symptoms_log")],
        [InlineKeyboardButton(f"{config.EMOJIS['report']} צפה בהיסטוריה", callback_data="symptoms_history")],
        [InlineKeyboardButton(f"{config.EMOJIS['back']} חזור לתפריט", callback_data="main_menu")],
    ]

    return InlineKeyboardMarkup(keyboard)


def get_reports_keyboard() -> InlineKeyboardMarkup:
    """Reports menu keyboard"""
    keyboard = [
        [
            InlineKeyboardButton(f"{config.EMOJIS['calendar']} דוח שבועי", callback_data="report_weekly"),
            InlineKeyboardButton(f"{config.EMOJIS['calendar']} דוח חודשי", callback_data="report_monthly"),
        ],
        [
            InlineKeyboardButton(f"{config.EMOJIS['medicine']} דוח תרופות", callback_data="report_medicines"),
            InlineKeyboardButton(f"{config.EMOJIS['symptoms']} דוח תופעות לוואי", callback_data="report_symptoms"),
        ],
        [InlineKeyboardButton(f"{config.EMOJIS['doctor']} שלח לרופא", callback_data="report_send_doctor")],
        [InlineKeyboardButton(f"{config.EMOJIS['back']} חזור לתפריט", callback_data="main_menu")],
    ]

    return InlineKeyboardMarkup(keyboard)


def get_time_selection_keyboard() -> InlineKeyboardMarkup:
    """Time selection keyboard for scheduling"""
    keyboard = []

    # Morning hours (6-12)
    morning_row = []
    for hour in range(6, 12):
        morning_row.append(InlineKeyboardButton(f"🌅 {hour:02d}:00", callback_data=f"time_{hour:02d}_00"))
        if len(morning_row) == 3:
            keyboard.append(morning_row)
            morning_row = []

    if morning_row:
        keyboard.append(morning_row)

    # Afternoon hours (12-18)
    afternoon_row = []
    for hour in range(12, 18):
        afternoon_row.append(InlineKeyboardButton(f"☀️ {hour:02d}:00", callback_data=f"time_{hour:02d}_00"))
        if len(afternoon_row) == 3:
            keyboard.append(afternoon_row)
            afternoon_row = []

    if afternoon_row:
        keyboard.append(afternoon_row)

    # Evening hours (18-24)
    evening_row = []
    for hour in range(18, 24):
        evening_row.append(InlineKeyboardButton(f"🌙 {hour:02d}:00", callback_data=f"time_{hour:02d}_00"))
        if len(evening_row) == 3:
            keyboard.append(evening_row)
            evening_row = []

    if evening_row:
        keyboard.append(evening_row)

    # Custom time button
    keyboard.append([InlineKeyboardButton(f"{config.EMOJIS['settings']} שעה מותאמת אישית", callback_data="time_custom")])

    # Cancel button
    keyboard.append([InlineKeyboardButton(f"{config.EMOJIS['back']} ביטול", callback_data="time_cancel")])

    return InlineKeyboardMarkup(keyboard)


def get_inventory_update_keyboard(medicine_id: int, pack_size: int = None) -> InlineKeyboardMarkup:
    """Keyboard for quick inventory updates (by packs)."""
    pack = int(pack_size) if pack_size else 28
    fixed_steps = [28, 56, 84]
    pack_steps = [pack, pack * 2, pack * 3]
    show_fixed = len(set(pack_steps) & set(fixed_steps)) == 0

    keyboard: List[List[InlineKeyboardButton]] = []

    # Add-quantity explicit button at the top
    keyboard.append([InlineKeyboardButton("➕ הוסף כמות כדורים", callback_data=f"inventory_{medicine_id}_add_dialog")])

    # Add fixed increments only if they do not duplicate pack-based steps
    if show_fixed:
        keyboard.append(
            [
                InlineKeyboardButton("+28", callback_data=f"inventory_{medicine_id}_+28"),
                InlineKeyboardButton("+56", callback_data=f"inventory_{medicine_id}_+56"),
                InlineKeyboardButton("+84", callback_data=f"inventory_{medicine_id}_+84"),
            ]
        )

    # Pack-based increments
    keyboard.append(
        [
            InlineKeyboardButton(f"+1 חבילה (+{pack})", callback_data=f"inventory_{medicine_id}_+{pack}"),
            InlineKeyboardButton(f"+2 חבילות (+{pack*2})", callback_data=f"inventory_{medicine_id}_+{pack*2}"),
            InlineKeyboardButton(f"+3 חבילות (+{pack*3})", callback_data=f"inventory_{medicine_id}_+{pack*3}"),
        ]
    )

    keyboard.append(
        [InlineKeyboardButton(f"{config.EMOJIS['settings']} הזן כמות מלאי", callback_data=f"inventory_{medicine_id}_custom")]
    )
    keyboard.append([InlineKeyboardButton(f"{config.EMOJIS['back']} חזור", callback_data=f"medicine_view_{medicine_id}")])

    return InlineKeyboardMarkup(keyboard)


def get_confirmation_keyboard(action: str, item_id: int = None) -> InlineKeyboardMarkup:
    """Generic confirmation keyboard"""
    callback_prefix = f"{action}_{item_id}" if item_id else action

    keyboard = [
        [InlineKeyboardButton(f"{config.EMOJIS['success']} כן, אני בטוח", callback_data=f"{callback_prefix}_confirm")],
        [InlineKeyboardButton(f"{config.EMOJIS['error']} לא, ביטול", callback_data=f"{callback_prefix}_cancel")],
    ]

    return InlineKeyboardMarkup(keyboard)


def get_cancel_keyboard() -> InlineKeyboardMarkup:
    """Simple cancel button"""
    keyboard = [[InlineKeyboardButton(f"{config.EMOJIS['back']} חזור", callback_data="cancel")]]

    return InlineKeyboardMarkup(keyboard)


def get_pagination_keyboard(current_page: int, total_pages: int, callback_prefix: str) -> InlineKeyboardMarkup:
    """Pagination keyboard for lists"""
    keyboard = []

    nav_row = []

    # Previous page button
    if current_page > 1:
        nav_row.append(
            InlineKeyboardButton(f"{config.EMOJIS['back']} הקודם", callback_data=f"{callback_prefix}_page_{current_page - 1}")
        )

    # Page indicator
    nav_row.append(InlineKeyboardButton(f"📄 {current_page}/{total_pages}", callback_data="page_info"))

    # Next page button
    if current_page < total_pages:
        nav_row.append(
            InlineKeyboardButton(f"הבא {config.EMOJIS['next']}", callback_data=f"{callback_prefix}_page_{current_page + 1}")
        )

    if nav_row:
        keyboard.append(nav_row)

    return InlineKeyboardMarkup(keyboard)


# Utility functions for keyboard management


def create_quick_reply_keyboard(options: List[str]) -> ReplyKeyboardMarkup:
    """Create a quick reply keyboard from list of options"""
    keyboard = []
    row = []

    for i, option in enumerate(options):
        row.append(KeyboardButton(option))

        # Create new row every 2 buttons
        if len(row) == 2 or i == len(options) - 1:
            keyboard.append(row)
            row = []

    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)


def hide_keyboard() -> ReplyKeyboardMarkup:
    """Hide the current keyboard"""
    from telegram import ReplyKeyboardRemove

    return ReplyKeyboardRemove()


# Emergency contact keyboard
def get_emergency_keyboard() -> InlineKeyboardMarkup:
    """Emergency actions keyboard"""
    keyboard = [
        [InlineKeyboardButton("🚨 חירום - צור קשר עם מטפל", callback_data="emergency_caregiver")],
        [InlineKeyboardButton("🏥 חירום רפואי - 101", url="tel:101")],
        [InlineKeyboardButton(f"{config.EMOJIS['doctor']} פנה לרופא המשפחה", callback_data="emergency_doctor")],
    ]

    return InlineKeyboardMarkup(keyboard)


def get_symptoms_medicine_picker(medicines: List) -> InlineKeyboardMarkup:
    """Build a keyboard to select a medicine for symptoms logging."""
    keyboard = []
    # Show up to 8 medicines; each as a row button
    for med in medicines[:8]:
        name = getattr(med, "name", "תרופה")
        mid = getattr(med, "id", None)
        if mid is None:
            continue
        # Icon heuristics based on common names (minimal noise): mushroom and cannabis
        lower_name = str(name).lower()
        mushroom_tokens = [
            "אמניטה",
            "אמניטה מוסכריה",
            "פסילו",
            "פסילוסבין",
            "amanita",
            "muscaria",
            "psilo",
            "psilocybin",
            "psilocybe",
        ]
        cannabis_tokens = ["קנאביס", "cannabis", "cbd", "thc"]
        if any(tok in lower_name for tok in mushroom_tokens):
            label = f"🍄 {name}"
        elif any(tok in lower_name for tok in cannabis_tokens):
            label = f"🌿 {name}"
        else:
            label = f"{name}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"symptoms_log_med_{mid}")])
    # Fallback when no medicines
    if not medicines:
        keyboard.append([InlineKeyboardButton(f"{config.EMOJIS['info']} אין תרופות רשומות", callback_data="main_menu")])
    # Back button
    keyboard.append([InlineKeyboardButton(f"{config.EMOJIS['back']} חזור", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)


def get_symptoms_history_picker(medicines: List) -> InlineKeyboardMarkup:
    """Build a keyboard to filter symptoms history by medicine or show all."""
    keyboard = []
    # All option
    keyboard.append([InlineKeyboardButton(f"{config.EMOJIS['report']} כל התרופות", callback_data="symptoms_history_all")])
    # Per-medicine options (limit to 8 for brevity)
    for med in medicines[:8]:
        name = getattr(med, "name", "תרופה")
        mid = getattr(med, "id", None)
        if mid is None:
            continue
        keyboard.append(
            [InlineKeyboardButton(f"{config.EMOJIS['medicine']} {name}", callback_data=f"symptoms_history_med_{mid}")]
        )
    # Back
    keyboard.append([InlineKeyboardButton(f"{config.EMOJIS['back']} חזור", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)


def get_symptom_logs_list_keyboard(logs: List) -> InlineKeyboardMarkup:
    """Build a keyboard listing recent symptom logs with per-item edit/delete actions."""
    keyboard = []
    for log in logs:
        ts = log.log_date.strftime("%d/%m %H:%M") if hasattr(log, "log_date") and log.log_date else ""
        title = (log.symptoms or log.side_effects or "—")[:25]
        keyboard.append([InlineKeyboardButton(f"{ts} — {title}", callback_data=f"symptoms_view_{log.id}")])
        keyboard.append(
            [
                InlineKeyboardButton("ערוך", callback_data=f"symptoms_edit_{log.id}"),
                InlineKeyboardButton("מחק", callback_data=f"symptoms_delete_{log.id}"),
            ]
        )
    keyboard.append([InlineKeyboardButton(f"{config.EMOJIS['back']} חזור", callback_data="symptoms_history")])
    return InlineKeyboardMarkup(keyboard)
