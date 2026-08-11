"""
Error-path tests for GnuCashImporter.

These tests verify that every code path that calls find_account() raises a
clear, descriptive Exception (not AttributeError) when the account name does
not exist in the book.

Before the fix, these paths crashed with:
    AttributeError: 'NoneType' object has no attribute 'GetCommodity'
    (or similar method calls on None)

After the fix, every path raises Exception with the missing account name
in the message.

Coverage:
- create_transaction: first split account missing (currency-derivation path)
- create_transaction: non-first split account missing (split-loop path)
- update_transaction: desired split account missing
- import_taxtable: first entry account missing
- import_taxtable: subsequent entry account missing
- import_invoice: invoice entry account (income account) missing
- import_invoice: AR account missing on POSTED directive
- import_invoice: bank account missing on PAYMENT directive
- import_bill: bill entry account (expense account) missing
- import_bill: AP account missing on POSTED directive
- import_bill: bank account missing on PAYMENT directive
- import_from_file integration: first-split unknown account → error_count==1
- import_from_file integration: second-split unknown account → error_count==1
"""

import os
import tempfile

import pytest

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_book():
    """
    Create a minimal GnuCash session with CAD accounts.

    Returns (session, book) — caller is responsible for session.end().

    Account hierarchy:
        Assets:Bank:Checking  CAD
        Expenses:Dining       CAD
        Income:Sales          CAD
        Liabilities:CreditCard CAD
        Equity:Opening        CAD
    """
    import gnucash
    from gnucash import Account, Session

    fd, path = tempfile.mkstemp(suffix='.gnucash')
    os.close(fd)
    os.unlink(path)

    try:
        from gnucash import SessionOpenMode
        session = Session(f'xml://{path}', SessionOpenMode.SESSION_NEW_STORE)
    except ImportError:
        session = Session(f'xml://{path}', is_new=True)

    book = session.book
    root = book.get_root_account()
    cad = book.get_table().lookup('CURRENCY', 'CAD')

    def _acct(name, acct_type, parent, commodity=None):
        a = Account(book)
        a.SetName(name)
        a.SetType(acct_type)
        a.SetCommodity(commodity or cad)
        parent.append_child(a)
        return a

    assets = _acct('Assets', gnucash.ACCT_TYPE_ASSET, root)
    bank = _acct('Bank', gnucash.ACCT_TYPE_BANK, assets)
    _acct('Checking', gnucash.ACCT_TYPE_BANK, bank)

    expenses = _acct('Expenses', gnucash.ACCT_TYPE_EXPENSE, root)
    _acct('Dining', gnucash.ACCT_TYPE_EXPENSE, expenses)

    income = _acct('Income', gnucash.ACCT_TYPE_INCOME, root)
    _acct('Sales', gnucash.ACCT_TYPE_INCOME, income)

    liabilities = _acct('Liabilities', gnucash.ACCT_TYPE_LIABILITY, root)
    _acct('CreditCard', gnucash.ACCT_TYPE_CREDIT, liabilities)

    equity = _acct('Equity', gnucash.ACCT_TYPE_EQUITY, root)
    _acct('Opening', gnucash.ACCT_TYPE_EQUITY, equity)

    return session, book, path


def _split_directive(account_name, amount_str):
    """Build a minimal SPLIT PlaintextDirective."""
    from services.plaintext_parser import DirectiveType, PlaintextDirective
    d = PlaintextDirective(DirectiveType.SPLIT, 1, '')
    d.props = {'account': account_name, 'amount': amount_str}
    d.metadata = {}
    return d


def _tx_directive_with_currency(splits, date='2024-06-15', desc='Test', currency_mnemonic='CAD'):
    """
    Build a TRANSACTION directive that carries explicit currency metadata.

    This exercises the split-loop path (currency already known).
    """
    from services.plaintext_parser import DirectiveType, PlaintextDirective
    d = PlaintextDirective(DirectiveType.TRANSACTION, 0, '2024-06-15')
    d.props = {'date': date, 'tx_num': None, 'tx_desc': desc}
    d.metadata = {'currency.namespace': 'CURRENCY', 'currency.mnemonic': currency_mnemonic}
    d.children = splits
    return d


