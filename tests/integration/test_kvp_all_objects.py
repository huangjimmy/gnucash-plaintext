"""
Integration tests for KVP metadata on customer, vendor, invoice, bill, and account objects.

Covers test cases C-KVP-01 through A-KVP-04 as described in F-010.

Tests use real GnuCash sessions (no mocks). Run in Docker via scripts/test.sh.
"""

import os
import tempfile

import pytest

from infrastructure.gnucash.utils import wrap_invoice_or_bill

# ---------------------------------------------------------------------------
# Session helpers (same pattern as test_kvp_metadata.py)
# ---------------------------------------------------------------------------

def _make_session(path):
    """Open a new GnuCash session at *path* (SESSION_NEW_STORE)."""
    from gnucash import Session
    try:
        from gnucash import SessionOpenMode
        return Session(f'xml://{path}', SessionOpenMode.SESSION_NEW_STORE)
    except ImportError:
        return Session(f'xml://{path}', is_new=True)


def _open_session(path):
    """Open an existing GnuCash session at *path*."""
    from gnucash import Session
    try:
        from gnucash import SessionOpenMode
        return Session(f'xml://{path}', SessionOpenMode.SESSION_NORMAL_OPEN)
    except ImportError:
        return Session(f'xml://{path}')


def _make_biz_book():
    """
    Create a minimal GnuCash book with accounts needed for business objects:
      - Assets:Accounts Receivable  (RECEIVABLE)
      - Assets:Bank:Checking        (BANK)
      - Liabilities:Accounts Payable (PAYABLE)
      - Income:Services             (INCOME)
      - Expenses:Purchases          (EXPENSE)

    Returns (session, book, path). Caller is responsible for cleanup.
    """
    import gnucash
    from gnucash import Account

    fd, path = tempfile.mkstemp(suffix='.gnucash')
    os.close(fd)
    os.unlink(path)

    session = _make_session(path)
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
    _acct('Accounts Receivable', gnucash.ACCT_TYPE_RECEIVABLE, assets)
    bank = _acct('Bank', gnucash.ACCT_TYPE_BANK, assets)
    _acct('Checking', gnucash.ACCT_TYPE_BANK, bank)

    liabilities = _acct('Liabilities', gnucash.ACCT_TYPE_LIABILITY, root)
    _acct('Accounts Payable', gnucash.ACCT_TYPE_PAYABLE, liabilities)

    income = _acct('Income', gnucash.ACCT_TYPE_INCOME, root)
    _acct('Services', gnucash.ACCT_TYPE_INCOME, income)

    expenses = _acct('Expenses', gnucash.ACCT_TYPE_EXPENSE, root)
    _acct('Purchases', gnucash.ACCT_TYPE_EXPENSE, expenses)

    return session, book, path


def _cleanup(path):
    """Remove GnuCash file and its lock file if they exist."""
    if os.path.exists(path):
        os.unlink(path)
    lock = path + '.LCK'
    if os.path.exists(lock):
        os.unlink(lock)


def _build_customer_directive(cust_id, name, currency='CAD', extra_meta=None):
    """Build a PlaintextDirective for a CUSTOMER."""
    from services.plaintext_parser import DirectiveType, PlaintextDirective

    d = PlaintextDirective(DirectiveType.CUSTOMER, level=0, line='')
    d.props = {'id': cust_id}
    d.metadata = {'name': name, 'currency': currency}
    if extra_meta:
        d.metadata.update(extra_meta)
    d.children = []
    return d


def _build_vendor_directive(vendor_id, name, currency='CAD', extra_meta=None):
    """Build a PlaintextDirective for a VENDOR."""
    from services.plaintext_parser import DirectiveType, PlaintextDirective

    d = PlaintextDirective(DirectiveType.VENDOR, level=0, line='')
    d.props = {'id': vendor_id}
    d.metadata = {'name': name, 'currency': currency}
    if extra_meta:
        d.metadata.update(extra_meta)
    d.children = []
    return d


