"""
GnuCash repository for file operations and data access.

Provides high-level interface for working with GnuCash files.
Manages sessions, transactions, accounts, and file operations.
"""

import gzip
import os
import re
import shutil
import tempfile
import zlib
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Dict, List, Optional

from gnucash import Account, Query, Session, Split, Transaction
from gnucash.gnucash_core import GnuCashBackendException

from infrastructure.gnucash.engine import load_gnc_engine
from infrastructure.gnucash.kvp import forget_custom_key_changes
from infrastructure.gnucash.utils import transaction_under_construction

if TYPE_CHECKING:
    from services.ledger_validator import ValidationResult


class BookUnavailableError(RuntimeError):
    """The book could not be opened, said in words rather than a backend code.

    GnuCash answers every one of these the same way — `call to begin resulted
    in the following errors, ERR_BACKEND_LOCKED` — and nothing translated it,
    so a book open in GnuCash, which is the commonest situation there is, met
    every command in this tool as a traceback with no message at all.
    """


_LOCKED = (
    'The book is locked, which means GnuCash has it open — or a run '
    'that did not finish left the lock behind. Close it in GnuCash, '
    'or delete the `.LCK` and `.LNK` files beside the book, and try '
    'again.')

_NO_SUCH_BOOK = (
    'There is no file at that path. Check the path; a new book is created '
    'with `import --new`.')

_A_FILE_IS_ALREADY_THERE = (
    'There is already a file at that path, and a new book is not written over '
    'it. Choose a path where no file is.')

_NO_DIRECTORY_FOR_THE_BOOK = (
    'The directory the new book would go in does not exist. Create it first, '
    'or choose a path in a directory that does.')

_NOT_A_BOOK = (
    'That is not a GnuCash book this tool can read. It reads the XML '
    'file GnuCash writes by default; a directory, a plaintext ledger '
    'or a book kept in a database is not one.')

_CUT_SHORT = (
    'The book ends partway through: the file stops before the end GnuCash '
    'writes, which is what a copy or a save that did not finish leaves. It is '
    'not read, because what is there is not the whole book. GnuCash keeps a '
    'copy from before each save beside the book, named like '
    '`book.gnucash.20260914120000.gnucash`.')


def _what_gnucash_meant(error: Exception, creating: bool = False) -> str:
    """A backend refusal, as the sentence that says which state the book is in."""
    text = str(error)
    if 'ERR_BACKEND_LOCKED' in text:
        return _LOCKED
    if 'ERR_BACKEND_STORE_EXISTS' in text:
        return _A_FILE_IS_ALREADY_THERE
    if 'ERR_FILEIO_FILE_NOT_FOUND' in text:
        return _NO_DIRECTORY_FOR_THE_BOOK if creating else _NO_SUCH_BOOK
    if 'ERR_BACKEND_READONLY' in text:
        return (
            'The book is somewhere this command cannot write. GnuCash locks a '
            'book by creating files beside it, so a read-only directory '
            'refuses even a command that only reads. Copy the book somewhere '
            'writable, or get write access to the directory it is '
            'in.')
    if 'ERR_BACKEND_NO_HANDLER' in text:
        return _NOT_A_BOOK
    return f'GnuCash could not open the book: {text}'


def _why_the_file_is_not_a_whole_book(path: str) -> Optional[str]:
    """The sentence refusing a file GnuCash would read as a book holding nothing, or None.

    From GnuCash 4.4 on, a file of no bytes, an XML file in GnuCash's old `<gnc>`
    format and a book cut short all open with no error, as a book with no
    accounts, and the session records nothing: `get_error()` answers 0. GnuCash
    3.4 and 3.8 refuse all three
    (`tests/research/what_gnucash_says_to_an_empty_file_or_a_book_cut_short_probe.py`,
    `whether_a_session_records_a_book_it_could_not_parse_probe.py`). Read as
    empty, `export` wrote a ledger holding nothing and said it had exported it.

    A book GnuCash writes is XML whose root is `gnc-v2`, and it ends with
    `</gnc-v2>` — followed by blank lines on 5.10 and by three comment lines on
    3.4 — compressed or not. Anything that is not XML at all, a plaintext
    ledger or a directory, is left to GnuCash, whose refusal is translated
    above.
    """
    if not os.path.isfile(path):
        return None
    size = os.path.getsize(path)
    if size == 0:
        return _NOT_A_BOOK
    with open(path, 'rb') as raw:
        head = raw.read(1024)
        raw.seek(max(0, size - 1024))
        tail = raw.read()
    compressed = head[:2] == b'\x1f\x8b'
    if compressed:
        head = b''
        try:
            with gzip.open(path, 'rb') as stream:
                for chunk in iter(lambda: stream.read(1 << 20), b''):
                    head = head if len(head) >= 1024 else (head + chunk)[:1024]
                    tail = (tail + chunk)[-1024:]
        except EOFError:
            return _CUT_SHORT
        except (OSError, zlib.error):
            return _NOT_A_BOOK
    if not head.lstrip().startswith(b'<?xml'):
        return None
    if b'<gnc-v2' not in head:
        return _NOT_A_BOOK
    if b'</gnc-v2>' not in tail:
        return _CUT_SHORT
    return None


