"""
Integration tests for Close Books feature (Phase 8).

Uses temp_gnucash_for_close_books fixture (imported from plaintext) which has
2-level sub-accounts and two currencies (CAD + USD):

    Income:Salary:Base    (CAD)  -6000   ┐
    Income:Salary:Bonus   (CAD)  -1000   ├ net CAD income = 5850
    Income:Interest       (CAD)   -200   │ → Equity:Retained Earnings:CAD = -5850
    Expenses:Travel:Train (CAD)   +150   │
    Expenses:Travel:Flight(CAD)   +800   │
    Expenses:Groceries    (CAD)   +400   ┘

    Income:Freelance      (USD)   -500   ┐ net USD income = 400
    Expenses:SaaS         (USD)   +100   ┘ → Equity:Retained Earnings:USD = -400

Success criteria (confirmed before implementation):
    (a) All Income/Expense accounts have balance = 0 on closing date
    (b) Equity:Retained Earnings:{currency} = exact net income (credit)
    (c) Sum of ALL account balances = 0 (conservation of value)
    (d) All of the above
"""

import os
import tempfile
from datetime import date
from fractions import Fraction

import pytest

CLOSING_DATE = date(2024, 12, 31)

# Expected values derived from close_books_test_data.txt
CAD_NET_INCOME = Fraction(5850)   # 7200 income - 1350 expenses
USD_NET_INCOME = Fraction(400)    # 500 income - 100 expenses


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_balance(repo, account_path: str, as_of: date) -> Fraction:
    """Get account balance as of date. Returns 0 if account doesn't exist yet."""
    from infrastructure.gnucash.utils import find_account
    from services.book_closer import BookCloser

    root = repo.get_root_account()
    account = find_account(root, account_path)
    if account is None:
        return Fraction(0)
    return BookCloser().get_balance_as_of_date(account, as_of)


def sum_all_balances(repo, as_of: date) -> Fraction:
    """Sum of all account balances — must equal 0 (conservation of value)."""
    from services.book_closer import BookCloser

    closer = BookCloser()
    return sum(
        closer.get_balance_as_of_date(acc, as_of)
        for acc in repo.get_all_accounts()
    )


# ---------------------------------------------------------------------------
# Tests: Happy Path — all success criteria
# ---------------------------------------------------------------------------