def _build_invoice_directive(inv_id, customer_id, currency='CAD', extra_meta=None):
    """Build a minimal unposted PlaintextDirective for an INVOICE."""
    from services.plaintext_parser import DirectiveType, PlaintextDirective

    d = PlaintextDirective(DirectiveType.INVOICE, level=0, line='')
    d.props = {'id': inv_id}
    d.metadata = {
        'customer_id': customer_id,
        'currency': currency,
        'date_opened': '2024-01-01',
        'posted': 'none',
        'payment': 'none',
    }
    if extra_meta:
        d.metadata.update(extra_meta)
    d.children = []
    return d


def _build_bill_directive(bill_id, vendor_id, currency='CAD', extra_meta=None):
    """Build a minimal unposted PlaintextDirective for a BILL."""
    from services.plaintext_parser import DirectiveType, PlaintextDirective

    d = PlaintextDirective(DirectiveType.BILL, level=0, line='')
    d.props = {'id': bill_id}
    d.metadata = {
        'vendor_id': vendor_id,
        'currency': currency,
        'date_opened': '2024-01-01',
        'posted': 'none',
        'payment': 'none',
    }
    if extra_meta:
        d.metadata.update(extra_meta)
    d.children = []
    return d


def _build_account_directive(account_full_name, acct_type, currency_namespace='CURRENCY',
                              currency_mnemonic='CAD', extra_meta=None):
    """Build a PlaintextDirective for an OPEN_ACCOUNT."""
    from services.plaintext_parser import DirectiveType, PlaintextDirective

    d = PlaintextDirective(DirectiveType.OPEN_ACCOUNT, level=0, line='')
    d.props = {'account': account_full_name}
    d.metadata = {
        'type': acct_type,
        'placeholder': False,
        'code': '',
        'description': '',
        'tax_related': False,
        'commodity.namespace': currency_namespace,
        'commodity.mnemonic': currency_mnemonic,
    }
    if extra_meta:
        d.metadata.update(extra_meta)
    d.children = []
    return d


def _lookup_customers(book):
    """Return all Customer objects from book via QOF query."""
    import gnucash.gnucash_business as gb
    from gnucash import Query
    q = Query()
    q.search_for('gncCustomer')
    q.set_book(book)
    customers = [gb.Customer(instance=r) for r in q.run()]
    q.destroy()
    return customers


def _lookup_vendors(book):
    """Return all Vendor objects from book via QOF query."""
    import gnucash.gnucash_business as gb
    from gnucash import Query
    q = Query()
    q.search_for('gncVendor')
    q.set_book(book)
    vendors = [gb.Vendor(instance=r) for r in q.run()]
    q.destroy()
    return vendors


def _lookup_invoices(book):
    """Return all Invoice objects from book via QOF query."""
    import gnucash.gnucash_business as gb
    from gnucash import Query
    q = Query()
    q.search_for('gncInvoice')
    q.set_book(book)
    invoices = [wrap_invoice_or_bill(r) for r in q.run()]
    q.destroy()
    return invoices


# ---------------------------------------------------------------------------
# TestCustomerKvp
# ---------------------------------------------------------------------------

