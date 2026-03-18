"""
Unit tests for IncomeStatementService and FxRates.

Uses temp_gnucash_for_close_books fixture (imported from plaintext).
All transactions are in 2024; tests verify balances within different date ranges.

Account structure and balances (full year 2024):
    Income:Salary:Base    (CAD)  6000  (Jan + Feb salaries)
    Income:Salary:Bonus   (CAD)  1000  (Mar bonus)
    Income:Interest       (CAD)   200  (Apr)
    Income:Freelance      (USD)   500  (Aug)
    Expenses:Travel:Train (CAD)   150  (May)
    Expenses:Travel:Flight(CAD)   800  (Jun)
    Expenses:Groceries    (CAD)   400  (Jul)
    Expenses:SaaS         (USD)   100  (Sep)

    CAD net income = 7200 - 1350 = 5850
    USD net income = 500 - 100 = 400
"""

from datetime import date
from fractions import Fraction

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _open_read_only(path):
    from gnucash import Session
    try:
        from gnucash import SessionOpenMode
        return Session(f"xml://{path}", SessionOpenMode.SESSION_READ_ONLY)
    except ImportError:
        return Session(f"xml://{path}", ignore_lock=True)


FULL_YEAR = (date(2024, 1, 1), date(2024, 12, 31))
H1 = (date(2024, 1, 1), date(2024, 6, 30))   # Jan–Jun
H2 = (date(2024, 7, 1), date(2024, 12, 31))  # Jul–Dec


# ---------------------------------------------------------------------------
# TestGetBalanceInRange
# ---------------------------------------------------------------------------

class TestGetBalanceInRange:

    def test_zero_before_period(self, temp_gnucash_for_close_books):
        from services.income_statement import IncomeStatementService
        session = _open_read_only(temp_gnucash_for_close_books)
        try:
            root = session.book.get_root_account()
            from infrastructure.gnucash.utils import find_account
            acc = find_account(root, "Income:Salary:Base")
            svc = IncomeStatementService()
            bal = svc.get_balance_in_range(acc, date(2023, 1, 1), date(2023, 12, 31))
            assert bal == Fraction(0)
        finally:
            session.end()

    def test_includes_transaction_on_start_date(self, temp_gnucash_for_close_books):
        """Transaction on Jan 31 is included when start = Jan 1."""
        from services.income_statement import IncomeStatementService
        session = _open_read_only(temp_gnucash_for_close_books)
        try:
            root = session.book.get_root_account()
            from infrastructure.gnucash.utils import find_account
            acc = find_account(root, "Income:Salary:Base")
            svc = IncomeStatementService()
            bal = svc.get_balance_in_range(acc, date(2024, 1, 31), date(2024, 1, 31))
            # Raw GnuCash value: income is credit = -3000
            assert bal == Fraction(-3000)
        finally:
            session.end()

    def test_excludes_transaction_before_start(self, temp_gnucash_for_close_books):
        """Jan transaction excluded when start = Feb 1."""
        from services.income_statement import IncomeStatementService
        session = _open_read_only(temp_gnucash_for_close_books)
        try:
            root = session.book.get_root_account()
            from infrastructure.gnucash.utils import find_account
            acc = find_account(root, "Income:Salary:Base")
            svc = IncomeStatementService()
            bal = svc.get_balance_in_range(acc, date(2024, 2, 1), date(2024, 12, 31))
            assert bal == Fraction(-3000)  # only Feb
        finally:
            session.end()

    def test_excludes_transaction_after_end(self, temp_gnucash_for_close_books):
        """Feb transaction excluded when end = Jan 31."""
        from services.income_statement import IncomeStatementService
        session = _open_read_only(temp_gnucash_for_close_books)
        try:
            root = session.book.get_root_account()
            from infrastructure.gnucash.utils import find_account
            acc = find_account(root, "Income:Salary:Base")
            svc = IncomeStatementService()
            bal = svc.get_balance_in_range(acc, date(2024, 1, 1), date(2024, 1, 31))
            assert bal == Fraction(-3000)  # only Jan
        finally:
            session.end()


