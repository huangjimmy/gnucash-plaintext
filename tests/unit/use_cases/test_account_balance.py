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

Recursive parent balances (single-currency subtrees, no FX needed):
  Expenses:Food           CAD  80.00  (Groceries + Dining)
  Income:HKDIncome        HKD -1000.00  (Freelance + Dividends)
"""

from datetime import date
from fractions import Fraction

import pytest


def _open_repo(path, mode=None):
    from repositories.gnucash_repository import GnuCashRepository, SessionMode
    repo = GnuCashRepository(path)
    repo.open(mode=mode or SessionMode.READ_ONLY)
    return repo


def _exec(repo, **kwargs):
    from use_cases.account_balance import AccountBalanceUseCase
    return AccountBalanceUseCase(repo).execute(**kwargs)


# ---------------------------------------------------------------------------
# No prefix: all accounts with recursive totals
# ---------------------------------------------------------------------------

class TestAccountBalanceNoPrefix:
    """No account_prefix: all accounts, each with recursive cumulative balance."""

    def test_mixed_currency_without_fx_raises_error(self, temp_gnucash_account_balance):
        """Whole-book export errors when mixed-currency accounts exist and no FX rates."""
        from services.fx_rates import MissingFxRateError
        repo = _open_repo(temp_gnucash_account_balance)
        try:
            with pytest.raises(MissingFxRateError):
                _exec(repo, as_of=date(2024, 12, 31))
        finally:
            repo.close()

    def test_all_accounts_shown_with_fx(self, temp_gnucash_account_balance, tmp_path):
        """With FX rates, all accounts (parent + leaf) appear in output."""
        from repositories.gnucash_repository import SessionMode
        from services.fx_rates import FxRates

        rates_file = tmp_path / "rates.yaml"
        rates_file.write_text("HKD: 0.17\n")
        fx_rates = FxRates.load(str(rates_file))

        repo = _open_repo(temp_gnucash_account_balance, SessionMode.NORMAL)
        try:
            result = _exec(repo, as_of=date(2024, 12, 31), fx_rates=fx_rates)
        finally:
            repo.close()

        paths = {b.account_path for b in result.balances}
        # Parent accounts
        assert "Assets" in paths
        assert "Assets:Bank" in paths
        assert "Liabilities" in paths
        assert "Income" in paths
        assert "Income:HKDIncome" in paths
        assert "Expenses" in paths
        assert "Expenses:Food" in paths
        assert "Expenses:HKDExpenses" in paths
        # Leaf accounts
        assert "Assets:Bank:Checking" in paths
        assert "Assets:Bank:HKD" in paths
        assert "Expenses:Food:Groceries" in paths
        assert "Expenses:Food:Dining" in paths

    def test_all_balances_in_cad_with_fx(self, temp_gnucash_account_balance, tmp_path):
        """With FX rates, every account balance is reported in CAD."""
        from repositories.gnucash_repository import SessionMode
        from services.fx_rates import FxRates

        rates_file = tmp_path / "rates.yaml"
        rates_file.write_text("HKD: 0.17\n")
        fx_rates = FxRates.load(str(rates_file))

        repo = _open_repo(temp_gnucash_account_balance, SessionMode.NORMAL)
        try:
            result = _exec(repo, as_of=date(2024, 12, 31), fx_rates=fx_rates)
        finally:
            repo.close()

        for bal in result.balances:
            assert bal.currency == "CAD", (
                f"Expected CAD, got {bal.currency} for {bal.account_path}"
            )


# ---------------------------------------------------------------------------
# With prefix (no --with-children): single account, recursive total
# ---------------------------------------------------------------------------

class TestAccountBalanceWithPrefix:
    """account_prefix given, include_children=False (default): one account with recursive total."""

    def test_single_cad_leaf(self, temp_gnucash_account_balance):
        """Single CAD leaf: balance equals its direct splits."""
        repo = _open_repo(temp_gnucash_account_balance)
        try:
            result = _exec(repo, as_of=date(2024, 12, 31),
                           account_prefix="Assets:Bank:Checking")
        finally:
            repo.close()

        assert len(result.balances) == 1
        bal = result.balances[0]
        assert bal.account_path == "Assets:Bank:Checking"
        assert bal.currency == "CAD"
        assert bal.amount == Fraction(3420)

    def test_single_hkd_leaf(self, temp_gnucash_account_balance):
        """Single HKD leaf: balance in HKD."""
        repo = _open_repo(temp_gnucash_account_balance)
        try:
            result = _exec(repo, as_of=date(2024, 12, 31),
                           account_prefix="Assets:Bank:HKD")
        finally:
            repo.close()

        assert len(result.balances) == 1
        bal = result.balances[0]
        assert bal.account_path == "Assets:Bank:HKD"
        assert bal.currency == "HKD"
        assert bal.amount == Fraction(8700)

    def test_parent_single_currency_recursive_total(self, temp_gnucash_account_balance):
        """Expenses:Food (all CAD) shows recursive sum of Groceries + Dining."""
        repo = _open_repo(temp_gnucash_account_balance)
        try:
            result = _exec(repo, as_of=date(2024, 12, 31),
                           account_prefix="Expenses:Food")
        finally:
            repo.close()

        assert len(result.balances) == 1
        bal = result.balances[0]
        assert bal.account_path == "Expenses:Food"
        assert bal.currency == "CAD"
        assert bal.amount == Fraction(80)   # 50 + 30

    def test_parent_single_currency_hkd(self, temp_gnucash_account_balance):
        """Income:HKDIncome (all HKD) shows recursive sum of sub-accounts."""
        repo = _open_repo(temp_gnucash_account_balance)
        try:
            result = _exec(repo, as_of=date(2024, 12, 31),
                           account_prefix="Income:HKDIncome")
        finally:
            repo.close()

        assert len(result.balances) == 1
        bal = result.balances[0]
        assert bal.account_path == "Income:HKDIncome"
        assert bal.currency == "HKD"
        # Income accounts: -400 (Freelance) + -600 (Dividends) = -1000
        assert bal.amount == Fraction(-1000)

    def test_nonexistent_prefix_raises_value_error(self, temp_gnucash_account_balance):
        """Typo in account prefix should raise ValueError, not return empty result."""
        repo = _open_repo(temp_gnucash_account_balance)
        try:
            with pytest.raises(ValueError, match="not found"):
                _exec(repo, as_of=date(2024, 12, 31), account_prefix="Asset:Bank")
        finally:
            repo.close()

    def test_mixed_currency_parent_requires_fx(self, temp_gnucash_account_balance):
        """Assets:Bank has CAD + HKD children: raises error without FX rates."""
        from services.fx_rates import MissingFxRateError
        repo = _open_repo(temp_gnucash_account_balance)
        try:
            with pytest.raises(MissingFxRateError):
                _exec(repo, as_of=date(2024, 12, 31), account_prefix="Assets:Bank")
        finally:
            repo.close()

    def test_mixed_currency_parent_with_fx(self, temp_gnucash_account_balance, tmp_path):
        """Assets:Bank with FX: recursive CAD total = 3420 + 8700*0.17 = 4899."""
        from repositories.gnucash_repository import SessionMode
        from services.fx_rates import FxRates

        rates_file = tmp_path / "rates.yaml"
        rates_file.write_text("HKD: 0.17\n")
        fx_rates = FxRates.load(str(rates_file))

        repo = _open_repo(temp_gnucash_account_balance, SessionMode.NORMAL)
        try:
            result = _exec(repo, as_of=date(2024, 12, 31),
                           account_prefix="Assets:Bank", fx_rates=fx_rates)
        finally:
            repo.close()

        assert len(result.balances) == 1
        bal = result.balances[0]
        assert bal.account_path == "Assets:Bank"
        assert bal.currency == "CAD"
        # 3420 CAD + 8700 HKD at 0.17 — exactly, since a rate is a ratio and
        # 0.17 is 17/100, not the double nearest to it.
        assert bal.amount == Fraction(3420) + Fraction(8700) * Fraction(17, 100)

    def test_as_of_date_cutoff(self, temp_gnucash_account_balance):
        """Balance as of 2024-01-31 excludes June transactions."""
        repo = _open_repo(temp_gnucash_account_balance)
        try:
            result = _exec(repo, as_of=date(2024, 1, 31),
                           account_prefix="Assets:Bank:Checking")
        finally:
            repo.close()

        assert result.balances[0].amount == Fraction(500)

    def test_no_consolidated_cad_without_fx(self, temp_gnucash_account_balance):
        """consolidated_cad is None when no fx_rates provided."""
        repo = _open_repo(temp_gnucash_account_balance)
        try:
            result = _exec(repo, as_of=date(2024, 12, 31),
                           account_prefix="Expenses:Food")
        finally:
            repo.close()

        assert result.consolidated_cad is None

    def test_consolidated_cad_equals_account_balance(self, temp_gnucash_account_balance, tmp_path):
        """consolidated_cad equals the matched account's recursive CAD balance."""
        from repositories.gnucash_repository import SessionMode
        from services.fx_rates import FxRates

        rates_file = tmp_path / "rates.yaml"
        rates_file.write_text("HKD: 0.17\n")
        fx_rates = FxRates.load(str(rates_file))

        repo = _open_repo(temp_gnucash_account_balance, SessionMode.NORMAL)
        try:
            result = _exec(repo, as_of=date(2024, 12, 31),
                           account_prefix="Assets:Bank", fx_rates=fx_rates)
        finally:
            repo.close()

        assert result.consolidated_cad is not None
        expected = Fraction(3420) + Fraction(8700) * Fraction(17, 100)
        assert result.consolidated_cad == expected