class TestCustomerKvp:
    def test_import_stores_custom_keys(self):
        """C-KVP-01: import_customer with jw.country stores it as KVP."""
        from infrastructure.gnucash.kvp import get_custom_metadata
        from services.gnucash_importer import GnuCashImporter

        session, book, path = _make_biz_book()
        try:
            d = _build_customer_directive(
                'CUST-001', 'Acme Logistics',
                extra_meta={'jw.country': 'CA', 'jw.postal_code': 'H3A 3H3'},
            )
            GnuCashImporter.import_customer(d, book)
            session.save()
            session.end()

            session2 = _open_session(path)
            book2 = session2.book
            customers = _lookup_customers(book2)
            assert len(customers) == 1
            custom = get_custom_metadata(customers[0])
            assert custom.get('jw.country') == 'CA'
            assert custom.get('jw.postal_code') == 'H3A 3H3'
            session2.end()
        finally:
            _cleanup(path)

    def test_export_emits_custom_keys(self):
        """C-KVP-02: get_custom_metadata on customer → export includes custom keys."""
        from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata
        from use_cases.export_business_objects import ExportBusinessObjectsUseCase

        session, book, path = _make_biz_book()
        try:
            d = _build_customer_directive('CUST-002', 'Beta Corp')
            from services.gnucash_importer import GnuCashImporter
            GnuCashImporter.import_customer(d, book)

            customers = _lookup_customers(book)
            assert len(customers) == 1
            set_custom_metadata(customers[0], {'jw.country': 'US', 'erp.id': 'ERP-42'})

            session.save()
            session.end()

            session2 = _open_session(path)
            book2 = session2.book
            use_case = ExportBusinessObjectsUseCase(book2)
            output = use_case.execute()
            session2.end()

            assert 'jw.country: "US"' in output
            assert 'erp.id: "ERP-42"' in output
        finally:
            _cleanup(path)

    def test_roundtrip(self):
        """C-KVP-03: import → save → export → custom keys present in output."""
        from services.gnucash_importer import GnuCashImporter
        from use_cases.export_business_objects import ExportBusinessObjectsUseCase

        session, book, path = _make_biz_book()
        try:
            d = _build_customer_directive(
                'CUST-003', 'Gamma Ltd',
                extra_meta={'jw.country': 'CA', 'jw.tier': 'premium'},
            )
            GnuCashImporter.import_customer(d, book)
            session.save()
            session.end()

            session2 = _open_session(path)
            book2 = session2.book
            use_case = ExportBusinessObjectsUseCase(book2)
            output = use_case.execute()
            session2.end()

            assert 'jw.country: "CA"' in output
            assert 'jw.tier: "premium"' in output
        finally:
            _cleanup(path)

    def test_kvp_isolation_between_customers(self):
        """C-KVP-04: custom KVP on one customer does not appear on another."""
        from services.gnucash_importer import GnuCashImporter
        from use_cases.export_business_objects import ExportBusinessObjectsUseCase

        session, book, path = _make_biz_book()
        try:
            d1 = _build_customer_directive(
                'CUST-010', 'Alpha Inc',
                extra_meta={'jw.secret': 'alpha-only'},
            )
            d2 = _build_customer_directive('CUST-011', 'Beta Inc')
            GnuCashImporter.import_customer(d1, book)
            GnuCashImporter.import_customer(d2, book)
            session.save()
            session.end()

            session2 = _open_session(path)
            book2 = session2.book
            use_case = ExportBusinessObjectsUseCase(book2)
            output = use_case.execute()
            session2.end()

            # Split output into customer blocks
            blocks = [b for b in output.split('\n\n') if b.startswith('customer')]
            cust10_block = next((b for b in blocks if '"CUST-010"' in b), '')
            cust11_block = next((b for b in blocks if '"CUST-011"' in b), '')
            assert 'jw.secret' in cust10_block
            assert 'jw.secret' not in cust11_block
        finally:
            _cleanup(path)

    def test_known_keys_not_stored_as_kvp(self):
        """C-KVP-05: name, addr1, email must NOT appear in custom KVP."""
        from infrastructure.gnucash.kvp import get_custom_metadata
        from services.gnucash_importer import GnuCashImporter

        session, book, path = _make_biz_book()
        try:
            d = _build_customer_directive(
                'CUST-020', 'Delta Corp',
                extra_meta={
                    'addr1': '123 Main St',
                    'email': 'test@example.com',
                    'jw.country': 'CA',
                },
            )
            GnuCashImporter.import_customer(d, book)
            session.save()
            session.end()

            session2 = _open_session(path)
            book2 = session2.book
            customers = _lookup_customers(book2)
            assert len(customers) == 1
            custom = get_custom_metadata(customers[0])
            assert 'name' not in custom
            assert 'addr1' not in custom
            assert 'email' not in custom
            # Only the truly custom key should be present
            assert custom.get('jw.country') == 'CA'
            session2.end()
        finally:
            _cleanup(path)

    def test_colon_key_raises(self):
        """C-KVP-06: a key with ':' in directive.metadata raises ValueError."""
        from infrastructure.gnucash.kvp import set_custom_metadata
        from services.gnucash_importer import GnuCashImporter

        session, book, path = _make_biz_book()
        try:
            # We test set_custom_metadata directly — import_customer only calls it
            # for keys not in KNOWN_CUSTOMER_METADATA_KEYS, but 'jw:country' is not
            # a known key so it would be passed through.
            d = _build_customer_directive('CUST-030', 'Epsilon Corp')
            GnuCashImporter.import_customer(d, book)
            customers = _lookup_customers(book)
            assert len(customers) == 1

            with pytest.raises(ValueError, match="must not contain ':'"):
                set_custom_metadata(customers[0], {'jw:country': 'CA'})

            session.end()
        finally:
            _cleanup(path)


