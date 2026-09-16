"""The first day of a fiscal year, from its last day."""

from datetime import date

from services.fiscal_year import fiscal_year_start


class TestFiscalYearStart:

    def test_calendar_year(self):
        assert fiscal_year_start(date(2024, 12, 31)) == date(2024, 1, 1)

    def test_march_fiscal_year(self):
        assert fiscal_year_start(date(2024, 3, 31)) == date(2023, 4, 1)

    def test_mid_year(self):
        assert fiscal_year_start(date(2024, 6, 30)) == date(2023, 7, 1)

    def test_leap_year_feb29(self):
        """Feb 29 fiscal year end: prior year has no Feb 29, falls back to Mar 1 start."""
        # 2024-02-29 → one year ago = 2023-02-28 (fallback) → +1 day = 2023-03-01
        assert fiscal_year_start(date(2024, 2, 29)) == date(2023, 3, 1)
