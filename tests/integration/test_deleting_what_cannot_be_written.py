"""A transaction plaintext cannot state is still deletable.

`delete-transactions` renders an undo copy before it deletes, so the user can
re-import what they removed. When the export refuses — a split holding a figure
finer than its currency, which GnuCash stores and this format has no way to
say — that copy cannot be made.

Refusing the deletion for it was a trap. A book holding such a figure is
exactly the book someone reaches for this command to fix: `export` refuses it,
and `delete-transactions` refused it for the same reason one step removed, so
there was no way to get rid of it inside the tool at all. What is lost is the
copy, so that is what the command says — in the backup's place, and again on
stderr, because a reader who redirected the backup and did not read it would
otherwise find out on the day they needed to undo.

The book is built through the bindings because this tool's own importer will
not write such a split.
"""

import os
import tempfile

import pytest
from click.testing import CliRunner

from cli.main import cli


@pytest.fixture
def book_and_guid():
    """A CAD book holding 1.819 on a thousandths account, and its tx GUID."""
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

    def child(parent, name, kind, scu=None):
        account = Account(book)
        account.SetName(name)
        account.SetType(kind)
        account.SetCommodity(cad)
        if scu is not None:
            account.SetCommoditySCU(scu)
        parent.append_child(account)
        return account

    assets = child(root, 'Assets', gnucash.ACCT_TYPE_ASSET)
    bank = child(assets, 'Bank', gnucash.ACCT_TYPE_BANK, 1000)
    expenses = child(root, 'Expenses', gnucash.ACCT_TYPE_EXPENSE)
    fuel = child(expenses, 'Fuel', gnucash.ACCT_TYPE_EXPENSE, 1000)

    transaction = Transaction(book)
    transaction.BeginEdit()
    transaction.SetCurrency(cad)
    transaction.SetDate(1, 2, 2026)
    transaction.SetDescription('One litre')
    out = Split(book)
    out.SetParent(transaction)
    out.SetAccount(fuel)
    out.SetValue(GncNumeric(1819, 1000))
    out.SetAmount(GncNumeric(1819, 1000))
    back = Split(book)
    back.SetParent(transaction)
    back.SetAccount(bank)
    back.SetValue(GncNumeric(-1819, 1000))
    back.SetAmount(GncNumeric(-1819, 1000))
    transaction.CommitEdit()
    guid = transaction.GetGUID().to_string()

    session.save()
    session.end()
    yield path, guid
    if os.path.exists(path):
        os.unlink(path)


def _remaining(path):
    from gnucash import Query, Transaction

    from repositories.gnucash_repository import GnuCashRepository, SessionMode

    repo = GnuCashRepository(path)
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        descriptions = [Transaction(instance=raw).GetDescription()
                        for raw in query.run()]
        query.destroy()
        return descriptions
    finally:
        repo.close()


class TestTheDeletionGoesThrough:
    def test_the_transaction_is_gone(self, book_and_guid, tmp_path):
        """It is removed — this command is the only way to remove it."""
        path, guid = book_and_guid
        CliRunner().invoke(cli, [
            'delete-transactions', path, '--by-guid', guid,
            '-o', str(tmp_path / 'undo.txt')])

        assert _remaining(path) == [], _remaining(path)

    def test_the_run_does_not_report_success(self, book_and_guid, tmp_path):
        """Deleted with no way back is not a run to chain on.

        The warning is on stderr and the backup file says so in its own
        place, but `delete-transactions … -o undo.txt && next-step` reads
        neither: the file exists, it holds only comments, and the exit code
        said everything was fine. The same shape as `import` printing
        `Errors: N` and exiting 0, which this release changed for the same
        reason — a script cannot read a summary.
        """
        path, guid = book_and_guid
        result = CliRunner().invoke(cli, [
            'delete-transactions', path, '--by-guid', guid,
            '-o', str(tmp_path / 'undo.txt')])

        assert result.exit_code != 0, result.output

    def test_it_says_the_deletion_happened(self, book_and_guid, tmp_path):
        path, guid = book_and_guid
        result = CliRunner().invoke(cli, [
            'delete-transactions', path, '--by-guid', guid,
            '-o', str(tmp_path / 'undo.txt')])

        assert f'{guid}: deleted' in result.output, result.output
        assert 'One litre' in result.output, result.output