# ---------------------------------------------------------------------------
# TestVendorKvp
# ---------------------------------------------------------------------------

class TestVendorKvp:
    def test_import_stores_custom_keys(self):
        """V-KVP-01: import_vendor with custom keys stores them as KVP."""
        from infrastructure.gnucash.kvp import get_custom_metadata
        from services.gnucash_importer import GnuCashImporter

        session, book, path = _make_biz_book()
        try:
            d = _build_vendor_directive(
                'VEND-001', 'Office Supplies Inc',
                extra_meta={'jw.country': 'CA', 'jw.vendor_type': 'supplies'},
            )
            GnuCashImporter.import_vendor(d, book)
            session.save()
            session.end()

            session2 = _open_session(path)
            book2 = session2.book
            vendors = _lookup_vendors(book2)
            assert len(vendors) == 1
            custom = get_custom_metadata(vendors[0])
            assert custom.get('jw.country') == 'CA'
            assert custom.get('jw.vendor_type') == 'supplies'
            session2.end()
        finally:
            _cleanup(path)

    def test_export_emits_custom_keys(self):
        """V-KVP-02: custom KVP on vendor appears in export output."""
        from infrastructure.gnucash.kvp import set_custom_metadata
        from services.gnucash_importer import GnuCashImporter
        from use_cases.export_business_objects import ExportBusinessObjectsUseCase

        session, book, path = _make_biz_book()
        try:
            d = _build_vendor_directive('VEND-002', 'Tech Parts Ltd')
            GnuCashImporter.import_vendor(d, book)
            vendors = _lookup_vendors(book)
            assert len(vendors) == 1
            set_custom_metadata(vendors[0], {'jw.rating': 'preferred', 'erp.code': 'V-007'})

            session.save()
            session.end()

            session2 = _open_session(path)
            book2 = session2.book
            use_case = ExportBusinessObjectsUseCase(book2)
            output = use_case.execute()
            session2.end()

            assert 'jw.rating: "preferred"' in output
            assert 'erp.code: "V-007"' in output
        finally:
            _cleanup(path)

    def test_roundtrip(self):
        """V-KVP-03: import → save → export → custom keys present in output."""
        from services.gnucash_importer import GnuCashImporter
        from use_cases.export_business_objects import ExportBusinessObjectsUseCase

        session, book, path = _make_biz_book()
        try:
            d = _build_vendor_directive(
                'VEND-003', 'Cloud Services Co',
                extra_meta={'jw.country': 'US', 'jw.payment_terms': 'net30'},
            )
            GnuCashImporter.import_vendor(d, book)
            session.save()
            session.end()

            session2 = _open_session(path)
            book2 = session2.book
            use_case = ExportBusinessObjectsUseCase(book2)
            output = use_case.execute()
            session2.end()

            assert 'jw.country: "US"' in output
            assert 'jw.payment_terms: "net30"' in output
        finally:
            _cleanup(path)


# ---------------------------------------------------------------------------
# TestInvoiceKvp
# ---------------------------------------------------------------------------

