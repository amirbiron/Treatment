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
        [
            KeyboardButton(f"{config.EMOJIS['medicine']} התרופות שלי"),
            KeyboardButton(f"{config.EMOJIS['reminder']} תזכורות")
        ],
        [
            KeyboardButton(f"{config.EMOJIS['inventory']} מלאי"),
            KeyboardButton(f"{config.EMOJIS['symptoms']} תופעות לוואי")
        ],
        [
            KeyboardButton(f"{config.EMOJIS['report']} דוחות"),
            KeyboardButton(f"{config.EMOJIS['caregiver']} מטפלים")
        ],
        [
            KeyboardButton(f"{config.EMOJIS['settings']} הגדרות"),
            KeyboardButton(f"{config.EMOJIS['info']} עזרה")
        ]
    ]
    
    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="בחרו פעולה..."
    )


def get_reminder_keyboard(medicine_id: int) -> InlineKeyboardMarkup:
    """Keyboard for medicine reminder notifications"""
    keyboard = [
        [
            InlineKeyboardButton(
                f"{config.EMOJIS['success']} לקחתי!",
                callback_data=f"dose_taken_{medicine_id}"
            )
        ],
        [
            InlineKeyboardButton(
                f"{config.EMOJIS['clock']} דחה ל-{config.REMINDER_SNOOZE_MINUTES} דקות",
                callback_data=f"dose_snooze_{medicine_id}"
            )
        ],
        [
            InlineKeyboardButton(
                f"{config.EMOJIS['error']} לא אקח",
                callback_data=f"dose_skip_{medicine_id}"
            )
        ]
    ]
    
    return InlineKeyboardMarkup(keyboard)


def get_medicines_keyboard(medicines: List) -> InlineKeyboardMarkup:
    """Keyboard for displaying user's medicines"""
    keyboard = []
    
    # Add medicine buttons (max 5 per page)
    for i, medicine in enumerate(medicines[:config.MAX_MEDICINES_PER_PAGE]):
        status_emoji = config.EMOJIS['success'] if medicine.is_active else config.EMOJIS['error']
        # Removed warning emoji from button label for clarity
        
        button_text = f"{status_emoji} {medicine.name}"
        keyboard.append([
            InlineKeyboardButton(
                button_text,
                callback_data=f"medicine_view_{medicine.id}"
            )
        ])
    
    # Action buttons
    action_row = [
        InlineKeyboardButton(
            f"{config.EMOJIS['medicine']} הוסף תרופה",
            callback_data="medicine_add"
        )
    ]
    
    if medicines:
        action_row.append(
            InlineKeyboardButton(
                f"{config.EMOJIS['settings']} ערוך תרופות",
                callback_data="medicine_manage"
            )
        )
    
    keyboard.append(action_row)
    
    # Navigation buttons if more than 5 medicines
    if len(medicines) > config.MAX_MEDICINES_PER_PAGE:
        nav_row = []
        nav_row.append(
            InlineKeyboardButton(
                f"{config.EMOJIS['next']} עוד תרופות",
                callback_data="medicine_next_page"
            )
        )
        keyboard.append(nav_row)
    
    # Back to main menu
    keyboard.append([
        InlineKeyboardButton(
            f"{config.EMOJIS['back']} חזור לתפריט",
            callback_data="main_menu"
        )
    ])
    
    return InlineKeyboardMarkup(keyboard)


def get_medicine_detail_keyboard(medicine_id: int) -> InlineKeyboardMarkup:
    """Keyboard for individual medicine details"""
    keyboard = [
        [
            InlineKeyboardButton(
                f"{config.EMOJIS['clock']} שנה שעות",
                callback_data=f"medicine_schedule_{medicine_id}"
            ),
            InlineKeyboardButton(
                f"{config.EMOJIS['inventory']} עדכן מלאי",
                callback_data=f"medicine_inventory_{medicine_id}"
            )
        ],
        [
            InlineKeyboardButton(
                f"{config.EMOJIS['settings']} ערוך פרטים",
                callback_data=f"medicine_edit_{medicine_id}"
            ),
            InlineKeyboardButton(
                f"{config.EMOJIS['report']} היסטוריה",
                callback_data=f"medicine_history_{medicine_id}"
            )
        ],
        [
            InlineKeyboardButton(
                f"{config.EMOJIS['error']} השבת/הפעל",
                callback_data=f"medicine_toggle_{medicine_id}"
            )
        ],
        [
            InlineKeyboardButton(
                f"{config.EMOJIS['back']} חזור לרשימה",
                callback_data="medicines_list"
            )
        ]
    ]
    
    return InlineKeyboardMarkup(keyboard)