class TestTheMissingCopyIsLoud:
    def test_stderr_warns_that_there_is_no_undo_copy(
            self, book_and_guid, tmp_path):
        path, guid = book_and_guid
        result = CliRunner().invoke(cli, [
            'delete-transactions', path, '--by-guid', guid,
            '-o', str(tmp_path / 'undo.txt')])

        assert 'WARNING no undo copy' in result.output, result.output
        assert '1.819' in result.output, result.output

    def test_the_backup_file_says_so_in_its_own_place(
            self, book_and_guid, tmp_path):
        """A reader who only ever looks at the file still learns it."""
        path, guid = book_and_guid
        undo = tmp_path / 'undo.txt'
        CliRunner().invoke(cli, [
            'delete-transactions', path, '--by-guid', guid, '-o', str(undo)])

        text = undo.read_text()
        assert 'No undo copy could be written' in text, text
        assert guid in text, text
        assert '1.819' in text, text

    def test_the_backup_holds_no_transaction_to_re_import(
            self, book_and_guid, tmp_path):
        """Every line is a comment, so importing it is a no-op, not a lie."""
        path, guid = book_and_guid
        undo = tmp_path / 'undo.txt'
        CliRunner().invoke(cli, [
            'delete-transactions', path, '--by-guid', guid, '-o', str(undo)])

        body = [line for line in undo.read_text().splitlines()
                if line.strip() and not line.startswith('#')]
        assert body == [], body

        back = tmp_path / 'back.gnucash'
        result = CliRunner().invoke(
            cli, ['import', '--new', str(back), str(undo)])
        assert result.exit_code == 0, result.output
        assert 'Errors:       0' in result.output, result.output


class TestAnOrdinaryDeletionIsUnchanged:
    """The copy is still a copy when the format can state the transaction."""

    def test_the_backup_re_imports(self, tmp_path):
        book = tmp_path / 'book.gnucash'
        assert CliRunner().invoke(cli, [
            'import', '--new', str(book),
            'tests/fixtures/account_with_finer_scu.txt']).exit_code == 0

        exported = tmp_path / 'listing.txt'
        assert CliRunner().invoke(
            cli, ['export', str(book), str(exported)]).exit_code == 0
        # The `guid:` line directly under the transaction header — account
        # blocks carry one at the same indent, and taking the first match
        # picked an account and deleted nothing.
        lines = exported.read_text().splitlines()
        header = next(i for i, line in enumerate(lines) if '10 litres' in line)
        guid = lines[header + 1].split('"')[1]

        undo = tmp_path / 'undo.txt'
        result = CliRunner().invoke(cli, [
            'delete-transactions', str(book), '--by-guid', guid,
            '-o', str(undo)])

        assert result.exit_code == 0, result.output
        assert 'WARNING no undo copy' not in result.output, result.output
        assert 'Expenses:Fuel 18.190 CAD' in undo.read_text(), undo.read_text()

        # And it re-imports, which is what "undo copy" means. The collecting
        # loop that gathers refusals appends to `lines` as it goes, so a
        # partial-write bug there shows up as a backup that will not parse,
        # not as a missing string — the assertion above would pass through it.
        restored = tmp_path / 'restored.gnucash'
        result = CliRunner().invoke(
            cli, ['import', '--new', str(restored), str(undo)])
        assert result.exit_code == 0, result.output
        assert 'Errors:       0' in result.output, result.output
        assert 'Transactions: 1' in result.output, result.output

        listing = tmp_path / 'restored.txt'
        assert CliRunner().invoke(
            cli, ['export', str(restored), str(listing)]).exit_code == 0
        text = listing.read_text()
        assert 'Expenses:Fuel 18.190 CAD' in text, text
        assert 'Assets:Bank -18.190 CAD' in text, text