def _tx_directive_without_currency(splits, date='2024-06-15', desc='Test'):
    """
    Build a TRANSACTION directive WITHOUT currency metadata.

    The importer will try to derive currency from the first split account.
    This exercises the currency-detection path.
    """
    from services.plaintext_parser import DirectiveType, PlaintextDirective
    d = PlaintextDirective(DirectiveType.TRANSACTION, 0, '2024-06-15')
    d.props = {'date': date, 'tx_num': None, 'tx_desc': desc}
    d.metadata = {}
    d.children = splits
    return d


# ---------------------------------------------------------------------------
# create_transaction — first split unknown (currency-derivation path)
# ---------------------------------------------------------------------------

class TestCreateTransactionErrors:

    def test_first_split_unknown_account_raises_exception(self):
        """
        When currency.mnemonic is absent, importer derives currency from the
        first split's account.  A missing account must raise Exception with
        the account name — not AttributeError on NoneType.
        """
        from services.gnucash_importer import GnuCashImporter

        session, book, path = _make_book()
        try:
            splits = [
                _split_directive('Assets:DoesNotExist', '50.00'),
                _split_directive('Expenses:Dining', '-50.00'),
            ]
            directive = _tx_directive_without_currency(splits)

            with pytest.raises(Exception, match="Assets:DoesNotExist"):
                GnuCashImporter.create_transaction(directive, book)
        finally:
            session.end()
            if os.path.exists(path):
                os.unlink(path)

    def test_first_split_unknown_account_is_not_attribute_error(self):
        """Error must be a descriptive Exception, not the raw AttributeError from None."""
        from services.gnucash_importer import GnuCashImporter

        session, book, path = _make_book()
        try:
            splits = [
                _split_directive('Expenses:Ghost', '10.00'),
                _split_directive('Assets:Bank:Checking', '-10.00'),
            ]
            directive = _tx_directive_without_currency(splits)

            with pytest.raises(Exception) as exc_info:
                GnuCashImporter.create_transaction(directive, book)

            assert not isinstance(exc_info.value, AttributeError), (
                "Must not propagate raw AttributeError from NoneType")
            assert 'Expenses:Ghost' in str(exc_info.value)
        finally:
            session.end()
            if os.path.exists(path):
                os.unlink(path)

    def test_non_first_split_unknown_account_raises_exception(self):
        """
        When currency is provided explicitly, the importer still looks up each
        split account.  A missing account in the split loop must raise Exception.
        """
        from services.gnucash_importer import GnuCashImporter

        session, book, path = _make_book()
        try:
            splits = [
                _split_directive('Expenses:Dining', '30.00'),
                _split_directive('Assets:Bank:NoSuchAccount', '-30.00'),  # bad
            ]
            directive = _tx_directive_with_currency(splits)

            with pytest.raises(Exception, match="Assets:Bank:NoSuchAccount"):
                GnuCashImporter.create_transaction(directive, book)
        finally:
            session.end()
            if os.path.exists(path):
                os.unlink(path)

    def test_non_first_split_unknown_account_is_not_attribute_error(self):
        """Same 'not AttributeError' check for the split-loop path."""
        from services.gnucash_importer import GnuCashImporter

        session, book, path = _make_book()
        try:
            splits = [
                _split_directive('Expenses:Dining', '30.00'),
                _split_directive('Assets:Phantom', '-30.00'),
            ]
            directive = _tx_directive_with_currency(splits)

            with pytest.raises(Exception) as exc_info:
                GnuCashImporter.create_transaction(directive, book)

            assert not isinstance(exc_info.value, AttributeError)
            assert 'Assets:Phantom' in str(exc_info.value)
        finally:
            session.end()
            if os.path.exists(path):
                os.unlink(path)

    def test_valid_accounts_succeed(self):
        """Sanity-check: a transaction with valid accounts must not raise."""
        from services.gnucash_importer import GnuCashImporter

        session, book, path = _make_book()
        try:
            splits = [
                _split_directive('Expenses:Dining', '30.00'),
                _split_directive('Assets:Bank:Checking', '-30.00'),
            ]
            directive = _tx_directive_with_currency(splits)

            from gnucash import Transaction
            result = GnuCashImporter.create_transaction(directive, book)
            assert isinstance(result, Transaction)
            assert result.GetDescription() == 'Test'
            assert result.GetDate().strftime('%Y-%m-%d') == '2024-06-15'
        finally:
            session.end()
            if os.path.exists(path):
                os.unlink(path)


# ---------------------------------------------------------------------------
# update_transaction — unknown split account
# ---------------------------------------------------------------------------

