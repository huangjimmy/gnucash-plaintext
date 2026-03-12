"""
Unit tests for BookCloser service.

Uses temp_gnucash_for_close_books fixture (imported from plaintext) which has
realistic 2-level sub-accounts (Income:Salary:Base, Expenses:Travel:Train, etc.)
and two currencies (CAD + USD). Tests each method in isolation.
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


def find(root, path):
    from infrastructure.gnucash.utils import find_account
    return find_account(root, path)


# ---------------------------------------------------------------------------
# TestGetBalanceAsOfDate
# ---------------------------------------------------------------------------


class TestGetBalanceAsOfDate:
    """get_balance_as_of_date — sum splits up to and including the date"""

    def test_zero_before_first_transaction(self, temp_gnucash_for_close_books):
        """Balance is 0 before any transactions exist"""
        from services.book_closer import BookCloser

        session = _open_read_only(temp_gnucash_for_close_books)
        try:
            root = session.book.get_root_account()
            acc = find(root, "Income:Salary:Base")
            bal = BookCloser().get_balance_as_of_date(acc, date(2023, 12, 31))
            assert bal == Fraction(0)
        finally:
            session.end()

    def test_includes_transaction_on_exact_date(self, temp_gnucash_for_close_books):
        """Balance on Jan 31 includes the January salary"""
        from services.book_closer import BookCloser

        session = _open_read_only(temp_gnucash_for_close_books)
        try:
            root = session.book.get_root_account()
            acc = find(root, "Income:Salary:Base")
            bal = BookCloser().get_balance_as_of_date(acc, date(2024, 1, 31))
            assert bal == Fraction(-3000)  # only Jan salary
        finally:
            session.end()

    def test_accumulates_across_months(self, temp_gnucash_for_close_books):
        """Balance after Feb includes both Jan and Feb salaries"""
        from services.book_closer import BookCloser

        session = _open_read_only(temp_gnucash_for_close_books)
        try:
            root = session.book.get_root_account()
            acc = find(root, "Income:Salary:Base")
            bal = BookCloser().get_balance_as_of_date(acc, date(2024, 2, 28))
            assert bal == Fraction(-6000)  # Jan + Feb
        finally:
            session.end()

    def test_excludes_future_transactions(self, temp_gnucash_for_close_books):
        """Balance as of June does not include the August freelance income"""
        from services.book_closer import BookCloser

        session = _open_read_only(temp_gnucash_for_close_books)
        try:
            root = session.book.get_root_account()
            acc = find(root, "Income:Freelance")
            bal = BookCloser().get_balance_as_of_date(acc, date(2024, 6, 30))
            assert bal == Fraction(0)
        finally:
            session.end()

    def test_two_level_expense_balance(self, temp_gnucash_for_close_books):
        """2-level expense sub-account (Expenses:Travel:Train) balance correct"""
        from services.book_closer import BookCloser

        session = _open_read_only(temp_gnucash_for_close_books)
        try:
            root = session.book.get_root_account()
            acc = find(root, "Expenses:Travel:Train")
            bal = BookCloser().get_balance_as_of_date(acc, date(2024, 12, 31))
            assert bal == Fraction(150)
        finally:
            session.end()

    def test_exclude_guids_zeroes_account(self, temp_gnucash_for_close_books):
        """Excluding all transaction GUIDs for an account yields zero"""
        from services.book_closer import BookCloser

        session = _open_read_only(temp_gnucash_for_close_books)
        try:
            root = session.book.get_root_account()
            acc = find(root, "Income:Interest")
            exclude = {
                split.GetParent().GetGUID().to_string()
                for split in acc.GetSplitList()
            }
            bal = BookCloser().get_balance_as_of_date(
                acc, date(2024, 12, 31), exclude_guids=exclude
            )
            assert bal == Fraction(0)
        finally:
            session.end()


# ---------------------------------------------------------------------------
# TestIsClosed
# ---------------------------------------------------------------------------


class TestIsClosed:
    """is_closed — True iff all Income/Expense balances are zero"""

    def test_not_closed_with_active_balances(self, temp_gnucash_for_close_books):
        """Returns False before any closing"""
        from services.book_closer import BookCloser

        session = _open_read_only(temp_gnucash_for_close_books)
        try:
            root = session.book.get_root_account()
            assert not BookCloser().is_closed(root, date(2024, 12, 31))
        finally:
            session.end()

    def test_closed_before_all_transactions(self, temp_gnucash_for_close_books):
        """Returns True for a date before any transactions (all balances zero)"""
        from services.book_closer import BookCloser

        session = _open_read_only(temp_gnucash_for_close_books)
        try:
            root = session.book.get_root_account()
            assert BookCloser().is_closed(root, date(2023, 12, 31))
        finally:
            session.end()

    def test_placeholder_accounts_dont_affect_is_closed(
        self, temp_gnucash_for_close_books
    ):
        """Placeholder Income/Expense accounts (no direct splits) don't block is_closed"""
        from services.book_closer import BookCloser

        session = _open_read_only(temp_gnucash_for_close_books)
        try:
            root = session.book.get_root_account()
            closer = BookCloser()
            # Placeholder Income, Expenses, Income:Salary, Expenses:Travel
            # have no splits → balance = 0 → should not prevent is_closed
            # Before any transactions: all leaf AND placeholder balances are 0
            assert closer.is_closed(root, date(2023, 12, 31))
        finally:
            session.end()


