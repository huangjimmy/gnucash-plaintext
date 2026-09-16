"""
Tests for AccountCategorizer service

These tests use real GnuCash files created in Docker (no mocks).
"""

import sys

import pytest

from repositories.gnucash_repository import GnuCashRepository, SessionMode


class TestAccountCategory:
    """Test account category detection"""

    def test_get_category_asset(self, temp_gnucash_file):
        """Test getting category for asset accounts"""
        from services.account_categorizer import AccountCategorizer, AccountCategory

        repo = GnuCashRepository(temp_gnucash_file)
        repo.open(SessionMode.READ_ONLY)

        try:
            book = repo.book
            root = book.get_root_account()

            from tests.conftest import find_account
            checking = find_account(root, "Assets:Bank:Checking")

            categorizer = AccountCategorizer()
            category = categorizer.get_category(checking)

            assert category == AccountCategory.ASSET

        finally:
            repo.close()

    def test_get_category_expense(self, temp_gnucash_file):
        """Test getting category for expense accounts"""
        from services.account_categorizer import AccountCategorizer, AccountCategory

        repo = GnuCashRepository(temp_gnucash_file)
        repo.open(SessionMode.READ_ONLY)

        try:
            book = repo.book
            root = book.get_root_account()

            from tests.conftest import find_account
            groceries = find_account(root, "Expenses:Groceries")

            categorizer = AccountCategorizer()
            category = categorizer.get_category(groceries)

            assert category == AccountCategory.EXPENSE

        finally:
            repo.close()

    def test_get_type_name(self, temp_gnucash_file):
        """Test getting human-readable type names"""
        from services.account_categorizer import AccountCategorizer

        repo = GnuCashRepository(temp_gnucash_file)
        repo.open(SessionMode.READ_ONLY)

        try:
            book = repo.book
            root = book.get_root_account()

            from tests.conftest import find_account
            checking = find_account(root, "Assets:Bank:Checking")
            groceries = find_account(root, "Expenses:Groceries")

            categorizer = AccountCategorizer()

            assert categorizer.get_type_name(checking) == "Bank"
            assert categorizer.get_type_name(groceries) == "Expense"

        finally:
            repo.close()


class TestAccountCheckers:
    """Test account type checking methods"""

    def test_is_asset_account(self, temp_gnucash_file):
        """Test checking if account is asset"""
        from services.account_categorizer import AccountCategorizer

        repo = GnuCashRepository(temp_gnucash_file)
        repo.open(SessionMode.READ_ONLY)

        try:
            book = repo.book
            root = book.get_root_account()

            from tests.conftest import find_account
            checking = find_account(root, "Assets:Bank:Checking")
            groceries = find_account(root, "Expenses:Groceries")

            categorizer = AccountCategorizer()

            assert categorizer.is_asset_account(checking) is True
            assert categorizer.is_asset_account(groceries) is False

        finally:
            repo.close()

    def test_is_expense_account(self, temp_gnucash_file):
        """Test checking if account is expense"""
        from services.account_categorizer import AccountCategorizer

        repo = GnuCashRepository(temp_gnucash_file)
        repo.open(SessionMode.READ_ONLY)

        try:
            book = repo.book
            root = book.get_root_account()

            from tests.conftest import find_account
            checking = find_account(root, "Assets:Bank:Checking")
            groceries = find_account(root, "Expenses:Groceries")

            categorizer = AccountCategorizer()

            assert categorizer.is_expense_account(groceries) is True
            assert categorizer.is_expense_account(checking) is False

        finally:
            repo.close()


class TestAccountCategorization:
    """Test categorizing lists of accounts"""

    def test_categorize_accounts(self, temp_gnucash_file):
        """Test categorizing a list of accounts"""
        from services.account_categorizer import AccountCategorizer, AccountCategory

        repo = GnuCashRepository(temp_gnucash_file)
        repo.open(SessionMode.READ_ONLY)

        try:
            book = repo.book
            root = book.get_root_account()

            from tests.conftest import find_account
            checking = find_account(root, "Assets:Bank:Checking")
            groceries = find_account(root, "Expenses:Groceries")
            dining = find_account(root, "Expenses:Dining")

            categorizer = AccountCategorizer()
            categorized = categorizer.categorize_accounts([checking, groceries, dining])

            # Should have 1 asset and 2 expenses
            assert len(categorized[AccountCategory.ASSET]) == 1
            assert len(categorized[AccountCategory.EXPENSE]) == 2
            assert checking in categorized[AccountCategory.ASSET]
            assert groceries in categorized[AccountCategory.EXPENSE]
            assert dining in categorized[AccountCategory.EXPENSE]

        finally:
            repo.close()

    def test_get_accounts_by_category(self, temp_gnucash_file):
        """Test getting accounts by category"""
        from services.account_categorizer import AccountCategorizer, AccountCategory

        repo = GnuCashRepository(temp_gnucash_file)
        repo.open(SessionMode.READ_ONLY)

        try:
            book = repo.book
            root = book.get_root_account()

            categorizer = AccountCategorizer()

            # Get all expense accounts
            expenses = categorizer.get_accounts_by_category(root, AccountCategory.EXPENSE)
            expense_names = [acc.GetName() for acc in expenses]

            # Should include Expenses, Groceries, and Dining
            assert "Expenses" in expense_names
            assert "Groceries" in expense_names
            assert "Dining" in expense_names

            # Get all asset accounts
            assets = categorizer.get_accounts_by_category(root, AccountCategory.ASSET)
            asset_names = [acc.GetName() for acc in assets]

            # Should include Assets, Bank, and Checking
            assert "Assets" in asset_names
            assert "Bank" in asset_names
            assert "Checking" in asset_names

        finally:
            repo.close()


