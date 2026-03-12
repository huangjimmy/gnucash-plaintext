"""
Account categorization service for GnuCash accounts.

Categorizes accounts by type, validates hierarchies, and provides
account lookup and analysis capabilities.
"""

from typing import Dict, List, Optional, Tuple

import gnucash
from gnucash import Account


class AccountType:
    """Account type constants matching GnuCash types"""
    ASSET = gnucash.ACCT_TYPE_ASSET
    BANK = gnucash.ACCT_TYPE_BANK
    CASH = gnucash.ACCT_TYPE_CASH
    CREDIT = gnucash.ACCT_TYPE_CREDIT
    LIABILITY = gnucash.ACCT_TYPE_LIABILITY
    STOCK = gnucash.ACCT_TYPE_STOCK
    MUTUAL = gnucash.ACCT_TYPE_MUTUAL
    INCOME = gnucash.ACCT_TYPE_INCOME
    EXPENSE = gnucash.ACCT_TYPE_EXPENSE
    EQUITY = gnucash.ACCT_TYPE_EQUITY
    RECEIVABLE = gnucash.ACCT_TYPE_RECEIVABLE
    PAYABLE = gnucash.ACCT_TYPE_PAYABLE
    ROOT = gnucash.ACCT_TYPE_ROOT
    TRADING = gnucash.ACCT_TYPE_TRADING


class AccountCategory:
    """High-level account category groupings"""
    ASSET = "Asset"
    LIABILITY = "Liability"
    INCOME = "Income"
    EXPENSE = "Expense"
    EQUITY = "Equity"
    OTHER = "Other"