class TestInvoiceKvp:
    def test_import_stores_custom_keys(self):
        """I-KVP-01: import_invoice with jw.po_ref stores it as KVP."""
        from infrastructure.gnucash.kvp import get_custom_metadata
        from services.gnucash_importer import GnuCashImporter

        session, book, path = _make_biz_book()
        try:
            # Create customer first
            cust_d = _build_customer_directive('CUST-INV-001', 'Invoice Customer')
            GnuCashImporter.import_customer(cust_d, book)

            inv_d = _build_invoice_directive(
                'INV-KVP-001', 'CUST-INV-001',
                extra_meta={'jw.po_ref': 'PO-2024-001', 'jw.project': 'Alpha'},
            )
            GnuCashImporter.import_invoice(inv_d, book)
            session.save()
            session.end()

            session2 = _open_session(path)
            book2 = session2.book
            invoices = _lookup_invoices(book2)
            # Filter to customer invoices only (not bills)
            cust_invoices = []
            for inv in invoices:
                try:
                    cust = inv.GetOwner().GetCustomer()
                    if cust is not None:
                        cust_invoices.append(inv)
                except Exception:
                    pass
            assert len(cust_invoices) == 1
            custom = get_custom_metadata(cust_invoices[0])
            assert custom.get('jw.po_ref') == 'PO-2024-001'
            assert custom.get('jw.project') == 'Alpha'
            session2.end()
        finally:
            _cleanup(path)

    def test_export_emits_custom_keys(self):
        """I-KVP-02: custom KVP on invoice appears in export output."""
        from infrastructure.gnucash.kvp import set_custom_metadata
        from services.gnucash_importer import GnuCashImporter
        from use_cases.export_business_objects import ExportBusinessObjectsUseCase

        session, book, path = _make_biz_book()
        try:
            cust_d = _build_customer_directive('CUST-INV-002', 'Export Invoice Customer')
            GnuCashImporter.import_customer(cust_d, book)

            inv_d = _build_invoice_directive('INV-KVP-002', 'CUST-INV-002')
            GnuCashImporter.import_invoice(inv_d, book)

            invoices = _lookup_invoices(book)
            cust_invoices = []
            for inv in invoices:
                try:
                    cust = inv.GetOwner().GetCustomer()
                    if cust is not None:
                        cust_invoices.append(inv)
                except Exception:
                    pass
            assert len(cust_invoices) == 1
            set_custom_metadata(cust_invoices[0], {'jw.po_ref': 'PO-EXPORT-001'})

            session.save()
            session.end()

            session2 = _open_session(path)
            book2 = session2.book
            use_case = ExportBusinessObjectsUseCase(book2)
            output = use_case.execute()
            session2.end()

            assert 'jw.po_ref: "PO-EXPORT-001"' in output
        finally:
            _cleanup(path)

    def test_roundtrip(self):
        """I-KVP-03: import → save → export → custom keys present in output."""
        from services.gnucash_importer import GnuCashImporter
        from use_cases.export_business_objects import ExportBusinessObjectsUseCase

        session, book, path = _make_biz_book()
        try:
            cust_d = _build_customer_directive('CUST-INV-003', 'Roundtrip Invoice Customer')
            GnuCashImporter.import_customer(cust_d, book)

            inv_d = _build_invoice_directive(
                'INV-KVP-003', 'CUST-INV-003',
                extra_meta={'jw.po_ref': 'PO-2024-RT', 'jw.department': 'engineering'},
            )
            GnuCashImporter.import_invoice(inv_d, book)
            session.save()
            session.end()

            session2 = _open_session(path)
            book2 = session2.book
            use_case = ExportBusinessObjectsUseCase(book2)
            output = use_case.execute()
            session2.end()

            assert 'jw.po_ref: "PO-2024-RT"' in output
            assert 'jw.department: "engineering"' in output
        finally:
            _cleanup(path)


# ---------------------------------------------------------------------------
# TestBillKvp
# ---------------------------------------------------------------------------

