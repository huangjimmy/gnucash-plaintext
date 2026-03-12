"""
Pytest fixtures for GnuCash testing

Provides temp GnuCash file creation for testing without mocks.
Tests run in Docker with real GnuCash Python bindings.
"""

import os
import sys
import tempfile
from datetime import date

import pytest


def find_account(root_account, account_path):
    """
    Find account by full path (e.g., 'Assets:Bank:Checking').

    Helper function for tests - replicates utils.find_account logic
    without importing old code into new tests.
    """
    if account_path == "" or account_path == "Root Account":
        return root_account

    names = account_path.split(":")

    def find_child(account, name):
        for child in account.get_children_sorted():
            if child.GetName() == name:
                return child
        return None

    acc = root_account
    for name in names:
        acc = find_child(acc, name)
        if acc is None:
            return None
    return acc


@pytest.fixture
def temp_gnucash_file():
    """
    Create a temporary GnuCash file for testing.

    Yields the file path, then cleans up after the test.

    Example:
        def test_something(temp_gnucash_file):
            repo = GnuCashRepository(temp_gnucash_file)
            # ... test code
    """
    # Create temp file path (don't create the file yet)
    fd, path = tempfile.mkstemp(suffix='.gnucash')
    os.close(fd)
    os.unlink(path)  # Delete the empty file so GnuCash can create it

    try:
        # Import GnuCash modules
        import gnucash
        from gnucash import Account, GncNumeric, Session, Split, Transaction

        # Determine GnuCash API version for session API
        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{path}', SessionOpenMode.SESSION_NEW_STORE)
        except ImportError:
            # Fall back to older GnuCash API (< 4.0)
            session = Session(f'xml://{path}', is_new=True)

        book = session.book
        root = book.get_root_account()
        commod_table = book.get_table()
        cad = commod_table.lookup('CURRENCY', 'CAD')

        # Create basic account hierarchy
        # Assets
        assets = Account(book)
        assets.SetName('Assets')
        assets.SetType(gnucash.ACCT_TYPE_ASSET)
        assets.SetCommodity(cad)
        root.append_child(assets)

        # Assets:Bank
        bank = Account(book)
        bank.SetName('Bank')
        bank.SetType(gnucash.ACCT_TYPE_BANK)
        bank.SetCommodity(cad)
        assets.append_child(bank)

        # Assets:Bank:Checking
        checking = Account(book)
        checking.SetName('Checking')
        checking.SetType(gnucash.ACCT_TYPE_BANK)
        checking.SetCommodity(cad)
        bank.append_child(checking)

        # Expenses
        expenses = Account(book)
        expenses.SetName('Expenses')
        expenses.SetType(gnucash.ACCT_TYPE_EXPENSE)
        expenses.SetCommodity(cad)
        root.append_child(expenses)

        # Expenses:Groceries
        groceries = Account(book)
        groceries.SetName('Groceries')
        groceries.SetType(gnucash.ACCT_TYPE_EXPENSE)
        groceries.SetCommodity(cad)
        expenses.append_child(groceries)

        # Expenses:Dining
        dining = Account(book)
        dining.SetName('Dining')
        dining.SetType(gnucash.ACCT_TYPE_EXPENSE)
        dining.SetCommodity(cad)
        expenses.append_child(dining)

        # Save and close
        session.save()
        session.end()

        yield path

    finally:
        # Cleanup
        if os.path.exists(path):
            os.unlink(path)
        # Also cleanup lock file if it exists
        lock_path = path + '.LCK'
        if os.path.exists(lock_path):
            os.unlink(lock_path)


