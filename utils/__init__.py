"""
Utils Package
Common utilities and helper functions for Medicine Reminder Bot
"""

# Optional helpers module (may not exist in some deployments)
try:
    from .helpers import (
        # Date and Time utilities
        get_timezone,
        now_in_timezone,
        format_datetime_hebrew,
        format_date_hebrew,
        format_time_hebrew,
        parse_time_string,
        get_next_occurrence,
        time_until,
        # Validation utilities
        validate_medicine_name,
        validate_dosage,
        validate_inventory_count,
        validate_telegram_id,
        validate_phone_number,
        # Text processing utilities
        clean_text,
        truncate_text,
        format_list_hebrew,
        extract_mentions,
        mask_sensitive_data,
        # Data processing utilities
        calculate_adherence_rate,
        calculate_average_mood,
        group_by_date,
        calculate_streaks,
        paginate_items,
        # Formatting utilities
        format_medication_schedule,
        format_inventory_status,
        format_adherence_rate,
        format_file_size,
        # Safe conversion utilities
        safe_int,
        safe_float,
        safe_str,
        # Async utilities
        async_retry,
        async_batch_process,
        # Report utilities
        generate_summary_stats,
        create_progress_bar,
        # Cache utilities
        SimpleCache,
        cache,
        # Export utilities
        create_csv_content,
        create_report_filename,
    )

    _HELPERS_AVAILABLE = True
except ImportError:
    _HELPERS_AVAILABLE = False

from .keyboards import (
    # Main keyboards
    get_main_menu_keyboard,
    get_reminder_keyboard,
    get_medicines_keyboard,
    get_medicine_detail_keyboard,
    get_settings_keyboard,
    get_caregiver_keyboard,
    get_symptoms_keyboard,
    get_symptoms_medicine_picker,
    get_symptoms_history_picker,
    get_reports_keyboard,
    # Utility keyboards
    get_time_selection_keyboard,
    get_inventory_update_keyboard,
    get_confirmation_keyboard,
    get_cancel_keyboard,
    get_pagination_keyboard,
    get_emergency_keyboard,
    # Helper functions
    create_quick_reply_keyboard,
    hide_keyboard,
)

__version__ = "1.0.0"
__author__ = "Medicine Reminder Bot Team"

# Package metadata
__all__ = []

if _HELPERS_AVAILABLE:
    __all__ += [
        # From helpers
        "get_timezone",
        "now_in_timezone",
        "format_datetime_hebrew",
        "format_date_hebrew",
        "format_time_hebrew",
        "parse_time_string",
        "get_next_occurrence",
        "time_until",
        "validate_medicine_name",
        "validate_dosage",
        "validate_inventory_count",
        "validate_telegram_id",
        "validate_phone_number",
        "clean_text",
        "truncate_text",
        "format_list_hebrew",
        "extract_mentions",
        "mask_sensitive_data",
        "calculate_adherence_rate",
        "calculate_average_mood",
        "group_by_date",
        "calculate_streaks",
        "paginate_items",
        "format_medication_schedule",
        "format_inventory_status",
        "format_adherence_rate",
        "format_file_size",
        "safe_int",
        "safe_float",
        "safe_str",
        "async_retry",
        "async_batch_process",
        "generate_summary_stats",
        "create_progress_bar",
        "SimpleCache",
        "cache",
        "create_csv_content",
        "create_report_filename",
    ]

__all__ += [
    # From keyboards
    "get_main_menu_keyboard",
    "get_reminder_keyboard",
    "get_medicines_keyboard",
    "get_medicine_detail_keyboard",
    "get_settings_keyboard",
    "get_caregiver_keyboard",
    "get_symptoms_keyboard",
    "get_symptoms_medicine_picker",
    "get_reports_keyboard",
    "get_time_selection_keyboard",
    "get_inventory_update_keyboard",
    "get_confirmation_keyboard",
    "get_cancel_keyboard",
    "get_pagination_keyboard",
    "get_emergency_keyboard",
    "create_quick_reply_keyboard",
    "hide_keyboard",
]
