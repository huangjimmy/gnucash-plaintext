"""
Basic tests for TransactionMatcher that don't require GnuCash

These can run anywhere, useful for quick verification.
"""

import pytest


class TestTransactionMatcherBasic:
    """Test basic functionality without GnuCash"""

    def test_get_signature_for_plaintext(self):
        """Test creating signature from plaintext data"""
        from services.transaction_matcher import TransactionMatcher

        matcher = TransactionMatcher()
        sig = matcher.get_signature_for_plaintext(
            "2024-01-15",
            ["Assets:Bank:Checking", "Expenses:Groceries"]
        )

        assert sig == ("2024-01-15", ("Assets:Bank:Checking", "Expenses:Groceries"))

    def test_signature_accounts_are_sorted(self):
        """Test that accounts in signature are sorted"""
        from services.transaction_matcher import TransactionMatcher

        matcher = TransactionMatcher()

        sig1 = matcher.get_signature_for_plaintext(
            "2024-01-15",
            ["Zebra:Account", "Apple:Account", "Mango:Account"]
        )

        # Should be sorted
        _, accounts = sig1
        assert accounts == ("Apple:Account", "Mango:Account", "Zebra:Account")

    def test_signature_order_independence(self):
        """Test that account order doesn't affect signature"""
        from services.transaction_matcher import TransactionMatcher

        matcher = TransactionMatcher()

        sig1 = matcher.get_signature_for_plaintext(
            "2024-01-15",
            ["Assets:Bank:Checking", "Expenses:Groceries"]
        )

        sig2 = matcher.get_signature_for_plaintext(
            "2024-01-15",
            ["Expenses:Groceries", "Assets:Bank:Checking"]
        )

        # Should be identical (accounts are sorted)
        assert sig1 == sig2

    def test_signature_date_matters(self):
        """Test that different dates produce different signatures"""
        from services.transaction_matcher import TransactionMatcher

        matcher = TransactionMatcher()

        sig1 = matcher.get_signature_for_plaintext(
            "2024-01-15",
            ["Assets:Bank:Checking", "Expenses:Groceries"]
        )

        sig2 = matcher.get_signature_for_plaintext(
            "2024-01-16",  # Different date
            ["Assets:Bank:Checking", "Expenses:Groceries"]
        )

        assert sig1 != sig2

    def test_signature_accounts_matter(self):
        """Test that different accounts produce different signatures"""
        from services.transaction_matcher import TransactionMatcher

        matcher = TransactionMatcher()

        sig1 = matcher.get_signature_for_plaintext(
            "2024-01-15",
            ["Assets:Bank:Checking", "Expenses:Groceries"]
        )

        sig2 = matcher.get_signature_for_plaintext(
            "2024-01-15",
            ["Assets:Bank:Checking", "Expenses:Dining"]  # Different account
        )

        assert sig1 != sig2


if __name__ == "__main__":
    # Allow running directly for quick tests
    pytest.main([__file__, "-v"])
