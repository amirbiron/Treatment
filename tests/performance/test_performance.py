import pytest
from datetime import date

from utils.helpers import format_list_hebrew, group_by_date


class TestPerformance:
    """Performance tests for helper functions"""

    def test_large_list_formatting_performance(self, benchmark):
        """Benchmark large list formatting"""
        large_list = [f"item_{i}" for i in range(1000)]

        result = benchmark(format_list_hebrew, large_list)
        assert len(result) > 0

    def test_date_grouping_performance(self, benchmark):
        """Benchmark date grouping with large dataset"""

        class MockItem:
            def __init__(self, date_val):
                self.date_field = date_val

        # Create 10000 items with periodic dates
        items = [MockItem(date(2024, 1, (i % 30) + 1)) for i in range(10000)]

        result = benchmark(group_by_date, items, "date_field")
        assert len(result) <= 30  # Max 30 days in January
