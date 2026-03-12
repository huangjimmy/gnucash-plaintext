"""
Transaction Matcher Service

Provides duplicate detection for transactions using two strategies:
1. GUID-based matching: For transactions exported from GnuCash with GUID metadata
2. Signature-based matching: For new transactions (e.g., from QFX) using (date + accounts)

This service operates on GnuCash Transaction objects directly, no duplicate domain models.
"""

from typing import List, Optional, Set, Tuple


class TransactionMatcher:
    """
    Match transactions to detect duplicates and conflicts.

    A transaction is considered:
    - DUPLICATE: Same signature (date + accounts), amounts match
    - CONFLICT: Same signature (date + accounts), amounts differ
    - NEW: No matching signature found
    """

    def __init__(self):
        """Initialize transaction matcher."""
        pass

    def find_duplicates(
        self,
        existing_transactions: List,  # List[gnucash.Transaction]
        incoming_transactions: List,  # List[gnucash.Transaction]
    ) -> Tuple[List, List, List]:
        """
        Find duplicates, conflicts, and new transactions.

        Args:
            existing_transactions: Transactions already in GnuCash file
            incoming_transactions: New transactions to check

        Returns:
            Tuple of (new_transactions, duplicates, conflicts)
            - new_transactions: Transactions not in existing (safe to add)
            - duplicates: Transactions already exist (skip)
            - conflicts: Same signature but different amounts (needs resolution)
        """
        new = []
        duplicates = []
        conflicts = []

        # Build lookup index of existing transactions by signature
        existing_by_signature = {}
        for tx in existing_transactions:
            sig = self.get_signature(tx)
            if sig not in existing_by_signature:
                existing_by_signature[sig] = []
            existing_by_signature[sig].append(tx)

        # Check each incoming transaction
        for incoming_tx in incoming_transactions:
            incoming_sig = self.get_signature(incoming_tx)

            if incoming_sig not in existing_by_signature:
                # No match found - this is a new transaction
                new.append(incoming_tx)
            else:
                # Found transaction(s) with same signature
                matching_txs = existing_by_signature[incoming_sig]

                # Check if amounts match (duplicate) or differ (conflict)
                is_duplicate = False
                for existing_tx in matching_txs:
                    if self._amounts_match(incoming_tx, existing_tx):
                        is_duplicate = True
                        duplicates.append(incoming_tx)
                        break

                if not is_duplicate:
                    # Same signature but different amounts = conflict
                    conflicts.append(incoming_tx)

        return new, duplicates, conflicts

    def get_signature(self, transaction) -> Tuple[str, Tuple[str, ...]]:
        """
        Extract transaction signature: (date, sorted_account_names).

        This signature is used to identify potentially duplicate transactions.
        Two transactions with the same signature are either duplicates or conflicts.

        Args:
            transaction: GnuCash Transaction object

        Returns:
            Tuple of (date_string, tuple_of_sorted_account_names)

        Example:
            ("2024-01-15", ("Assets:Bank:Checking", "Expenses:Groceries"))
        """
        # Get transaction date
        tx_date = transaction.GetDate()
        date_str = tx_date.strftime("%Y-%m-%d")

        # Get all split accounts
        splits = transaction.GetSplitList()
        account_names = []

        for split in splits:
            account = split.GetAccount()
            account_name = self._get_account_full_name(account)
            account_names.append(account_name)

        # Sort account names for consistent signature
        sorted_accounts = tuple(sorted(account_names))

        return (date_str, sorted_accounts)

    def get_signature_for_plaintext(
        self,
        date_str: str,
        account_names: List[str]
    ) -> Tuple[str, Tuple[str, ...]]:
        """
        Create signature from plaintext transaction data (before creating GnuCash object).

        Useful for checking duplicates before importing from plaintext.

        Args:
            date_str: Date in YYYY-MM-DD format
            account_names: List of account names from splits

        Returns:
            Tuple of (date_string, tuple_of_sorted_account_names)
        """
        sorted_accounts = tuple(sorted(account_names))
        return (date_str, sorted_accounts)

    def find_by_guid(
        self,
        transactions: List,  # List[gnucash.Transaction]
        guid: str
    ) -> Optional[object]:  # Optional[gnucash.Transaction]
        """
        Find transaction by GnuCash GUID.

        GUIDs are unique identifiers assigned by GnuCash. Used for finding
        transactions that were previously exported from GnuCash.

        Args:
            transactions: List of GnuCash Transaction objects
            guid: GnuCash GUID string (32-character hex)

        Returns:
            Transaction object if found, None otherwise
        """
        for tx in transactions:
            tx_guid = tx.GetGUID().to_string()
            if tx_guid == guid:
                return tx
        return None

    def _get_account_full_name(self, account) -> str:
        """
        Get full hierarchical name of account (e.g., "Assets:Bank:Checking").

        Args:
            account: GnuCash Account object

        Returns:
            Full account name with hierarchy separated by colons
        """
        names = []
        current = account

        # Walk up the account hierarchy
        while current is not None:
            account_name = current.GetName()

            # Skip root account (empty name or "Root Account")
            if account_name and account_name != "Root Account":
                names.insert(0, account_name)

            current = current.get_parent()

        return ":".join(names)

    def _amounts_match(self, tx1, tx2) -> bool:
        """
        Check if two transactions have matching split amounts.

        Two transactions are duplicates if they have the same signature AND
        the same amounts for each split.

        Args:
            tx1: First GnuCash Transaction
            tx2: Second GnuCash Transaction

        Returns:
            True if all split amounts match, False otherwise
        """
        splits1 = tx1.GetSplitList()
        splits2 = tx2.GetSplitList()

        # Different number of splits = not a match
        if len(splits1) != len(splits2):
            return False

        # Build amount dictionary by account for tx1
        amounts1 = {}
        for split in splits1:
            account = split.GetAccount()
            account_name = self._get_account_full_name(account)
            amount = split.GetValue()
            amounts1[account_name] = amount

        # Check if tx2 has same amounts for same accounts
        for split in splits2:
            account = split.GetAccount()
            account_name = self._get_account_full_name(account)
            amount = split.GetValue()

            if account_name not in amounts1:
                return False

            # Compare amounts (GnuCash uses GncNumeric, use .equal() method)
            # Note: != operator doesn't work correctly on GnuCash 3.8/4.4
            if not amounts1[account_name].equal(amount):
                return False

        return True

    def has_duplicate_signature(
        self,
        transactions: List,  # List[gnucash.Transaction]
        date_str: str,
        account_names: List[str]
    ) -> bool:
        """
        Check if any transaction in list has the given signature.

        Convenience method for quick duplicate checks without creating
        GnuCash objects.

        Args:
            transactions: List of GnuCash Transaction objects
            date_str: Date in YYYY-MM-DD format
            account_names: List of account names

        Returns:
            True if a transaction with matching signature exists
        """
        target_sig = self.get_signature_for_plaintext(date_str, account_names)

        for tx in transactions:
            tx_sig = self.get_signature(tx)
            if tx_sig == target_sig:
                return True

        return False

    def get_duplicate_count(
        self,
        transactions: List  # List[gnucash.Transaction]
    ) -> int:
        """
        Count duplicate transactions in a list.

        Useful for reporting how many duplicates exist in a file.

        Args:
            transactions: List of GnuCash Transaction objects

        Returns:
            Number of duplicate transactions found
        """
        seen_signatures: Set[Tuple[str, Tuple[str, ...]]] = set()
        duplicate_count = 0

        for tx in transactions:
            sig = self.get_signature(tx)
            if sig in seen_signatures:
                duplicate_count += 1
            else:
                seen_signatures.add(sig)

        return duplicate_count
