"""
Unit tests for KVP metadata storage on GnuCash transactions and splits.

Covers:
- set_custom_metadata / get_custom_metadata roundtrip on a transaction
- Custom metadata imported via create_transaction and read back
- Custom metadata exported via format_as_plaintext appears in output
- Full roundtrip: import plaintext with custom tags → export → custom tags in output
- update_transaction merges custom metadata (new keys added, existing keys updated)
- Split-level custom metadata roundtrip
- Known keys (notes, guid, etc.) are NOT stored as custom KVP
- Empty/missing custom metadata returns {}

Tests use real GnuCash sessions (no mocks). Run in Docker.
"""

import os
import tempfile

import pytest

# ---------------------------------------------------------------------------
# Helpers
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


def _make_book():
    """
    Create a minimal GnuCash book with CAD accounts for testing.

    Returns (session, book, path). Caller must call session.end() and
    clean up path after use.
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
    bank = _acct('Bank', gnucash.ACCT_TYPE_BANK, assets)
    _acct('Checking', gnucash.ACCT_TYPE_BANK, bank)
    expenses = _acct('Expenses', gnucash.ACCT_TYPE_EXPENSE, root)
    _acct('Dining', gnucash.ACCT_TYPE_EXPENSE, expenses)

    return session, book, path


def _build_directive(date_str, tx_desc, splits, metadata=None):
    """
    Build a minimal PlaintextDirective for a TRANSACTION.

    *splits* is a list of dicts: {'account': str, 'amount': str, ...optional metadata...}
    """
    from services.plaintext_parser import DirectiveType, PlaintextDirective

    tx_dir = PlaintextDirective(DirectiveType.TRANSACTION, level=0, line='')
    tx_dir.props = {'date': date_str, 'tx_num': None, 'tx_desc': tx_desc}
    tx_dir.metadata = metadata or {}

    for s in splits:
        split_dir = PlaintextDirective(DirectiveType.SPLIT, level=1, line='')
        split_dir.props = {'account': s['account'], 'amount': s['amount']}
        split_dir.metadata = {k: v for k, v in s.items() if k not in ('account', 'amount')}
        tx_dir.children.append(split_dir)

    return tx_dir


# ---------------------------------------------------------------------------
# Tests: set_custom_metadata / get_custom_metadata low-level roundtrip
# ---------------------------------------------------------------------------

class TestKvpRoundtrip:
    def test_set_and_get_custom_metadata_on_transaction(self):
        """set_custom_metadata followed by get_custom_metadata returns original dict."""
        from gnucash import GncNumeric, Split, Transaction

        from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata

        session, book, path = _make_book()
        try:
            cad = book.get_table().lookup('CURRENCY', 'CAD')
            root = book.get_root_account()

            checking = root.lookup_by_name('Assets').lookup_by_name('Bank').lookup_by_name('Checking')
            dining = root.lookup_by_name('Expenses').lookup_by_name('Dining')

            tx = Transaction(book)
            tx.BeginEdit()
            tx.SetCurrency(cad)
            tx.SetDate(1, 1, 2024)
            tx.SetDescription('Test tx')

            s1 = Split(book)
            s1.SetParent(tx)
            s1.SetAccount(dining)
            s1.SetValue(GncNumeric(2000, 100))

            s2 = Split(book)
            s2.SetParent(tx)
            s2.SetAccount(checking)
            s2.SetValue(GncNumeric(-2000, 100))

            metadata = {'receipt': 'R-001', 'category': 'food', 'amount_usd': '14.50'}
            set_custom_metadata(tx, metadata)

            tx.CommitEdit()
            session.save()
            session.end()

            # Re-open and read back
            session2 = _open_session(path)
            book2 = session2.book
            from gnucash import Query
            q = Query()
            q.search_for('Trans')
            q.set_book(book2)
            txs = [Transaction(instance=t) for t in q.run()]
            assert len(txs) == 1

            result = get_custom_metadata(txs[0])
            assert result == metadata
            session2.end()

        finally:
            if os.path.exists(path):
                os.unlink(path)
            lock = path + '.LCK'
            if os.path.exists(lock):
                os.unlink(lock)

    def test_get_custom_metadata_returns_empty_when_no_slot(self):
        """get_custom_metadata returns {} when no KVP slot has been set."""
        from gnucash import GncNumeric, Split, Transaction

        from infrastructure.gnucash.kvp import get_custom_metadata

        session, book, path = _make_book()
        try:
            cad = book.get_table().lookup('CURRENCY', 'CAD')
            root = book.get_root_account()
            checking = root.lookup_by_name('Assets').lookup_by_name('Bank').lookup_by_name('Checking')
            dining = root.lookup_by_name('Expenses').lookup_by_name('Dining')

            tx = Transaction(book)
            tx.BeginEdit()
            tx.SetCurrency(cad)
            tx.SetDate(2, 1, 2024)
            tx.SetDescription('No metadata tx')

            s1 = Split(book)
            s1.SetParent(tx)
            s1.SetAccount(dining)
            s1.SetValue(GncNumeric(1000, 100))

            s2 = Split(book)
            s2.SetParent(tx)
            s2.SetAccount(checking)
            s2.SetValue(GncNumeric(-1000, 100))

            tx.CommitEdit()

            result = get_custom_metadata(tx)
            assert result == {}

            session.end()

        finally:
            if os.path.exists(path):
                os.unlink(path)
            lock = path + '.LCK'
            if os.path.exists(lock):
                os.unlink(lock)

    def test_set_custom_metadata_noop_for_empty_dict(self):
        """set_custom_metadata with empty dict does not raise and leaves slot empty."""
        from gnucash import GncNumeric, Split, Transaction

        from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata

        session, book, path = _make_book()
        try:
            cad = book.get_table().lookup('CURRENCY', 'CAD')
            root = book.get_root_account()
            checking = root.lookup_by_name('Assets').lookup_by_name('Bank').lookup_by_name('Checking')
            dining = root.lookup_by_name('Expenses').lookup_by_name('Dining')

            tx = Transaction(book)
            tx.BeginEdit()
            tx.SetCurrency(cad)
            tx.SetDate(3, 1, 2024)
            tx.SetDescription('Empty meta tx')

            s1 = Split(book)
            s1.SetParent(tx)
            s1.SetAccount(dining)
            s1.SetValue(GncNumeric(500, 100))

            s2 = Split(book)
            s2.SetParent(tx)
            s2.SetAccount(checking)
            s2.SetValue(GncNumeric(-500, 100))

            set_custom_metadata(tx, {})
            tx.CommitEdit()

            assert get_custom_metadata(tx) == {}
            session.end()

        finally:
            if os.path.exists(path):
                os.unlink(path)
            lock = path + '.LCK'
            if os.path.exists(lock):
                os.unlink(lock)

    def test_split_level_custom_metadata_roundtrip(self):
        """set_custom_metadata / get_custom_metadata roundtrip works on a Split."""
        from gnucash import GncNumeric, Split, Transaction

        from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata

        session, book, path = _make_book()
        try:
            cad = book.get_table().lookup('CURRENCY', 'CAD')
            root = book.get_root_account()
            checking = root.lookup_by_name('Assets').lookup_by_name('Bank').lookup_by_name('Checking')
            dining = root.lookup_by_name('Expenses').lookup_by_name('Dining')

            tx = Transaction(book)
            tx.BeginEdit()
            tx.SetCurrency(cad)
            tx.SetDate(4, 1, 2024)
            tx.SetDescription('Split meta tx')

            s1 = Split(book)
            s1.SetParent(tx)
            s1.SetAccount(dining)
            s1.SetValue(GncNumeric(3000, 100))
            set_custom_metadata(s1, {'vendor': 'Acme', 'ref': '42'})

            s2 = Split(book)
            s2.SetParent(tx)
            s2.SetAccount(checking)
            s2.SetValue(GncNumeric(-3000, 100))

            tx.CommitEdit()
            session.save()
            session.end()

            session2 = _open_session(path)
            book2 = session2.book
            from gnucash import Query
            q = Query()
            q.search_for('Trans')
            q.set_book(book2)
            txs = [Transaction(instance=t) for t in q.run()]
            assert len(txs) == 1

            splits = txs[0].GetSplitList()
            dining_split = next(
                s for s in splits if s.GetAccount().GetName() == 'Dining'
            )
            result = get_custom_metadata(dining_split)
            assert result == {'vendor': 'Acme', 'ref': '42'}
            session2.end()

        finally:
            if os.path.exists(path):
                os.unlink(path)
            lock = path + '.LCK'
            if os.path.exists(lock):
                os.unlink(lock)


# ---------------------------------------------------------------------------
# Tests: create_transaction stores custom metadata via importer
# ---------------------------------------------------------------------------

class TestCreateTransactionKvpMetadata:
    def test_custom_tx_metadata_stored_on_import(self):
        """create_transaction stores non-standard metadata keys as KVP."""
        from gnucash import Query, Transaction

        from infrastructure.gnucash.kvp import get_custom_metadata
        from services.gnucash_importer import GnuCashImporter

        session, book, path = _make_book()
        try:
            directive = _build_directive('2024-01-10', 'Lunch', [
                {'account': 'Expenses:Dining', 'amount': '25.00'},
                {'account': 'Assets:Bank:Checking', 'amount': '-25.00'},
            ], metadata={'receipt': 'R-999', 'notes': 'business lunch'})

            GnuCashImporter.create_transaction(directive, book)
            session.save()
            session.end()

            session2 = _open_session(path)
            book2 = session2.book
            q = Query()
            q.search_for('Trans')
            q.set_book(book2)
            txs = [Transaction(instance=t) for t in q.run()]
            assert len(txs) == 1

            custom = get_custom_metadata(txs[0])
            # 'receipt' is custom (not in KNOWN_TX_METADATA_KEYS) → must be stored
            assert custom.get('receipt') == 'R-999'
            # 'notes' is a known key → must NOT be stored as custom KVP
            assert 'notes' in txs[0].GetNotes() or txs[0].GetNotes() == 'business lunch'
            assert 'notes' not in custom
            session2.end()

        finally:
            if os.path.exists(path):
                os.unlink(path)
            lock = path + '.LCK'
            if os.path.exists(lock):
                os.unlink(lock)

    def test_known_tx_keys_not_stored_as_custom_kvp(self):
        """create_transaction does not store guid/notes/doc_link as custom KVP."""
        from gnucash import Query, Transaction

        from infrastructure.gnucash.kvp import get_custom_metadata
        from services.gnucash_importer import GnuCashImporter

        session, book, path = _make_book()
        try:
            directive = _build_directive('2024-01-11', 'Office dinner', [
                {'account': 'Expenses:Dining', 'amount': '80.00'},
                {'account': 'Assets:Bank:Checking', 'amount': '-80.00'},
            ], metadata={
                'guid': 'abcdef1234567890abcdef1234567890',
                'notes': 'team event',
                'doc_link': 'https://example.com/receipt.pdf',
            })

            GnuCashImporter.create_transaction(directive, book)
            session.save()
            session.end()

            session2 = _open_session(path)
            book2 = session2.book
            q = Query()
            q.search_for('Trans')
            q.set_book(book2)
            txs = [Transaction(instance=t) for t in q.run()]
            assert len(txs) == 1

            custom = get_custom_metadata(txs[0])
            for known_key in ('guid', 'notes', 'doc_link'):
                assert known_key not in custom, f"'{known_key}' should not be in custom KVP"
            session2.end()

        finally:
            if os.path.exists(path):
                os.unlink(path)
            lock = path + '.LCK'
            if os.path.exists(lock):
                os.unlink(lock)

    def test_custom_split_metadata_stored_on_import(self):
        """create_transaction stores non-standard split metadata keys as KVP."""
        from gnucash import Query, Transaction

        from infrastructure.gnucash.kvp import get_custom_metadata
        from services.gnucash_importer import GnuCashImporter

        session, book, path = _make_book()
        try:
            directive = _build_directive('2024-01-12', 'Split meta test', [
                {'account': 'Expenses:Dining', 'amount': '40.00',
                 'vendor': 'Pizza Palace', 'memo': 'team lunch'},
                {'account': 'Assets:Bank:Checking', 'amount': '-40.00'},
            ])

            GnuCashImporter.create_transaction(directive, book)
            session.save()
            session.end()

            session2 = _open_session(path)
            book2 = session2.book
            q = Query()
            q.search_for('Trans')
            q.set_book(book2)
            txs = [Transaction(instance=t) for t in q.run()]
            assert len(txs) == 1

            splits = txs[0].GetSplitList()
            dining_split = next(
                s for s in splits if s.GetAccount().GetName() == 'Dining'
            )
            custom = get_custom_metadata(dining_split)
            assert custom.get('vendor') == 'Pizza Palace'
            # 'memo' is a known split key → must NOT be stored as custom KVP
            assert 'memo' not in custom
            session2.end()

        finally:
            if os.path.exists(path):
                os.unlink(path)
            lock = path + '.LCK'
            if os.path.exists(lock):
                os.unlink(lock)

    def test_no_custom_metadata_when_all_keys_are_known(self):
        """create_transaction stores no KVP when all keys are standard."""
        from gnucash import Query, Transaction

        from infrastructure.gnucash.kvp import get_custom_metadata
        from services.gnucash_importer import GnuCashImporter

        session, book, path = _make_book()
        try:
            directive = _build_directive('2024-01-13', 'Standard tx', [
                {'account': 'Expenses:Dining', 'amount': '10.00', 'memo': 'lunch'},
                {'account': 'Assets:Bank:Checking', 'amount': '-10.00'},
            ], metadata={'notes': 'just a note'})

            GnuCashImporter.create_transaction(directive, book)
            session.save()
            session.end()

            session2 = _open_session(path)
            book2 = session2.book
            q = Query()
            q.search_for('Trans')
            q.set_book(book2)
            txs = [Transaction(instance=t) for t in q.run()]
            assert len(txs) == 1

            assert get_custom_metadata(txs[0]) == {}
            session2.end()

        finally:
            if os.path.exists(path):
                os.unlink(path)
            lock = path + '.LCK'
            if os.path.exists(lock):
                os.unlink(lock)


# ---------------------------------------------------------------------------
# Tests: export emits custom metadata lines
# ---------------------------------------------------------------------------

class TestExportEmitsCustomMetadata:
    def test_custom_tx_metadata_appears_in_plaintext_output(self):
        """format_as_plaintext emits custom KVP metadata lines after notes."""
        from gnucash import GncNumeric, Query, Split, Transaction

        from infrastructure.gnucash.kvp import set_custom_metadata
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        session, book, path = _make_book()
        try:
            cad = book.get_table().lookup('CURRENCY', 'CAD')
            root = book.get_root_account()
            checking = root.lookup_by_name('Assets').lookup_by_name('Bank').lookup_by_name('Checking')
            dining = root.lookup_by_name('Expenses').lookup_by_name('Dining')

            tx = Transaction(book)
            tx.BeginEdit()
            tx.SetCurrency(cad)
            tx.SetDate(5, 1, 2024)
            tx.SetDescription('Export test')

            s1 = Split(book)
            s1.SetParent(tx)
            s1.SetAccount(dining)
            s1.SetValue(GncNumeric(1500, 100))

            s2 = Split(book)
            s2.SetParent(tx)
            s2.SetAccount(checking)
            s2.SetValue(GncNumeric(-1500, 100))

            set_custom_metadata(tx, {'invoice_no': 'INV-001', 'project': 'alpha'})
            tx.CommitEdit()
            session.save()
            session.end()

            repo = GnuCashRepository(path)
            repo.open()
            try:
                use_case = ExportTransactionsUseCase(repo)
                result = use_case.execute()
                output = use_case.format_as_plaintext(result)
            finally:
                repo.close()

            assert 'invoice_no: "INV-001"' in output
            assert 'project: "alpha"' in output

        finally:
            if os.path.exists(path):
                os.unlink(path)
            lock = path + '.LCK'
            if os.path.exists(lock):
                os.unlink(lock)

    def test_custom_split_metadata_appears_in_plaintext_output(self):
        """format_as_plaintext emits custom split KVP metadata lines after memo."""
        from gnucash import GncNumeric, Query, Split, Transaction

        from infrastructure.gnucash.kvp import set_custom_metadata
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        session, book, path = _make_book()
        try:
            cad = book.get_table().lookup('CURRENCY', 'CAD')
            root = book.get_root_account()
            checking = root.lookup_by_name('Assets').lookup_by_name('Bank').lookup_by_name('Checking')
            dining = root.lookup_by_name('Expenses').lookup_by_name('Dining')

            tx = Transaction(book)
            tx.BeginEdit()
            tx.SetCurrency(cad)
            tx.SetDate(6, 1, 2024)
            tx.SetDescription('Split export test')

            s1 = Split(book)
            s1.SetParent(tx)
            s1.SetAccount(dining)
            s1.SetValue(GncNumeric(2000, 100))
            set_custom_metadata(s1, {'cost_center': 'marketing', 'approved_by': 'Alice'})

            s2 = Split(book)
            s2.SetParent(tx)
            s2.SetAccount(checking)
            s2.SetValue(GncNumeric(-2000, 100))

            tx.CommitEdit()
            session.save()
            session.end()

            repo = GnuCashRepository(path)
            repo.open()
            try:
                use_case = ExportTransactionsUseCase(repo)
                result = use_case.execute()
                output = use_case.format_as_plaintext(result)
            finally:
                repo.close()

            assert 'approved_by: "Alice"' in output
            assert 'cost_center: "marketing"' in output

        finally:
            if os.path.exists(path):
                os.unlink(path)
            lock = path + '.LCK'
            if os.path.exists(lock):
                os.unlink(lock)

    def test_no_custom_metadata_lines_when_none_stored(self):
        """format_as_plaintext does not add custom metadata lines when none stored."""
        from gnucash import GncNumeric, Split, Transaction

        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        session, book, path = _make_book()
        try:
            cad = book.get_table().lookup('CURRENCY', 'CAD')
            root = book.get_root_account()
            checking = root.lookup_by_name('Assets').lookup_by_name('Bank').lookup_by_name('Checking')
            dining = root.lookup_by_name('Expenses').lookup_by_name('Dining')

            tx = Transaction(book)
            tx.BeginEdit()
            tx.SetCurrency(cad)
            tx.SetDate(7, 1, 2024)
            tx.SetDescription('No custom meta')

            s1 = Split(book)
            s1.SetParent(tx)
            s1.SetAccount(dining)
            s1.SetValue(GncNumeric(500, 100))

            s2 = Split(book)
            s2.SetParent(tx)
            s2.SetAccount(checking)
            s2.SetValue(GncNumeric(-500, 100))

            tx.CommitEdit()
            session.save()
            session.end()

            repo = GnuCashRepository(path)
            repo.open()
            try:
                use_case = ExportTransactionsUseCase(repo)
                result = use_case.execute()
                output = use_case.format_as_plaintext(result)
            finally:
                repo.close()

            # pt/__data slot should not appear in output at all
            assert 'pt/__data' not in output

        finally:
            if os.path.exists(path):
                os.unlink(path)
            lock = path + '.LCK'
            if os.path.exists(lock):
                os.unlink(lock)


# ---------------------------------------------------------------------------
# Tests: full roundtrip — import plaintext with custom tags → export → tags present
# ---------------------------------------------------------------------------

class TestFullRoundtrip:
    def test_import_then_export_preserves_custom_tx_metadata(self):
        """Custom metadata imported via create_transaction survives export roundtrip."""
        from gnucash import Query, Transaction

        from infrastructure.gnucash.kvp import get_custom_metadata
        from repositories.gnucash_repository import GnuCashRepository
        from services.gnucash_importer import GnuCashImporter
        from use_cases.export_transactions import ExportTransactionsUseCase

        session, book, path = _make_book()
        try:
            directive = _build_directive('2024-02-01', 'Roundtrip tx', [
                {'account': 'Expenses:Dining', 'amount': '60.00'},
                {'account': 'Assets:Bank:Checking', 'amount': '-60.00'},
            ], metadata={'tax_category': 'meals_entertainment', 'fiscal_year': '2024'})

            GnuCashImporter.create_transaction(directive, book)
            session.save()
            session.end()

            repo = GnuCashRepository(path)
            repo.open()
            try:
                use_case = ExportTransactionsUseCase(repo)
                result = use_case.execute()
                output = use_case.format_as_plaintext(result)
            finally:
                repo.close()

            assert 'tax_category: "meals_entertainment"' in output
            assert 'fiscal_year: "2024"' in output

        finally:
            if os.path.exists(path):
                os.unlink(path)
            lock = path + '.LCK'
            if os.path.exists(lock):
                os.unlink(lock)

    def test_import_then_export_preserves_custom_split_metadata(self):
        """Custom split metadata imported via create_transaction survives export roundtrip."""
        from repositories.gnucash_repository import GnuCashRepository
        from services.gnucash_importer import GnuCashImporter
        from use_cases.export_transactions import ExportTransactionsUseCase

        session, book, path = _make_book()
        try:
            directive = _build_directive('2024-02-02', 'Split roundtrip tx', [
                {'account': 'Expenses:Dining', 'amount': '35.00',
                 'po_number': 'PO-2024-007'},
                {'account': 'Assets:Bank:Checking', 'amount': '-35.00'},
            ])

            GnuCashImporter.create_transaction(directive, book)
            session.save()
            session.end()

            repo = GnuCashRepository(path)
            repo.open()
            try:
                use_case = ExportTransactionsUseCase(repo)
                result = use_case.execute()
                output = use_case.format_as_plaintext(result)
            finally:
                repo.close()

            assert 'po_number: "PO-2024-007"' in output

        finally:
            if os.path.exists(path):
                os.unlink(path)
            lock = path + '.LCK'
            if os.path.exists(lock):
                os.unlink(lock)


# ---------------------------------------------------------------------------
# Tests: update_transaction merges custom metadata
# ---------------------------------------------------------------------------

class TestUpdateTransactionKvpMetadata:
    @pytest.fixture
    def book_with_tx(self):
        """
        Temp GnuCash file with one transaction that already has custom KVP metadata.

        Yields (path, guid_string).
        """
        from gnucash import GncNumeric, Split, Transaction

        from infrastructure.gnucash.kvp import set_custom_metadata

        session, book, path = _make_book()
        try:
            cad = book.get_table().lookup('CURRENCY', 'CAD')
            root = book.get_root_account()
            checking = root.lookup_by_name('Assets').lookup_by_name('Bank').lookup_by_name('Checking')
            dining = root.lookup_by_name('Expenses').lookup_by_name('Dining')

            tx = Transaction(book)
            tx.BeginEdit()
            tx.SetCurrency(cad)
            tx.SetDate(10, 1, 2024)
            tx.SetDescription('Original')

            s1 = Split(book)
            s1.SetParent(tx)
            s1.SetAccount(dining)
            s1.SetValue(GncNumeric(4500, 100))

            s2 = Split(book)
            s2.SetParent(tx)
            s2.SetAccount(checking)
            s2.SetValue(GncNumeric(-4500, 100))

            set_custom_metadata(tx, {'existing_key': 'original_value', 'keep_key': 'keep_me'})
            tx.CommitEdit()
            guid = tx.GetGUID().to_string()

            session.save()
            session.end()

            yield path, guid

        finally:
            if os.path.exists(path):
                os.unlink(path)
            lock = path + '.LCK'
            if os.path.exists(lock):
                os.unlink(lock)

    def test_update_adds_new_custom_metadata_keys(self, book_with_tx):
        """update_transaction adds new custom KVP keys not previously present."""
        from gnucash import Query, Transaction

        from infrastructure.gnucash.kvp import get_custom_metadata
        from services.gnucash_importer import GnuCashImporter

        path, guid = book_with_tx
        session = _open_session(path)
        book = session.book

        q = Query()
        q.search_for('Trans')
        q.set_book(book)
        txs = [Transaction(instance=t) for t in q.run()]
        existing_tx = next(t for t in txs if t.GetGUID().to_string() == guid)

        directive = _build_directive('2024-01-10', 'Original', [
            {'account': 'Expenses:Dining', 'amount': '45.00'},
            {'account': 'Assets:Bank:Checking', 'amount': '-45.00'},
        ], metadata={'new_key': 'new_value'})

        GnuCashImporter.update_transaction(existing_tx, directive, book)
        session.save()
        session.end()

        session2 = _open_session(path)
        book2 = session2.book
        q2 = Query()
        q2.search_for('Trans')
        q2.set_book(book2)
        txs2 = [Transaction(instance=t) for t in q2.run()]
        updated = next(t for t in txs2 if t.GetGUID().to_string() == guid)

        custom = get_custom_metadata(updated)
        assert custom.get('new_key') == 'new_value'
        assert custom.get('keep_key') == 'keep_me'
        session2.end()

    def test_update_overwrites_existing_custom_metadata_keys(self, book_with_tx):
        """update_transaction overwrites custom KVP keys that already exist."""
        from gnucash import Query, Transaction

        from infrastructure.gnucash.kvp import get_custom_metadata
        from services.gnucash_importer import GnuCashImporter

        path, guid = book_with_tx
        session = _open_session(path)
        book = session.book

        q = Query()
        q.search_for('Trans')
        q.set_book(book)
        txs = [Transaction(instance=t) for t in q.run()]
        existing_tx = next(t for t in txs if t.GetGUID().to_string() == guid)

        directive = _build_directive('2024-01-10', 'Original', [
            {'account': 'Expenses:Dining', 'amount': '45.00'},
            {'account': 'Assets:Bank:Checking', 'amount': '-45.00'},
        ], metadata={'existing_key': 'updated_value'})

        GnuCashImporter.update_transaction(existing_tx, directive, book)
        session.save()
        session.end()

        session2 = _open_session(path)
        book2 = session2.book
        q2 = Query()
        q2.search_for('Trans')
        q2.set_book(book2)
        txs2 = [Transaction(instance=t) for t in q2.run()]
        updated = next(t for t in txs2 if t.GetGUID().to_string() == guid)

        custom = get_custom_metadata(updated)
        assert custom.get('existing_key') == 'updated_value'
        # key not mentioned in directive but was in original → preserved
        assert custom.get('keep_key') == 'keep_me'
        session2.end()

    def test_update_split_custom_metadata_merged(self, book_with_tx):
        """update_transaction merges split-level custom KVP metadata."""
        from gnucash import GncNumeric, Query, Split, Transaction

        from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata
        from services.gnucash_importer import GnuCashImporter

        path, guid = book_with_tx
        # First add custom metadata to the split
        session = _open_session(path)
        book = session.book
        q = Query()
        q.search_for('Trans')
        q.set_book(book)
        txs = [Transaction(instance=t) for t in q.run()]
        existing_tx = next(t for t in txs if t.GetGUID().to_string() == guid)

        existing_tx.BeginEdit()
        for split in existing_tx.GetSplitList():
            if split.GetAccount().GetName() == 'Dining':
                set_custom_metadata(split, {'split_key': 'original', 'stable': 'yes'})
        existing_tx.CommitEdit()
        session.save()
        session.end()

        import time

        # Now update with a directive that adds a new split key
        session2 = _open_session(path)
        book2 = session2.book
        q2 = Query()
        q2.search_for('Trans')
        q2.set_book(book2)
        txs2 = [Transaction(instance=t) for t in q2.run()]
        existing_tx2 = next(t for t in txs2 if t.GetGUID().to_string() == guid)

        directive = _build_directive('2024-01-10', 'Original', [
            {'account': 'Expenses:Dining', 'amount': '45.00', 'split_key': 'updated'},
            {'account': 'Assets:Bank:Checking', 'amount': '-45.00'},
        ])

        GnuCashImporter.update_transaction(existing_tx2, directive, book2)
        session2.save()
        session2.end()

        session3 = _open_session(path)
        book3 = session3.book
        q3 = Query()
        q3.search_for('Trans')
        q3.set_book(book3)
        txs3 = [Transaction(instance=t) for t in q3.run()]
        updated = next(t for t in txs3 if t.GetGUID().to_string() == guid)

        dining_split = next(
            s for s in updated.GetSplitList() if s.GetAccount().GetName() == 'Dining'
        )
        custom = get_custom_metadata(dining_split)
        assert custom.get('split_key') == 'updated'
        assert custom.get('stable') == 'yes'
        session3.end()


# ---------------------------------------------------------------------------
# Tests: key validation — colons disallowed in custom metadata keys
# ---------------------------------------------------------------------------

class TestCustomMetadataKeyValidation:
    def test_colon_in_key_raises_value_error(self):
        """set_custom_metadata raises ValueError when a key contains ':'."""
        import pytest

        from infrastructure.gnucash.kvp import set_custom_metadata

        session, book, path = _make_book()
        try:
            from gnucash import GncNumeric, Split, Transaction
            cad = book.get_table().lookup('CURRENCY', 'CAD')
            root = book.get_root_account()
            checking = root.lookup_by_name('Assets').lookup_by_name('Bank').lookup_by_name('Checking')
            dining = root.lookup_by_name('Expenses').lookup_by_name('Dining')

            tx = Transaction(book)
            tx.BeginEdit()
            tx.SetCurrency(cad)
            tx.SetDate(1, 3, 2024)
            tx.SetDescription('Colon key test')
            s1 = Split(book)
            s1.SetParent(tx)
            s1.SetAccount(dining)
            s1.SetValue(GncNumeric(1000, 100))
            s2 = Split(book)
            s2.SetParent(tx)
            s2.SetAccount(checking)
            s2.SetValue(GncNumeric(-1000, 100))

            with pytest.raises(ValueError, match="must not contain ':'"):
                set_custom_metadata(tx, {'a:b': 'value'})

            tx.RollbackEdit()
            session.end()
        finally:
            import os
            if os.path.exists(path):
                os.unlink(path)
            lock = path + '.LCK'
            if os.path.exists(lock):
                os.unlink(lock)

    def test_colon_in_nested_key_raises_value_error(self):
        """Multi-segment colon key like 'a:b:c' also raises ValueError."""
        import pytest

        from infrastructure.gnucash.kvp import set_custom_metadata

        session, book, path = _make_book()
        try:
            from gnucash import GncNumeric, Split, Transaction
            cad = book.get_table().lookup('CURRENCY', 'CAD')
            root = book.get_root_account()
            checking = root.lookup_by_name('Assets').lookup_by_name('Bank').lookup_by_name('Checking')
            dining = root.lookup_by_name('Expenses').lookup_by_name('Dining')

            tx = Transaction(book)
            tx.BeginEdit()
            tx.SetCurrency(cad)
            tx.SetDate(2, 3, 2024)
            tx.SetDescription('Nested colon key test')
            s1 = Split(book)
            s1.SetParent(tx)
            s1.SetAccount(dining)
            s1.SetValue(GncNumeric(500, 100))
            s2 = Split(book)
            s2.SetParent(tx)
            s2.SetAccount(checking)
            s2.SetValue(GncNumeric(-500, 100))

            with pytest.raises(ValueError, match="must not contain ':'"):
                set_custom_metadata(tx, {'a:b:c': 'value'})

            tx.RollbackEdit()
            session.end()
        finally:
            import os
            if os.path.exists(path):
                os.unlink(path)
            lock = path + '.LCK'
            if os.path.exists(lock):
                os.unlink(lock)

    def test_dot_in_key_is_allowed(self):
        """Keys with dots (e.g. 'tax.category') are valid and round-trip correctly."""
        from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata

        session, book, path = _make_book()
        try:
            from gnucash import GncNumeric, Split, Transaction
            cad = book.get_table().lookup('CURRENCY', 'CAD')
            root = book.get_root_account()
            checking = root.lookup_by_name('Assets').lookup_by_name('Bank').lookup_by_name('Checking')
            dining = root.lookup_by_name('Expenses').lookup_by_name('Dining')

            tx = Transaction(book)
            tx.BeginEdit()
            tx.SetCurrency(cad)
            tx.SetDate(3, 3, 2024)
            tx.SetDescription('Dot key test')
            s1 = Split(book)
            s1.SetParent(tx)
            s1.SetAccount(dining)
            s1.SetValue(GncNumeric(2000, 100))
            s2 = Split(book)
            s2.SetParent(tx)
            s2.SetAccount(checking)
            s2.SetValue(GncNumeric(-2000, 100))

            set_custom_metadata(tx, {'tax.category': 'meals', 'receipt.id': 'R-42'})
            tx.CommitEdit()

            result = get_custom_metadata(tx)
            assert result.get('tax.category') == 'meals'
            assert result.get('receipt.id') == 'R-42'
            session.end()
        finally:
            import os
            if os.path.exists(path):
                os.unlink(path)
            lock = path + '.LCK'
            if os.path.exists(lock):
                os.unlink(lock)

    def test_import_with_colon_key_raises(self):
        """create_transaction raises ValueError when a custom key contains ':'."""
        import pytest

        from services.gnucash_importer import GnuCashImporter

        session, book, path = _make_book()
        try:
            directive = _build_directive('2024-03-04', 'Colon key import', [
                {'account': 'Expenses:Dining', 'amount': '10.00'},
                {'account': 'Assets:Bank:Checking', 'amount': '-10.00'},
            ], metadata={'bad:key': 'value'})

            with pytest.raises(ValueError, match="must not contain ':'"):
                GnuCashImporter.create_transaction(directive, book)

            session.end()
        finally:
            import os
            if os.path.exists(path):
                os.unlink(path)
            lock = path + '.LCK'
            if os.path.exists(lock):
                os.unlink(lock)

    def test_update_with_colon_key_raises(self):
        """update_transaction raises ValueError when a custom tx key contains ':'."""
        import os

        import pytest
        from gnucash import Query, Transaction

        from services.gnucash_importer import GnuCashImporter

        session, book, path = _make_book()
        try:
            # Create a transaction first
            directive = _build_directive('2024-03-05', 'Update colon test', [
                {'account': 'Expenses:Dining', 'amount': '20.00'},
                {'account': 'Assets:Bank:Checking', 'amount': '-20.00'},
            ])
            GnuCashImporter.create_transaction(directive, book)
            session.save()
            session.end()

            session2 = _open_session(path)
            book2 = session2.book
            q = Query()
            q.search_for('Trans')
            q.set_book(book2)
            txs = [Transaction(instance=t) for t in q.run()]
            existing_tx = txs[0]

            bad_directive = _build_directive('2024-03-05', 'Update colon test', [
                {'account': 'Expenses:Dining', 'amount': '20.00'},
                {'account': 'Assets:Bank:Checking', 'amount': '-20.00'},
            ], metadata={'bad:key': 'value'})

            with pytest.raises(ValueError, match="must not contain ':'"):
                GnuCashImporter.update_transaction(existing_tx, bad_directive, book2)

            session2.end()
        finally:
            if os.path.exists(path):
                os.unlink(path)
            lock = path + '.LCK'
            if os.path.exists(lock):
                os.unlink(lock)