# ---------------------------------------------------------------------------
# TestGroupAccountsByCurrency
# ---------------------------------------------------------------------------


class TestGroupAccountsByCurrency:
    """group_accounts_by_currency — groups non-zero Income/Expense by commodity"""

    def test_cad_group_contains_all_leaf_accounts(self, temp_gnucash_for_close_books):
        """CAD group contains all 5 CAD leaf income/expense accounts"""
        from services.book_closer import BookCloser

        session = _open_read_only(temp_gnucash_for_close_books)
        try:
            root = session.book.get_root_account()
            groups = BookCloser().group_accounts_by_currency(root, date(2024, 12, 31))

            assert "CAD" in groups
            names = {a.GetName() for a, _ in groups["CAD"]}
            assert names == {"Base", "Bonus", "Interest", "Train", "Flight", "Groceries"}
        finally:
            session.end()

    def test_usd_group_contains_usd_leaf_accounts(self, temp_gnucash_for_close_books):
        """USD group contains Income:Freelance and Expenses:SaaS"""
        from services.book_closer import BookCloser

        session = _open_read_only(temp_gnucash_for_close_books)
        try:
            root = session.book.get_root_account()
            groups = BookCloser().group_accounts_by_currency(root, date(2024, 12, 31))

            assert "USD" in groups
            names = {a.GetName() for a, _ in groups["USD"]}
            assert names == {"Freelance", "SaaS"}
        finally:
            session.end()

    def test_placeholder_accounts_not_included(self, temp_gnucash_for_close_books):
        """Placeholder Income:Salary has no splits → not included in groups"""
        from services.book_closer import BookCloser

        session = _open_read_only(temp_gnucash_for_close_books)
        try:
            root = session.book.get_root_account()
            groups = BookCloser().group_accounts_by_currency(root, date(2024, 12, 31))

            # "Salary" (placeholder) and "Travel" (placeholder) should not appear
            # since they have zero direct balance
            cad_names = {a.GetName() for a, _ in groups.get("CAD", [])}
            assert "Salary" not in cad_names
            assert "Travel" not in cad_names
        finally:
            session.end()

    def test_asset_accounts_not_included(self, temp_gnucash_for_close_books):
        """Asset accounts never appear in the groups"""
        from services.book_closer import BookCloser

        session = _open_read_only(temp_gnucash_for_close_books)
        try:
            root = session.book.get_root_account()
            groups = BookCloser().group_accounts_by_currency(root, date(2024, 12, 31))
            all_names = {a.GetName() for accs in groups.values() for a, _ in accs}
            assert "Checking" not in all_names
            assert "USD" not in all_names  # Assets:Bank:USD
        finally:
            session.end()

    def test_cad_balances_correct(self, temp_gnucash_for_close_books):
        """Each CAD account's balance in the group matches expected value"""
        from services.book_closer import BookCloser

        session = _open_read_only(temp_gnucash_for_close_books)
        try:
            root = session.book.get_root_account()
            groups = BookCloser().group_accounts_by_currency(root, date(2024, 12, 31))

            balances = {a.GetName(): b for a, b in groups["CAD"]}
            assert balances["Base"] == Fraction(-6000)
            assert balances["Bonus"] == Fraction(-1000)
            assert balances["Interest"] == Fraction(-200)
            assert balances["Train"] == Fraction(150)
            assert balances["Flight"] == Fraction(800)
            assert balances["Groceries"] == Fraction(400)
        finally:
            session.end()

    def test_empty_before_transactions(self, temp_gnucash_for_close_books):
        """Before any transactions, all balances are zero → empty dict"""
        from services.book_closer import BookCloser

        session = _open_read_only(temp_gnucash_for_close_books)
        try:
            root = session.book.get_root_account()
            groups = BookCloser().group_accounts_by_currency(root, date(2023, 12, 31))
            assert groups == {}
        finally:
            session.end()