class TestUpdateTransactionErrors:

    def _make_book_with_transaction(self):
        """Create book + one transaction; returns (session, book, tx, path)."""
        import gnucash
        from gnucash import Account, GncNumeric, Session, Split, Transaction

        fd, path = tempfile.mkstemp(suffix='.gnucash')
        os.close(fd)
        os.unlink(path)

        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{path}', SessionOpenMode.SESSION_NEW_STORE)
        except ImportError:
            session = Session(f'xml://{path}', is_new=True)

        book = session.book
        root = book.get_root_account()
        cad = book.get_table().lookup('CURRENCY', 'CAD')

        def _acct(name, acct_type, parent):
            a = Account(book)
            a.SetName(name)
            a.SetType(acct_type)
            a.SetCommodity(cad)
            parent.append_child(a)
            return a

        assets = _acct('Assets', gnucash.ACCT_TYPE_ASSET, root)
        bank = _acct('Bank', gnucash.ACCT_TYPE_BANK, assets)
        checking = _acct('Checking', gnucash.ACCT_TYPE_BANK, bank)
        expenses = _acct('Expenses', gnucash.ACCT_TYPE_EXPENSE, root)
        dining = _acct('Dining', gnucash.ACCT_TYPE_EXPENSE, expenses)

        tx = Transaction(book)
        tx.BeginEdit()
        tx.SetCurrency(cad)
        tx.SetDate(15, 6, 2024)
        tx.SetDescription('Dinner')

        s1 = Split(book)
        s1.SetParent(tx)
        s1.SetAccount(dining)
        s1.SetValue(GncNumeric(3000, 100))

        s2 = Split(book)
        s2.SetParent(tx)
        s2.SetAccount(checking)
        s2.SetValue(GncNumeric(-3000, 100))

        tx.CommitEdit()
        return session, book, tx, path

    def test_unknown_split_account_raises_value_error(self):
        """update_transaction with a nonexistent split account raises ValueError."""
        from services.gnucash_importer import GnuCashImporter

        session, book, tx, path = self._make_book_with_transaction()
        try:
            splits = [
                _split_directive('Expenses:Dining', '30.00'),
                _split_directive('Assets:Bank:NoSuchAccount', '-30.00'),
            ]
            directive = _tx_directive_with_currency(splits)
            directive.metadata['guid'] = tx.GetGUID().to_string()

            with pytest.raises(ValueError, match="Account not found"):
                GnuCashImporter.update_transaction(tx, directive, book)
        finally:
            session.end()
            if os.path.exists(path):
                os.unlink(path)

    def test_unknown_split_account_message_contains_name(self):
        """ValueError message must include the missing account name."""
        from services.gnucash_importer import GnuCashImporter

        session, book, tx, path = self._make_book_with_transaction()
        try:
            splits = [
                _split_directive('Expenses:Dining', '30.00'),
                _split_directive('Assets:Bank:Ghost', '-30.00'),
            ]
            directive = _tx_directive_with_currency(splits)
            directive.metadata['guid'] = tx.GetGUID().to_string()

            with pytest.raises(ValueError) as exc_info:
                GnuCashImporter.update_transaction(tx, directive, book)

            assert 'Assets:Bank:Ghost' in str(exc_info.value)
        finally:
            session.end()
            if os.path.exists(path):
                os.unlink(path)

    def test_transaction_not_left_in_edit_state_after_error(self):
        """
        After a ValueError from update_transaction the transaction must not
        be left in an open BeginEdit() state (RollbackEdit should be called).
        """
        from services.gnucash_importer import GnuCashImporter

        session, book, tx, path = self._make_book_with_transaction()
        try:
            splits = [
                _split_directive('Expenses:Dining', '30.00'),
                _split_directive('Assets:Nowhere', '-30.00'),
            ]
            directive = _tx_directive_with_currency(splits)
            directive.metadata['guid'] = tx.GetGUID().to_string()

            with pytest.raises(ValueError):
                GnuCashImporter.update_transaction(tx, directive, book)

            # If RollbackEdit was called, we can call BeginEdit again without error
            tx.BeginEdit()
            tx.RollbackEdit()
        finally:
            session.end()
            if os.path.exists(path):
                os.unlink(path)


# ---------------------------------------------------------------------------
# import_taxtable — unknown entry accounts
# ---------------------------------------------------------------------------

