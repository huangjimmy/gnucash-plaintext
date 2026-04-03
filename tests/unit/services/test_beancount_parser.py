"""
Unit tests for BeancountParser.

These tests are pure Python — no GnuCash session required.
The parser expects beancount files with gnucash-* metadata annotations.
"""

import pytest

# ---------------------------------------------------------------------------
# Minimal valid beancount snippets
# ---------------------------------------------------------------------------

COMMODITY_BLOCK = """\
2024-01-01 commodity CAD
  gnucash-mnemonic: "CAD"
  gnucash-namespace: "CURRENCY"
  gnucash-fullname: "Canadian Dollar"
  gnucash-fraction: "100"
"""

ACCOUNT_CHECKING = """\
2024-01-01 open Assets:Bank:Checking CAD
  gnucash-name: "Assets:Bank:Checking"
  gnucash-guid: "aaa111"
  gnucash-type: "BANK"
  gnucash-placeholder: "false"
"""

ACCOUNT_GROCERIES = """\
2024-01-01 open Expenses:Groceries CAD
  gnucash-name: "Expenses:Groceries"
  gnucash-guid: "bbb222"
  gnucash-type: "EXPENSE"
  gnucash-placeholder: "false"
"""

TX_BLOCK = """\
2024-03-01 * "Grocery shopping"
  gnucash-guid: "tx-guid-001"
  Assets:Bank:Checking -50.00 CAD
  Expenses:Groceries 50.00 CAD
"""

FULL_VALID = COMMODITY_BLOCK + "\n" + ACCOUNT_CHECKING + "\n" + ACCOUNT_GROCERIES + "\n" + TX_BLOCK


# ---------------------------------------------------------------------------
# Commodity parsing
# ---------------------------------------------------------------------------

class TestBeancountParserCommodity:
    def test_commodity_parsed(self):
        from services.beancount_parser import BeancountParser
        p = BeancountParser()
        p.parse(COMMODITY_BLOCK + "\n" + ACCOUNT_CHECKING + "\n")
        assert len(p.commodities) == 1
        c = p.commodities[0]
        assert c.symbol == 'CAD'
        assert c.gnucash_mnemonic == 'CAD'
        assert c.gnucash_namespace == 'CURRENCY'
        assert c.gnucash_fullname == 'Canadian Dollar'
        assert c.gnucash_fraction == 100

    def test_commodity_missing_mnemonic_raises(self):
        from services.beancount_parser import BeancountParser, BeancountValidationError
        content = """\
2024-01-01 commodity CAD
  gnucash-namespace: "CURRENCY"
"""
        p = BeancountParser()
        with pytest.raises(BeancountValidationError, match="gnucash-mnemonic"):
            p.parse(content)

    def test_commodity_missing_namespace_raises(self):
        from services.beancount_parser import BeancountParser, BeancountValidationError
        content = """\
2024-01-01 commodity CAD
  gnucash-mnemonic: "CAD"
"""
        p = BeancountParser()
        with pytest.raises(BeancountValidationError, match="gnucash-namespace"):
            p.parse(content)


# ---------------------------------------------------------------------------
# Account parsing
# ---------------------------------------------------------------------------

class TestBeancountParserAccount:
    def test_account_parsed(self):
        from services.beancount_parser import BeancountParser
        p = BeancountParser()
        p.parse(ACCOUNT_CHECKING)
        assert len(p.accounts) == 1
        a = p.accounts[0]
        assert a.account == 'Assets:Bank:Checking'
        assert a.gnucash_name == 'Assets:Bank:Checking'
        assert a.gnucash_guid == 'aaa111'
        assert a.gnucash_type == 'BANK'
        assert a.gnucash_placeholder == 'false'

    def test_account_missing_required_metadata_raises(self):
        from services.beancount_parser import BeancountParser, BeancountValidationError
        # Missing gnucash-guid
        content = """\
2024-01-01 open Assets:Bank:Checking CAD
  gnucash-name: "Assets:Bank:Checking"
  gnucash-type: "BANK"
  gnucash-placeholder: "false"
"""
        p = BeancountParser()
        with pytest.raises(BeancountValidationError, match="gnucash-guid"):
            p.parse(content)

    def test_account_registered_in_opened_accounts(self):
        from services.beancount_parser import BeancountParser
        p = BeancountParser()
        p.parse(ACCOUNT_CHECKING)
        assert 'Assets:Bank:Checking' in p.opened_accounts

    def test_get_account_mapping(self):
        from services.beancount_parser import BeancountParser
        p = BeancountParser()
        p.parse(ACCOUNT_CHECKING + "\n" + ACCOUNT_GROCERIES)
        mapping = p.get_account_mapping()
        assert mapping['Assets:Bank:Checking'] == 'Assets:Bank:Checking'
        assert mapping['Expenses:Groceries'] == 'Expenses:Groceries'


