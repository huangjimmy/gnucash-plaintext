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

        assert sig == ("2024-01-15", ("Assets:Bank:Checking", "Expenses:Groceries"), None)

    def test_signature_accounts_are_sorted(self):
        """Test that accounts in signature are sorted"""
        from services.transaction_matcher import TransactionMatcher

        matcher = TransactionMatcher()

        sig1 = matcher.get_signature_for_plaintext(
            "2024-01-15",
            ["Zebra:Account", "Apple:Account", "Mango:Account"]
        )

        _, accounts, _ = sig1
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

    def test_signature_doc_link_matters(self):
        """Test that different doc_links produce different signatures"""
        from services.transaction_matcher import TransactionMatcher

        matcher = TransactionMatcher()

        sig1 = matcher.get_signature_for_plaintext(
            "2024-01-15",
            ["Assets:Bank:Checking", "Expenses:Groceries"],
            doc_link="receipts/trip_a.txt",
        )

        sig2 = matcher.get_signature_for_plaintext(
            "2024-01-15",
            ["Assets:Bank:Checking", "Expenses:Groceries"],
            doc_link="receipts/trip_b.txt",  # Different receipt
        )

        assert sig1 != sig2

    def test_signature_same_doc_link_matches(self):
        """Test that same doc_link produces same signature"""
        from services.transaction_matcher import TransactionMatcher

        matcher = TransactionMatcher()

        sig1 = matcher.get_signature_for_plaintext(
            "2024-01-15",
            ["Assets:Bank:Checking", "Expenses:Groceries"],
            doc_link="receipts/trip.txt",
        )

        sig2 = matcher.get_signature_for_plaintext(
            "2024-01-15",
            ["Assets:Bank:Checking", "Expenses:Groceries"],
            doc_link="receipts/trip.txt",
        )

        assert sig1 == sig2

    def test_signature_none_doc_link_matches_none(self):
        """Test that None doc_link matches None (both transactions lack a receipt)"""
        from services.transaction_matcher import TransactionMatcher

        matcher = TransactionMatcher()

        sig1 = matcher.get_signature_for_plaintext(
            "2024-01-15",
            ["Assets:Bank:Checking", "Expenses:Groceries"],
            doc_link=None,
        )

        sig2 = matcher.get_signature_for_plaintext(
            "2024-01-15",
            ["Assets:Bank:Checking", "Expenses:Groceries"],
        )  # doc_link defaults to None

        assert sig1 == sig2

    def test_signature_none_vs_non_none_doc_link_differs(self):
        """Test that None doc_link does not match a non-None doc_link"""
        from services.transaction_matcher import TransactionMatcher

        matcher = TransactionMatcher()

        sig_none = matcher.get_signature_for_plaintext(
            "2024-01-15",
            ["Assets:Bank:Checking", "Expenses:Groceries"],
            doc_link=None,
        )

        sig_set = matcher.get_signature_for_plaintext(
            "2024-01-15",
            ["Assets:Bank:Checking", "Expenses:Groceries"],
            doc_link="receipts/trip.txt",
        )

        assert sig_none != sig_set


if __name__ == "__main__":
    # Allow running directly for quick tests
    pytest.main([__file__, "-v"])