class TestImportTaxTableErrors:

    def _taxtable_entry_directive(self, account_name, rate='5%'):
        from services.plaintext_parser import DirectiveType, PlaintextDirective
        d = PlaintextDirective(DirectiveType.TAXTABLE_ENTRY, 1, '')
        d.props = {}
        d.metadata = {'account': account_name, 'rate': rate}
        return d

    def _taxtable_directive(self, name, entries):
        from services.plaintext_parser import DirectiveType, PlaintextDirective
        d = PlaintextDirective(DirectiveType.TAXTABLE, 0, '')
        d.props = {'name': name}
        d.metadata = {}
        d.children = entries
        return d

    def test_first_entry_unknown_account_raises_exception(self):
        from services.gnucash_importer import GnuCashImporter

        session, book, path = _make_book()
        try:
            entries = [self._taxtable_entry_directive('Income:TaxBucket')]
            directive = self._taxtable_directive('GST', entries)

            with pytest.raises(Exception, match="Income:TaxBucket"):
                GnuCashImporter.import_taxtable(directive, book)
        finally:
            session.end()
            if os.path.exists(path):
                os.unlink(path)

    def test_subsequent_entry_unknown_account_raises_exception(self):
        from services.gnucash_importer import GnuCashImporter

        session, book, path = _make_book()
        try:
            # First entry uses a valid account so taxtable is created
            entries = [
                self._taxtable_entry_directive('Income:Sales', '5%'),
                self._taxtable_entry_directive('Income:GhostAccount', '2%'),  # bad
            ]
            directive = self._taxtable_directive('HST', entries)

            with pytest.raises(Exception, match="Income:GhostAccount"):
                GnuCashImporter.import_taxtable(directive, book)
        finally:
            session.end()
            if os.path.exists(path):
                os.unlink(path)


# ---------------------------------------------------------------------------
# import_invoice — unknown accounts
# ---------------------------------------------------------------------------

class TestImportInvoiceErrors:

    def _make_book_with_customer(self):
        """Returns (session, book, path) with a customer 'C001' in the book."""
        import gnucash
        from gnucash import Account, Session
        from gnucash.gnucash_business import Customer

        fd, path = tempfile.mkstemp(suffix='.gnucash')
        os.close(fd)
        os.unlink(path)

        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{path}', SessionOpenMode.SESSION_NEW_STORE)
        except ImportError:
            session = Session(f'xml://{path}', is_new=True)

        book = session.book
        root = book.get_root_account()
        cad = book.get_table().lookup('CURRENCY', 'CAD')

        def _acct(name, acct_type, parent):
            a = Account(book)
            a.SetName(name)
            a.SetType(acct_type)
            a.SetCommodity(cad)
            parent.append_child(a)
            return a

        assets = _acct('Assets', gnucash.ACCT_TYPE_ASSET, root)
        _acct('Bank', gnucash.ACCT_TYPE_BANK, assets)
        _acct('AccountsReceivable', gnucash.ACCT_TYPE_RECEIVABLE, assets)

        income = _acct('Income', gnucash.ACCT_TYPE_INCOME, root)
        _acct('Sales', gnucash.ACCT_TYPE_INCOME, income)

        customer = Customer(book, 'C001', cad)
        customer.BeginEdit()
        customer.SetName('Test Customer')
        customer.CommitEdit()

        return session, book, path

    def _invoice_directive(self, customer_id, entries):
        from services.plaintext_parser import DirectiveType, PlaintextDirective
        d = PlaintextDirective(DirectiveType.INVOICE, 0, '')
        d.props = {'id': 'INV001'}
        d.metadata = {
            'currency': 'CAD',
            'customer_id': customer_id,
            'date_opened': '2024-06-01',
        }
        d.children = entries
        return d

    def _invoice_entry_directive(self, account_name):
        from services.plaintext_parser import DirectiveType, PlaintextDirective
        d = PlaintextDirective(DirectiveType.INVOICE_ENTRY, 1, '')
        d.props = {}
        d.metadata = {
            'date': '2024-06-01',
            'description': 'Consulting',
            'action': 'Hours',
            'account': account_name,
            'quantity': '1',
            'price': '100.00',
            'taxable': 'false',
            'tax_included': 'false',
        }
        return d

    def _posted_directive(self, ar_account_name):
        from services.plaintext_parser import DirectiveType, PlaintextDirective
        d = PlaintextDirective(DirectiveType.POSTED, 1, '')
        d.props = {}
        d.metadata = {
            'ar_account': ar_account_name,
            'date': '2024-06-01',
            'due': '2024-07-01',
            'memo': 'Invoice INV001',
            'accumulate': 'false',
        }
        return d

    def _payment_directive(self, bank_account_name):
        from services.plaintext_parser import DirectiveType, PlaintextDirective
        d = PlaintextDirective(DirectiveType.PAYMENT, 1, '')
        d.props = {}
        d.metadata = {
            'bank_account': bank_account_name,
            'date': '2024-06-15',
            'amount': '100.00',
            'memo': 'Payment',
            'num': None,
        }
        return d

    def test_invoice_entry_unknown_account_raises_exception(self):
        """Missing income account on invoice entry must raise Exception."""
        from services.gnucash_importer import GnuCashImporter

        session, book, path = self._make_book_with_customer()
        try:
            entries = [self._invoice_entry_directive('Income:DoesNotExist')]
            directive = self._invoice_directive('C001', entries)

            with pytest.raises(Exception, match="Income:DoesNotExist"):
                GnuCashImporter.import_invoice(directive, book)
        finally:
            session.end()
            if os.path.exists(path):
                os.unlink(path)

    def test_invoice_ar_account_not_found_raises_exception(self):
        """Missing AR account on POSTED directive must raise Exception."""
        from services.gnucash_importer import GnuCashImporter

        session, book, path = self._make_book_with_customer()
        try:
            entries = [
                self._invoice_entry_directive('Income:Sales'),
                self._posted_directive('Assets:NoSuchARAccount'),
            ]
            directive = self._invoice_directive('C001', entries)

            with pytest.raises(Exception, match="Assets:NoSuchARAccount"):
                GnuCashImporter.import_invoice(directive, book)
        finally:
            session.end()
            if os.path.exists(path):
                os.unlink(path)

    def test_invoice_payment_bank_not_found_raises_exception(self):
        """Missing bank account on PAYMENT directive must raise Exception."""
        from services.gnucash_importer import GnuCashImporter

        session, book, path = self._make_book_with_customer()
        try:
            entries = [
                self._invoice_entry_directive('Income:Sales'),
                self._posted_directive('Assets:AccountsReceivable'),
                self._payment_directive('Assets:Bank:NoSuchBank'),
            ]
            directive = self._invoice_directive('C001', entries)

            with pytest.raises(Exception, match="Assets:Bank:NoSuchBank"):
                GnuCashImporter.import_invoice(directive, book)
        finally:
            session.end()
            if os.path.exists(path):
                os.unlink(path)