class TestAccountHierarchy:
    """Test account hierarchy methods"""

    def test_get_account_hierarchy(self, temp_gnucash_file):
        """Test getting account hierarchy"""
        from services.account_categorizer import AccountCategorizer, AccountCategory

        repo = GnuCashRepository(temp_gnucash_file)
        repo.open(SessionMode.READ_ONLY)

        try:
            book = repo.book
            root = book.get_root_account()

            from tests.conftest import find_account
            checking = find_account(root, "Assets:Bank:Checking")

            categorizer = AccountCategorizer()
            hierarchy = categorizer.get_account_hierarchy(checking)

            # Should be: Assets -> Bank -> Checking
            assert len(hierarchy) == 3
            assert hierarchy[0] == ("Assets", AccountCategory.ASSET)
            assert hierarchy[1] == ("Bank", AccountCategory.ASSET)
            assert hierarchy[2] == ("Checking", AccountCategory.ASSET)

        finally:
            repo.close()

    def test_validate_account_hierarchy(self, temp_gnucash_file):
        """Test validating account hierarchy"""
        from services.account_categorizer import AccountCategorizer

        repo = GnuCashRepository(temp_gnucash_file)
        repo.open(SessionMode.READ_ONLY)

        try:
            book = repo.book
            root = book.get_root_account()

            from tests.conftest import find_account
            checking = find_account(root, "Assets:Bank:Checking")

            categorizer = AccountCategorizer()
            is_valid, error = categorizer.validate_account_hierarchy(checking)

            # Valid hierarchy (all assets)
            assert is_valid is True
            assert error is None

        finally:
            repo.close()


class TestAccountSearch:
    """Test account search methods"""

    def test_find_matching_accounts(self, temp_gnucash_file):
        """Test finding accounts by name pattern"""
        from services.account_categorizer import AccountCategorizer

        repo = GnuCashRepository(temp_gnucash_file)
        repo.open(SessionMode.READ_ONLY)

        try:
            book = repo.book
            root = book.get_root_account()

            categorizer = AccountCategorizer()

            # Find accounts with "check" in name (case-insensitive)
            matching = categorizer.find_matching_accounts(root, "check")
            names = [acc.GetName() for acc in matching]

            assert "Checking" in names

            # Find accounts with "grocer" in name
            matching = categorizer.find_matching_accounts(root, "grocer")
            names = [acc.GetName() for acc in matching]

            assert "Groceries" in names

        finally:
            repo.close()

    def test_get_leaf_accounts(self, temp_gnucash_file):
        """Test getting leaf accounts"""
        from services.account_categorizer import AccountCategorizer

        repo = GnuCashRepository(temp_gnucash_file)
        repo.open(SessionMode.READ_ONLY)

        try:
            book = repo.book
            root = book.get_root_account()

            categorizer = AccountCategorizer()
            leaves = categorizer.get_leaf_accounts(root)
            leaf_names = [acc.GetName() for acc in leaves]

            # Checking, Groceries, and Dining are leaves
            assert "Checking" in leaf_names
            assert "Groceries" in leaf_names
            assert "Dining" in leaf_names

            # Assets, Bank, Expenses are not leaves (have children)
            assert "Assets" not in leaf_names
            assert "Bank" not in leaf_names
            assert "Expenses" not in leaf_names

        finally:
            repo.close()