def get_settings_keyboard() -> InlineKeyboardMarkup:
    """Settings menu keyboard"""
    keyboard = [
        [
            InlineKeyboardButton(
                f"{config.EMOJIS['clock']} אזור זמן",
                callback_data="settings_timezone"
            ),
            InlineKeyboardButton(
                f"{config.EMOJIS['reminder']} הגדרות תזכורות",
                callback_data="settings_reminders"
            )
        ],
        [
            InlineKeyboardButton(
                f"{config.EMOJIS['inventory']} הגדרות מלאי",
                callback_data="settings_inventory"
            ),
            InlineKeyboardButton(
                f"{config.EMOJIS['caregiver']} הגדרות מטפלים",
                callback_data="settings_caregivers"
            )
        ],
        [
            InlineKeyboardButton(
                f"{config.EMOJIS['report']} הגדרות דוחות",
                callback_data="settings_reports"
            )
        ],
        [
            InlineKeyboardButton(
                f"{config.EMOJIS['back']} חזור לתפריט",
                callback_data="main_menu"
            )
        ]
    ]
    
    return InlineKeyboardMarkup(keyboard)


def get_caregiver_keyboard() -> InlineKeyboardMarkup:
    """Caregiver management keyboard"""
    keyboard = [
        [
            InlineKeyboardButton(
                f"{config.EMOJIS['caregiver']} הוסף מטפל",
                callback_data="caregiver_add"
            )
        ],
        [
            InlineKeyboardButton(
                f"{config.EMOJIS['settings']} נהל מטפלים",
                callback_data="caregiver_manage"
            ),
            InlineKeyboardButton(
                f"{config.EMOJIS['report']} שלח דוח",
                callback_data="caregiver_send_report"
            )
        ],
        [
            InlineKeyboardButton(
                f"{config.EMOJIS['back']} חזור לתפריט",
                callback_data="main_menu"
            )
        ]
    ]
    
    return InlineKeyboardMarkup(keyboard)


def get_symptoms_keyboard() -> InlineKeyboardMarkup:
    """Symptoms tracking keyboard"""
    keyboard = [
        [
            InlineKeyboardButton(
                f"{config.EMOJIS['symptoms']} רשום תופעות לוואי",
                callback_data="symptoms_log"
            )
        ],
        [
            InlineKeyboardButton(
                f"{config.EMOJIS['report']} צפה בהיסטוריה",
                callback_data="symptoms_history"
            )
        ],
        [
            InlineKeyboardButton(
                f"{config.EMOJIS['back']} חזור לתפריט",
                callback_data="main_menu"
            )
        ]
    ]
    
    return InlineKeyboardMarkup(keyboard)


def get_reports_keyboard() -> InlineKeyboardMarkup:
    """Reports menu keyboard"""
    keyboard = [
        [
            InlineKeyboardButton(
                f"{config.EMOJIS['calendar']} דוח שבועי",
                callback_data="report_weekly"
            ),
            InlineKeyboardButton(
                f"{config.EMOJIS['calendar']} דוח חודשי",
                callback_data="report_monthly"
            )
        ],
        [
            InlineKeyboardButton(
                f"{config.EMOJIS['medicine']} דוח תרופות",
                callback_data="report_medicines"
            ),
            InlineKeyboardButton(
                f"{config.EMOJIS['symptoms']} דוח תופעות לוואי",
                callback_data="report_symptoms"
            )
        ],
        [
            InlineKeyboardButton(
                f"{config.EMOJIS['doctor']} שלח לרופא",
                callback_data="report_send_doctor"
            )
        ],
        [
            InlineKeyboardButton(
                f"{config.EMOJIS['back']} חזור לתפריט",
                callback_data="main_menu"
            )
        ]
    ]
    
    return InlineKeyboardMarkup(keyboard)


def get_time_selection_keyboard() -> InlineKeyboardMarkup:
    """Time selection keyboard for scheduling"""
    keyboard = []
    
    # Morning hours (6-12)
    morning_row = []
    for hour in range(6, 12):
        morning_row.append(
            InlineKeyboardButton(
                f"🌅 {hour:02d}:00",
                callback_data=f"time_{hour:02d}_00"
            )
        )
        if len(morning_row) == 3:
            keyboard.append(morning_row)
            morning_row = []
    
    if morning_row:
        keyboard.append(morning_row)
    
    # Afternoon hours (12-18)
    afternoon_row = []
    for hour in range(12, 18):
        afternoon_row.append(
            InlineKeyboardButton(
                f"☀️ {hour:02d}:00",
                callback_data=f"time_{hour:02d}_00"
            )
        )
        if len(afternoon_row) == 3:
            keyboard.append(afternoon_row)
            afternoon_row = []
    
    if afternoon_row:
        keyboard.append(afternoon_row)
    
    # Evening hours (18-24)
    evening_row = []
    for hour in range(18, 24):
        evening_row.append(
            InlineKeyboardButton(
                f"🌙 {hour:02d}:00",
                callback_data=f"time_{hour:02d}_00"
            )
        )
        if len(evening_row) == 3:
            keyboard.append(evening_row)
            evening_row = []
    
    if evening_row:
        keyboard.append(evening_row)
    
    # Custom time button
    keyboard.append([
        InlineKeyboardButton(
            f"{config.EMOJIS['settings']} שעה מותאמת אישית",
            callback_data="time_custom"
        )
    ])
    
    # Cancel button
    keyboard.append([
        InlineKeyboardButton(
            f"{config.EMOJIS['back']} ביטול",
            callback_data="time_cancel"
        )
    ])
    
    return InlineKeyboardMarkup(keyboard)


