"""
Unit tests for PlaintextParser and its line-level parse helpers.

These tests are pure Python — no GnuCash session required.
"""

import os
import tempfile

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse(text: str):
    """Parse a plaintext string and return the root directive."""
    from services.plaintext_parser import PlaintextParser
    p = PlaintextParser()
    p.parse_string(text)
    return p


# ---------------------------------------------------------------------------
# parse_transaction_head
# ---------------------------------------------------------------------------

class TestParseTransactionHead:
    def test_date_and_description(self):
        from services.plaintext_parser import parse_transaction_head
        date, num, desc = parse_transaction_head('2024-03-01 * "Grocery shopping"')
        assert date == '2024-03-01'
        assert num is None
        assert desc == 'Grocery shopping'

    def test_date_num_and_description(self):
        from services.plaintext_parser import parse_transaction_head
        date, num, desc = parse_transaction_head('2024-03-01 * "42" "Grocery shopping"')
        assert date == '2024-03-01'
        assert num == '42'
        assert desc == 'Grocery shopping'

    def test_date_only(self):
        from services.plaintext_parser import parse_transaction_head
        date, num, desc = parse_transaction_head('2024-03-01 *')
        assert date == '2024-03-01'
        assert num is None
        assert desc is None

    def test_non_transaction_line_returns_none(self):
        from services.plaintext_parser import parse_transaction_head
        date, num, desc = parse_transaction_head('  Expenses:Dining  30.45 CAD')
        assert date is None
        assert num is None
        assert desc is None


# ---------------------------------------------------------------------------
# parse_split
# ---------------------------------------------------------------------------

class TestParseSplit:
    def test_basic_split(self):
        from services.plaintext_parser import parse_split
        account, amount, symbol = parse_split('  Expenses:Dining  30.45 CAD')
        assert account == 'Expenses:Dining'
        assert amount == '30.45'
        assert symbol == 'CAD'

    def test_negative_amount(self):
        from services.plaintext_parser import parse_split
        account, amount, symbol = parse_split('  Assets:Bank:Checking  -30.45 CAD')
        assert account == 'Assets:Bank:Checking'
        assert amount == '-30.45'
        assert symbol == 'CAD'

    def test_non_split_line_returns_none(self):
        from services.plaintext_parser import parse_split
        account, amount, symbol = parse_split('2024-03-01 * "Grocery shopping"')
        assert account is None
        assert amount is None
        assert symbol is None


# ---------------------------------------------------------------------------
# parse_metadata
# ---------------------------------------------------------------------------

class TestParseMetadata:
    def test_simple_key_value(self):
        from services.plaintext_parser import parse_metadata
        key, value = parse_metadata('  notes: some note here')
        assert key == 'notes'
        assert value == 'some note here'

    def test_key_with_dots(self):
        from services.plaintext_parser import parse_metadata
        key, value = parse_metadata('  commodity.mnemonic: CAD')
        assert key == 'commodity.mnemonic'
        assert value == 'CAD'

    def test_non_metadata_line_returns_none(self):
        from services.plaintext_parser import parse_metadata
        key, value = parse_metadata('  Expenses:Dining  30.45 CAD')
        assert key is None
        assert value is None

    def test_quoted_value_decoded(self):
        from services.plaintext_parser import parse_metadata
        key, value = parse_metadata('  notes: "a quoted note"')
        assert key == 'notes'
        assert value == 'a quoted note'


# ---------------------------------------------------------------------------
# parse_open_account
# ---------------------------------------------------------------------------

class TestParseOpenAccount:
    def test_basic_account(self):
        from services.plaintext_parser import parse_open_account
        # The open_account_pattern captures everything after "open " into the account
        # group; the commodity symbol (if on the same line) is included in the name.
        # Use the name-only form to test a clean result.
        date, directive, name = parse_open_account('2024-01-01 open Assets:Bank:Checking')
        assert date == '2024-01-01'
        assert directive == 'open'
        assert name == 'Assets:Bank:Checking'

    def test_non_account_line_returns_none(self):
        from services.plaintext_parser import parse_open_account
        date, directive, name = parse_open_account('2024-03-01 * "Grocery shopping"')
        assert date is None


# ---------------------------------------------------------------------------
# parse_commodity_directive
# ---------------------------------------------------------------------------

