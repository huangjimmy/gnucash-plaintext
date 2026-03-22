"""
Integration tests for the delete-transaction-by-guid CLI command.

Verifies:
- Valid GUID: transaction deleted, backup written to stdout or -o file
- Unknown GUID: non-zero exit, clear error message
- Backup plaintext can be re-imported to restore the transaction
"""

import os
import tempfile

import pytest
from click.testing import CliRunner

from cli.main import cli


def _make_gnucash_with_transaction():
    """Return (path, guid) for a GnuCash file containing one CAD transaction."""
    fd, path = tempfile.mkstemp(suffix='.gnucash')
    os.close(fd)
    os.unlink(path)

    import gnucash
    from gnucash import Account, GncNumeric, Session, Split, Transaction

    try:
        from gnucash import SessionOpenMode
        session = Session(f'xml://{path}', SessionOpenMode.SESSION_NEW_STORE)
    except ImportError:
        session = Session(f'xml://{path}', is_new=True)

    book = session.book
    root = book.get_root_account()
    commod_table = book.get_table()
    cad = commod_table.lookup('CURRENCY', 'CAD')

    assets = Account(book)
    assets.SetName('Assets')
    assets.SetType(gnucash.ACCT_TYPE_ASSET)
    assets.SetCommodity(cad)
    root.append_child(assets)

    checking = Account(book)
    checking.SetName('Checking')
    checking.SetType(gnucash.ACCT_TYPE_BANK)
    checking.SetCommodity(cad)
    assets.append_child(checking)

    expenses = Account(book)
    expenses.SetName('Expenses')
    expenses.SetType(gnucash.ACCT_TYPE_EXPENSE)
    expenses.SetCommodity(cad)
    root.append_child(expenses)

    dining = Account(book)
    dining.SetName('Dining')
    dining.SetType(gnucash.ACCT_TYPE_EXPENSE)
    dining.SetCommodity(cad)
    expenses.append_child(dining)

    tx = Transaction(book)
    tx.BeginEdit()
    tx.SetCurrency(cad)
    tx.SetDate(15, 6, 2024)
    tx.SetDescription('Dinner out')

    s1 = Split(book)
    s1.SetParent(tx)
    s1.SetAccount(dining)
    s1.SetValue(GncNumeric(4500, 100))

    s2 = Split(book)
    s2.SetParent(tx)
    s2.SetAccount(checking)
    s2.SetValue(GncNumeric(-4500, 100))

    tx.CommitEdit()
    guid = tx.GetGUID().to_string()
    session.save()
    session.end()

    return path, guid


def run_cli(*args):
    runner = CliRunner()
    return runner.invoke(cli, ['delete-transaction-by-guid'] + list(args))


class TestDeleteTransactionByGuidCli:

    def test_unknown_guid_fails(self):
        """Non-existent GUID exits non-zero with an error message."""
        path, _guid = _make_gnucash_with_transaction()
        try:
            result = run_cli(path, 'a' * 32)
            assert result.exit_code != 0
            assert 'not found in book' in result.output
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_valid_guid_exits_zero(self):
        """Valid GUID deletes the transaction and exits 0."""
        path, guid = _make_gnucash_with_transaction()
        try:
            result = run_cli(path, guid)
            assert result.exit_code == 0, result.output
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_backup_contains_guid(self):
        """Stdout backup includes the transaction GUID."""
        path, guid = _make_gnucash_with_transaction()
        try:
            result = run_cli(path, guid)
            assert result.exit_code == 0, result.output
            assert guid in result.output
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_output_file_flag(self, tmp_path):
        """With -o, backup is written to file and stdout shows the file path."""
        path, guid = _make_gnucash_with_transaction()
        backup = str(tmp_path / 'backup.txt')
        try:
            result = run_cli(path, guid, '-o', backup)
            assert result.exit_code == 0, result.output
            assert 'Backup written to' in result.output
            with open(backup) as f:
                content = f.read()
            assert guid in content
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_backup_is_reimportable(self, tmp_path):
        """The backup plaintext can be re-imported to restore the deleted transaction."""
        from gnucash import Query, Transaction

        from repositories.gnucash_repository import GnuCashRepository
        from services.conflict_resolver import ResolutionStrategy
        from use_cases.import_transactions import ImportTransactionsUseCase

        path, guid = _make_gnucash_with_transaction()
        backup = str(tmp_path / 'backup.txt')
        try:
            # Delete with backup
            result = run_cli(path, guid, '-o', backup)
            assert result.exit_code == 0, result.output

            # Wait 1s so the re-import save gets a different backup filename
            import time
            time.sleep(1)

            # Re-import backup
            repo = GnuCashRepository(path)
            repo.open()
            try:
                uc = ImportTransactionsUseCase(repo)
                import_result = uc.import_from_file(backup, ResolutionStrategy.SKIP)
                repo.save()
            finally:
                repo.close()

            assert import_result.imported_count == 1

            # Verify transaction is back in the book
            try:
                from gnucash import Session, SessionOpenMode
                session = Session(f'xml://{path}', SessionOpenMode.SESSION_NORMAL_OPEN)
            except ImportError:
                from gnucash import Session
                session = Session(f'xml://{path}')
            book = session.book
            q = Query()
            q.search_for('Trans')
            q.set_book(book)
            txs = [Transaction(instance=t) for t in q.run()]
            assert len(txs) == 1
            assert txs[0].GetDescription() == 'Dinner out'
            session.end()
        finally:
            if os.path.exists(path):
                os.unlink(path)