# ---------------------------------------------------------------------------
# import_bill — unknown accounts
# ---------------------------------------------------------------------------

class TestImportBillErrors:

    def _make_book_with_vendor(self):
        """Returns (session, book, path) with vendor 'V001' in the book."""
        import gnucash
        from gnucash import Account, Session
        from gnucash.gnucash_business import Vendor

        fd, path = tempfile.mkstemp(suffix='.gnucash')
        os.close(fd)
        os.unlink(path)

        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{path}', SessionOpenMode.SESSION_NEW_STORE)
        except ImportError:
            session = Session(f'xml://{path}', is_new=True)

        book = session.book
        root = book.get_root_account()
        cad = book.get_table().lookup('CURRENCY', 'CAD')

        def _acct(name, acct_type, parent):
            a = Account(book)
            a.SetName(name)
            a.SetType(acct_type)
            a.SetCommodity(cad)
            parent.append_child(a)
            return a

        assets = _acct('Assets', gnucash.ACCT_TYPE_ASSET, root)
        _acct('Bank', gnucash.ACCT_TYPE_BANK, assets)

        liabilities = _acct('Liabilities', gnucash.ACCT_TYPE_LIABILITY, root)
        _acct('AccountsPayable', gnucash.ACCT_TYPE_PAYABLE, liabilities)

        expenses = _acct('Expenses', gnucash.ACCT_TYPE_EXPENSE, root)
        _acct('Supplies', gnucash.ACCT_TYPE_EXPENSE, expenses)

        vendor = Vendor(book, 'V001', cad)
        vendor.BeginEdit()
        vendor.SetName('Test Vendor')
        vendor.CommitEdit()

        return session, book, path

    def _bill_directive(self, vendor_id, entries):
        from services.plaintext_parser import DirectiveType, PlaintextDirective
        d = PlaintextDirective(DirectiveType.BILL, 0, '')
        d.props = {'id': 'BILL001'}
        d.metadata = {
            'currency': 'CAD',
            'vendor_id': vendor_id,
            'date_opened': '2024-06-01',
        }
        d.children = entries
        return d

    def _bill_entry_directive(self, account_name):
        from services.plaintext_parser import DirectiveType, PlaintextDirective
        d = PlaintextDirective(DirectiveType.BILL_ENTRY, 1, '')
        d.props = {}
        d.metadata = {
            'date': '2024-06-01',
            'description': 'Office supplies',
            'account': account_name,
            'quantity': '1',
            'price': '50.00',
            'taxable': 'false',
        }
        return d

    def _posted_directive(self, ap_account_name):
        from services.plaintext_parser import DirectiveType, PlaintextDirective
        d = PlaintextDirective(DirectiveType.POSTED, 1, '')
        d.props = {}
        d.metadata = {
            'ap_account': ap_account_name,
            'date': '2024-06-01',
            'due': '2024-07-01',
            'memo': 'Bill BILL001',
            'accumulate': 'false',
        }
        return d

    def _payment_directive(self, bank_account_name):
        from services.plaintext_parser import DirectiveType, PlaintextDirective
        d = PlaintextDirective(DirectiveType.PAYMENT, 1, '')
        d.props = {}
        d.metadata = {
            'bank_account': bank_account_name,
            'date': '2024-06-15',
            'amount': '50.00',
            'memo': 'Payment',
            'num': None,
        }
        return d

    def test_bill_entry_unknown_account_raises_exception(self):
        """Missing expense account on bill entry must raise Exception."""
        from services.gnucash_importer import GnuCashImporter

        session, book, path = self._make_book_with_vendor()
        try:
            entries = [self._bill_entry_directive('Expenses:DoesNotExist')]
            directive = self._bill_directive('V001', entries)

            with pytest.raises(Exception, match="Expenses:DoesNotExist"):
                GnuCashImporter.import_bill(directive, book)
        finally:
            session.end()
            if os.path.exists(path):
                os.unlink(path)

    def test_bill_ap_account_not_found_raises_exception(self):
        """Missing AP account on POSTED directive must raise Exception."""
        from services.gnucash_importer import GnuCashImporter

        session, book, path = self._make_book_with_vendor()
        try:
            entries = [
                self._bill_entry_directive('Expenses:Supplies'),
                self._posted_directive('Liabilities:NoSuchAPAccount'),
            ]
            directive = self._bill_directive('V001', entries)

            with pytest.raises(Exception, match="Liabilities:NoSuchAPAccount"):
                GnuCashImporter.import_bill(directive, book)
        finally:
            session.end()
            if os.path.exists(path):
                os.unlink(path)

    def test_bill_payment_bank_not_found_raises_exception(self):
        """Missing bank account on PAYMENT directive must raise Exception."""
        from services.gnucash_importer import GnuCashImporter

        session, book, path = self._make_book_with_vendor()
        try:
            entries = [
                self._bill_entry_directive('Expenses:Supplies'),
                self._posted_directive('Liabilities:AccountsPayable'),
                self._payment_directive('Assets:Bank:NoSuchBank'),
            ]
            directive = self._bill_directive('V001', entries)

            with pytest.raises(Exception, match="Assets:Bank:NoSuchBank"):
                GnuCashImporter.import_bill(directive, book)
        finally:
            session.end()
            if os.path.exists(path):
                os.unlink(path)


