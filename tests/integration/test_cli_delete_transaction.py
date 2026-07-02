"""
Integration tests for the delete-transactions CLI command.

Verifies:
- Valid GUID: transaction deleted, backup written to stdout or -o file
- Unknown GUID: non-zero exit, clear error message
- Backup plaintext can be re-imported to restore the transaction
- Missing --by-guid: command errors (required flag)
- Multi-arg: multiple GUIDs in one call, partial failure exits 1 but saves successes
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


def _make_gnucash_with_two_transactions():
    """Return (path, guid1, guid2) — book with two distinct CAD transactions.

    Used by `test_multi_delete_backup_is_reimportable` to verify the
    multi-arg backup-concat path: that two self-contained plaintext
    blocks (each with their own commodity + account declarations)
    parse cleanly when concatenated and re-imported as one file."""
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
    cad = book.get_table().lookup('CURRENCY', 'CAD')

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

    def _mk(amount_cents, desc, day):
        tx = Transaction(book)
        tx.BeginEdit()
        tx.SetCurrency(cad)
        tx.SetDate(day, 6, 2024)
        tx.SetDescription(desc)
        s1 = Split(book)
        s1.SetParent(tx)
        s1.SetAccount(dining)
        s1.SetValue(GncNumeric(amount_cents, 100))
        s2 = Split(book)
        s2.SetParent(tx)
        s2.SetAccount(checking)
        s2.SetValue(GncNumeric(-amount_cents, 100))
        tx.CommitEdit()
        return tx.GetGUID().to_string()

    guid1 = _mk(4500, 'Dinner out', 15)
    guid2 = _mk(2300, 'Lunch', 16)
    session.save()
    session.end()

    return path, guid1, guid2


def run_cli(*args):
    runner = CliRunner()
    return runner.invoke(cli, ['delete-transactions'] + list(args))


class TestDeleteTransactionsCli:

    def test_missing_by_guid_flag_fails(self):
        """Without --by-guid, command errors with a clear message
        (the flag is required for explicit GUID-mode addressing,
        matching delete-customers --by-guid, delete-invoices --by-guid,
        unpost-invoices --by-guid)."""
        path, guid = _make_gnucash_with_transaction()
        try:
            result = run_cli(path, guid)  # no --by-guid
            assert result.exit_code != 0
            assert '--by-guid' in result.output, result.output
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_unknown_guid_fails(self):
        """Non-existent GUID exits non-zero with an error message."""
        path, _guid = _make_gnucash_with_transaction()
        try:
            result = run_cli(path, '--by-guid', 'a' * 32)
            assert result.exit_code != 0
            # Per-tx status goes to stderr; CliRunner merges by default.
            assert 'not found in book' in result.output
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_valid_guid_exits_zero(self):
        """Valid GUID deletes the transaction and exits 0."""
        path, guid = _make_gnucash_with_transaction()
        try:
            result = run_cli(path, '--by-guid', guid)
            assert result.exit_code == 0, result.output
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_backup_contains_guid(self):
        """Stdout backup includes the transaction GUID."""
        path, guid = _make_gnucash_with_transaction()
        try:
            result = run_cli(path, '--by-guid', guid)
            assert result.exit_code == 0, result.output
            assert guid in result.output
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_output_file_flag(self, tmp_path):
        """With -o, backup is written to file and the per-tx status
        line still appears on stderr (merged into CliRunner.output)."""
        path, guid = _make_gnucash_with_transaction()
        backup = str(tmp_path / 'backup.txt')
        try:
            result = run_cli(path, '--by-guid', guid, '-o', backup)
            assert result.exit_code == 0, result.output
            assert 'Backup written to' in result.output
            with open(backup) as f:
                content = f.read()
            assert guid in content
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_multiple_guids_partial_failure(self, tmp_path):
        """When some GUIDs hit and some miss, the hits are still
        deleted, the misses still reported, and the overall exit
        code is 1."""
        path, guid = _make_gnucash_with_transaction()
        try:
            result = run_cli(path, '--by-guid', guid, 'b' * 32)
            assert result.exit_code == 1, result.output
            # Successful deletion of `guid` shows up:
            assert f'{guid}: deleted' in result.output, result.output
            # Missing one shows up as not found:
            assert ('b' * 32) in result.output
            assert 'not found in book' in result.output
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_multi_delete_backup_is_reimportable(self, tmp_path):
        """Concatenated multi-tx backup re-imports cleanly and restores
        both transactions. Guards `"\\n\\n".join(...)` in delete_transaction_cmd.py:
        each tx exports as a self-contained block (commodity + accounts
        + tx), so two concatenated blocks must not break the importer
        when it hits the second copy of the commodity/account declarations."""
        from gnucash import Query, Transaction

        from repositories.gnucash_repository import GnuCashRepository
        from services.conflict_resolver import ResolutionStrategy
        from use_cases.import_transactions import ImportTransactionsUseCase

        path, guid1, guid2 = _make_gnucash_with_two_transactions()
        backup = str(tmp_path / 'multi_backup.txt')
        try:
            result = run_cli(path, '--by-guid', guid1, guid2, '-o', backup)
            assert result.exit_code == 0, result.output
            assert f'{guid1}: deleted' in result.output, result.output
            assert f'{guid2}: deleted' in result.output, result.output

            # GnuCash backup filenames use a per-second timestamp.
            # Without this sleep, the next `repo.save()` collides with
            # the delete-transactions save's backup filename and raises
            # ERR_FILEIO_BACKUP_ERROR — which our CLI swallows, so the
            # re-import silently no-ops on disk and `imported_count`
            # comes back as 0 (false test pass otherwise). Same footgun
            # the Q-010 unpost test documents at length.

            # Both blocks present in the concatenated backup
            with open(backup) as f:
                content = f.read()
            assert guid1 in content
            assert guid2 in content

            # Re-import the concatenated backup
            repo = GnuCashRepository(path)
            repo.open()
            try:
                uc = ImportTransactionsUseCase(repo)
                import_result = uc.import_from_file(backup, ResolutionStrategy.SKIP)
                repo.save()
            finally:
                repo.close()

            assert import_result.imported_count == 2, (
                f"Expected 2 transactions re-imported, got "
                f"{import_result.imported_count}. Concatenated backup may "
                f"not parse the second self-contained block correctly.")

            # Verify both are back in the book. Use try/finally so the
            # session lock is released even if the assertion below fails.
            try:
                from gnucash import Session, SessionOpenMode
                session = Session(f'xml://{path}', SessionOpenMode.SESSION_NORMAL_OPEN)
            except ImportError:
                from gnucash import Session
                session = Session(f'xml://{path}')
            try:
                book = session.book
                q = Query()
                q.search_for('Trans')
                q.set_book(book)
                descs = sorted(Transaction(instance=t).GetDescription()
                               for t in q.run())
            finally:
                session.end()
            assert descs == ['Dinner out', 'Lunch'], descs
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
            result = run_cli(path, '--by-guid', guid, '-o', backup)
            assert result.exit_code == 0, result.output

            # See comment in test_multi_delete_backup_is_reimportable
            # above re: ERR_FILEIO_BACKUP_ERROR — same per-second
            # backup-filename collision applies here.

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