class TestBillKvp:
    def test_import_stores_custom_keys(self):
        """B-KVP-01: import_bill with custom keys stores them as KVP."""
        from infrastructure.gnucash.kvp import get_custom_metadata
        from services.gnucash_importer import GnuCashImporter

        session, book, path = _make_biz_book()
        try:
            vend_d = _build_vendor_directive('VEND-BILL-001', 'Bill Vendor')
            GnuCashImporter.import_vendor(vend_d, book)

            bill_d = _build_bill_directive(
                'BILL-KVP-001', 'VEND-BILL-001',
                extra_meta={'jw.po_ref': 'PO-BILL-001', 'jw.approver': 'Alice'},
            )
            GnuCashImporter.import_bill(bill_d, book)
            session.save()
            session.end()

            session2 = _open_session(path)
            book2 = session2.book
            invoices = _lookup_invoices(book2)
            bills = []
            for inv in invoices:
                try:
                    vendor = inv.GetOwner().GetVendor()
                    if vendor is not None:
                        bills.append(inv)
                except Exception:
                    pass
            assert len(bills) == 1
            custom = get_custom_metadata(bills[0])
            assert custom.get('jw.po_ref') == 'PO-BILL-001'
            assert custom.get('jw.approver') == 'Alice'
            session2.end()
        finally:
            _cleanup(path)

    def test_export_emits_custom_keys(self):
        """B-KVP-02: custom KVP on bill appears in export output."""
        from infrastructure.gnucash.kvp import set_custom_metadata
        from services.gnucash_importer import GnuCashImporter
        from use_cases.export_business_objects import ExportBusinessObjectsUseCase

        session, book, path = _make_biz_book()
        try:
            vend_d = _build_vendor_directive('VEND-BILL-002', 'Export Bill Vendor')
            GnuCashImporter.import_vendor(vend_d, book)

            bill_d = _build_bill_directive('BILL-KVP-002', 'VEND-BILL-002')
            GnuCashImporter.import_bill(bill_d, book)

            invoices = _lookup_invoices(book)
            bills = []
            for inv in invoices:
                try:
                    vendor = inv.GetOwner().GetVendor()
                    if vendor is not None:
                        bills.append(inv)
                except Exception:
                    pass
            assert len(bills) == 1
            set_custom_metadata(bills[0], {'jw.cost_centre': 'DEPT-42'})

            session.save()
            session.end()

            session2 = _open_session(path)
            book2 = session2.book
            use_case = ExportBusinessObjectsUseCase(book2)
            output = use_case.execute()
            session2.end()

            assert 'jw.cost_centre: "DEPT-42"' in output
        finally:
            _cleanup(path)

    def test_roundtrip(self):
        """B-KVP-03: import → save → export → custom keys present in output."""
        from services.gnucash_importer import GnuCashImporter
        from use_cases.export_business_objects import ExportBusinessObjectsUseCase

        session, book, path = _make_biz_book()
        try:
            vend_d = _build_vendor_directive('VEND-BILL-003', 'Roundtrip Bill Vendor')
            GnuCashImporter.import_vendor(vend_d, book)

            bill_d = _build_bill_directive(
                'BILL-KVP-003', 'VEND-BILL-003',
                extra_meta={'jw.po_ref': 'PO-BILL-RT', 'jw.category': 'office'},
            )
            GnuCashImporter.import_bill(bill_d, book)
            session.save()
            session.end()

            session2 = _open_session(path)
            book2 = session2.book
            use_case = ExportBusinessObjectsUseCase(book2)
            output = use_case.execute()
            session2.end()

            assert 'jw.po_ref: "PO-BILL-RT"' in output
            assert 'jw.category: "office"' in output
        finally:
            _cleanup(path)


# ---------------------------------------------------------------------------
# TestAccountKvp
# ---------------------------------------------------------------------------