class TestAccountInfo:
    """Test account information methods"""

    def test_get_account_summary(self, temp_gnucash_file):
        """Test getting account summary"""
        from services.account_categorizer import AccountCategorizer, AccountCategory

        repo = GnuCashRepository(temp_gnucash_file)
        repo.open(SessionMode.READ_ONLY)

        try:
            book = repo.book
            root = book.get_root_account()

            from tests.conftest import find_account
            checking = find_account(root, "Assets:Bank:Checking")

            categorizer = AccountCategorizer()
            summary = categorizer.get_account_summary(checking)

            assert summary['name'] == "Checking"
            assert summary['full_name'] == "Assets:Bank:Checking"
            assert summary['type'] == "Bank"
            assert summary['category'] == AccountCategory.ASSET
            assert 'hidden' in summary
            assert 'placeholder' in summary

        finally:
            repo.close()


class TestTransactionMethods:
    """Test transaction-related methods"""

    def test_categorize_split_accounts(self, temp_gnucash_with_transactions):
        """Test categorizing split accounts"""
        from gnucash import Transaction

        from services.account_categorizer import AccountCategorizer, AccountCategory

        repo = GnuCashRepository(temp_gnucash_with_transactions)
        repo.open(SessionMode.READ_ONLY)

        try:
            book = repo.book

            # Get first transaction (Groceries)
            from gnucash import Query
            query = Query()
            query.search_for('Trans')
            query.set_book(book)
            result = query.run()
            tx = Transaction(instance=result[0])

            categorizer = AccountCategorizer()
            splits = tx.GetSplitList()
            categorized = categorizer.categorize_split_accounts(splits)

            # Should have 1 asset split (Checking) and 1 expense split (Groceries)
            assert len(categorized[AccountCategory.ASSET]) == 1
            assert len(categorized[AccountCategory.EXPENSE]) == 1

        finally:
            repo.close()


class TestPlaceholderAccounts:
    """Test placeholder account methods"""

    def test_get_placeholder_accounts_empty(self, temp_gnucash_file):
        """Test getting placeholder accounts when none exist"""
        from services.account_categorizer import AccountCategorizer

        repo = GnuCashRepository(temp_gnucash_file)
        repo.open(SessionMode.READ_ONLY)

        try:
            book = repo.book
            root = book.get_root_account()

            categorizer = AccountCategorizer()
            placeholders = categorizer.get_placeholder_accounts(root)

            # No placeholders in our test file
            assert len(placeholders) == 0

        finally:
            repo.close()

    def test_get_placeholder_accounts_lists_the_books_placeholders(self, tmp_path):
        """The HKD book's four top-level accounts are placeholders, and nothing else is."""
        from services.account_categorizer import AccountCategorizer
        from tests.integration.text_report_pages import book_from

        book = book_from(tmp_path, 'a_book_kept_in_hkd.txt')
        repo = GnuCashRepository(str(book))
        repo.open(SessionMode.READ_ONLY)

        try:
            placeholders = AccountCategorizer().get_placeholder_accounts(
                repo.book.get_root_account())

            assert sorted(account.GetName() for account in placeholders) == [
                'Assets', 'Equity', 'Expenses', 'Income']

        finally:
            repo.close()


class TestTheOtherCategories:
    """Liability, income and equity accounts, and an account under a parent of another category."""

    def test_is_liability_income_and_equity_account(self, tmp_path):
        from services.account_categorizer import AccountCategorizer
        from tests.conftest import find_account
        from tests.integration.text_report_pages import book_from

        book = book_from(tmp_path, 'balance_sheet_book.txt')
        repo = GnuCashRepository(str(book))
        repo.open(SessionMode.READ_ONLY)

        try:
            root = repo.book.get_root_account()
            card = find_account(root, 'Liabilities:CreditCard')
            sales = find_account(root, 'Income:Sales')
            equity = find_account(root, 'Equity')
            categorizer = AccountCategorizer()

            assert categorizer.is_liability_account(card) is True
            assert categorizer.is_liability_account(sales) is False
            assert categorizer.is_income_account(sales) is True
            assert categorizer.is_income_account(card) is False
            assert categorizer.is_equity_account(equity) is True
            assert categorizer.is_equity_account(card) is False

        finally:
            repo.close()

    def test_a_top_level_account_is_valid_and_a_child_of_another_category_is_not(self, tmp_path):
        from services.account_categorizer import AccountCategorizer
        from tests.conftest import find_account
        from tests.integration.text_report_pages import book_from

        book = book_from(tmp_path, 'an_expense_account_filed_under_assets.txt')
        repo = GnuCashRepository(str(book))
        repo.open(SessionMode.READ_ONLY)

        try:
            root = repo.book.get_root_account()
            categorizer = AccountCategorizer()

            assert categorizer.validate_account_hierarchy(find_account(root, 'Assets')) == (True, None)
            valid, error = categorizer.validate_account_hierarchy(
                find_account(root, 'Assets:Parking'))
            assert valid is False
            assert 'Parking' in error and 'Assets' in error, error

        finally:
            repo.close()