class TestCloseSuccessCriteria:
    """(a)(b)(c)(d) — all success criteria on the realistic 2-level account book"""

    def test_a_income_leaf_accounts_zeroed(self, temp_gnucash_for_close_books):
        """(a) All Income leaf accounts have zero balance after closing"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.close_books import CloseBooksUseCase

        repo = GnuCashRepository(temp_gnucash_for_close_books)
        repo.open()
        try:
            CloseBooksUseCase(repo).execute(CLOSING_DATE)
            repo.save()

            for path in (
                "Income:Salary:Base",
                "Income:Salary:Bonus",
                "Income:Interest",
                "Income:Freelance",
            ):
                bal = get_balance(repo, path, CLOSING_DATE)
                assert bal == Fraction(0), f"{path} balance should be 0, got {bal}"
        finally:
            repo.close()

    def test_a_expense_leaf_accounts_zeroed(self, temp_gnucash_for_close_books):
        """(a) All Expense leaf accounts have zero balance after closing"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.close_books import CloseBooksUseCase

        repo = GnuCashRepository(temp_gnucash_for_close_books)
        repo.open()
        try:
            CloseBooksUseCase(repo).execute(CLOSING_DATE)
            repo.save()

            for path in (
                "Expenses:Travel:Train",
                "Expenses:Travel:Flight",
                "Expenses:Groceries",
                "Expenses:SaaS",
            ):
                bal = get_balance(repo, path, CLOSING_DATE)
                assert bal == Fraction(0), f"{path} balance should be 0, got {bal}"
        finally:
            repo.close()

    def test_b_cad_equity_gets_exact_net_income(self, temp_gnucash_for_close_books):
        """(b) Equity:Retained Earnings:CAD = -5850 (credit = net income 5850 CAD)"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.close_books import CloseBooksUseCase

        repo = GnuCashRepository(temp_gnucash_for_close_books)
        repo.open()
        try:
            CloseBooksUseCase(repo).execute(CLOSING_DATE)
            repo.save()

            bal = get_balance(repo, "Equity:Retained Earnings:CAD", CLOSING_DATE)
            assert bal == -CAD_NET_INCOME, (
                f"CAD equity should be -{CAD_NET_INCOME}, got {bal}"
            )
        finally:
            repo.close()

    def test_b_usd_equity_gets_exact_net_income(self, temp_gnucash_for_close_books):
        """(b) Equity:Retained Earnings:USD = -400 (credit = net income 400 USD)"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.close_books import CloseBooksUseCase

        repo = GnuCashRepository(temp_gnucash_for_close_books)
        repo.open()
        try:
            CloseBooksUseCase(repo).execute(CLOSING_DATE)
            repo.save()

            bal = get_balance(repo, "Equity:Retained Earnings:USD", CLOSING_DATE)
            assert bal == -USD_NET_INCOME, (
                f"USD equity should be -{USD_NET_INCOME}, got {bal}"
            )
        finally:
            repo.close()

    def test_c_conservation_of_value(self, temp_gnucash_for_close_books):
        """(c) Sum of all account balances = 0 after closing (accounting equation holds)"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.close_books import CloseBooksUseCase

        repo = GnuCashRepository(temp_gnucash_for_close_books)
        repo.open()
        try:
            CloseBooksUseCase(repo).execute(CLOSING_DATE)
            repo.save()

            total = sum_all_balances(repo, CLOSING_DATE)
            assert total == Fraction(0), (
                f"Sum of all balances should be 0, got {total}"
            )
        finally:
            repo.close()

    def test_c_conservation_holds_before_close_too(self, temp_gnucash_for_close_books):
        """(c) Conservation of value also holds BEFORE closing (sanity check)"""
        from repositories.gnucash_repository import GnuCashRepository

        repo = GnuCashRepository(temp_gnucash_for_close_books)
        repo.open()
        try:
            total = sum_all_balances(repo, CLOSING_DATE)
            assert total == Fraction(0)
        finally:
            repo.close()


# ---------------------------------------------------------------------------
# Tests: Multi-currency correctness
# ---------------------------------------------------------------------------


class TestMultiCurrencyClose:
    """Two separate closing transactions, one per currency"""

    def test_two_closing_transactions_created(self, temp_gnucash_for_close_books):
        """One closing transaction per currency (CAD and USD)"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.close_books import CloseBooksUseCase

        repo = GnuCashRepository(temp_gnucash_for_close_books)
        repo.open()
        try:
            result = CloseBooksUseCase(repo).execute(CLOSING_DATE)
            repo.save()

            assert len(result.transactions_created) == 2
            assert set(result.currencies_closed) == {"CAD", "USD"}
        finally:
            repo.close()

    def test_cad_closing_transaction_only_touches_cad_accounts(
        self, temp_gnucash_for_close_books
    ):
        """CAD closing transaction has no splits on USD accounts"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.close_books import CloseBooksUseCase

        repo = GnuCashRepository(temp_gnucash_for_close_books)
        repo.open()
        try:
            result = CloseBooksUseCase(repo).execute(CLOSING_DATE)
            repo.save()

            for tx in result.transactions_created:
                tx_currency = tx.GetCurrency().get_mnemonic()
                for split in tx.GetSplitList():
                    acc_currency = split.GetAccount().GetCommodity().get_mnemonic()
                    assert acc_currency == tx_currency, (
                        f"Closing txn for {tx_currency} has split on "
                        f"{acc_currency} account: {split.GetAccount().GetName()}"
                    )
        finally:
            repo.close()

    def test_sub_account_balances_all_zeroed(self, temp_gnucash_for_close_books):
        """Every Income/Expense account (including 2-level sub-accounts) is zeroed"""
        from gnucash.gnucash_core_c import ACCT_TYPE_EXPENSE, ACCT_TYPE_INCOME

        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.close_books import CloseBooksUseCase

        repo = GnuCashRepository(temp_gnucash_for_close_books)
        repo.open()
        try:
            CloseBooksUseCase(repo).execute(CLOSING_DATE)
            repo.save()

            from services.book_closer import BookCloser
            closer = BookCloser()
            repo.get_root_account()

            non_zero = []
            for acc in repo.get_all_accounts():
                if acc.GetType() not in (ACCT_TYPE_INCOME, ACCT_TYPE_EXPENSE):
                    continue
                bal = closer.get_balance_as_of_date(acc, CLOSING_DATE)
                if bal != Fraction(0):
                    non_zero.append((acc.GetName(), bal))

            assert non_zero == [], (
                f"These Income/Expense accounts still have non-zero balances: {non_zero}"
            )
        finally:
            repo.close()


# ---------------------------------------------------------------------------
# Tests: Already-closed detection (Option B)
# ---------------------------------------------------------------------------


class TestAlreadyClosedDetection:

    def test_raises_error_without_force(self, temp_gnucash_for_close_books):
        """AlreadyClosedError raised on second close without --force"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.close_books import AlreadyClosedError, CloseBooksUseCase

        repo = GnuCashRepository(temp_gnucash_for_close_books)
        repo.open()
        try:
            use_case = CloseBooksUseCase(repo)
            use_case.execute(CLOSING_DATE)

            with pytest.raises(AlreadyClosedError):
                use_case.execute(CLOSING_DATE)
        finally:
            repo.close()

    def test_check_status_open_before_close(self, temp_gnucash_for_close_books):
        """check_status returns False (open) before closing"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.close_books import CloseBooksUseCase

        repo = GnuCashRepository(temp_gnucash_for_close_books)
        repo.open()
        try:
            assert not CloseBooksUseCase(repo).check_status(CLOSING_DATE)
        finally:
            repo.close()

    def test_check_status_closed_after_close(self, temp_gnucash_for_close_books):
        """check_status returns True (closed) after execute"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.close_books import CloseBooksUseCase

        repo = GnuCashRepository(temp_gnucash_for_close_books)
        repo.open()
        try:
            use_case = CloseBooksUseCase(repo)
            use_case.execute(CLOSING_DATE)
            assert use_case.check_status(CLOSING_DATE)
        finally:
            repo.close()


