"""
Unit tests for CloseBooksUseCase.

Uses temp_gnucash_for_close_books fixture (imported from plaintext) with
2-level sub-accounts and two currencies (CAD + USD).

    CAD net income = 5850  (Income 7200 - Expenses 1350)
    USD net income = 400   (Income 500  - Expenses 100)
"""

from datetime import date
from fractions import Fraction

import pytest

CLOSING_DATE = date(2024, 12, 31)
CAD_NET = Fraction(5850)
USD_NET = Fraction(400)


# ---------------------------------------------------------------------------
# TestCheckStatus
# ---------------------------------------------------------------------------


class TestCheckStatus:
    """CloseBooksUseCase.check_status delegates to BookCloser.is_closed"""

    def test_open_before_closing(self, temp_gnucash_for_close_books):
        """Returns False (open) when accounts have non-zero balances"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.close_books import CloseBooksUseCase

        with GnuCashRepository(temp_gnucash_for_close_books) as repo:
            assert not CloseBooksUseCase(repo).check_status(CLOSING_DATE)

    def test_closed_after_execute(self, temp_gnucash_for_close_books):
        """Returns True after a successful execute"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.close_books import CloseBooksUseCase

        with GnuCashRepository(temp_gnucash_for_close_books) as repo:
            use_case = CloseBooksUseCase(repo)
            use_case.execute(CLOSING_DATE)
            assert use_case.check_status(CLOSING_DATE)

    def test_open_before_year_transactions_exist(self, temp_gnucash_for_close_books):
        """Returns True for a date before all transactions (all balances zero)"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.close_books import CloseBooksUseCase

        with GnuCashRepository(temp_gnucash_for_close_books) as repo:
            # Before 2024, all balances are zero → treated as closed
            assert CloseBooksUseCase(repo).check_status(date(2023, 12, 31))

    def test_status_does_not_modify_book(self, temp_gnucash_for_close_books):
        """check_status creates no transactions"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.close_books import CloseBooksUseCase

        with GnuCashRepository(temp_gnucash_for_close_books) as repo:
            count_before = len(repo.get_all_transactions())
            CloseBooksUseCase(repo).check_status(CLOSING_DATE)
            assert len(repo.get_all_transactions()) == count_before


# ---------------------------------------------------------------------------
# TestExecuteResult
# ---------------------------------------------------------------------------


class TestExecuteResult:
    """Result object structure and content"""

    def test_closing_date_in_result(self, temp_gnucash_for_close_books):
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.close_books import CloseBooksUseCase

        with GnuCashRepository(temp_gnucash_for_close_books) as repo:
            result = CloseBooksUseCase(repo).execute(CLOSING_DATE)
            assert result.closing_date == CLOSING_DATE

    def test_both_currencies_in_result(self, temp_gnucash_for_close_books):
        """Both CAD and USD appear in currencies_closed"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.close_books import CloseBooksUseCase

        with GnuCashRepository(temp_gnucash_for_close_books) as repo:
            result = CloseBooksUseCase(repo).execute(CLOSING_DATE)
            assert set(result.currencies_closed) == {"CAD", "USD"}

    def test_two_transactions_created(self, temp_gnucash_for_close_books):
        """One closing transaction per currency = 2 total"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.close_books import CloseBooksUseCase

        with GnuCashRepository(temp_gnucash_for_close_books) as repo:
            result = CloseBooksUseCase(repo).execute(CLOSING_DATE)
            assert len(result.transactions_created) == 2

    def test_equity_accounts_created_listed(self, temp_gnucash_for_close_books):
        """Both Equity:Retained Earnings:CAD and :USD appear in created list"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.close_books import CloseBooksUseCase

        with GnuCashRepository(temp_gnucash_for_close_books) as repo:
            result = CloseBooksUseCase(repo).execute(CLOSING_DATE)
            assert "Equity:Retained Earnings:CAD" in result.equity_accounts_created
            assert "Equity:Retained Earnings:USD" in result.equity_accounts_created

    def test_force_reuses_existing_equity_accounts(self, temp_gnucash_for_close_books):
        """On --force, pre-existing equity accounts are NOT listed as newly created"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.close_books import CloseBooksUseCase

        with GnuCashRepository(temp_gnucash_for_close_books) as repo:
            use_case = CloseBooksUseCase(repo)
            use_case.execute(CLOSING_DATE)
            result = use_case.execute(CLOSING_DATE, force=True)
            assert result.equity_accounts_created == []


# ---------------------------------------------------------------------------
# TestExecuteEdgeCases
# ---------------------------------------------------------------------------