class AccountCategorizer:
    """Service for categorizing and analyzing GnuCash accounts"""

    # Mapping from GnuCash account types to high-level categories
    TYPE_TO_CATEGORY = {
        AccountType.ASSET: AccountCategory.ASSET,
        AccountType.BANK: AccountCategory.ASSET,
        AccountType.CASH: AccountCategory.ASSET,
        AccountType.STOCK: AccountCategory.ASSET,
        AccountType.MUTUAL: AccountCategory.ASSET,
        AccountType.RECEIVABLE: AccountCategory.ASSET,
        AccountType.CREDIT: AccountCategory.LIABILITY,
        AccountType.LIABILITY: AccountCategory.LIABILITY,
        AccountType.PAYABLE: AccountCategory.LIABILITY,
        AccountType.INCOME: AccountCategory.INCOME,
        AccountType.EXPENSE: AccountCategory.EXPENSE,
        AccountType.EQUITY: AccountCategory.EQUITY,
        AccountType.ROOT: AccountCategory.OTHER,
        AccountType.TRADING: AccountCategory.OTHER,
    }

    def __init__(self):
        """Initialize account categorizer"""
        pass

    def get_category(self, account: Account) -> str:
        """
        Get high-level category for an account.

        Args:
            account: GnuCash Account object

        Returns:
            Category string (Asset, Liability, Income, Expense, Equity, Other)
        """
        account_type = account.GetType()
        return self.TYPE_TO_CATEGORY.get(account_type, AccountCategory.OTHER)

    def get_type_name(self, account: Account) -> str:
        """
        Get human-readable type name for an account.

        Args:
            account: GnuCash Account object

        Returns:
            Type name string
        """
        account_type = account.GetType()

        type_names = {
            AccountType.ASSET: "Asset",
            AccountType.BANK: "Bank",
            AccountType.CASH: "Cash",
            AccountType.CREDIT: "Credit Card",
            AccountType.LIABILITY: "Liability",
            AccountType.STOCK: "Stock",
            AccountType.MUTUAL: "Mutual Fund",
            AccountType.INCOME: "Income",
            AccountType.EXPENSE: "Expense",
            AccountType.EQUITY: "Equity",
            AccountType.RECEIVABLE: "Accounts Receivable",
            AccountType.PAYABLE: "Accounts Payable",
            AccountType.ROOT: "Root",
            AccountType.TRADING: "Trading",
        }

        return type_names.get(account_type, "Unknown")

    def is_asset_account(self, account: Account) -> bool:
        """Check if account is an asset account"""
        return self.get_category(account) == AccountCategory.ASSET

    def is_liability_account(self, account: Account) -> bool:
        """Check if account is a liability account"""
        return self.get_category(account) == AccountCategory.LIABILITY

    def is_income_account(self, account: Account) -> bool:
        """Check if account is an income account"""
        return self.get_category(account) == AccountCategory.INCOME

    def is_expense_account(self, account: Account) -> bool:
        """Check if account is an expense account"""
        return self.get_category(account) == AccountCategory.EXPENSE

    def is_equity_account(self, account: Account) -> bool:
        """Check if account is an equity account"""
        return self.get_category(account) == AccountCategory.EQUITY

    def categorize_accounts(self, accounts: List[Account]) -> Dict[str, List[Account]]:
        """
        Categorize a list of accounts by their high-level category.

        Args:
            accounts: List of GnuCash Account objects

        Returns:
            Dictionary mapping category names to lists of accounts
        """
        categorized = {
            AccountCategory.ASSET: [],
            AccountCategory.LIABILITY: [],
            AccountCategory.INCOME: [],
            AccountCategory.EXPENSE: [],
            AccountCategory.EQUITY: [],
            AccountCategory.OTHER: [],
        }

        for account in accounts:
            category = self.get_category(account)
            categorized[category].append(account)

        return categorized

    def get_account_hierarchy(self, account: Account) -> List[Tuple[str, str]]:
        """
        Get the account hierarchy from root to this account.

        Args:
            account: GnuCash Account object

        Returns:
            List of (name, category) tuples from root to account
        """
        hierarchy = []
        current = account

        while current is not None and not current.is_root():
            name = current.GetName()
            category = self.get_category(current)
            hierarchy.insert(0, (name, category))
            current = current.get_parent()

        return hierarchy

    def validate_account_hierarchy(self, account: Account) -> Tuple[bool, Optional[str]]:
        """
        Validate that account's hierarchy is consistent.

        Checks that child accounts are appropriate for parent type.

        Args:
            account: GnuCash Account object

        Returns:
            Tuple of (is_valid, error_message)
        """
        parent = account.get_parent()

        if parent is None or parent.is_root():
            # Top-level accounts are always valid
            return True, None

        parent_category = self.get_category(parent)
        account_category = self.get_category(account)

        # Child must have same category as parent
        if parent_category != account_category:
            return False, (
                f"Account category mismatch: {account.GetName()} "
                f"({account_category}) under {parent.GetName()} "
                f"({parent_category})"
            )

        return True, None

    def get_accounts_by_category(
        self,
        root_account: Account,
        category: str
    ) -> List[Account]:
        """
        Get all accounts under root that match the given category.

        Args:
            root_account: Root account to start search
            category: Category to filter by

        Returns:
            List of matching accounts
        """
        matching = []

        def visit(account: Account):
            if not account.is_root() and self.get_category(account) == category:
                matching.append(account)

            for child in account.get_children_sorted():
                visit(child)

        visit(root_account)
        return matching

    def get_account_summary(self, account: Account) -> Dict[str, any]:
        """
        Get summary information for an account.

        Args:
            account: GnuCash Account object

        Returns:
            Dictionary with account details
        """
        from infrastructure.gnucash.utils import get_account_full_name

        return {
            'name': account.GetName(),
            'full_name': get_account_full_name(account),
            'type': self.get_type_name(account),
            'category': self.get_category(account),
            'code': account.GetCode(),
            'description': account.GetDescription(),
            'hidden': account.GetHidden(),
            'placeholder': account.GetPlaceholder(),
        }

    def find_matching_accounts(
        self,
        root_account: Account,
        name_pattern: str
    ) -> List[Account]:
        """
        Find accounts whose names contain the pattern (case-insensitive).

        Args:
            root_account: Root account to start search
            name_pattern: Pattern to search for in account names

        Returns:
            List of matching accounts
        """
        matching = []
        pattern_lower = name_pattern.lower()

        def visit(account: Account):
            if not account.is_root() and pattern_lower in account.GetName().lower():
                matching.append(account)

            for child in account.get_children_sorted():
                visit(child)

        visit(root_account)
        return matching

    def get_leaf_accounts(self, root_account: Account) -> List[Account]:
        """
        Get all leaf accounts (accounts with no children) under root.

        Args:
            root_account: Root account to start search

        Returns:
            List of leaf accounts
        """
        leaves = []

        def visit(account: Account):
            children = account.get_children_sorted()

            if not children and not account.is_root():
                # No children and not root = leaf
                leaves.append(account)
            else:
                # Has children, visit them
                for child in children:
                    visit(child)

        visit(root_account)
        return leaves

    def get_placeholder_accounts(self, root_account: Account) -> List[Account]:
        """
        Get all placeholder accounts under root.

        Placeholder accounts are parent accounts that can't have transactions.

        Args:
            root_account: Root account to start search

        Returns:
            List of placeholder accounts
        """
        placeholders = []

        def visit(account: Account):
            if not account.is_root() and account.GetPlaceholder():
                placeholders.append(account)

            for child in account.get_children_sorted():
                visit(child)

        visit(root_account)
        return placeholders

    def is_balanced_transaction(
        self,
        splits: List,
        tolerance_numerator: int = 0
    ) -> bool:
        """
        Check if splits balance (sum to zero).

        Args:
            splits: List of Split objects
            tolerance_numerator: Tolerance for rounding (default 0 = exact)

        Returns:
            True if balanced within tolerance
        """
        if not splits:
            return True

        # Sum all split values
        total_num = 0

        for split in splits:
            value = split.GetValue()
            total_num += value.num()

        # Check if within tolerance
        return abs(total_num) <= tolerance_numerator

    def categorize_split_accounts(
        self,
        splits: List
    ) -> Dict[str, List]:
        """
        Categorize the accounts involved in splits.

        Args:
            splits: List of Split objects

        Returns:
            Dictionary mapping categories to lists of splits
        """
        categorized = {
            AccountCategory.ASSET: [],
            AccountCategory.LIABILITY: [],
            AccountCategory.INCOME: [],
            AccountCategory.EXPENSE: [],
            AccountCategory.EQUITY: [],
            AccountCategory.OTHER: [],
        }

        for split in splits:
            account = split.GetAccount()
            category = self.get_category(account)
            categorized[category].append(split)

        return categorized
