"""
Unit tests for helper functions
Tests the utility functions in utils/helpers.py
"""

import pytest
from datetime import datetime, time, date, timedelta
import pytz

from utils.helpers import (
    validate_medicine_name,
    validate_dosage,
    validate_inventory_count,
    validate_telegram_id,
    validate_phone_number,
    parse_time_string,
    format_datetime_hebrew,
    format_date_hebrew,
    format_time_hebrew,
    get_next_occurrence,
    time_until,
    clean_text,
    truncate_text,
    format_list_hebrew,
    calculate_adherence_rate,
    calculate_average_mood,
    group_by_date,
    calculate_streaks,
    paginate_items,
    format_medication_schedule,
    format_inventory_status,
    format_adherence_rate,
    safe_int,
    safe_float,
    safe_str,
    create_progress_bar,
    SimpleCache,
)


class TestValidationFunctions:
    """Test validation utility functions"""

    def test_validate_medicine_name(self):
        """Test medicine name validation"""
        # Valid names
        assert validate_medicine_name("אקמול")[0] == True
        assert validate_medicine_name("Paracetamol")[0] == True
        assert validate_medicine_name('אקמול 500 מ"ג')[0] == True
        assert validate_medicine_name("Vitamin D-3")[0] == True

        # Invalid names
        assert validate_medicine_name("")[0] == False
        assert validate_medicine_name(" ")[0] == False
        assert validate_medicine_name("א")[0] == False  # Too short
        assert validate_medicine_name("a" * 201)[0] == False  # Too long
        assert validate_medicine_name("medicine@#$%")[0] == False  # Invalid chars

    def test_validate_dosage(self):
        """Test dosage validation"""
        # Valid dosages
        assert validate_dosage('500 מ"ג')[0] == True
        assert validate_dosage("1 כדור")[0] == True
        assert validate_dosage("כפית")[0] == True
        assert validate_dosage("2 טיפות")[0] == True

        # Invalid dosages
        assert validate_dosage("")[0] == False
        assert validate_dosage(" ")[0] == False
        assert validate_dosage("a" * 101)[0] == False  # Too long

    def test_validate_inventory_count(self):
        """Test inventory count validation"""
        # Valid counts
        valid, _, count = validate_inventory_count("30")
        assert valid == True
        assert count == 30.0

        valid, _, count = validate_inventory_count("15.5")
        assert valid == True
        assert count == 15.5

        valid, _, count = validate_inventory_count("אפס")
        assert valid == True
        assert count == 0.0

        valid, _, count = validate_inventory_count("עשרה")
        assert valid == True
        assert count == 10.0

        # Invalid counts
        assert validate_inventory_count("-5")[0] == False  # Negative
        assert validate_inventory_count("10000")[0] == False  # Too large
        assert validate_inventory_count("abc")[0] == False  # Not a number
        assert validate_inventory_count("")[0] == False  # Empty

    def test_validate_telegram_id(self):
        """Test Telegram ID validation"""
        # Valid IDs
        assert validate_telegram_id("123456789")[0] == True
        assert validate_telegram_id(123456789)[0] == True
        assert validate_telegram_id("1234567890")[0] == True

        # Invalid IDs
        assert validate_telegram_id("0")[0] == False  # Too short
        assert validate_telegram_id("-123")[0] == False  # Negative
        assert validate_telegram_id("abc")[0] == False  # Not a number
        assert validate_telegram_id("12345678901234567")[0] == False  # Too long

    def test_validate_phone_number(self):
        """Test Israeli phone number validation"""
        # Valid numbers
        assert validate_phone_number("0501234567")[0] == True
        assert validate_phone_number("050-123-4567")[0] == True
        assert validate_phone_number("050 123 4567")[0] == True
        assert validate_phone_number("+972501234567")[0] == True
        assert validate_phone_number("021234567")[0] == True  # Landline
        assert validate_phone_number("+97221234567")[0] == True

        # Invalid numbers
        assert validate_phone_number("")[0] == False
        assert validate_phone_number("123")[0] == False  # Too short
        assert validate_phone_number("0601234567")[0] == False  # Invalid prefix
        assert validate_phone_number("abc123def")[0] == False  # Letters