class TestExecuteEdgeCases:
    """Edge cases and error conditions"""

    def test_already_closed_raises_error(self, temp_gnucash_for_close_books):
        """AlreadyClosedError raised on second execute without --force"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.close_books import AlreadyClosedError, CloseBooksUseCase

        with GnuCashRepository(temp_gnucash_for_close_books) as repo:
            use_case = CloseBooksUseCase(repo)
            use_case.execute(CLOSING_DATE)
            with pytest.raises(AlreadyClosedError):
                use_case.execute(CLOSING_DATE)

    def test_dry_run_flag_set(self, temp_gnucash_for_close_books):
        """Result.dry_run is True when dry_run=True"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.close_books import CloseBooksUseCase

        with GnuCashRepository(temp_gnucash_for_close_books) as repo:
            result = CloseBooksUseCase(repo).execute(CLOSING_DATE, dry_run=True)
            assert result.dry_run is True

    def test_dry_run_no_transactions_created(self, temp_gnucash_for_close_books):
        """dry_run=True creates no transactions or accounts"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.close_books import CloseBooksUseCase

        with GnuCashRepository(temp_gnucash_for_close_books) as repo:
            tx_before = len(repo.get_all_transactions())
            acc_before = len(repo.get_all_accounts())

            result = CloseBooksUseCase(repo).execute(CLOSING_DATE, dry_run=True)

            assert len(repo.get_all_transactions()) == tx_before
            assert len(repo.get_all_accounts()) == acc_before
            assert result.transactions_created == []

    def test_dry_run_reports_currencies_without_closing(
        self, temp_gnucash_for_close_books
    ):
        """dry_run still reports which currencies WOULD be closed"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.close_books import CloseBooksUseCase

        with GnuCashRepository(temp_gnucash_for_close_books) as repo:
            result = CloseBooksUseCase(repo).execute(CLOSING_DATE, dry_run=True)
            assert set(result.currencies_closed) == {"CAD", "USD"}

    def test_custom_equity_template_used(self, temp_gnucash_for_close_books):
        """Custom equity_template creates accounts under that path"""
        from infrastructure.gnucash.utils import find_account
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.close_books import CloseBooksUseCase

        with GnuCashRepository(temp_gnucash_for_close_books) as repo:
            CloseBooksUseCase(repo).execute(
                CLOSING_DATE, equity_template="Equity:Closing 2024"
            )
            root = repo.get_root_account()
            assert find_account(root, "Equity:Closing 2024:CAD") is not None
            assert find_account(root, "Equity:Closing 2024:USD") is not None

    def test_force_clears_income_expense_then_recloses(
        self, temp_gnucash_for_close_books
    ):
        """After --force, Income/Expense are zero and equity is correct, not doubled"""
        from infrastructure.gnucash.utils import find_account
        from repositories.gnucash_repository import GnuCashRepository
        from services.book_closer import BookCloser
        from use_cases.close_books import CloseBooksUseCase

        with GnuCashRepository(temp_gnucash_for_close_books) as repo:
            use_case = CloseBooksUseCase(repo)
            use_case.execute(CLOSING_DATE)
            use_case.execute(CLOSING_DATE, force=True)

            closer = BookCloser()
            root = repo.get_root_account()

            # Equity should be -5850, not -11700
            cad_eq = find_account(root, "Equity:Retained Earnings:CAD")
            bal = closer.get_balance_as_of_date(cad_eq, CLOSING_DATE)
            assert bal == -CAD_NET, (
                f"Expected -{CAD_NET}, got {bal} — old closing was not deleted"
            )


# ---------------------------------------------------------------------------
# TestGetSummary
# ---------------------------------------------------------------------------


class TestGetSummary:
    """CloseBooksResult.get_summary — human-readable output"""

    def test_normal_run_summary(self, temp_gnucash_for_close_books):
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.close_books import CloseBooksUseCase

        with GnuCashRepository(temp_gnucash_for_close_books) as repo:
            result = CloseBooksUseCase(repo).execute(CLOSING_DATE)
            summary = result.get_summary()
            assert "Books closed" in summary
            assert "2024-12-31" in summary
            assert "CAD" in summary
            assert "USD" in summary

    def test_dry_run_summary(self, temp_gnucash_for_close_books):
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.close_books import CloseBooksUseCase

        with GnuCashRepository(temp_gnucash_for_close_books) as repo:
            result = CloseBooksUseCase(repo).execute(CLOSING_DATE, dry_run=True)
            summary = result.get_summary()
            assert "DRY RUN" in summary
            assert "2024-12-31" in summary
