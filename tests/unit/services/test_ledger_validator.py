"""
Tests for LedgerValidator service

These tests use real GnuCash files created in Docker (no mocks).
"""

import sys
from datetime import datetime

import pytest


class TestValidationError:
    """Test ValidationError class"""

    def test_create_validation_error(self):
        """Test creating validation error"""
        from services.ledger_validator import ValidationError

        error = ValidationError("ERROR", "TEST_CODE", "Test message")

        assert error.severity == "ERROR"
        assert error.code == "TEST_CODE"
        assert error.message == "Test message"
        assert error.context == {}

    def test_validation_error_with_context(self):
        """Test validation error with context"""
        from services.ledger_validator import ValidationError

        error = ValidationError(
            "WARNING",
            "TEST_CODE",
            "Test message",
            {'key': 'value'}
        )

        assert error.context == {'key': 'value'}

    def test_validation_error_to_dict(self):
        """Test converting validation error to dict"""
        from services.ledger_validator import ValidationError

        error = ValidationError(
            "ERROR",
            "TEST_CODE",
            "Test message",
            {'key': 'value'}
        )

        d = error.to_dict()

        assert d['severity'] == "ERROR"
        assert d['code'] == "TEST_CODE"
        assert d['message'] == "Test message"
        assert d['context'] == {'key': 'value'}


class TestValidationResult:
    """Test ValidationResult class"""

    def test_create_validation_result(self):
        """Test creating validation result"""
        from services.ledger_validator import ValidationResult

        result = ValidationResult()

        assert len(result.errors) == 0
        assert len(result.warnings) == 0
        assert len(result.info) == 0
        assert result.is_valid() is True

    def test_add_error(self):
        """Test adding error"""
        from services.ledger_validator import ValidationResult

        result = ValidationResult()
        result.add_error("TEST_CODE", "Test error")

        assert len(result.errors) == 1
        assert result.has_errors() is True
        assert result.is_valid() is False

    def test_add_warning(self):
        """Test adding warning"""
        from services.ledger_validator import ValidationResult

        result = ValidationResult()
        result.add_warning("TEST_CODE", "Test warning")

        assert len(result.warnings) == 1
        assert result.has_warnings() is True
        assert result.is_valid() is True  # Warnings don't fail validation

    def test_get_summary(self):
        """Test getting summary"""
        from services.ledger_validator import ValidationResult

        result = ValidationResult()
        assert "no issues" in result.get_summary().lower()

        result.add_error("TEST", "Error")
        result.add_warning("TEST", "Warning")

        summary = result.get_summary()
        assert "1 error(s)" in summary
        assert "1 warning(s)" in summary


class TestTransactionValidation:
    """Test transaction validation"""

    def test_validate_valid_transaction(self, temp_gnucash_with_transactions):
        """Test validating a valid transaction"""
        from gnucash import Session, Transaction

        from services.ledger_validator import LedgerValidator

        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{temp_gnucash_with_transactions}',
                            SessionOpenMode.SESSION_READ_ONLY)
        except ImportError:
            # Fall back to older GnuCash API (< 4.0)
            session = Session(f'xml://{temp_gnucash_with_transactions}',
                            ignore_lock=True)

        try:
            book = session.book

            # Get first transaction
            from gnucash import Query
            query = Query()
            query.search_for('Trans')
            query.set_book(book)
            result = query.run()
            tx = Transaction(instance=result[0])

            validator = LedgerValidator()
            validation_result = validator.validate_transaction(tx)

            # Should be valid (may have warnings about description)
            assert validation_result.is_valid()

        finally:
            session.end()

    def test_validate_transaction_balance(self, temp_gnucash_with_transactions):
        """Test validating transaction balance"""
        from gnucash import Session, Transaction

        from services.ledger_validator import LedgerValidator

        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{temp_gnucash_with_transactions}',
                            SessionOpenMode.SESSION_READ_ONLY)
        except ImportError:
            # Fall back to older GnuCash API (< 4.0)
            session = Session(f'xml://{temp_gnucash_with_transactions}',
                            ignore_lock=True)

        try:
            book = session.book

            from gnucash import Query
            query = Query()
            query.search_for('Trans')
            query.set_book(book)
            result = query.run()
            tx = Transaction(instance=result[0])

            validator = LedgerValidator()

            # Test the internal balance check
            splits = tx.GetSplitList()
            is_balanced = validator._is_transaction_balanced(splits)

            assert is_balanced is True

        finally:
            session.end()

    def test_validate_transaction_no_splits(self, temp_gnucash_file):
        """Test validating transaction with no splits"""
        from gnucash import Session, Transaction

        from services.ledger_validator import LedgerValidator

        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{temp_gnucash_file}',
                            SessionOpenMode.SESSION_NORMAL_OPEN)
        except ImportError:
            # Fall back to older GnuCash API (< 4.0)
            session = Session(f'xml://{temp_gnucash_file}')

        try:
            book = session.book
            commod_table = book.get_table()
            cad = commod_table.lookup('CURRENCY', 'CAD')

            # Create transaction with no splits
            tx = Transaction(book)
            tx.BeginEdit()
            tx.SetCurrency(cad)
            tx.SetDate(15, 1, 2024)
            tx.SetDescription("Test transaction")
            tx.CommitEdit()

            validator = LedgerValidator()
            validation_result = validator.validate_transaction(tx)

            # Should have error about no splits
            assert not validation_result.is_valid()
            assert any(e.code == "NO_SPLITS" for e in validation_result.errors)

        finally:
            session.end()


