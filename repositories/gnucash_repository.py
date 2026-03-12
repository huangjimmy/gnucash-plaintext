"""
GnuCash repository for file operations and data access.

Provides high-level interface for working with GnuCash files.
Manages sessions, transactions, accounts, and file operations.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Callable, Dict, List, Optional

from gnucash import Account, Query, Session, Split, Transaction

if TYPE_CHECKING:
    from services.ledger_validator import ValidationResult


class SessionMode:
    """Session opening modes"""
    READ_ONLY = "read_only"
    NORMAL = "normal"
    NEW = "new"


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

    def open(self, mode: str = SessionMode.NORMAL):
        """
        Open GnuCash file session.

        Args:
            mode: Session mode (READ_ONLY, NORMAL, or NEW)
        """
        if self.session is not None:
            raise RuntimeError("Session already open")

        uri = f"xml://{self.file_path}"

        # Use version-specific session API (try new API first)
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

        self._book = self.session.book

    def close(self):
        """Close GnuCash file session."""
        if self.session is not None:
            self.session.end()
            self.session = None
            self._book = None

    def save(self):
        """Save changes to GnuCash file."""
        if self.session is None:
            raise RuntimeError("No session open")
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
        transactions = []
        for split in account.GetSplitList():
            tx = split.GetParent()
            if tx not in transactions:
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

        # Create transaction
        tx = Transaction(self.book)
        tx.BeginEdit()
        tx.SetCurrency(currency)
        tx.SetDate(*date_tuple)
        tx.SetDescription(description)

        # Create splits
        for split_data in splits_data:
            account_path = split_data['account_path']
            value = split_data['value']

            account = self.get_account(account_path)
            if account is None:
                tx.Destroy()
                raise ValueError(f"Account not found: {account_path}")

            split = Split(self.book)
            split.SetParent(tx)
            split.SetAccount(account)
            split.SetValue(value)

        tx.CommitEdit()
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