class TestTimeAndDateFunctions:
    """Test time and date utility functions"""

    def test_parse_time_string(self):
        """Test time string parsing"""
        # Valid formats
        assert parse_time_string("08:30") == time(8, 30)
        assert parse_time_string("14:15") == time(14, 15)
        assert parse_time_string("8:30") == time(8, 30)
        assert parse_time_string("08.30") == time(8, 30)
        assert parse_time_string("08-30") == time(8, 30)
        assert parse_time_string("08 : 30") == time(8, 30)
        assert parse_time_string("0830") == time(8, 30)

        # Invalid formats
        assert parse_time_string("25:30") == None  # Invalid hour
        assert parse_time_string("08:60") == None  # Invalid minute
        assert parse_time_string("abc") == None  # Not a time
        assert parse_time_string("") == None  # Empty

    def test_format_datetime_hebrew(self):
        """Test Hebrew datetime formatting"""
        dt = datetime(2024, 1, 15, 14, 30, 0)  # Monday
        formatted = format_datetime_hebrew(dt)

        assert "יום שני" in formatted
        assert "ינואר" in formatted
        assert "2024" in formatted
        assert "14:30" in formatted

    def test_format_date_hebrew(self):
        """Test Hebrew date formatting"""
        d = date(2024, 1, 15)  # Monday
        formatted = format_date_hebrew(d)

        assert "יום שני" in formatted
        assert "ינואר" in formatted
        assert "2024" in formatted

    def test_format_time_hebrew(self):
        """Test Hebrew time formatting"""
        t = time(14, 30)
        formatted = format_time_hebrew(t)

        assert formatted == "14:30"

    def test_get_next_occurrence(self):
        """Test getting next occurrence of a time"""
        target_time = time(14, 30)
        next_occurrence = get_next_occurrence(target_time)

        # Should be today or tomorrow at 14:30
        assert next_occurrence.time() == target_time
        assert next_occurrence.date() >= date.today()

    def test_time_until(self):
        """Test time until calculation"""
        # Test future time
        future_time = datetime.now() + timedelta(hours=2, minutes=30)
        result = time_until(future_time)
        assert "שעות" in result and "דקות" in result

        # Test past time
        past_time = datetime.now() - timedelta(hours=1)
        result = time_until(past_time)
        assert result == "עבר"


class TestTextProcessingFunctions:
    """Test text processing utility functions"""

    def test_clean_text(self):
        """Test text cleaning"""
        # Test whitespace cleanup
        assert clean_text("  hello   world  ") == "hello world"

        # Test max length
        assert clean_text("a" * 50, max_length=10) == "aaaaaaaaaa..."

        # Test empty text
        assert clean_text("") == ""
        assert clean_text(None) == ""

    def test_truncate_text(self):
        """Test text truncation"""
        text = "This is a long text that needs to be truncated"

        assert truncate_text(text, 20) == "This is a long te..."
        assert truncate_text(text, 100) == text  # No truncation needed
        assert truncate_text("", 10) == ""

    def test_format_list_hebrew(self):
        """Test Hebrew list formatting"""
        # Test various list sizes
        assert format_list_hebrew([]) == ""
        assert format_list_hebrew(["אחד"]) == "אחד"
        assert format_list_hebrew(["אחד", "שניים"]) == "אחד ושניים"
        assert format_list_hebrew(["אחד", "שניים", "שלושה"]) == "אחד, שניים ושלושה"

        # Test custom conjunction
        assert format_list_hebrew(["א", "ב"], "או") == "א או ב"


class TestDataProcessingFunctions:
    """Test data processing utility functions"""

    def test_calculate_adherence_rate(self):
        """Test adherence rate calculation"""
        assert calculate_adherence_rate(9, 10) == 90.0
        assert calculate_adherence_rate(5, 10) == 50.0
        assert calculate_adherence_rate(0, 10) == 0.0
        assert calculate_adherence_rate(0, 0) == 0.0  # Edge case

    def test_calculate_average_mood(self):
        """Test average mood calculation"""
        assert calculate_average_mood([1, 2, 3, 4, 5]) == 3.0
        assert calculate_average_mood([8, 9, 10]) == 9.0
        assert calculate_average_mood([]) == 0.0
        assert calculate_average_mood([15, -1, 5]) == 5.0  # Filters invalid scores

    def test_calculate_streaks(self):
        """Test streak calculation"""
        # Test empty list
        result = calculate_streaks([])
        assert result["current"] == 0
        assert result["longest"] == 0

        # Test consecutive dates
        dates = [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)]
        result = calculate_streaks(dates)
        assert result["longest"] == 3

        # Test non-consecutive dates
        dates = [date(2024, 1, 1), date(2024, 1, 3), date(2024, 1, 4)]  # Gap
        result = calculate_streaks(dates)
        assert result["longest"] == 2

    def test_paginate_items(self):
        """Test pagination"""
        items = list(range(25))  # 0-24

        # First page
        page_items, total_pages, has_more = paginate_items(items, 1, 10)
        assert len(page_items) == 10
        assert page_items == list(range(10))
        assert total_pages == 3
        assert has_more == True

        # Last page
        page_items, total_pages, has_more = paginate_items(items, 3, 10)
        assert len(page_items) == 5
        assert page_items == list(range(20, 25))
        assert total_pages == 3
        assert has_more == False