class TestAccountValidation:
    """Test account validation"""

    def test_validate_valid_account(self, temp_gnucash_file):
        """Test validating a valid account"""
        from gnucash import Session

        from services.ledger_validator import LedgerValidator

        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{temp_gnucash_file}',
                            SessionOpenMode.SESSION_READ_ONLY)
        except ImportError:
            # Fall back to older GnuCash API (< 4.0)
            session = Session(f'xml://{temp_gnucash_file}',
                            ignore_lock=True)

        try:
            book = session.book
            root = book.get_root_account()

            from tests.conftest import find_account
            checking = find_account(root, "Assets:Bank:Checking")

            validator = LedgerValidator()
            validation_result = validator.validate_account(checking)

            # Should be valid
            assert validation_result.is_valid()

        finally:
            session.end()


class TestAccountHierarchyValidation:
    """Test account hierarchy validation"""

    def test_validate_account_hierarchy(self, temp_gnucash_file):
        """Test validating account hierarchy"""
        from gnucash import Session

        from services.ledger_validator import LedgerValidator

        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{temp_gnucash_file}',
                            SessionOpenMode.SESSION_READ_ONLY)
        except ImportError:
            # Fall back to older GnuCash API (< 4.0)
            session = Session(f'xml://{temp_gnucash_file}',
                            ignore_lock=True)

        try:
            book = session.book
            root = book.get_root_account()

            validator = LedgerValidator()
            validation_result = validator.validate_account_hierarchy(root)

            # Should be valid (our test hierarchy is consistent)
            assert validation_result.is_valid()

        finally:
            session.end()


class TestTransactionsValidation:
    """Test validating multiple transactions"""

    def test_validate_transactions(self, temp_gnucash_with_transactions):
        """Test validating list of transactions"""
        from gnucash import Session, Transaction

        from services.ledger_validator import LedgerValidator

        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{temp_gnucash_with_transactions}',
                            SessionOpenMode.SESSION_READ_ONLY)
        except ImportError:
            # Fall back to older GnuCash API (< 4.0)
            session = Session(f'xml://{temp_gnucash_with_transactions}',
                            ignore_lock=True)

        try:
            book = session.book

            # Get all transactions
            from gnucash import Query
            query = Query()
            query.search_for('Trans')
            query.set_book(book)
            result = query.run()
            transactions = [Transaction(instance=tx) for tx in result]

            validator = LedgerValidator()
            validation_result = validator.validate_transactions(transactions)

            # Should be valid (no duplicates in our test data)
            assert validation_result.is_valid()

        finally:
            session.end()

    def test_validate_transactions_with_duplicates(self, temp_gnucash_with_transactions):
        """Test validating transactions with duplicates"""
        from gnucash import GncNumeric, Session, Split, Transaction

        from services.ledger_validator import LedgerValidator

        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{temp_gnucash_with_transactions}',
                            SessionOpenMode.SESSION_NORMAL_OPEN)
        except ImportError:
            # Fall back to older GnuCash API (< 4.0)
            session = Session(f'xml://{temp_gnucash_with_transactions}')

        try:
            book = session.book

            # Get existing transactions
            from gnucash import Query
            query = Query()
            query.search_for('Trans')
            query.set_book(book)
            result = query.run()
            transactions = [Transaction(instance=tx) for tx in result]

            # Create duplicate
            commod_table = book.get_table()
            cad = commod_table.lookup('CURRENCY', 'CAD')

            dup_tx = Transaction(book)
            dup_tx.BeginEdit()
            dup_tx.SetCurrency(cad)
            dup_tx.SetDate(15, 1, 2024)
            dup_tx.SetDescription("Duplicate")

            from tests.conftest import find_account
            root = book.get_root_account()
            checking = find_account(root, "Assets:Bank:Checking")
            groceries = find_account(root, "Expenses:Groceries")

            split1 = Split(book)
            split1.SetParent(dup_tx)
            split1.SetAccount(groceries)
            split1.SetValue(GncNumeric(5000, 100))

            split2 = Split(book)
            split2.SetParent(dup_tx)
            split2.SetAccount(checking)
            split2.SetValue(GncNumeric(-5000, 100))

            dup_tx.CommitEdit()

            # Add duplicate to list
            transactions.append(dup_tx)

            validator = LedgerValidator()
            validation_result = validator.validate_transactions(transactions, check_duplicates=True)

            # Should have warning about duplicates
            assert validation_result.has_warnings()
            assert any(w.code == "DUPLICATES_FOUND" for w in validation_result.warnings)

        finally:
            session.end()