# ---------------------------------------------------------------------------
# TestIncomeStatementCompute — CAD only
# ---------------------------------------------------------------------------

class TestIncomeStatementComputeCadOnly:

    def test_full_year_income_lines(self, temp_gnucash_for_close_books):
        """Full year: income section has 4 leaf accounts."""
        from services.income_statement import IncomeStatementService
        session = _open_read_only(temp_gnucash_for_close_books)
        try:
            root = session.book.get_root_account()
            svc = IncomeStatementService()
            result = svc.compute(root, *FULL_YEAR)
            # Income lines: Base, Bonus, Interest (CAD), Freelance (USD)
            assert len(result.income.lines) == 4
        finally:
            session.end()

    def test_full_year_income_cad_total(self, temp_gnucash_for_close_books):
        """Full year CAD income = 7200."""
        from services.income_statement import IncomeStatementService
        session = _open_read_only(temp_gnucash_for_close_books)
        try:
            root = session.book.get_root_account()
            svc = IncomeStatementService()
            result = svc.compute(root, *FULL_YEAR)
            assert result.income.currency_totals.get("CAD") == Fraction(7200)
        finally:
            session.end()

    def test_full_year_income_usd_total(self, temp_gnucash_for_close_books):
        """Full year USD income = 500."""
        from services.income_statement import IncomeStatementService
        session = _open_read_only(temp_gnucash_for_close_books)
        try:
            root = session.book.get_root_account()
            svc = IncomeStatementService()
            result = svc.compute(root, *FULL_YEAR)
            assert result.income.currency_totals.get("USD") == Fraction(500)
        finally:
            session.end()

    def test_full_year_expense_cad_total(self, temp_gnucash_for_close_books):
        """Full year CAD expenses = 1350."""
        from services.income_statement import IncomeStatementService
        session = _open_read_only(temp_gnucash_for_close_books)
        try:
            root = session.book.get_root_account()
            svc = IncomeStatementService()
            result = svc.compute(root, *FULL_YEAR)
            assert result.expenses.currency_totals.get("CAD") == Fraction(1350)
        finally:
            session.end()

    def test_full_year_net_cad(self, temp_gnucash_for_close_books):
        """CAD net income = 7200 - 1350 = 5850."""
        from services.income_statement import IncomeStatementService
        session = _open_read_only(temp_gnucash_for_close_books)
        try:
            root = session.book.get_root_account()
            svc = IncomeStatementService()
            result = svc.compute(root, *FULL_YEAR)
            assert result.net_currency_totals.get("CAD") == Fraction(5850)
        finally:
            session.end()

    def test_full_year_net_usd(self, temp_gnucash_for_close_books):
        """USD net income = 500 - 100 = 400."""
        from services.income_statement import IncomeStatementService
        session = _open_read_only(temp_gnucash_for_close_books)
        try:
            root = session.book.get_root_account()
            svc = IncomeStatementService()
            result = svc.compute(root, *FULL_YEAR)
            assert result.net_currency_totals.get("USD") == Fraction(400)
        finally:
            session.end()

    def test_no_cad_total_without_fx_rates(self, temp_gnucash_for_close_books):
        """Without FX rates, cad_total is None and fx_rates_provided is False."""
        from services.income_statement import IncomeStatementService
        session = _open_read_only(temp_gnucash_for_close_books)
        try:
            root = session.book.get_root_account()
            svc = IncomeStatementService()
            result = svc.compute(root, *FULL_YEAR)
            assert result.fx_rates_provided is False
            assert result.net_cad_total is None
            assert result.income.cad_total is None
            assert result.expenses.cad_total is None
        finally:
            session.end()

    def test_half_year_h1_excludes_h2_transactions(self, temp_gnucash_for_close_books):
        """H1 (Jan-Jun): groceries (Jul), SaaS (Sep), freelance (Aug) excluded."""
        from services.income_statement import IncomeStatementService
        session = _open_read_only(temp_gnucash_for_close_books)
        try:
            root = session.book.get_root_account()
            svc = IncomeStatementService()
            result = svc.compute(root, *H1)
            # H1 expenses: only Train (May=150) + Flight (Jun=800) = 950
            assert result.expenses.currency_totals.get("CAD") == Fraction(950)
            # H1 income: Salary Base (Jan+Feb=6000) + Bonus (Mar=1000) + Interest (Apr=200)
            assert result.income.currency_totals.get("CAD") == Fraction(7200)
            # No USD in H1 (freelance = Aug, SaaS = Sep)
            assert "USD" not in result.income.currency_totals
            assert "USD" not in result.expenses.currency_totals
        finally:
            session.end()

    def test_income_lines_show_positive_display_balance(self, temp_gnucash_for_close_books):
        """Income lines show positive balance (negated from GnuCash's credit convention)."""
        from services.income_statement import IncomeStatementService
        session = _open_read_only(temp_gnucash_for_close_books)
        try:
            root = session.book.get_root_account()
            svc = IncomeStatementService()
            result = svc.compute(root, *FULL_YEAR)
            for line in result.income.lines:
                assert line.balance > 0, f"Income line {line.path} has non-positive balance"
        finally:
            session.end()

    def test_expense_lines_show_positive_display_balance(self, temp_gnucash_for_close_books):
        """Expense lines show positive balance (debit convention, already positive)."""
        from services.income_statement import IncomeStatementService
        session = _open_read_only(temp_gnucash_for_close_books)
        try:
            root = session.book.get_root_account()
            svc = IncomeStatementService()
            result = svc.compute(root, *FULL_YEAR)
            for line in result.expenses.lines:
                assert line.balance > 0, f"Expense line {line.path} has non-positive balance"
        finally:
            session.end()