# ---------------------------------------------------------------------------
# TestFindClosingTransactions
# ---------------------------------------------------------------------------


class TestFindClosingTransactions:
    """find_closing_transactions — find by description prefix + date"""

    def test_finds_two_closing_transactions(self, temp_gnucash_for_close_books):
        """After closing, two closing transactions exist (one per currency)"""
        from repositories.gnucash_repository import GnuCashRepository
        from services.book_closer import BookCloser
        from use_cases.close_books import CloseBooksUseCase

        repo = GnuCashRepository(temp_gnucash_for_close_books)
        repo.open()
        try:
            closing_date = date(2024, 12, 31)
            CloseBooksUseCase(repo).execute(closing_date)

            root = repo.get_root_account()
            txns = BookCloser().find_closing_transactions(root, closing_date)
            assert len(txns) == 2
            descs = {tx.GetDescription() for tx in txns}
            assert descs == {"Closing entry (CAD)", "Closing entry (USD)"}
        finally:
            repo.close()

    def test_ignores_regular_transactions(self, temp_gnucash_for_close_books):
        """Regular transactions (salary, groceries etc.) are not returned"""
        from repositories.gnucash_repository import GnuCashRepository
        from services.book_closer import BookCloser

        repo = GnuCashRepository(temp_gnucash_for_close_books)
        repo.open()
        try:
            root = repo.get_root_account()
            # Query on a date that has regular transactions (Jan 31 = salary)
            txns = BookCloser().find_closing_transactions(root, date(2024, 1, 31))
            assert txns == []
        finally:
            repo.close()

    def test_no_duplicates(self, temp_gnucash_for_close_books):
        """Each transaction is returned exactly once"""
        from repositories.gnucash_repository import GnuCashRepository
        from services.book_closer import BookCloser
        from use_cases.close_books import CloseBooksUseCase

        repo = GnuCashRepository(temp_gnucash_for_close_books)
        repo.open()
        try:
            closing_date = date(2024, 12, 31)
            CloseBooksUseCase(repo).execute(closing_date)

            root = repo.get_root_account()
            txns = BookCloser().find_closing_transactions(root, closing_date)
            guids = [tx.GetGUID().to_string() for tx in txns]
            assert len(guids) == len(set(guids))
        finally:
            repo.close()


# ---------------------------------------------------------------------------
# TestGetOrCreateEquityAccount
# ---------------------------------------------------------------------------


class TestGetOrCreateEquityAccount:
    """get_or_create_equity_account — find or create nested equity account"""

    def test_creates_multi_level_path(self, temp_gnucash_for_close_books):
        """Creates Equity:Retained Earnings:CAD with all intermediate levels"""
        from infrastructure.gnucash.utils import find_account
        from repositories.gnucash_repository import GnuCashRepository
        from services.book_closer import BookCloser

        repo = GnuCashRepository(temp_gnucash_for_close_books)
        repo.open()
        try:
            book = repo.book
            root = repo.get_root_account()
            account, was_created = BookCloser().get_or_create_equity_account(
                book, root, "Equity:Retained Earnings", "CAD"
            )
            assert was_created is True
            assert find_account(root, "Equity:Retained Earnings") is not None
            assert find_account(root, "Equity:Retained Earnings:CAD") is not None
            assert account.GetCommodity().get_mnemonic() == "CAD"
        finally:
            repo.close()

    def test_idempotent_on_second_call(self, temp_gnucash_for_close_books):
        """Second call returns existing account with was_created=False"""
        from repositories.gnucash_repository import GnuCashRepository
        from services.book_closer import BookCloser

        repo = GnuCashRepository(temp_gnucash_for_close_books)
        repo.open()
        try:
            book = repo.book
            root = repo.get_root_account()
            closer = BookCloser()
            closer.get_or_create_equity_account(book, root, "Equity:Retained Earnings", "CAD")
            _, was_created = closer.get_or_create_equity_account(
                book, root, "Equity:Retained Earnings", "CAD"
            )
            assert was_created is False
        finally:
            repo.close()

    def test_creates_separate_account_per_currency(self, temp_gnucash_for_close_books):
        """USD and CAD get separate equity sub-accounts"""
        from infrastructure.gnucash.utils import find_account
        from repositories.gnucash_repository import GnuCashRepository
        from services.book_closer import BookCloser

        repo = GnuCashRepository(temp_gnucash_for_close_books)
        repo.open()
        try:
            book = repo.book
            root = repo.get_root_account()
            closer = BookCloser()
            closer.get_or_create_equity_account(book, root, "Equity:Retained Earnings", "CAD")
            closer.get_or_create_equity_account(book, root, "Equity:Retained Earnings", "USD")

            cad_acc = find_account(root, "Equity:Retained Earnings:CAD")
            usd_acc = find_account(root, "Equity:Retained Earnings:USD")
            assert cad_acc is not None
            assert usd_acc is not None
            assert cad_acc.GetCommodity().get_mnemonic() == "CAD"
            assert usd_acc.GetCommodity().get_mnemonic() == "USD"
        finally:
            repo.close()


