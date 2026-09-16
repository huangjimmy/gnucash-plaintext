"""The first day of a fiscal year, from its last day."""

from datetime import date, timedelta


def fiscal_year_start(fiscal_year_end: date) -> date:
    """
    Compute fiscal year start from fiscal year end.

    Returns the same month/day one year earlier, plus one day.
    Examples:
        2024-12-31 → 2024-01-01
        2024-03-31 → 2023-04-01
        2024-02-29 → 2023-03-01 (Feb 29 falls back to Feb 28, then +1 day = Mar 1)
    """
    try:
        one_year_ago = date(fiscal_year_end.year - 1, fiscal_year_end.month, fiscal_year_end.day)
    except ValueError:
        # Feb 29 in a non-leap prior year: fall back to Feb 28
        one_year_ago = date(fiscal_year_end.year - 1, fiscal_year_end.month, fiscal_year_end.day - 1)
    return one_year_ago + timedelta(days=1)