@lru_cache(maxsize=1)
def _a_session_without_its_lock_closes_another_file() -> bool:
    """Whether this GnuCash's XML backend closes a lock it never took when a session ends.

    On 3.4, 3.8 and 4.4 a session whose backend took no lock — a book opened
    read-only, and on 3.4 and 3.8 a missing or a locked book, or a new book
    where a file already is or in a directory that does not exist — still
    closes its lock descriptor when it ends, and that field holds the number
    the previous backend at the same address used. Whatever file has that number by then is
    closed. 4.8 and later close nothing of the kind. Measured on all eleven
    builds (CLAUDE.md finding 27).
    """
    found = re.match(r'(\d+)\.(\d+)', (load_gnc_engine().gnc_version() or b'').decode())
    return found is not None and (int(found.group(1)), int(found.group(2))) < (4, 8)


class SessionMode:
    """Session opening modes"""
    READ_ONLY = "read_only"
    NORMAL = "normal"
    NEW = "new"


#: What a service kept about the books opened before this one, each a function
#: that forgets it, run whenever a book is opened. A service registers its own:
#: the repository keeps no business state and knows nothing of what is kept.
WHAT_TO_FORGET_WHEN_A_BOOK_OPENS: List[Callable[[], None]] = []


class GnuCashRepository:
    """Repository for GnuCash file operations"""

    def __init__(self, file_path: str):
        """
        Initialize repository for a GnuCash file.

        Args:
            file_path: Path to GnuCash XML file
        """
        self.file_path = file_path
        self.session = None
        self._book = None
        # The directory holding the copy a book to read was opened from, on a
        # GnuCash where `_a_session_without_its_lock_closes_another_file`.
        self._private_copy = None
        # Whether the book was opened to read. Asked by `save`, which a
        # read-only session on GnuCash 4.8 and later carries out without
        # complaint where the private copy on 3.4 refused it.
        self._read_only = False

    def open(self, mode: str = SessionMode.NORMAL):
        """
        Open GnuCash file session.

        Args:
            mode: Session mode (READ_ONLY, NORMAL, or NEW)
        """
        if self.session is not None:
            raise RuntimeError("Session already open")
        self._read_only = mode == SessionMode.READ_ONLY
        for forget in WHAT_TO_FORGET_WHEN_A_BOOK_OPENS:
            forget()

        uri = f"xml://{self.file_path}"

        # Where a session that took no lock closes a file of the process's
        # when it ends, no such session is made. What GnuCash would refuse
        # before taking a lock is refused here first: a missing or a locked
        # book, and a new book where a file already is or in a directory that
        # does not exist. A book to read is opened for writing as a private
        # copy, whose backend takes a lock of its own and closes only that;
        # the book itself gets no lock, as a read-only open takes none, and
        # nothing is saved from the copy.
        creating = mode == SessionMode.NEW
        if not creating:
            refusal = _why_the_file_is_not_a_whole_book(self.file_path)
            if refusal is not None:
                raise BookUnavailableError(refusal)
        if _a_session_without_its_lock_closes_another_file():
            if creating:
                if os.path.lexists(self.file_path):
                    raise BookUnavailableError(_A_FILE_IS_ALREADY_THERE)
                if not os.path.isdir(os.path.dirname(os.path.abspath(self.file_path))):
                    raise BookUnavailableError(_NO_DIRECTORY_FOR_THE_BOOK)
            elif not os.path.lexists(self.file_path):
                raise BookUnavailableError(_NO_SUCH_BOOK)
            elif mode == SessionMode.NORMAL and os.path.lexists(f'{self.file_path}.LCK'):
                raise BookUnavailableError(_LOCKED)
            elif mode == SessionMode.READ_ONLY and os.path.isfile(self.file_path):
                uri = self._a_private_copy()
                mode = SessionMode.NORMAL

        # Use version-specific session API (try new API first). A refusal is
        # translated here rather than at each of the thirty commands: some
        # wrap this call and print `str(e)`, some do not wrap it at all, and
        # the reader met either the backend's own `ERR_BACKEND_LOCKED` or a
        # traceback, depending on which command they had run.
        #
        # Whatever stops the open, the copy goes with it: a caller whose
        # `open()` raised has no session to close.
        opened = False
        try:
            try:
                from gnucash import SessionOpenMode

                if mode == SessionMode.READ_ONLY:
                    session_mode = SessionOpenMode.SESSION_READ_ONLY
                elif mode == SessionMode.NEW:
                    session_mode = SessionOpenMode.SESSION_NEW_STORE
                else:
                    session_mode = SessionOpenMode.SESSION_NORMAL_OPEN

                self.session = Session(uri, session_mode)
            except ImportError:
                # Fall back to older GnuCash API (< 4.0)
                if mode == SessionMode.READ_ONLY:
                    self.session = Session(uri, ignore_lock=True)
                elif mode == SessionMode.NEW:
                    self.session = Session(uri, is_new=True)
                else:
                    self.session = Session(uri)
            opened = True
        except GnuCashBackendException as e:
            raise BookUnavailableError(_what_gnucash_meant(e, creating)) from e
        finally:
            if not opened:
                self._discard_the_private_copy()

        self._book = self.session.book

    def _a_private_copy(self) -> str:
        """The book copied into a directory of its own, as the URI to open it by.

        The directory is recorded as this repository's only once the copy is
        in it. `open` discards the copy in a `finally` that begins *after*
        this call, so a copy that fails partway — a full filesystem is the
        way — would otherwise leave a `gnucash-read-only-` directory behind
        with nothing left holding a reference to it.
        """
        try:
            directory = tempfile.mkdtemp(prefix='gnucash-read-only-')
        except OSError as trouble:
            # Below GnuCash 4.8 every book read goes through a copy, so a
            # temporary directory that cannot be written stops an ordinary
            # `export`. Said as a sentence, like every other reason a book
            # will not open; raw it was an `OSError` traceback, since
            # `cli.main._Cli.invoke` translates four exception types and this
            # is none of them.
            raise BookUnavailableError(
                f'The book has to be copied to be read on this GnuCash, and the '
                f'copy could not be made: {trouble}. Set TMPDIR to a directory '
                f'with room in it, or read the book with a newer GnuCash.'
            ) from trouble
        # The book was read whole a moment ago, by the check `open` makes
        # before anything else, so copying it meets nothing that read did not.
        copy = os.path.join(directory, os.path.basename(self.file_path))
        try:
            shutil.copyfile(self.file_path, copy)
        except BaseException:  # pragma: no cover - a disk that fills between two calls
            # The directory is this repository's only once the copy is in it,
            # so `open`'s own `finally` cannot discard one left by a copy that
            # failed — nothing would be holding it.
            shutil.rmtree(directory, ignore_errors=True)
            raise
        self._private_copy = directory
        return f'xml://{copy}'

    def _discard_the_private_copy(self):
        if self._private_copy is not None:
            shutil.rmtree(self._private_copy, ignore_errors=True)
            self._private_copy = None

    def close(self):
        """Close GnuCash file session, and free the book it loaded.

        `end()` closes the file and leaves the book in memory; `destroy()` ends
        the session and frees the book. Ended alone, every book a process opened
        stayed until the process exited: 100 opens of a 300-transaction book
        kept 48.5 MiB, and the test suite, which opens about 12,000 books in one
        process, grew to 1.7 GB.

        `destroy()` is called alone, never after `end()`. On GnuCash 3.4, 3.8
        and 4.4 ending a session twice closes the book's lock file twice, by
        its number, and the second close takes any file opened under that
        number in between (CLAUDE.md finding 26).

        Nothing read from the book may be used after this: its accounts,
        commodities and transactions are freed with it.

        And the log of KVP changes an index of the book was kept from
        (`log_custom_key_changes`) is started afresh. It is the book's: kept,
        every command in a long-lived process, the suite's among them, added
        to it with nothing ever taking it away.
        """
        if self.session is not None:
            session = self.session
            self.session = None
            self._book = None
            session.destroy()
        forget_custom_key_changes()
        self._discard_the_private_copy()

    def save(self):
        """Save changes to GnuCash file."""
        if self.session is None:
            raise RuntimeError("No session open")
        if self._read_only:
            raise RuntimeError("The book was opened read-only, so nothing is saved to it")
        self.session.save()

    @property
    def book(self):
        """Get book object."""
        if self._book is None:
            raise RuntimeError("No session open")
        return self._book

    def __enter__(self):
        """Context manager entry."""
        if self.session is None:
            self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    # Account operations

    def get_root_account(self) -> Account:
        """
        Get root account.

        Returns:
            Root Account object
        """
        return self.book.get_root_account()

    def get_account(self, account_path: str) -> Optional[Account]:
        """
        Get account by full path.

        Args:
            account_path: Full account path (e.g., "Assets:Bank:Checking")

        Returns:
            Account object or None if not found
        """
        from infrastructure.gnucash.utils import find_account

        root = self.get_root_account()
        return find_account(root, account_path)

    def get_all_accounts(self) -> List[Account]:
        """
        Get all accounts (excluding root).

        Returns:
            List of Account objects
        """
        accounts = []
        root = self.get_root_account()

        def visit(account: Account):
            if not account.is_root():
                accounts.append(account)

            for child in account.get_children_sorted():
                visit(child)

        visit(root)
        return accounts

    def get_accounts_by_type(self, account_type: int) -> List[Account]:
        """
        Get accounts by GnuCash type.

        Args:
            account_type: GnuCash account type constant

        Returns:
            List of matching accounts
        """
        all_accounts = self.get_all_accounts()
        return [acc for acc in all_accounts if acc.GetType() == account_type]

    def create_account(
        self,
        name: str,
        account_type: int,
        parent_path: Optional[str] = None,
        currency_code: str = "USD"
    ) -> Account:
        """
        Create a new account.

        Args:
            name: Account name
            account_type: GnuCash account type constant
            parent_path: Parent account path (None for root-level)
            currency_code: Currency code (default USD)

        Returns:
            Created Account object
        """
        # Get parent
        if parent_path:
            parent = self.get_account(parent_path)
            if parent is None:
                raise ValueError(f"Parent account not found: {parent_path}")
        else:
            parent = self.get_root_account()

        # Get currency
        commod_table = self.book.get_table()
        currency = commod_table.lookup('CURRENCY', currency_code)

        # Create account
        account = Account(self.book)
        account.SetName(name)
        account.SetType(account_type)
        account.SetCommodity(currency)
        parent.append_child(account)

        return account

    # Transaction operations

    def get_all_transactions(self) -> List[Transaction]:
        """
        Get all transactions in the book.

        Returns:
            List of Transaction objects
        """
        query = Query()
        query.search_for('Trans')
        query.set_book(self.book)
        result = query.run()

        # Wrap SwigPyObjects in Transaction objects
        return [Transaction(instance=tx) for tx in result]

    def get_transactions_by_account(self, account: Account) -> List[Transaction]:
        """
        Get all transactions involving an account.

        Args:
            account: Account to search for

        Returns:
            List of Transaction objects
        """
        # By guid, not by `in`: two wrappers of one transaction compare unequal
        # on GnuCash 3.4, so a transaction with two splits on the account was
        # listed twice there and once on 5.10.
        transactions = []
        listed = set()
        for split in account.GetSplitList():
            tx = split.GetParent()
            guid = tx.GetGUID().to_string()
            if guid not in listed:
                listed.add(guid)
                transactions.append(tx)

        return transactions

    def get_transactions_by_date_range(
        self,
        start_date: str,
        end_date: str
    ) -> List[Transaction]:
        """
        Get transactions within date range.

        Args:
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format

        Returns:
            List of Transaction objects
        """
        from datetime import datetime

        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")

        all_transactions = self.get_all_transactions()
        filtered = []

        for tx in all_transactions:
            tx_date = tx.GetDate()
            tx_datetime = datetime(tx_date.year, tx_date.month, tx_date.day)

            if start <= tx_datetime <= end:
                filtered.append(tx)

        return filtered

    def create_transaction(
        self,
        description: str,
        date_tuple: tuple,
        splits_data: List[Dict],
        currency_code: str = "USD"
    ) -> Transaction:
        """
        Create a new transaction.

        Args:
            description: Transaction description
            date_tuple: Date as (day, month, year)
            splits_data: List of dicts with 'account_path' and 'value' (GncNumeric)
            currency_code: Currency code

        Returns:
            Created Transaction object
        """
        # Get currency
        commod_table = self.book.get_table()
        currency = commod_table.lookup('CURRENCY', currency_code)

        # Everything from the moment the transaction exists is inside the
        # guard: a failure part-way through takes it with it, rather than
        # leaving the entry in the book carrying whatever splits were already
        # attached, on top of an edit nothing will close.
        with transaction_under_construction(self.book) as tx:
            tx.SetCurrency(currency)
            tx.SetDate(*date_tuple)
            tx.SetDescription(description)

            for split_data in splits_data:
                account_path = split_data['account_path']
                value = split_data['value']

                account = self.get_account(account_path)
                if account is None:
                    raise ValueError(f"Account not found: {account_path}")

                split = Split(self.book)
                split.SetParent(tx)
                split.SetAccount(account)
                split.SetValue(value)

        return tx

    def delete_transaction(self, transaction: Transaction):
        """
        Delete a transaction.

        Args:
            transaction: Transaction to delete
        """
        transaction.BeginEdit()
        transaction.Destroy()
        transaction.CommitEdit()

    # Query operations

    def find_transactions(self, predicate: Callable[[Transaction], bool]) -> List[Transaction]:
        """
        Find transactions matching predicate.

        Args:
            predicate: Function that takes Transaction and returns bool

        Returns:
            List of matching transactions
        """
        all_transactions = self.get_all_transactions()
        return [tx for tx in all_transactions if predicate(tx)]

    def find_accounts(self, predicate: Callable[[Account], bool]) -> List[Account]:
        """
        Find accounts matching predicate.

        Args:
            predicate: Function that takes Account and returns bool

        Returns:
            List of matching accounts
        """
        all_accounts = self.get_all_accounts()
        return [acc for acc in all_accounts if predicate(acc)]

    # Commodity operations

    def get_commodity(self, namespace: str, mnemonic: str):
        """
        Get commodity.

        Args:
            namespace: Commodity namespace (e.g., "CURRENCY")
            mnemonic: Commodity mnemonic (e.g., "USD")

        Returns:
            Commodity object
        """
        commod_table = self.book.get_table()
        return commod_table.lookup(namespace, mnemonic)

    def get_default_currency(self):
        """
        Get default currency (USD).

        Returns:
            Currency commodity
        """
        return self.get_commodity('CURRENCY', 'USD')

    # Validation operations

    def validate(self) -> 'ValidationResult':
        """
        Validate entire ledger.

        Returns:
            ValidationResult from LedgerValidator
        """
        from services.ledger_validator import LedgerValidator

        validator = LedgerValidator()
        root = self.get_root_account()
        transactions = self.get_all_transactions()

        return validator.validate_ledger(root, transactions)

    # Statistics

    def get_statistics(self) -> Dict:
        """
        Get repository statistics.

        Returns:
            Dictionary with counts and info
        """
        accounts = self.get_all_accounts()
        transactions = self.get_all_transactions()

        from services.account_categorizer import AccountCategorizer
        categorizer = AccountCategorizer()
        categorized = categorizer.categorize_accounts(accounts)

        return {
            'file_path': self.file_path,
            'total_accounts': len(accounts),
            'total_transactions': len(transactions),
            'accounts_by_category': {
                category: len(accts)
                for category, accts in categorized.items()
            }
        }

    # File operations

    @staticmethod
    def file_exists(file_path: str) -> bool:
        """Check if GnuCash file exists."""
        return Path(file_path).exists()

    @staticmethod
    def create_new_file(file_path: str):
        """
        Create a new empty GnuCash file with basic structure.

        The file will be created without any default currency or accounts.
        Commodities and accounts should be created by importing from plaintext
        which contains all necessary commodity and account declarations.

        Args:
            file_path: Path for new file

        Returns:
            GnuCashRepository instance
        """
        if Path(file_path).exists():
            raise FileExistsError(f"File already exists: {file_path}")

        # Create and save new file
        repo = GnuCashRepository(file_path)
        repo.open(mode=SessionMode.NEW)

        # GnuCash requires at least the root account to exist before saving
        # The root account is automatically created, we just need to access it
        repo.book.get_root_account()

        # Save and close
        repo.save()
        repo.close()

        return GnuCashRepository(file_path)