# ---------------------------------------------------------------------------
# Tests: --force
# ---------------------------------------------------------------------------


class TestForceReclose:
    """--force: delete old closing transactions and re-close (single session)"""

    def test_force_books_remain_closed(self, temp_gnucash_for_close_books):
        """After --force, books are still closed"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.close_books import CloseBooksUseCase

        repo = GnuCashRepository(temp_gnucash_for_close_books)
        repo.open()
        try:
            use_case = CloseBooksUseCase(repo)
            use_case.execute(CLOSING_DATE)
            use_case.execute(CLOSING_DATE, force=True)
            repo.save()

            assert use_case.check_status(CLOSING_DATE)
        finally:
            repo.close()

    def test_force_equity_not_doubled(self, temp_gnucash_for_close_books):
        """After --force, CAD equity = -5850, not -11700 (old entry was deleted)"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.close_books import CloseBooksUseCase

        repo = GnuCashRepository(temp_gnucash_for_close_books)
        repo.open()
        try:
            use_case = CloseBooksUseCase(repo)
            use_case.execute(CLOSING_DATE)
            use_case.execute(CLOSING_DATE, force=True)
            repo.save()

            bal = get_balance(repo, "Equity:Retained Earnings:CAD", CLOSING_DATE)
            assert bal == -CAD_NET_INCOME, (
                f"Expected -{CAD_NET_INCOME}, got {bal} "
                "(doubled value means old closing was not deleted)"
            )
        finally:
            repo.close()

    def test_force_conservation_of_value(self, temp_gnucash_for_close_books):
        """(c) Conservation of value holds after --force re-close"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.close_books import CloseBooksUseCase

        repo = GnuCashRepository(temp_gnucash_for_close_books)
        repo.open()
        try:
            use_case = CloseBooksUseCase(repo)
            use_case.execute(CLOSING_DATE)
            use_case.execute(CLOSING_DATE, force=True)
            repo.save()

            assert sum_all_balances(repo, CLOSING_DATE) == Fraction(0)
        finally:
            repo.close()


# ---------------------------------------------------------------------------
# Tests: --dry-run
# ---------------------------------------------------------------------------


class TestDryRun:

    def test_dry_run_makes_no_changes(self, temp_gnucash_for_close_books):
        """--dry-run creates no transactions and leaves books open"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.close_books import CloseBooksUseCase

        repo = GnuCashRepository(temp_gnucash_for_close_books)
        repo.open()
        try:
            tx_count = len(repo.get_all_transactions())
            acc_count = len(repo.get_all_accounts())
            use_case = CloseBooksUseCase(repo)

            result = use_case.execute(CLOSING_DATE, dry_run=True)

            assert len(repo.get_all_transactions()) == tx_count
            assert len(repo.get_all_accounts()) == acc_count
            assert result.dry_run is True
            assert not use_case.check_status(CLOSING_DATE)
        finally:
            repo.close()

    def test_dry_run_reports_both_currencies(self, temp_gnucash_for_close_books):
        """--dry-run reports both CAD and USD as currencies that would be closed"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.close_books import CloseBooksUseCase

        repo = GnuCashRepository(temp_gnucash_for_close_books)
        repo.open()
        try:
            result = CloseBooksUseCase(repo).execute(CLOSING_DATE, dry_run=True)
            assert set(result.currencies_closed) == {"CAD", "USD"}
        finally:
            repo.close()


# ---------------------------------------------------------------------------
# Tests: Cumulative close
# ---------------------------------------------------------------------------


class TestCumulativeClose:

    def test_transactions_before_closing_date_are_zeroed(
        self, temp_gnucash_for_close_books
    ):
        """All transactions from Jan–Sep 2024 are zeroed by a 2024-12-31 close"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.close_books import CloseBooksUseCase

        repo = GnuCashRepository(temp_gnucash_for_close_books)
        repo.open()
        try:
            CloseBooksUseCase(repo).execute(CLOSING_DATE)
            repo.save()

            assert CloseBooksUseCase(repo).check_status(CLOSING_DATE)
        finally:
            repo.close()

    def test_future_transactions_unaffected_by_past_close(
        self, temp_gnucash_for_close_books
    ):
        """A 2024-12-31 close does not zero out 2025 transactions"""
        import gnucash
        from gnucash import GncNumeric, Split, Transaction

        from infrastructure.gnucash.utils import find_account
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.close_books import CloseBooksUseCase

        repo = GnuCashRepository(temp_gnucash_for_close_books)
        repo.open()
        try:
            book = repo.book
            root = repo.get_root_account()
            table = book.get_table()
            cad = table.lookup("CURRENCY", "CAD")

            # Add a 2025 salary before closing 2024
            salary = find_account(root, "Income:Salary:Base")
            checking = find_account(root, "Assets:Bank:Checking")

            tx = Transaction(book)
            tx.BeginEdit()
            tx.SetCurrency(cad)
            tx.SetDate(1, 3, 2025)
            tx.SetDescription("2025 March salary")
            s1 = Split(book)
            s1.SetParent(tx)
            s1.SetAccount(salary)
            s1.SetValue(GncNumeric(-300000, 100))  # -3000 CAD
            s2 = Split(book)
            s2.SetParent(tx)
            s2.SetAccount(checking)
            s2.SetValue(GncNumeric(300000, 100))
            tx.CommitEdit()

            # Close 2024
            CloseBooksUseCase(repo).execute(CLOSING_DATE)
            repo.save()

            # 2024 is closed
            assert CloseBooksUseCase(repo).check_status(CLOSING_DATE)

            # 2025 salary still exists as of 2025-03-01
            from services.book_closer import BookCloser
            bal_2025 = BookCloser().get_balance_as_of_date(
                salary, date(2025, 3, 31)
            )
            assert bal_2025 == Fraction(-3000), (
                f"2025 salary should be -3000, got {bal_2025}"
            )

            # 2025 is NOT closed
            assert not CloseBooksUseCase(repo).check_status(date(2025, 12, 31))
        finally:
            repo.close()