class TestAccountKvp:
    def test_import_stores_custom_keys(self):
        """A-KVP-01: create_account with erp.cost_centre stores it as KVP."""
        from infrastructure.gnucash.kvp import get_custom_metadata
        from services.gnucash_importer import GnuCashImporter

        session, book, path = _make_biz_book()
        try:
            # The book already has an 'Expenses' root parent; add a child
            d = _build_account_directive(
                'Expenses:Operations',
                'Expense',
                extra_meta={'erp.cost_centre': 'DEPT-42', 'erp.gl_code': 'GL-500'},
            )
            GnuCashImporter.create_account(d, book)
            session.save()
            session.end()

            session2 = _open_session(path)
            book2 = session2.book
            root = book2.get_root_account()
            acct = root.lookup_by_name('Expenses').lookup_by_name('Operations')
            assert acct is not None, "Account 'Expenses:Operations' not found"
            custom = get_custom_metadata(acct)
            assert custom.get('erp.cost_centre') == 'DEPT-42'
            assert custom.get('erp.gl_code') == 'GL-500'
            session2.end()
        finally:
            _cleanup(path)

    def test_export_emits_custom_keys(self):
        """A-KVP-02: custom KVP on account appears in export output (tab-indented)."""
        from infrastructure.gnucash.kvp import set_custom_metadata
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        session, book, path = _make_biz_book()
        try:
            root = book.get_root_account()
            acct = root.lookup_by_name('Expenses').lookup_by_name('Purchases')
            assert acct is not None
            set_custom_metadata(acct, {'erp.cost_centre': 'DEPT-42'})

            session.save()
            session.end()

            repo = GnuCashRepository(path)
            repo.open()
            try:
                use_case = ExportTransactionsUseCase(repo)
                # Use all_accounts=True so accounts are exported even when there
                # are no transactions referencing them (book has no transactions).
                result = use_case.execute(all_accounts=True)
                output = use_case.format_as_plaintext(result)
            finally:
                repo.close()

            # The key should appear inside an 'open' block (tab-indented)
            assert 'erp.cost_centre: "DEPT-42"' in output
        finally:
            _cleanup(path)

    def test_roundtrip(self):
        """A-KVP-03: create_account with custom KVP → save → export → key in output."""
        from repositories.gnucash_repository import GnuCashRepository
        from services.gnucash_importer import GnuCashImporter
        from use_cases.export_transactions import ExportTransactionsUseCase

        session, book, path = _make_biz_book()
        try:
            d = _build_account_directive(
                'Expenses:Consulting',
                'Expense',
                extra_meta={'erp.cost_centre': 'DEPT-99', 'erp.project': 'consulting'},
            )
            GnuCashImporter.create_account(d, book)
            session.save()
            session.end()

            repo = GnuCashRepository(path)
            repo.open()
            try:
                use_case = ExportTransactionsUseCase(repo)
                # Use all_accounts=True so accounts are exported even when there
                # are no transactions referencing them (book has no transactions).
                result = use_case.execute(all_accounts=True)
                output = use_case.format_as_plaintext(result)
            finally:
                repo.close()

            assert 'erp.cost_centre: "DEPT-99"' in output
            assert 'erp.project: "consulting"' in output
        finally:
            _cleanup(path)

    def test_known_keys_not_stored_as_kvp(self):
        """A-KVP-04: guid, type, notes etc. must NOT appear in custom KVP."""
        from infrastructure.gnucash.kvp import get_custom_metadata
        from services.gnucash_importer import GnuCashImporter

        session, book, path = _make_biz_book()
        try:
            d = _build_account_directive(
                'Expenses:Research',
                'Expense',
                extra_meta={
                    'description': 'R&D expenses',
                    'notes': 'Research budget',
                    'code': 'EXP-R',
                    'erp.cost_centre': 'DEPT-RD',
                },
            )
            GnuCashImporter.create_account(d, book)
            session.save()
            session.end()

            session2 = _open_session(path)
            book2 = session2.book
            root = book2.get_root_account()
            acct = root.lookup_by_name('Expenses').lookup_by_name('Research')
            assert acct is not None
            custom = get_custom_metadata(acct)
            # Known keys must NOT be in custom KVP
            for known_key in ('guid', 'type', 'placeholder', 'code', 'description',
                              'notes', 'tax_related', 'commodity.namespace',
                              'commodity.mnemonic', 'commodity_scu', 'color'):
                assert known_key not in custom, (
                    f"Known key '{known_key}' should not be stored as custom KVP"
                )
            # Custom key must be present
            assert custom.get('erp.cost_centre') == 'DEPT-RD'
            session2.end()
        finally:
            _cleanup(path)