class TestFormattingFunctions:
    """Test formatting utility functions"""

    def test_format_medication_schedule(self):
        """Test medication schedule formatting"""
        schedules = [time(8, 0), time(14, 30), time(20, 0)]
        result = format_medication_schedule(schedules)
        assert "08:00" in result
        assert "14:30" in result
        assert "20:00" in result

        # Test empty schedule
        assert format_medication_schedule([]) == "לא מוגדר"

    def test_format_inventory_status(self):
        """Test inventory status formatting"""
        # Empty inventory
        result = format_inventory_status(0, 5)
        assert "❌" in result
        assert "נגמר" in result

        # Low inventory
        result = format_inventory_status(3, 5)
        assert "⚠️" in result
        assert "מלאי נמוך" in result

        # Good inventory
        result = format_inventory_status(10, 5)
        assert "✅" in result

    def test_format_adherence_rate(self):
        """Test adherence rate formatting"""
        # Excellent
        result = format_adherence_rate(95.0)
        assert "🟢" in result
        assert "מצוין" in result

        # Good
        result = format_adherence_rate(85.0)
        assert "🟡" in result
        assert "טוב" in result

        # Poor
        result = format_adherence_rate(60.0)
        assert "🔴" in result
        assert "נמוך" in result

    def test_create_progress_bar(self):
        """Test progress bar creation"""
        # Half progress
        result = create_progress_bar(5, 10, 10)
        assert "█" in result
        assert "░" in result
        assert "50.0%" in result

        # Full progress
        result = create_progress_bar(10, 10, 10)
        assert result.count("█") == 10
        assert "100.0%" in result

        # Empty progress
        result = create_progress_bar(0, 10, 10)
        assert result.count("░") == 10
        assert "0.0%" in result


class TestSafeConversionFunctions:
    """Test safe conversion utility functions"""

    def test_safe_int(self):
        """Test safe integer conversion"""
        assert safe_int("123") == 123
        assert safe_int("abc", 0) == 0
        assert safe_int(None, -1) == -1
        assert safe_int(12.5) == 12

    def test_safe_float(self):
        """Test safe float conversion"""
        assert safe_float("123.45") == 123.45
        assert safe_float("abc", 0.0) == 0.0
        assert safe_float(None, -1.0) == -1.0
        assert safe_float(12) == 12.0

    def test_safe_str(self):
        """Test safe string conversion"""
        assert safe_str(123) == "123"
        assert safe_str(None, "default") == "default"
        assert safe_str("text") == "text"


class TestCacheUtilities:
    """Test cache utility functions"""

    def test_simple_cache(self):
        """Test SimpleCache functionality"""
        cache = SimpleCache(default_ttl=1)  # 1 second TTL

        # Test set and get
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

        # Test non-existent key
        assert cache.get("non_existent") == None

        # Test TTL expiration
        import time

        cache.set("key2", "value2", ttl=1)
        time.sleep(1.1)  # Wait for expiration
        assert cache.get("key2") == None

        # Test removal
        cache.set("key3", "value3")
        assert cache.remove("key3") == True
        assert cache.get("key3") == None
        assert cache.remove("non_existent") == False

        # Test clear
        cache.set("key4", "value4")
        cache.clear()
        assert cache.get("key4") == None


class TestGroupByDate:
    """Test group_by_date function with mock objects"""

    def test_group_by_date(self):
        """Test grouping items by date field"""

        # Create mock objects with date attributes
        class MockItem:
            def __init__(self, date_val):
                self.created_at = date_val

        items = [
            MockItem(date(2024, 1, 1)),
            MockItem(date(2024, 1, 1)),
            MockItem(date(2024, 1, 2)),
        ]

        grouped = group_by_date(items, "created_at")

        assert len(grouped) == 2
        assert len(grouped[date(2024, 1, 1)]) == 2
        assert len(grouped[date(2024, 1, 2)]) == 1


# ============================================================================
# Integration Test Examples
# ============================================================================


class TestIntegrationExamples:
    """Example integration tests"""

    @pytest.mark.asyncio
    async def test_medicine_name_validation_flow(self):
        """Test complete medicine name validation flow"""
        # Test the complete flow of validating a medicine name
        test_names = [("אקמול", True), ("", False), ("Paracetamol 500mg", True), ("a" * 201, False)]

        for name, expected_valid in test_names:
            is_valid, error_msg = validate_medicine_name(name)
            assert is_valid == expected_valid
            if not expected_valid:
                assert error_msg != ""

    def test_time_parsing_and_formatting_flow(self):
        """Test complete time parsing and formatting flow"""
        time_strings = ["08:30", "14:15", "20:00"]

        parsed_times = []
        for time_str in time_strings:
            parsed_time = parse_time_string(time_str)
            assert parsed_time is not None
            parsed_times.append(parsed_time)

        # Format the schedule
        formatted = format_medication_schedule(parsed_times)
        assert "08:30" in formatted
        assert "14:15" in formatted
        assert "20:00" in formatted


# ============================================================================
# Fixtures for testing
# ============================================================================


@pytest.fixture
def sample_dates():
    """Provide sample dates for testing"""
    return [
        date(2024, 1, 1),
        date(2024, 1, 2),
        date(2024, 1, 3),
        date(2024, 1, 5),  # Gap
        date(2024, 1, 6),
    ]


@pytest.fixture
def sample_times():
    """Provide sample times for testing"""
    return [time(8, 0), time(14, 30), time(20, 0)]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