class TestParseCommodityDirective:
    def test_commodity_line(self):
        from services.plaintext_parser import parse_commodity_directive
        date, directive, symbol = parse_commodity_directive('2024-01-01 commodity CAD')
        assert date == '2024-01-01'
        assert directive == 'commodity'
        assert symbol == 'CAD'

    def test_non_commodity_line_returns_none(self):
        from services.plaintext_parser import parse_commodity_directive
        date, directive, symbol = parse_commodity_directive('2024-03-01 * "Grocery shopping"')
        assert date is None


# ---------------------------------------------------------------------------
# PlaintextParser.parse_string — full directive tree
# ---------------------------------------------------------------------------

class TestParseTransaction:
    def test_transaction_with_splits_and_metadata(self):
        text = """\
2024-03-01 * "Grocery shopping"
    notes: receipt #1234
    guid: abcd1234
    Expenses:Groceries  50.00 CAD
    Assets:Bank:Checking  -50.00 CAD
"""
        p = _parse(text)
        assert not p.errors
        txs = [d for d in p.root_directive.children
               if d.type.name == 'TRANSACTION']
        assert len(txs) == 1
        tx = txs[0]
        assert tx.props['tx_desc'] == 'Grocery shopping'
        assert tx.props['date'] == '2024-03-01'
        assert tx.props['tx_num'] is None
        assert tx.metadata['notes'] == 'receipt #1234'
        assert tx.metadata['guid'] == 'abcd1234'
        assert len(tx.children) == 2

    def test_transaction_with_tx_num(self):
        text = '2024-03-01 * "42" "Grocery shopping"\n    Expenses:Groceries  50.00 CAD\n    Assets:Bank:Checking  -50.00 CAD\n'
        p = _parse(text)
        tx = next(d for d in p.root_directive.children if d.type.name == 'TRANSACTION')
        assert tx.props['tx_num'] == '42'
        assert tx.props['tx_desc'] == 'Grocery shopping'

    def test_transaction_without_tx_num(self):
        text = '2024-03-01 * "Grocery shopping"\n    Expenses:Groceries  50.00 CAD\n    Assets:Bank:Checking  -50.00 CAD\n'
        p = _parse(text)
        tx = next(d for d in p.root_directive.children if d.type.name == 'TRANSACTION')
        assert tx.props['tx_num'] is None

    def test_two_splits_same_account(self):
        """Duplicate-account splits both appear as children."""
        text = """\
2024-03-07 * "Restaurant meal"
    Expenses:Dining  30.45 CAD
    Expenses:Dining  5.00 CAD
    Assets:Bank:Checking  -35.45 CAD
"""
        p = _parse(text)
        tx = next(d for d in p.root_directive.children if d.type.name == 'TRANSACTION')
        dining = [c for c in tx.children if c.props['account'] == 'Expenses:Dining']
        assert len(dining) == 2
        amounts = sorted(c.props['amount'] for c in dining)
        assert amounts == ['30.45', '5.00']

    def test_split_with_memo_and_action_metadata(self):
        text = """\
2024-03-01 * "Investment"
    Assets:Broker  10 MSFT
        memo: buy order
        action: Buy
        share_price: 150.00
    Assets:Bank:Checking  -1500.00 CAD
"""
        p = _parse(text)
        tx = next(d for d in p.root_directive.children if d.type.name == 'TRANSACTION')
        broker_split = next(c for c in tx.children if c.props['account'] == 'Assets:Broker')
        assert broker_split.metadata.get('memo') == 'buy order'
        assert broker_split.metadata.get('action') == 'Buy'
        assert broker_split.metadata.get('share_price') == 150.0

    def test_split_with_value_metadata(self):
        text = """\
2024-03-01 * "FX purchase"
    Assets:USD  100 USD
        value: 135.00
    Assets:Bank:Checking  -135.00 CAD
"""
        p = _parse(text)
        tx = next(d for d in p.root_directive.children if d.type.name == 'TRANSACTION')
        usd_split = next(c for c in tx.children if c.props['account'] == 'Assets:USD')
        assert usd_split.metadata.get('value') == 135.0

    def test_custom_metadata_on_transaction(self):
        text = """\
2024-03-01 * "Expense"
    my_ref: REF-001
    Expenses:Dining  25.00 CAD
    Assets:Bank:Checking  -25.00 CAD
"""
        p = _parse(text)
        tx = next(d for d in p.root_directive.children if d.type.name == 'TRANSACTION')
        assert tx.metadata.get('my_ref') == 'REF-001'

    def test_custom_metadata_on_split(self):
        text = """\
2024-03-01 * "Expense"
    Expenses:Dining  25.00 CAD
        vendor: Acme
    Assets:Bank:Checking  -25.00 CAD
"""
        p = _parse(text)
        tx = next(d for d in p.root_directive.children if d.type.name == 'TRANSACTION')
        dining = next(c for c in tx.children if c.props['account'] == 'Expenses:Dining')
        assert dining.metadata.get('vendor') == 'Acme'