# ---------------------------------------------------------------------------
# TestIncomeStatementComputeWithFx
# ---------------------------------------------------------------------------

class TestIncomeStatementComputeWithFx:

    def _fx(self):
        from services.fx_rates import FxRates
        return FxRates({"USD": 1.35})  # 1 USD = 1.35 CAD

    def test_cad_total_income_with_fx(self, temp_gnucash_for_close_books):
        """Income CAD total = 7200 + 500*1.35 = 7875."""
        from services.income_statement import IncomeStatementService
        session = _open_read_only(temp_gnucash_for_close_books)
        try:
            root = session.book.get_root_account()
            svc = IncomeStatementService()
            result = svc.compute(root, *FULL_YEAR, fx_rates=self._fx())
            expected = Fraction(7200) + Fraction(500) * Fraction(135, 100)
            assert result.income.cad_total == expected
        finally:
            session.end()

    def test_cad_total_expenses_with_fx(self, temp_gnucash_for_close_books):
        """Expenses CAD total = 1350 + 100*1.35 = 1485."""
        from services.income_statement import IncomeStatementService
        session = _open_read_only(temp_gnucash_for_close_books)
        try:
            root = session.book.get_root_account()
            svc = IncomeStatementService()
            result = svc.compute(root, *FULL_YEAR, fx_rates=self._fx())
            expected = Fraction(1350) + Fraction(100) * Fraction(135, 100)
            assert result.expenses.cad_total == expected
        finally:
            session.end()

    def test_net_cad_total_with_fx(self, temp_gnucash_for_close_books):
        """Net CAD = income_cad - expense_cad = (7200+675) - (1350+135) = 6390."""
        from services.income_statement import IncomeStatementService
        session = _open_read_only(temp_gnucash_for_close_books)
        try:
            root = session.book.get_root_account()
            svc = IncomeStatementService()
            result = svc.compute(root, *FULL_YEAR, fx_rates=self._fx())
            assert result.fx_rates_provided is True
            income_cad = Fraction(7200) + Fraction(500) * Fraction(135, 100)
            expense_cad = Fraction(1350) + Fraction(100) * Fraction(135, 100)
            assert result.net_cad_total == income_cad - expense_cad
        finally:
            session.end()

    def test_each_line_has_cad_balance(self, temp_gnucash_for_close_books):
        """When FX rates provided, every line has a non-None cad_balance."""
        from services.income_statement import IncomeStatementService
        session = _open_read_only(temp_gnucash_for_close_books)
        try:
            root = session.book.get_root_account()
            svc = IncomeStatementService()
            result = svc.compute(root, *FULL_YEAR, fx_rates=self._fx())
            for line in result.income.lines + result.expenses.lines:
                assert line.cad_balance is not None, f"{line.path} missing cad_balance"
        finally:
            session.end()