# ---------------------------------------------------------------------------
# With prefix + include_children=True (--with-children)
# ---------------------------------------------------------------------------

class TestAccountBalanceWithChildren:
    """account_prefix + include_children=True: matched account + all sub-accounts."""

    def test_expenses_food_subtree(self, temp_gnucash_account_balance):
        """Expenses:Food with children: shows Food, Groceries, Dining (all CAD)."""
        repo = _open_repo(temp_gnucash_account_balance)
        try:
            result = _exec(repo, as_of=date(2024, 12, 31),
                           account_prefix="Expenses:Food", include_children=True)
        finally:
            repo.close()

        paths = {b.account_path for b in result.balances}
        assert paths == {"Expenses:Food", "Expenses:Food:Groceries", "Expenses:Food:Dining"}

    def test_parent_recursive_total_with_children(self, temp_gnucash_account_balance):
        """Expenses:Food balance = Groceries + Dining = 80 CAD."""
        repo = _open_repo(temp_gnucash_account_balance)
        try:
            result = _exec(repo, as_of=date(2024, 12, 31),
                           account_prefix="Expenses:Food", include_children=True)
        finally:
            repo.close()

        food = next(b for b in result.balances if b.account_path == "Expenses:Food")
        groceries = next(b for b in result.balances if b.account_path == "Expenses:Food:Groceries")
        dining = next(b for b in result.balances if b.account_path == "Expenses:Food:Dining")
        assert food.amount == Fraction(80)
        assert groceries.amount == Fraction(50)
        assert dining.amount == Fraction(30)

    def test_assets_bank_with_fx_and_children(self, temp_gnucash_account_balance, tmp_path):
        """Assets:Bank with FX + children: bank total + each sub-account in CAD."""
        from repositories.gnucash_repository import SessionMode
        from services.fx_rates import FxRates

        rates_file = tmp_path / "rates.yaml"
        rates_file.write_text("HKD: 0.17\n")
        fx_rates = FxRates.load(str(rates_file))

        repo = _open_repo(temp_gnucash_account_balance, SessionMode.NORMAL)
        try:
            result = _exec(repo, as_of=date(2024, 12, 31),
                           account_prefix="Assets:Bank", fx_rates=fx_rates,
                           include_children=True)
        finally:
            repo.close()

        paths = {b.account_path for b in result.balances}
        assert paths == {"Assets:Bank", "Assets:Bank:Checking", "Assets:Bank:HKD"}

        for bal in result.balances:
            assert bal.currency == "CAD", (
                f"Expected CAD for {bal.account_path}, got {bal.currency}"
            )

        bank = next(b for b in result.balances if b.account_path == "Assets:Bank")
        assert bank.amount == Fraction(3420) + Fraction(8700) * Fraction(17, 100)

    def test_hkd_leaf_fx_metadata(self, temp_gnucash_account_balance, tmp_path):
        """Non-CAD leaf shows share_price and original amount when FX provided."""
        from repositories.gnucash_repository import SessionMode
        from services.fx_rates import FxRates

        rates_file = tmp_path / "rates.yaml"
        rates_file.write_text("HKD: 0.17\n")
        fx_rates = FxRates.load(str(rates_file))

        repo = _open_repo(temp_gnucash_account_balance, SessionMode.NORMAL)
        try:
            result = _exec(repo, as_of=date(2024, 12, 31),
                           account_prefix="Assets:Bank:HKD", fx_rates=fx_rates)
        finally:
            repo.close()

        bal = result.balances[0]
        assert bal.original_currency == "HKD"
        assert bal.original_amount == Fraction(8700)
        assert bal.share_price == Fraction(17, 100)
        assert bal.amount == Fraction(1479)
