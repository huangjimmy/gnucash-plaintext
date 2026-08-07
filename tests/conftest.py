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


def swallow_oserror(func, fallback=None):
    """`func` with an OSError treated as "the fd is already gone".

    Used for the pytest teardown paths that restore or read a file descriptor
    GnuCash may have closed under them. Only OSError is swallowed: anything
    else is a real fault and still propagates.

    `fallback` is what the call returns instead. None suits the restoring
    methods, which are called for their effect; a method whose result is used
    needs an empty value of the right type, or the failure moves one frame
    along instead of being handled.
    """
    def _safe(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except OSError:
            return fallback
    # Readable from outside, so a test can check which fallback a method was
    # given without reaching into pytest's internals to provoke the failure.
    _safe._gnc_fallback = fallback
    return _safe


def _harden_pytest_capture_teardown():
    """Stop a GnuCash fd-close from failing the run on a pytest teardown artifact.

    GnuCash's backend churns file descriptors during a run — it opens and removes
    a per-session `.LCK` lock file and writes per-session `.log` files for every
    book session — and intermittently closes the fd pytest saved when it set up
    fd-level output capture. At the end of the run, pytest's capture teardown
    (`FDCapture.done()`) restores that fd with `os.dup2(saved_fd, 0)`, which then
    raises `OSError: [Errno 9] Bad file descriptor` AFTER every test has already
    passed — failing the whole run on a teardown artifact. It is a probabilistic
    fd collision, not version-specific (seen on Ubuntu 20.04/Py3.8 and Debian
    11/Py3.9); its odds rise with the number of session open/close cycles a suite
    does.

    Default fd-level capture is kept (it shields pytest's live output from the
    fd churn — sys-level capture would route live output to the real fd and
    internal-error pytest on a mid-run close, which is worse). Instead, wrap the
    capture classes' fd-restoring methods so a closed fd is swallowed during
    teardown rather than crashing the process. Targeted (only OSError),
    defensive (no-ops if the pytest internals differ), and verified
    deterministically by closing pytest's own saved stdin fd: crash without
    this, clean exit with it. No test uses the fd-level capture fixtures
    (capfd/capfdbinary), so nothing depends on a perfectly-restored fd at exit.

    `done()` is the end-of-run path. `suspend()`/`resume()` are the per-test
    ones: `CaptureManager.item_capture` is a generator context manager that
    calls `suspend_global_capture` in its `finally`, so a saved fd GnuCash has
    closed surfaces as `contextlib.py __exit__ -> next(self.gen) -> OSError`
    and fails a test whose assertions all passed.

    `snap()` is the third, and it is the one that reads rather than restores:
    the same generator calls `read_global_capture()` after that `finally`, and
    the end of the run calls it again through `pop_outerr_to_orig`. It reads
    the capture temp file, so a closed descriptor raises there with the same
    `contextlib` frame — the shape seen on Ubuntu 20.04 / Py3.8, where 2807
    tests errored behind one closed fd. Its result is used, so it falls back to
    an empty capture of the right type rather than None: `bytes` for the binary
    classes, `str` for the rest. What is lost is the captured output of a test
    pytest is about to report on, which is empty far more often than not and
    never the reason a run is being read.

    Both shapes are the ten distro containers running at once, where the fd
    churn is heaviest; the same suite passes on its own.
    """
    try:
        from _pytest import capture as _cap
    except Exception:
        return

    for name in ('FDCaptureBinary', 'FDCapture', 'SysCaptureBinary', 'SysCapture'):
        cls = getattr(_cap, name, None)
        if cls is None or getattr(cls, '_gnc_hardened', False):
            continue
        for method in ('done', 'suspend', 'resume'):
            original = getattr(cls, method, None)
            if original is not None:
                setattr(cls, method, swallow_oserror(original))
        snap = getattr(cls, 'snap', None)
        if snap is not None:
            cls.snap = swallow_oserror(snap, b'' if name.endswith('Binary') else '')
        cls._gnc_hardened = True


def _harden_pytest_logging_teardown():
    """Same GnuCash fd-churn flake as `_harden_pytest_capture_teardown`, via a
    different teardown path: pytest's logging plugin closes its `log_file_handler`
    (a `logging.FileHandler`) in `pytest_unconfigure`. If GnuCash has meanwhile
    closed that fd, `stream.close()` raises `OSError: [Errno 9] Bad file
    descriptor` AFTER every test passed — failing the whole run on a teardown
    artifact (seen on Ubuntu 20.04 / Py3.8). Swallow OSError from logging handler
    close during teardown, mirroring the capture hardening. Targeted (only
    OSError, only on close) and defensive."""
    import logging as _logging

    for cls in (_logging.FileHandler, _logging.StreamHandler):
        if getattr(cls, '_gnc_close_hardened', False):
            continue
        cls.close = swallow_oserror(cls.close)
        cls._gnc_close_hardened = True


_harden_pytest_capture_teardown()
_harden_pytest_logging_teardown()


# Monkey-patch gnucash.Session so every save() first deletes any backup and
# log file that would collide on the current second's timestamp.  GnuCash
# names backups as <path>.<YYYYMMDDHHMMSS>.gnucash; two saves in the same
# wall-clock second hit ERR_FILEIO_BACKUP_ERROR.  By clearing both files
# right before the real save we eliminate the collision without needing
# time.sleep(1) between saves.  (This patch is test-only — production code
# is not affected.)
def _patch_session_save():
    import glob as _glob
    import os as _os
    import time as _time

    import gnucash as _gnucash

    _orig_init = _gnucash.Session.__init__

    def _patched_init(self, url, *args, **kwargs):
        self.__gnc_url = url
        return _orig_init(self, url, *args, **kwargs)

    _gnucash.Session.__init__ = _patched_init

    _orig_save = _gnucash.Session.save

    def _patched_save(self):
        if hasattr(self, '__gnc_url'):
            path = self.__gnc_url.replace('xml://', '', 1)
            ts = _time.strftime('%Y%m%d%H%M%S')
            for pattern in [f'{path}.{ts}.gnucash',
                            f'{path}.{ts}.log']:
                for f in _glob.glob(pattern):
                    _os.unlink(f)
        return _orig_save(self)

    _gnucash.Session.save = _patched_save


_patch_session_save()


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
def import_new_plaintext_with_transaction():
    """Path to plaintext fixture with accounts + one transaction, for --new CLI tests."""
    test_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(test_dir, 'fixtures', 'import_new_with_transaction.txt')


@pytest.fixture
def import_new_plaintext_accounts_only():
    """Path to plaintext fixture with accounts only (no transactions), for --new CLI tests."""
    test_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(test_dir, 'fixtures', 'import_new_accounts_only.txt')


@pytest.fixture
def import_new_plaintext_invalid_account_type():
    """Path to plaintext fixture with an unrecognised account type.

    Used to test --new cleanup: the importer raises a KeyError in ACCT_TYPE_MAP
    when it encounters 'INVALID_ACCOUNT_TYPE', exercising the failure cleanup path.
    """
    test_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(test_dir, 'fixtures', 'import_new_invalid_account_type.txt')


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


@pytest.fixture
def temp_gnucash_account_balance():
    """
    GnuCash file for account-balance tests, loaded from plaintext fixture.

    Covers all 5 account types (Asset, Liability, Equity, Income, Expense)
    in two currencies (CAD and HKD), with sub-accounts under Expenses:Food
    and Income:HKDIncome.

    Account structure:
      Assets:Bank:Checking          CAD   (500 opening + 3000 salary - 50 groceries - 30 dining = 3420)
      Assets:Bank:HKD               HKD   (8000 opening + 400 freelance + 600 dividends - 300 transport = 8700)
      Liabilities:CreditCard        CAD   (200 opening)
      Liabilities:HKDLoan           HKD   (500 opening)
      Equity:Opening                CAD   (balancing)
      Income:Salary                 CAD   (-3000)
      Income:HKDIncome:Freelance    HKD   (-400)
      Income:HKDIncome:Dividends    HKD   (-600)
      Expenses:Food:Groceries       CAD   (50)
      Expenses:Food:Dining          CAD   (30)
      Expenses:HKDExpenses:Transport HKD  (300)

    See tests/fixtures/account_balance_test_data.txt for the plaintext source.
    """
    from repositories.gnucash_repository import GnuCashRepository
    from services.conflict_resolver import ResolutionStrategy
    from use_cases.import_transactions import ImportTransactionsUseCase

    test_dir = os.path.dirname(os.path.abspath(__file__))
    plaintext_path = os.path.join(test_dir, 'fixtures', 'account_balance_test_data.txt')

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

        yield path

    finally:
        if os.path.exists(path):
            os.unlink(path)
        lock_path = path + '.LCK'
        if os.path.exists(lock_path):
            os.unlink(lock_path)