# ---------------------------------------------------------------------------
# TestFxRates
# ---------------------------------------------------------------------------

class TestFxRates:

    def test_to_cad_known_currency(self):
        from services.fx_rates import FxRates
        fx = FxRates({"HKD": 0.172})
        result = fx.to_cad(Fraction(1000), "HKD")
        assert abs(float(result) - 172.0) < 0.01

    def test_to_cad_cad_is_one(self):
        from services.fx_rates import FxRates
        fx = FxRates({})
        assert fx.to_cad(Fraction(500), "CAD") == Fraction(500)

    def test_to_cad_missing_raises(self):
        from services.fx_rates import FxRates, MissingFxRateError
        fx = FxRates({"HKD": 0.172})
        with pytest.raises(MissingFxRateError, match="CNY"):
            fx.to_cad(Fraction(100), "CNY")

    def test_missing_currencies(self):
        from services.fx_rates import FxRates
        fx = FxRates({"HKD": 0.172, "USD": 1.35})
        missing = fx.missing_currencies({"HKD", "USD", "CNY", "JPY"})
        assert missing == {"CNY", "JPY"}

    def test_load_valid_yaml(self, tmp_path):
        from services.fx_rates import FxRates
        f = tmp_path / "rates.yaml"
        f.write_text("HKD: 0.172\nCNY: 0.185\n")
        fx = FxRates.load(str(f))
        assert fx.has_rate("HKD")
        assert fx.has_rate("CNY")
        assert fx.has_rate("CAD")  # always present

    def test_load_missing_file_raises(self, tmp_path):
        from services.fx_rates import FxRates
        with pytest.raises(FileNotFoundError):
            FxRates.load(str(tmp_path / "nonexistent.yaml"))

    def test_load_invalid_rate_raises(self, tmp_path):
        from services.fx_rates import FxRates
        f = tmp_path / "bad.yaml"
        f.write_text("HKD: -0.1\n")
        with pytest.raises(ValueError, match="positive"):
            FxRates.load(str(f))

    def test_load_non_numeric_raises(self, tmp_path):
        from services.fx_rates import FxRates
        f = tmp_path / "bad.yaml"
        f.write_text("HKD: not_a_number\n")
        with pytest.raises(ValueError):
            FxRates.load(str(f))


# ---------------------------------------------------------------------------
# TestFiscalYearStart
# ---------------------------------------------------------------------------

class TestFiscalYearStart:

    def test_calendar_year(self):
        from use_cases.generate_income_statement import fiscal_year_start
        assert fiscal_year_start(date(2024, 12, 31)) == date(2024, 1, 1)

    def test_march_fiscal_year(self):
        from use_cases.generate_income_statement import fiscal_year_start
        assert fiscal_year_start(date(2024, 3, 31)) == date(2023, 4, 1)

    def test_mid_year(self):
        from use_cases.generate_income_statement import fiscal_year_start
        assert fiscal_year_start(date(2024, 6, 30)) == date(2023, 7, 1)

    def test_leap_year_feb29(self):
        """Feb 29 fiscal year end: prior year has no Feb 29, falls back to Mar 1 start."""
        from use_cases.generate_income_statement import fiscal_year_start
        # 2024-02-29 → one year ago = 2023-02-28 (fallback) → +1 day = 2023-03-01
        assert fiscal_year_start(date(2024, 2, 29)) == date(2023, 3, 1)