# ---------------------------------------------------------------------------
# Integration: import_from_file with unknown account names
# ---------------------------------------------------------------------------

class TestImportFromFileUnknownAccount:
    """
    End-to-end tests through ImportTransactionsUseCase.import_from_file().

    These exercise the full stack and confirm that unknown accounts in a
    plaintext file produce error_count==1 rather than an uncaught AttributeError.
    """

    def _write_plaintext(self, lines):
        fd, path = tempfile.mkstemp(suffix='.txt')
        with os.fdopen(fd, 'w') as f:
            f.write('\n'.join(lines))
        return path

    def test_first_split_unknown_account_counts_as_error(self, temp_gnucash_file):
        """
        Plaintext file where the first split references a nonexistent account.
        No currency header present, so importer tries to derive currency from
        first split (the fixed code path).
        """
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.import_transactions import ImportTransactionsUseCase

        plaintext = self._write_plaintext([
            '2024-06-15 * "Test"',
            '\tAssets:NonExistentAccount  50.00 CAD',
            '\tExpenses:Dining  -50.00 CAD',
        ])
        try:
            with GnuCashRepository(temp_gnucash_file) as repo:
                uc = ImportTransactionsUseCase(repo)
                result = uc.import_from_file(plaintext)

            assert result.error_count == 1
            assert result.imported_count == 0
        finally:
            os.unlink(plaintext)

    def test_second_split_unknown_account_counts_as_error(self, temp_gnucash_file):
        """
        Plaintext file where the second split references a nonexistent account.
        Currency header IS present, so currency detection succeeds but the
        split-loop path (the other fixed code path) raises.
        """
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.import_transactions import ImportTransactionsUseCase

        plaintext = self._write_plaintext([
            '2024-06-15 commodity CAD',
            '\tmnemonic: "CAD"',
            '\tfullname: "Canadian Dollar"',
            '\tnamespace: "CURRENCY"',
            '\tfraction: 100',
            '2024-06-15 * "Test"',
            '\tcurrency.namespace: "CURRENCY"',
            '\tcurrency.mnemonic: "CAD"',
            '\tExpenses:Dining  50.00 CAD',
            '\tAssets:Bank:NonExistentAccount  -50.00 CAD',
        ])
        try:
            with GnuCashRepository(temp_gnucash_file) as repo:
                uc = ImportTransactionsUseCase(repo)
                result = uc.import_from_file(plaintext)

            assert result.error_count == 1
            assert result.imported_count == 0
        finally:
            os.unlink(plaintext)

    def test_unknown_account_error_message_not_attribute_error(self, temp_gnucash_file):
        """
        The errors list must not contain 'AttributeError'.
        Before the fix, the error was: 'NoneType' object has no attribute 'GetCommodity'.
        After the fix, it must be a descriptive message with the account name.
        """
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.import_transactions import ImportTransactionsUseCase

        plaintext = self._write_plaintext([
            '2024-06-15 * "Test"',
            '\tAssets:GhostAccount  100.00 CAD',
            '\tExpenses:Dining  -100.00 CAD',
        ])
        try:
            with GnuCashRepository(temp_gnucash_file) as repo:
                uc = ImportTransactionsUseCase(repo)
                result = uc.import_from_file(plaintext)

            assert result.error_count == 1
            error_text = result.errors[0].get('error', '') if result.errors else ''
            assert 'AttributeError' not in error_text, (
                f"Error should not be AttributeError, got: {error_text}")
            assert 'Assets:GhostAccount' in error_text, (
                f"Error should name the missing account, got: {error_text}")
        finally:
            os.unlink(plaintext)

    def test_valid_import_still_succeeds(self, temp_gnucash_file):
        """Sanity check: a well-formed file with known accounts still imports."""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.import_transactions import ImportTransactionsUseCase

        plaintext = self._write_plaintext([
            '2024-06-15 * "Valid transaction"',
            '\tExpenses:Dining  50.00 CAD',
            '\tAssets:Bank:Checking  -50.00 CAD',
        ])
        try:
            with GnuCashRepository(temp_gnucash_file) as repo:
                uc = ImportTransactionsUseCase(repo)
                result = uc.import_from_file(plaintext)

            assert result.imported_count == 1
            assert result.error_count == 0
        finally:
            os.unlink(plaintext)