# ---------------------------------------------------------------------------
# TestCreateClosingTransaction
# ---------------------------------------------------------------------------


class TestCreateClosingTransaction:
    """create_closing_transaction — creates a balanced closing entry"""

    def _close_cad(self, temp_gnucash_for_close_books):
        """Helper: open, group CAD accounts, create equity+closing tx, return session+tx."""
        from repositories.gnucash_repository import GnuCashRepository
        from services.book_closer import BookCloser

        repo = GnuCashRepository(temp_gnucash_for_close_books)
        repo.open()
        root = repo.get_root_account()
        closer = BookCloser()
        closing_date = date(2024, 12, 31)
        groups = closer.group_accounts_by_currency(root, closing_date)
        equity, _ = closer.get_or_create_equity_account(
            repo.book, root, "Equity:Retained Earnings", "CAD"
        )
        tx = closer.create_closing_transaction(
            repo.book, closing_date, "CAD", groups["CAD"], equity
        )
        return repo, tx

    def test_transaction_is_balanced(self, temp_gnucash_for_close_books):
        """Sum of all split values = 0"""
        repo, tx = self._close_cad(temp_gnucash_for_close_books)
        try:
            total = sum(
                Fraction(s.GetValue().num(), s.GetValue().denom())
                for s in tx.GetSplitList()
            )
            assert total == Fraction(0), f"Transaction not balanced: {total}"
        finally:
            repo.close()

    def test_number_of_splits(self, temp_gnucash_for_close_books):
        """6 Income/Expense accounts + 1 equity split = 7 splits total"""
        repo, tx = self._close_cad(temp_gnucash_for_close_books)
        try:
            assert len(tx.GetSplitList()) == 7  # 6 I/E + 1 equity
        finally:
            repo.close()

    def test_equity_split_equals_net_income(self, temp_gnucash_for_close_books):
        """Equity:Retained Earnings:CAD split = sum(all account balances) = -5850"""
        repo, tx = self._close_cad(temp_gnucash_for_close_books)
        try:
            equity_split = next(
                s for s in tx.GetSplitList()
                if s.GetAccount().GetName() == "CAD"
            )
            v = equity_split.GetValue()
            assert Fraction(v.num(), v.denom()) == Fraction(-5850)
        finally:
            repo.close()

    def test_income_splits_negate_balance(self, temp_gnucash_for_close_books):
        """Each Income account split = -balance (positive, to zero out credit)"""
        repo, tx = self._close_cad(temp_gnucash_for_close_books)
        try:
            expected = {
                "Base": Fraction(6000),   # -(-6000)
                "Bonus": Fraction(1000),  # -(-1000)
                "Interest": Fraction(200),# -(-200)
            }
            for split in tx.GetSplitList():
                name = split.GetAccount().GetName()
                if name in expected:
                    v = split.GetValue()
                    actual = Fraction(v.num(), v.denom())
                    assert actual == expected[name], (
                        f"{name}: expected {expected[name]}, got {actual}"
                    )
        finally:
            repo.close()

    def test_expense_splits_negate_balance(self, temp_gnucash_for_close_books):
        """Each Expense account split = -balance (negative, to zero out debit)"""
        repo, tx = self._close_cad(temp_gnucash_for_close_books)
        try:
            expected = {
                "Train": Fraction(-150),   # -(+150)
                "Flight": Fraction(-800),  # -(+800)
                "Groceries": Fraction(-400), # -(+400)
            }
            for split in tx.GetSplitList():
                name = split.GetAccount().GetName()
                if name in expected:
                    v = split.GetValue()
                    actual = Fraction(v.num(), v.denom())
                    assert actual == expected[name], (
                        f"{name}: expected {expected[name]}, got {actual}"
                    )
        finally:
            repo.close()

    def test_description_and_date(self, temp_gnucash_for_close_books):
        """Description = 'Closing entry (CAD)', date = 2024-12-31"""
        repo, tx = self._close_cad(temp_gnucash_for_close_books)
        try:
            assert tx.GetDescription() == "Closing entry (CAD)"
            d = tx.GetDate()
            assert (d.year, d.month, d.day) == (2024, 12, 31)
        finally:
            repo.close()