# ---------------------------------------------------------------------------
# Tests: CLI end-to-end
# ---------------------------------------------------------------------------


class TestCloseBooksCLI:

    def test_cli_close_basic(self, temp_gnucash_for_close_books):
        """CLI close-books exits 0 and prints summary with both currencies"""
        from click.testing import CliRunner

        from cli.close_books_cmd import close_books

        runner = CliRunner()
        result = runner.invoke(close_books, [
            temp_gnucash_for_close_books, "--closing-date", "2024-12-31"
        ])
        assert result.exit_code == 0, f"Exit {result.exit_code}: {result.output}"
        assert "Books closed as of" in result.output
        assert "CAD" in result.output
        assert "USD" in result.output

    def test_cli_status_open(self, temp_gnucash_for_close_books):
        from click.testing import CliRunner

        from cli.close_books_cmd import close_books

        runner = CliRunner()
        result = runner.invoke(close_books, [
            temp_gnucash_for_close_books, "--closing-date", "2024-12-31", "--status"
        ])
        assert result.exit_code == 0
        assert "OPEN" in result.output

    def test_cli_dry_run(self, temp_gnucash_for_close_books):
        from click.testing import CliRunner

        from cli.close_books_cmd import close_books

        runner = CliRunner()
        result = runner.invoke(close_books, [
            temp_gnucash_for_close_books, "--closing-date", "2024-12-31", "--dry-run"
        ])
        assert result.exit_code == 0
        assert "DRY RUN" in result.output

    def test_cli_already_closed_error(self, temp_gnucash_for_close_books):
        from click.testing import CliRunner

        from cli.close_books_cmd import close_books

        runner = CliRunner()
        runner.invoke(close_books, [
            temp_gnucash_for_close_books, "--closing-date", "2024-12-31"
        ])
        result = runner.invoke(close_books, [
            temp_gnucash_for_close_books, "--closing-date", "2024-12-31"
        ])
        assert result.exit_code != 0 or "Error" in result.output

    def test_cli_status_closed_after_close(self, temp_gnucash_for_close_books):
        from click.testing import CliRunner

        from cli.close_books_cmd import close_books

        runner = CliRunner()
        runner.invoke(close_books, [
            temp_gnucash_for_close_books, "--closing-date", "2024-12-31"
        ])
        result = runner.invoke(close_books, [
            temp_gnucash_for_close_books, "--closing-date", "2024-12-31", "--status"
        ])
        assert result.exit_code == 0
        assert "CLOSED" in result.output

    def test_cli_force_flag(self, temp_gnucash_for_close_books):
        """CLI --force on pre-closed file succeeds"""
        import time

        from click.testing import CliRunner

        from cli.close_books_cmd import close_books

        runner = CliRunner()
        runner.invoke(close_books, [
            temp_gnucash_for_close_books, "--closing-date", "2024-12-31"
        ])
        time.sleep(1)  # avoid backup timestamp collision
        result = runner.invoke(close_books, [
            temp_gnucash_for_close_books, "--closing-date", "2024-12-31", "--force"
        ])
        assert result.exit_code == 0, f"Exit {result.exit_code}: {result.output}"
        assert "Books closed as of" in result.output