@pytest.fixture
def temp_gnucash_with_transactions():
    """
    Create a temporary GnuCash file with sample transactions.

    Yields the file path, then cleans up after the test.

    Sample transactions:
    - 2024-01-15: Groceries $50
    - 2024-01-20: Dining $30
    - 2024-01-25: Groceries $45 (different amount, same accounts)
    """
    fd, path = tempfile.mkstemp(suffix='.gnucash')
    os.close(fd)
    os.unlink(path)  # Delete the empty file so GnuCash can create it

    try:
        import gnucash
        from gnucash import Account, GncNumeric, Session, Split, Transaction

        # Open session
        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{path}', SessionOpenMode.SESSION_NEW_STORE)
        except ImportError:
            # Fall back to older GnuCash API (< 4.0)
            session = Session(f'xml://{path}', is_new=True)

        book = session.book
        root = book.get_root_account()
        commod_table = book.get_table()
        cad = commod_table.lookup('CURRENCY', 'CAD')

        # Create accounts
        assets = Account(book)
        assets.SetName('Assets')
        assets.SetType(gnucash.ACCT_TYPE_ASSET)
        assets.SetCommodity(cad)
        root.append_child(assets)

        bank = Account(book)
        bank.SetName('Bank')
        bank.SetType(gnucash.ACCT_TYPE_BANK)
        bank.SetCommodity(cad)
        assets.append_child(bank)

        checking = Account(book)
        checking.SetName('Checking')
        checking.SetType(gnucash.ACCT_TYPE_BANK)
        checking.SetCommodity(cad)
        bank.append_child(checking)

        expenses = Account(book)
        expenses.SetName('Expenses')
        expenses.SetType(gnucash.ACCT_TYPE_EXPENSE)
        expenses.SetCommodity(cad)
        root.append_child(expenses)

        groceries = Account(book)
        groceries.SetName('Groceries')
        groceries.SetType(gnucash.ACCT_TYPE_EXPENSE)
        groceries.SetCommodity(cad)
        expenses.append_child(groceries)

        dining = Account(book)
        dining.SetName('Dining')
        dining.SetType(gnucash.ACCT_TYPE_EXPENSE)
        dining.SetCommodity(cad)
        expenses.append_child(dining)

        # Transaction 1: 2024-01-15 Groceries $50
        tx1 = Transaction(book)
        tx1.BeginEdit()
        tx1.SetCurrency(cad)
        tx1.SetDate(15, 1, 2024)
        tx1.SetDescription("Grocery shopping")

        split1_1 = Split(book)
        split1_1.SetParent(tx1)
        split1_1.SetAccount(groceries)
        split1_1.SetValue(GncNumeric(5000, 100))

        split1_2 = Split(book)
        split1_2.SetParent(tx1)
        split1_2.SetAccount(checking)
        split1_2.SetValue(GncNumeric(-5000, 100))

        tx1.CommitEdit()

        # Transaction 2: 2024-01-20 Dining $30
        tx2 = Transaction(book)
        tx2.BeginEdit()
        tx2.SetCurrency(cad)
        tx2.SetDate(20, 1, 2024)
        tx2.SetDescription("Restaurant")

        split2_1 = Split(book)
        split2_1.SetParent(tx2)
        split2_1.SetAccount(dining)
        split2_1.SetValue(GncNumeric(3000, 100))

        split2_2 = Split(book)
        split2_2.SetParent(tx2)
        split2_2.SetAccount(checking)
        split2_2.SetValue(GncNumeric(-3000, 100))

        tx2.CommitEdit()

        # Transaction 3: 2024-01-25 Groceries $45
        tx3 = Transaction(book)
        tx3.BeginEdit()
        tx3.SetCurrency(cad)
        tx3.SetDate(25, 1, 2024)
        tx3.SetDescription("More groceries")

        split3_1 = Split(book)
        split3_1.SetParent(tx3)
        split3_1.SetAccount(groceries)
        split3_1.SetValue(GncNumeric(4500, 100))

        split3_2 = Split(book)
        split3_2.SetParent(tx3)
        split3_2.SetAccount(checking)
        split3_2.SetValue(GncNumeric(-4500, 100))

        tx3.CommitEdit()

        # Save and close
        session.save()
        session.end()

        yield path

    finally:
        if os.path.exists(path):
            os.unlink(path)
        lock_path = path + '.LCK'
        if os.path.exists(lock_path):
            os.unlink(lock_path)