# ---------------------------------------------------------------------------
# Transaction parsing
# ---------------------------------------------------------------------------

class TestBeancountParserTransaction:
    def test_transaction_parsed(self):
        from services.beancount_parser import BeancountParser
        p = BeancountParser()
        p.parse(FULL_VALID)
        assert len(p.transactions) == 1
        tx = p.transactions[0]
        assert tx.gnucash_guid == 'tx-guid-001'
        assert tx.narration == 'Grocery shopping'
        assert tx.flag == '*'
        assert len(tx.postings) == 2

    def test_transaction_posting_amounts(self):
        from services.beancount_parser import BeancountParser
        p = BeancountParser()
        p.parse(FULL_VALID)
        tx = p.transactions[0]
        amounts = {post.account: post.amount for post in tx.postings}
        assert amounts['Assets:Bank:Checking'] == '-50.00'
        assert amounts['Expenses:Groceries'] == '50.00'

    def test_transaction_missing_guid_raises(self):
        from services.beancount_parser import BeancountParser, BeancountValidationError
        content = (
            ACCOUNT_CHECKING + "\n" + ACCOUNT_GROCERIES + "\n"
            + "2024-03-01 * \"Grocery shopping\"\n"
            + "  Assets:Bank:Checking -50.00 CAD\n"
            + "  Expenses:Groceries 50.00 CAD\n"
        )
        p = BeancountParser()
        with pytest.raises(BeancountValidationError, match="gnucash-guid"):
            p.parse(content)

    def test_transaction_with_notes_and_doclink(self):
        from services.beancount_parser import BeancountParser
        content = (
            ACCOUNT_CHECKING + "\n" + ACCOUNT_GROCERIES + "\n"
            + "2024-03-01 * \"Grocery shopping\"\n"
            + "  gnucash-guid: \"tx-guid-002\"\n"
            + "  gnucash-notes: \"some note\"\n"
            + "  gnucash-doclink: \"https://example.com\"\n"
            + "  Assets:Bank:Checking -50.00 CAD\n"
            + "  Expenses:Groceries 50.00 CAD\n"
        )
        p = BeancountParser()
        p.parse(content)
        tx = p.transactions[0]
        assert tx.gnucash_notes == 'some note'
        assert tx.gnucash_doclink == 'https://example.com'

    def test_posting_with_memo_and_action(self):
        from services.beancount_parser import BeancountParser
        content = (
            ACCOUNT_CHECKING + "\n" + ACCOUNT_GROCERIES + "\n"
            + "2024-03-01 * \"Grocery shopping\"\n"
            + "  gnucash-guid: \"tx-guid-003\"\n"
            + "  Assets:Bank:Checking -50.00 CAD\n"
            + "    gnucash-memo: \"payment\"\n"
            + "    gnucash-action: \"payment\"\n"
            + "  Expenses:Groceries 50.00 CAD\n"
        )
        p = BeancountParser()
        p.parse(content)
        tx = p.transactions[0]
        checking = next(post for post in tx.postings if post.account == 'Assets:Bank:Checking')
        assert checking.gnucash_memo == 'payment'
        assert checking.gnucash_action == 'payment'

    def test_used_accounts_tracked(self):
        from services.beancount_parser import BeancountParser
        p = BeancountParser()
        p.parse(FULL_VALID)
        assert 'Assets:Bank:Checking' in p.used_accounts
        assert 'Expenses:Groceries' in p.used_accounts


# ---------------------------------------------------------------------------
# Validation: implicit accounts
# ---------------------------------------------------------------------------

class TestBeancountParserValidation:
    def test_implicit_account_raises(self):
        """Transaction references an account with no open directive."""
        from services.beancount_parser import BeancountParser, BeancountValidationError
        content = (
            ACCOUNT_CHECKING + "\n"
            + "2024-03-01 * \"Grocery shopping\"\n"
            + "  gnucash-guid: \"tx-guid-001\"\n"
            + "  Assets:Bank:Checking -50.00 CAD\n"
            + "  Expenses:Groceries 50.00 CAD\n"   # no open for this
        )
        p = BeancountParser()
        with pytest.raises(BeancountValidationError, match="Implicit accounts"):
            p.parse(content)

    def test_all_accounts_open_passes(self):
        from services.beancount_parser import BeancountParser
        p = BeancountParser()
        p.parse(FULL_VALID)  # should not raise
        assert len(p.transactions) == 1

    def test_comments_and_blank_lines_skipped(self):
        from services.beancount_parser import BeancountParser
        content = "; this is a comment\n\n" + FULL_VALID
        p = BeancountParser()
        p.parse(content)
        assert len(p.transactions) == 1