# ---------------------------------------------------------------------------
# create_commodity — idempotency and already-exists path
# ---------------------------------------------------------------------------

class TestCreateCommodity:
    def _commodity_directive(self, mnemonic='XTEST', namespace='FUND',
                              fullname='Test Commodity', fraction=100):
        from services.plaintext_parser import DirectiveType, PlaintextDirective
        d = PlaintextDirective(DirectiveType.CREATE_COMMODITY, 0, '')
        d.props = {'symbol': mnemonic, 'date': '2024-01-01'}
        d.metadata = {
            'mnemonic': mnemonic,
            'fullname': fullname,
            'namespace': namespace,
            'fraction': str(fraction),
        }
        return d

    def test_create_commodity_inserts_into_table(self):
        """A security — the only kind of commodity a file may invent.

        `XTEST` used to be declared here in the CURRENCY namespace, which
        GnuCash cannot store: it writes currencies without a name or a
        fraction and looks them up in its ISO 4217 table on read, so a code
        that is not in that table saves and then will not load. It is a fund
        now, which is what a unit nobody issues as currency actually is.
        """
        from services.gnucash_importer import GnuCashImporter

        session, book, path = _make_book()
        try:
            directive = self._commodity_directive()
            GnuCashImporter.create_commodity(directive, book)
            table = book.get_table()
            result = table.lookup('FUND', 'XTEST')
            assert result is not None
        finally:
            session.end()
            if os.path.exists(path):
                os.unlink(path)

    def test_a_currency_gnucash_does_not_issue_is_refused(self):
        """The same symbol in the CURRENCY namespace, which is not storable."""
        import pytest

        from services.gnucash_importer import GnuCashImporter

        session, book, path = _make_book()
        try:
            directive = self._commodity_directive(namespace='CURRENCY')
            with pytest.raises(Exception, match='ISO 4217'):
                GnuCashImporter.create_commodity(directive, book)
            assert book.get_table().lookup('CURRENCY', 'XTEST') is None
        finally:
            session.end()
            if os.path.exists(path):
                os.unlink(path)

    def test_create_commodity_already_exists_does_not_raise(self):
        """Calling create_commodity twice for the same symbol must not raise."""
        from services.gnucash_importer import GnuCashImporter

        session, book, path = _make_book()
        try:
            directive = self._commodity_directive()
            GnuCashImporter.create_commodity(directive, book)
            # Second call — commodity already exists
            GnuCashImporter.create_commodity(directive, book)
            # Still exactly one entry
            table = book.get_table()
            result = table.lookup('FUND', 'XTEST')
            assert result is not None
        finally:
            session.end()
            if os.path.exists(path):
                os.unlink(path)

    def test_create_commodity_wrong_type_raises(self):
        from services.gnucash_importer import GnuCashImporter
        from services.plaintext_parser import DirectiveType, PlaintextDirective

        session, book, path = _make_book()
        try:
            bad = PlaintextDirective(DirectiveType.TRANSACTION, 0, '')
            bad.props = {}
            bad.metadata = {}
            with pytest.raises(ValueError, match="Expected CREATE_COMMODITY"):
                GnuCashImporter.create_commodity(bad, book)
        finally:
            session.end()
            if os.path.exists(path):
                os.unlink(path)