@pytest.fixture
def temp_gnucash_for_close_books():
    """
    GnuCash file for close-books testing, imported from plaintext.

    Source: tests/fixtures/close_books_test_data.txt

    Account structure (2-level sub-accounts):
        Income:Salary:Base    (CAD) — -6000 CAD  (two months × 3000)
        Income:Salary:Bonus   (CAD) — -1000 CAD  (one-time bonus)
        Income:Interest       (CAD) —  -200 CAD
        Expenses:Travel:Train (CAD) —  +150 CAD
        Expenses:Travel:Flight(CAD) —  +800 CAD
        Expenses:Groceries    (CAD) —  +400 CAD
        Income:Freelance      (USD) —  -500 USD
        Expenses:SaaS         (USD) —  +100 USD

    Expected closing amounts:
        CAD net income = 7200 - 1350 = 5850
        Equity:Retained Earnings:CAD → -5850 (credit)
        USD net income = 500 - 100 = 400
        Equity:Retained Earnings:USD → -400 (credit)
    """
    from repositories.gnucash_repository import GnuCashRepository
    from services.conflict_resolver import ResolutionStrategy
    from use_cases.import_transactions import ImportTransactionsUseCase

    test_dir = os.path.dirname(os.path.abspath(__file__))
    plaintext_path = os.path.join(test_dir, 'fixtures', 'close_books_test_data.txt')

    fd, path = tempfile.mkstemp(suffix='.gnucash')
    os.close(fd)
    os.unlink(path)

    try:
        GnuCashRepository.create_new_file(path)

        repo = GnuCashRepository(path)
        repo.open()
        try:
            use_case = ImportTransactionsUseCase(repo)
            use_case.import_from_file(plaintext_path, ResolutionStrategy.SKIP)
            repo.save()
        finally:
            repo.close()

        import time
        time.sleep(1)  # Ensure tests that save again use a different backup timestamp

        yield path

    finally:
        if os.path.exists(path):
            os.unlink(path)
        lock_path = path + '.LCK'
        if os.path.exists(lock_path):
            os.unlink(lock_path)
        import glob as glob_module
        for backup in glob_module.glob(path + '.*.gnucash'):
            os.unlink(backup)


@pytest.fixture
def temp_gnucash_comprehensive():
    """
    Create a comprehensive GnuCash file from plaintext test data.

    This fixture generates a GnuCash file from tests/fixtures/comprehensive_test_data.txt which contains:
    - Multiple currencies (CAD, USD, JPY, HKD, KRW)
    - Non-currency commodities (Membership Rewards)
    - International account names (Chinese, Japanese, Korean)
    - Complex multi-currency transactions with forex
    - Transaction notes, split-level memo and action fields
    - Placeholder accounts, account metadata
    - 13 comprehensive transactions covering real-world scenarios

    To add more test cases, edit tests/fixtures/comprehensive_test_data.txt.

    Yields the file path, then cleans up after the test.

    Example:
        def test_something(temp_gnucash_comprehensive):
            repo = GnuCashRepository(temp_gnucash_comprehensive)
            # File has 5 currencies, 13 transactions
    """
    from repositories.gnucash_repository import GnuCashRepository
    from services.conflict_resolver import ResolutionStrategy
    from use_cases.import_transactions import ImportTransactionsUseCase

    # Get path to plaintext source file
    test_dir = os.path.dirname(os.path.abspath(__file__))
    plaintext_path = os.path.join(test_dir, 'fixtures', 'comprehensive_test_data.txt')

    # Create temp file path (but don't create the file yet)
    fd, path = tempfile.mkstemp(suffix='.gnucash')
    os.close(fd)
    os.unlink(path)  # Delete the temp file so create_new_file can create it

    try:
        # Create new GnuCash file
        GnuCashRepository.create_new_file(path)

        # Import from plaintext
        repo = GnuCashRepository(path)
        repo.open()
        try:
            use_case = ImportTransactionsUseCase(repo)
            use_case.import_from_file(plaintext_path, ResolutionStrategy.SKIP)
            repo.save()
        finally:
            repo.close()

        yield path

    finally:
        # Cleanup
        if os.path.exists(path):
            os.unlink(path)
        lock_path = path + '.LCK'
        if os.path.exists(lock_path):
            os.unlink(lock_path)