class TestLedgerValidation:
    """Test full ledger validation"""

    def test_validate_ledger(self, temp_gnucash_with_transactions):
        """Test validating entire ledger"""
        from gnucash import Session, Transaction

        from services.ledger_validator import LedgerValidator

        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{temp_gnucash_with_transactions}',
                            SessionOpenMode.SESSION_READ_ONLY)
        except ImportError:
            # Fall back to older GnuCash API (< 4.0)
            session = Session(f'xml://{temp_gnucash_with_transactions}',
                            ignore_lock=True)

        try:
            book = session.book
            root = book.get_root_account()

            # Get all transactions
            from gnucash import Query
            query = Query()
            query.search_for('Trans')
            query.set_book(book)
            result = query.run()
            transactions = [Transaction(instance=tx) for tx in result]

            validator = LedgerValidator()
            validation_result = validator.validate_ledger(root, transactions)

            # Should be valid
            assert validation_result.is_valid()

        finally:
            session.end()


class TestDateValidation:
    """Test date-related validation"""

    def test_check_transaction_date_order(self, temp_gnucash_with_transactions):
        """Test checking transaction date order"""
        from gnucash import Session, Transaction

        from services.ledger_validator import LedgerValidator

        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{temp_gnucash_with_transactions}',
                            SessionOpenMode.SESSION_READ_ONLY)
        except ImportError:
            # Fall back to older GnuCash API (< 4.0)
            session = Session(f'xml://{temp_gnucash_with_transactions}',
                            ignore_lock=True)

        try:
            book = session.book

            # Get all transactions
            from gnucash import Query
            query = Query()
            query.search_for('Trans')
            query.set_book(book)
            result = query.run()
            transactions = [Transaction(instance=tx) for tx in result]

            # Sort by date
            transactions.sort(key=lambda tx: tx.GetDate())

            validator = LedgerValidator()
            validation_result = validator.check_transaction_date_order(transactions)

            # Should have no issues (sorted)
            assert len(validation_result.get_all_issues()) == 0

        finally:
            session.end()

    def test_check_future_transactions(self, temp_gnucash_with_transactions):
        """Test checking for future transactions"""
        from gnucash import Session, Transaction

        from services.ledger_validator import LedgerValidator

        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{temp_gnucash_with_transactions}',
                            SessionOpenMode.SESSION_READ_ONLY)
        except ImportError:
            # Fall back to older GnuCash API (< 4.0)
            session = Session(f'xml://{temp_gnucash_with_transactions}',
                            ignore_lock=True)

        try:
            book = session.book

            # Get all transactions
            from gnucash import Query
            query = Query()
            query.search_for('Trans')
            query.set_book(book)
            result = query.run()
            transactions = [Transaction(instance=tx) for tx in result]

            validator = LedgerValidator()

            # Use a reference date in the past
            reference_date = datetime(2023, 1, 1)
            validation_result = validator.check_future_transactions(
                transactions,
                reference_date
            )

            # All transactions should be "future" relative to 2023
            assert len(validation_result.info) == len(transactions)

        finally:
            session.end()


class TestReportFormatting:
    """Test validation report formatting"""

    def test_format_validation_report(self):
        """Test formatting validation report"""
        from services.ledger_validator import LedgerValidator, ValidationResult

        validator = LedgerValidator()
        result = ValidationResult()

        result.add_error("TEST_ERROR", "Test error message", {'key': 'value'})
        result.add_warning("TEST_WARNING", "Test warning message")
        result.add_info("TEST_INFO", "Test info message")

        report = validator.format_validation_report(result)

        # Should contain all sections
        assert "VALIDATION REPORT" in report
        assert "ERRORS:" in report
        assert "WARNINGS:" in report
        assert "INFO:" in report
        assert "TEST_ERROR" in report
        assert "TEST_WARNING" in report
        assert "TEST_INFO" in report

    def test_format_validation_report_no_issues(self):
        """Test formatting report with no issues"""
        from services.ledger_validator import LedgerValidator, ValidationResult

        validator = LedgerValidator()
        result = ValidationResult()

        report = validator.format_validation_report(result)

        # Should indicate no issues
        assert "no issues" in report.lower()