# ---------------------------------------------------------------------------
# create_account — idempotency and error paths
# ---------------------------------------------------------------------------

class TestCreateAccount:
    def _account_directive(self, fullname, acct_type='Bank',
                            namespace='CURRENCY', mnemonic='CAD'):
        from services.plaintext_parser import DirectiveType, PlaintextDirective
        d = PlaintextDirective(DirectiveType.OPEN_ACCOUNT, 0, '')
        d.props = {'account': fullname, 'date': '2024-01-01'}
        d.metadata = {
            'type': acct_type,
            'commodity.namespace': namespace,
            'commodity.mnemonic': mnemonic,
        }
        return d

    def test_create_account_creates_new(self):
        from infrastructure.gnucash.utils import find_account
        from services.gnucash_importer import GnuCashImporter

        session, book, path = _make_book()
        try:
            directive = self._account_directive('Assets:Bank:Savings')
            GnuCashImporter.create_account(directive, book)
            root = book.get_root_account()
            assert find_account(root, 'Assets:Bank:Savings') is not None
        finally:
            session.end()
            if os.path.exists(path):
                os.unlink(path)

    def test_create_account_idempotent(self):
        """Calling create_account twice for the same name must not raise."""
        from services.gnucash_importer import GnuCashImporter

        session, book, path = _make_book()
        try:
            directive = self._account_directive('Assets:Bank:Savings')
            GnuCashImporter.create_account(directive, book)
            GnuCashImporter.create_account(directive, book)  # second call — no error
        finally:
            session.end()
            if os.path.exists(path):
                os.unlink(path)

    def test_create_account_unknown_parent_raises(self):
        from services.gnucash_importer import GnuCashImporter

        session, book, path = _make_book()
        try:
            # Parent "NoParent" does not exist
            directive = self._account_directive('NoParent:NewAccount')
            with pytest.raises(Exception, match="NoParent"):
                GnuCashImporter.create_account(directive, book)
        finally:
            session.end()
            if os.path.exists(path):
                os.unlink(path)

    def test_create_account_unknown_commodity_raises(self):
        from services.gnucash_importer import GnuCashImporter

        session, book, path = _make_book()
        try:
            directive = self._account_directive(
                'Assets:Bank:Savings',
                namespace='CURRENCY',
                mnemonic='NOTACURRENCY',
            )
            with pytest.raises(Exception, match="NOTACURRENCY"):
                GnuCashImporter.create_account(directive, book)
        finally:
            session.end()
            if os.path.exists(path):
                os.unlink(path)
