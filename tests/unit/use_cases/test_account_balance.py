"""
Unit tests for AccountBalanceUseCase.

Uses the temp_gnucash_account_balance fixture (loaded from
tests/fixtures/account_balance_test_data.txt) which covers all 5 account
types in two currencies with sub-accounts:

  Assets:Bank:Checking           CAD  3420.00  (500 + 3000 - 50 - 30)
  Assets:Bank:HKD                HKD  8700.00  (8000 + 400 + 600 - 300)
  Liabilities:CreditCard         CAD   200.00
  Liabilities:HKDLoan            HKD   500.00
  Equity:Opening                 CAD  (balancing)
  Income:Salary                  CAD -3000.00
  Income:HKDIncome:Freelance     HKD  -400.00
  Income:HKDIncome:Dividends     HKD  -600.00
  Expenses:Food:Groceries        CAD    50.00
  Expenses:Food:Dining           CAD    30.00
  Expenses:HKDExpenses:Transport HKD   300.00
"""

from datetime import date
from fractions import Fraction

import pytest


class TestAccountBalanceNoCurrency:
    """Without --fx-rates: each leaf account in its own currency."""

    def test_all_account_types_present(self, temp_gnucash_account_balance):
        from repositories.gnucash_repository import GnuCashRepository, SessionMode
        from use_cases.account_balance import AccountBalanceUseCase

        repo = GnuCashRepository(temp_gnucash_account_balance)
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            result = AccountBalanceUseCase(repo).execute(as_of=date(2024, 12, 31))
        finally:
            repo.close()

        paths = {b.account_path for b in result.balances}
        # Asset leafs
        assert "Assets:Bank:Checking" in paths
        assert "Assets:Bank:HKD" in paths
        # Liability leafs
        assert "Liabilities:CreditCard" in paths
        assert "Liabilities:HKDLoan" in paths
        # Equity
        assert "Equity:Opening" in paths
        # Income: HKDIncome has sub-accounts → only leaves appear
        assert "Income:Salary" in paths
        assert "Income:HKDIncome:Freelance" in paths
        assert "Income:HKDIncome:Dividends" in paths
        assert "Income:HKDIncome" not in paths
        # Expenses: Food has sub-accounts → only leaves appear
        assert "Expenses:Food:Groceries" in paths
        assert "Expenses:Food:Dining" in paths
        assert "Expenses:HKDExpenses:Transport" in paths
        assert "Expenses:Food" not in paths
        assert "Expenses:HKDExpenses" not in paths

    def test_checking_balance(self, temp_gnucash_account_balance):
        from repositories.gnucash_repository import GnuCashRepository, SessionMode
        from use_cases.account_balance import AccountBalanceUseCase

        repo = GnuCashRepository(temp_gnucash_account_balance)
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            result = AccountBalanceUseCase(repo).execute(as_of=date(2024, 12, 31))
        finally:
            repo.close()

        bal = next(b for b in result.balances if b.account_path == "Assets:Bank:Checking")
        assert bal.currency == "CAD"
        assert float(bal.amount) == pytest.approx(3420.00)

    def test_hkd_bank_balance(self, temp_gnucash_account_balance):
        from repositories.gnucash_repository import GnuCashRepository, SessionMode
        from use_cases.account_balance import AccountBalanceUseCase

        repo = GnuCashRepository(temp_gnucash_account_balance)
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            result = AccountBalanceUseCase(repo).execute(as_of=date(2024, 12, 31))
        finally:
            repo.close()

        bal = next(b for b in result.balances if b.account_path == "Assets:Bank:HKD")
        assert bal.currency == "HKD"
        assert float(bal.amount) == pytest.approx(8700.00)

    def test_expense_sub_accounts_reported_separately(self, temp_gnucash_account_balance):
        """Expenses:Food:Groceries and Expenses:Food:Dining are separate leaf entries."""
        from repositories.gnucash_repository import GnuCashRepository, SessionMode
        from use_cases.account_balance import AccountBalanceUseCase

        repo = GnuCashRepository(temp_gnucash_account_balance)
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            result = AccountBalanceUseCase(repo).execute(as_of=date(2024, 12, 31))
        finally:
            repo.close()

        groceries = next(b for b in result.balances if b.account_path == "Expenses:Food:Groceries")
        dining = next(b for b in result.balances if b.account_path == "Expenses:Food:Dining")
        assert float(groceries.amount) == pytest.approx(50.00)
        assert float(dining.amount) == pytest.approx(30.00)

    def test_income_sub_accounts_reported_separately(self, temp_gnucash_account_balance):
        """Income:HKDIncome:Freelance and Dividends are separate leaf entries."""
        from repositories.gnucash_repository import GnuCashRepository, SessionMode
        from use_cases.account_balance import AccountBalanceUseCase

        repo = GnuCashRepository(temp_gnucash_account_balance)
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            result = AccountBalanceUseCase(repo).execute(as_of=date(2024, 12, 31))
        finally:
            repo.close()

        freelance = next(b for b in result.balances if b.account_path == "Income:HKDIncome:Freelance")
        dividends = next(b for b in result.balances if b.account_path == "Income:HKDIncome:Dividends")
        # Income accounts have credit-normal sign in GnuCash
        assert float(freelance.amount) == pytest.approx(-400.00)
        assert float(dividends.amount) == pytest.approx(-600.00)

    def test_account_prefix_assets_bank(self, temp_gnucash_account_balance):
        from repositories.gnucash_repository import GnuCashRepository, SessionMode
        from use_cases.account_balance import AccountBalanceUseCase

        repo = GnuCashRepository(temp_gnucash_account_balance)
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            result = AccountBalanceUseCase(repo).execute(
                as_of=date(2024, 12, 31), account_prefix="Assets:Bank"
            )
        finally:
            repo.close()

        paths = {b.account_path for b in result.balances}
        assert paths == {"Assets:Bank:Checking", "Assets:Bank:HKD"}

    def test_account_prefix_expenses_food(self, temp_gnucash_account_balance):
        """Filtering to Expenses:Food returns its two leaf sub-accounts."""
        from repositories.gnucash_repository import GnuCashRepository, SessionMode
        from use_cases.account_balance import AccountBalanceUseCase

        repo = GnuCashRepository(temp_gnucash_account_balance)
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            result = AccountBalanceUseCase(repo).execute(
                as_of=date(2024, 12, 31), account_prefix="Expenses:Food"
            )
        finally:
            repo.close()

        paths = {b.account_path for b in result.balances}
        assert paths == {"Expenses:Food:Groceries", "Expenses:Food:Dining"}

    def test_as_of_before_june_activity(self, temp_gnucash_account_balance):
        """Balance as of 2024-01-31 excludes the June transactions."""
        from repositories.gnucash_repository import GnuCashRepository, SessionMode
        from use_cases.account_balance import AccountBalanceUseCase

        repo = GnuCashRepository(temp_gnucash_account_balance)
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            result = AccountBalanceUseCase(repo).execute(
                as_of=date(2024, 1, 31), account_prefix="Assets:Bank"
            )
        finally:
            repo.close()

        checking = next(b for b in result.balances if b.account_path == "Assets:Bank:Checking")
        # Only opening balance of 500, no salary yet
        assert float(checking.amount) == pytest.approx(500.00)

    def test_no_consolidated_cad_without_fx_rates(self, temp_gnucash_account_balance):
        from repositories.gnucash_repository import GnuCashRepository, SessionMode
        from use_cases.account_balance import AccountBalanceUseCase

        repo = GnuCashRepository(temp_gnucash_account_balance)
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            result = AccountBalanceUseCase(repo).execute(as_of=date(2024, 12, 31))
        finally:
            repo.close()

        assert result.consolidated_cad is None


