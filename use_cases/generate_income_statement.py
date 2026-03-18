"""
Use case for generating an income statement.

Orchestrates IncomeStatementService and renderers to produce
text/HTML/PDF output for a given fiscal period.
"""

from datetime import date, timedelta
from typing import Optional

from repositories.gnucash_repository import GnuCashRepository
from services.fx_rates import FxRates, MissingFxRateError
from services.income_statement import IncomeStatementResult, IncomeStatementService


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


class GenerateIncomeStatementUseCase:
    """Use case for generating an income statement report."""

    def __init__(self, repository: GnuCashRepository):
        self.repository = repository
        self.service = IncomeStatementService()

    def execute(
        self,
        start_date: date,
        end_date: date,
        fx_rates: Optional[FxRates] = None,
    ) -> IncomeStatementResult:
        """
        Generate income statement for the given date range.

        Args:
            start_date: First day of the period (inclusive)
            end_date: Last day of the period (inclusive)
            fx_rates: Optional FX rates for CAD conversion.
                      If provided, validates all currencies are covered before running.

        Returns:
            IncomeStatementResult

        Raises:
            MissingFxRateError: If fx_rates provided but a currency in the ledger has no rate
            ValueError: If start_date > end_date
        """
        if start_date > end_date:
            raise ValueError(
                f"start_date ({start_date}) must be on or before end_date ({end_date})"
            )

        root = self.repository.get_root_account()

        # Pre-validate FX coverage before doing any computation
        if fx_rates is not None:
            currencies = self.service.get_all_currencies(root, start_date, end_date)
            missing = fx_rates.missing_currencies(currencies)
            if missing:
                missing_list = ", ".join(sorted(missing))
                raise MissingFxRateError(
                    f"Missing FX rates for: {missing_list}. "
                    f"Add these currencies to your --fx-rates file."
                )

        return self.service.compute(root, start_date, end_date, fx_rates)