def get_inventory_update_keyboard(medicine_id: int) -> InlineKeyboardMarkup:
    """Keyboard for quick inventory updates"""
    keyboard = [
        [
            InlineKeyboardButton("+1", callback_data=f"inventory_{medicine_id}_+1"),
            InlineKeyboardButton("+5", callback_data=f"inventory_{medicine_id}_+5"),
            InlineKeyboardButton("+10", callback_data=f"inventory_{medicine_id}_+10")
        ],
        [
            InlineKeyboardButton("-1", callback_data=f"inventory_{medicine_id}_-1"),
            InlineKeyboardButton("-5", callback_data=f"inventory_{medicine_id}_-5"),
            InlineKeyboardButton("-10", callback_data=f"inventory_{medicine_id}_-10")
        ],
        [
            InlineKeyboardButton(
                f"{config.EMOJIS['settings']} הזן כמות מדויקת",
                callback_data=f"inventory_{medicine_id}_custom"
            )
        ],
        [
            InlineKeyboardButton(
                f"{config.EMOJIS['back']} חזור",
                callback_data=f"medicine_view_{medicine_id}"
            )
        ]
    ]
    
    return InlineKeyboardMarkup(keyboard)


def get_confirmation_keyboard(action: str, item_id: int = None) -> InlineKeyboardMarkup:
    """Generic confirmation keyboard"""
    callback_prefix = f"{action}_{item_id}" if item_id else action
    
    keyboard = [
        [
            InlineKeyboardButton(
                f"{config.EMOJIS['success']} כן, אני בטוח",
                callback_data=f"{callback_prefix}_confirm"
            )
        ],
        [
            InlineKeyboardButton(
                f"{config.EMOJIS['error']} לא, ביטול",
                callback_data=f"{callback_prefix}_cancel"
            )
        ]
    ]
    
    return InlineKeyboardMarkup(keyboard)


def get_cancel_keyboard() -> InlineKeyboardMarkup:
    """Simple cancel button"""
    keyboard = [
        [
            InlineKeyboardButton(
                f"{config.EMOJIS['back']} ביטול",
                callback_data="cancel"
            )
        ]
    ]
    
    return InlineKeyboardMarkup(keyboard)


def get_pagination_keyboard(
    current_page: int, 
    total_pages: int, 
    callback_prefix: str
) -> InlineKeyboardMarkup:
    """Pagination keyboard for lists"""
    keyboard = []
    
    nav_row = []
    
    # Previous page button
    if current_page > 1:
        nav_row.append(
            InlineKeyboardButton(
                f"{config.EMOJIS['back']} הקודם",
                callback_data=f"{callback_prefix}_page_{current_page - 1}"
            )
        )
    
    # Page indicator
    nav_row.append(
        InlineKeyboardButton(
            f"📄 {current_page}/{total_pages}",
            callback_data="page_info"
        )
    )
    
    # Next page button
    if current_page < total_pages:
        nav_row.append(
            InlineKeyboardButton(
                f"הבא {config.EMOJIS['next']}",
                callback_data=f"{callback_prefix}_page_{current_page + 1}"
            )
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
    
    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=True
    )


def hide_keyboard() -> ReplyKeyboardMarkup:
    """Hide the current keyboard"""
    from telegram import ReplyKeyboardRemove
    return ReplyKeyboardRemove()


# Emergency contact keyboard
def get_emergency_keyboard() -> InlineKeyboardMarkup:
    """Emergency actions keyboard"""
    keyboard = [
        [
            InlineKeyboardButton(
                f"🚨 חירום - צור קשר עם מטפל",
                callback_data="emergency_caregiver"
            )
        ],
        [
            InlineKeyboardButton(
                f"🏥 חירום רפואי - 101",
                url="tel:101"
            )
        ],
        [
            InlineKeyboardButton(
                f"{config.EMOJIS['doctor']} פנה לרופא המשפחה",
                callback_data="emergency_doctor"
            )
        ]
    ]
    
    return InlineKeyboardMarkup(keyboard)