class TestAccountBalanceWithFxRates:
    """With --fx-rates: all amounts converted to CAD."""

    def test_all_balances_in_cad(self, temp_gnucash_account_balance, tmp_path):
        from repositories.gnucash_repository import GnuCashRepository, SessionMode
        from services.fx_rates import FxRates
        from use_cases.account_balance import AccountBalanceUseCase

        rates_file = tmp_path / "rates.yaml"
        rates_file.write_text("HKD: 0.17\n")
        fx_rates = FxRates.load(str(rates_file))

        repo = GnuCashRepository(temp_gnucash_account_balance)
        repo.open(mode=SessionMode.NORMAL)
        try:
            result = AccountBalanceUseCase(repo).execute(
                as_of=date(2024, 12, 31),
                account_prefix="Assets:Bank",
                fx_rates=fx_rates,
            )
        finally:
            repo.close()

        for bal in result.balances:
            assert bal.currency == "CAD", f"Expected CAD, got {bal.currency} for {bal.account_path}"

    def test_consolidated_cad_assets_bank(self, temp_gnucash_account_balance, tmp_path):
        """Assets:Bank total: 3420 CAD + 8700 HKD * 0.17 = 3420 + 1479 = 4899 CAD."""
        from repositories.gnucash_repository import GnuCashRepository, SessionMode
        from services.fx_rates import FxRates
        from use_cases.account_balance import AccountBalanceUseCase

        rates_file = tmp_path / "rates.yaml"
        rates_file.write_text("HKD: 0.17\n")
        fx_rates = FxRates.load(str(rates_file))

        repo = GnuCashRepository(temp_gnucash_account_balance)
        repo.open(mode=SessionMode.NORMAL)
        try:
            result = AccountBalanceUseCase(repo).execute(
                as_of=date(2024, 12, 31),
                account_prefix="Assets:Bank",
                fx_rates=fx_rates,
            )
        finally:
            repo.close()

        assert result.consolidated_cad is not None
        hkd_rate = Fraction("0.17").limit_denominator(1_000_000)
        expected = Fraction(3420) + Fraction(8700) * hkd_rate
        assert abs(float(result.consolidated_cad) - float(expected)) < 0.01