class TestParseAccount:
    def test_open_account_directive(self):
        text = '2024-01-01 open Assets:Bank:Checking\n    type: BANK\n    commodity.namespace: CURRENCY\n    commodity.mnemonic: CAD\n'
        p = _parse(text)
        accounts = [d for d in p.root_directive.children if d.type.name == 'OPEN_ACCOUNT']
        assert len(accounts) == 1
        assert accounts[0].props['account'] == 'Assets:Bank:Checking'
        assert accounts[0].metadata.get('type') == 'BANK'

    def test_account_registered_in_accounts_dict(self):
        text = '2024-01-01 open Assets:Bank:Checking\n'
        p = _parse(text)
        assert 'Assets:Bank:Checking' in p.accounts


class TestParseCommodity:
    def test_commodity_directive(self):
        text = '2024-01-01 commodity CAD\n    namespace: CURRENCY\n    mnemonic: CAD\n'
        p = _parse(text)
        commodities = [d for d in p.root_directive.children if d.type.name == 'CREATE_COMMODITY']
        assert len(commodities) == 1
        assert commodities[0].props['symbol'] == 'CAD'

    def test_commodity_registered_in_commodities_dict(self):
        text = '2024-01-01 commodity CAD\n    namespace: CURRENCY\n    mnemonic: CAD\n'
        p = _parse(text)
        assert 'CAD' in p.commodities


class TestParseCustomerVendor:
    def test_customer_directive(self):
        text = 'customer "CUST-001"\n    name: Acme Corp\n    currency: CAD\n'
        p = _parse(text)
        customers = [d for d in p.root_directive.children if d.type.name == 'CUSTOMER']
        assert len(customers) == 1
        assert customers[0].props['id'] == 'CUST-001'

    def test_vendor_directive(self):
        text = 'vendor "VEND-001"\n    name: Supplier Inc\n    currency: CAD\n'
        p = _parse(text)
        vendors = [d for d in p.root_directive.children if d.type.name == 'VENDOR']
        assert len(vendors) == 1
        assert vendors[0].props['id'] == 'VEND-001'


class TestParseFile:
    def test_parse_file_matches_parse_string(self):
        """parse_file() and parse_string() on the same content produce same result."""
        content = '2024-03-01 * "Grocery shopping"\n    Expenses:Groceries  50.00 CAD\n    Assets:Bank:Checking  -50.00 CAD\n'

        from services.plaintext_parser import PlaintextParser

        p_string = PlaintextParser()
        p_string.parse_string(content)

        fd, path = tempfile.mkstemp(suffix='.txt')
        try:
            with os.fdopen(fd, 'w') as f:
                f.write(content)
            p_file = PlaintextParser()
            p_file.parse_file(path)
        finally:
            if os.path.exists(path):
                os.unlink(path)

        string_txs = [d for d in p_string.root_directive.children if d.type.name == 'TRANSACTION']
        file_txs = [d for d in p_file.root_directive.children if d.type.name == 'TRANSACTION']
        assert len(string_txs) == len(file_txs) == 1
        assert string_txs[0].props['tx_desc'] == file_txs[0].props['tx_desc']


class TestParseIndentationErrors:
    def test_mixed_tabs_and_spaces_adds_error(self):
        from services.plaintext_parser import PlaintextParser
        # First indented line uses tabs, to trigger mixed-indent detection
        text = '2024-03-01 * "Test"\n\t Expenses:Dining  25.00 CAD\n'
        p = PlaintextParser()
        p.parse_string(text)
        assert len(p.errors) > 0
