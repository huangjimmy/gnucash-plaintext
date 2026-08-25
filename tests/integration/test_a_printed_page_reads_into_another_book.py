"""A printed page reads into a book that never held its transactions.

`print-invoice --format plaintext` writes `posted_txn_guid:` on the `posted:`
block and `txn_guid:` / `txn_split_guid:` on each payment, naming the *source*
book's transactions. Read back into the same book those relink, which is what
stops a re-import posting and paying a second time.

Read into a different book they resolve to nothing — by construction, since
that book never held them. That is the case the printing exists for: handing
a page to somebody who does not have your ledger. The payment side has
explicit handling for it; the posted side has none, and nothing covered it.

If an unresolvable `posted_txn_guid:` refuses or mis-links, a printed page
is readable only inside the book it came from, which is the opposite of what
printing one is for.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
SOURCE = str(FIXTURES / 'a_payment_named_with_account.txt')


@pytest.fixture
def printed(tmp_path):
    """An invoice printed out of a book that holds its posting and payment."""
    source_book = tmp_path / 'source.gnucash'
    result = CliRunner().invoke(cli, [
        'import', '--new', str(source_book), SOURCE,
        '--include-business-objects'])
    assert result.exit_code == 0, result.output

    out = tmp_path / 'printed.txt'
    printed = CliRunner().invoke(cli, [
        'print-invoice', str(source_book), 'INV-SPELL',
        '--format', 'plaintext', '-o', str(out)])
    assert printed.exit_code == 0, printed.output
    text = out.read_text()
    assert 'posted_txn_guid' in text, text
    return out


def _guids_the_file_names(text, *keys):
    """`{key: [guid, …]}` for the guid-bearing keys a page carries."""
    found = {key: [] for key in keys}
    for line in text.splitlines():
        name, _, value = line.strip().partition(':')
        if name in found:
            found[name].append(value.strip().strip('"'))
    return found


def _guids_the_book_holds(book):
    """Every transaction and split guid in a book, normalised."""
    from gnucash import Query, Transaction

    from repositories.gnucash_repository import GnuCashRepository, SessionMode

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        held = set()
        for raw in query.run():
            transaction = Transaction(instance=raw)
            held.add(transaction.GetGUID().to_string())
            for split in transaction.GetSplitList():
                held.add(split.GetGUID().to_string())
        query.destroy()
        return held
    finally:
        repo.close()


@pytest.fixture
def elsewhere(tmp_path):
    """Another book with the same chart of accounts and nothing else.

    A printed page is the page, not a chart of accounts — so the
    accounts come from the ledger, and the transactions the page's guids
    name are exactly what this book does not have.
    """
    book = tmp_path / 'elsewhere.gnucash'
    result = CliRunner().invoke(cli, ['import', '--new', str(book), SOURCE])
    assert result.exit_code == 0, result.output
    return book


class TestIntoABookThatNeverHeldThem:
    def test_it_reads(self, printed, elsewhere):
        """The whole point of printing one."""
        result = CliRunner().invoke(cli, [
            'import', str(elsewhere), str(printed),
            '--include-business-objects'])

        assert result.exit_code == 0, result.output

    def test_the_invoice_is_posted_there(self, printed, elsewhere, tmp_path):
        """Not left as a draft because a guid it named was not found."""
        CliRunner().invoke(cli, [
            'import', str(elsewhere), str(printed),
            '--include-business-objects'])

        out = tmp_path / 'back.txt'
        assert CliRunner().invoke(cli, [
            'export', str(elsewhere), str(out),
            '--include-business-objects']).exit_code == 0
        text = out.read_text()
        assert 'INV-SPELL' in text, text
        assert 'posted: none' not in text, text

    def test_it_says_the_posting_guid_matched_nothing_here(self, printed,
                                                           elsewhere):
        """Not an error — reading it here is what printing it is for — but
        not silent either.

        `posted_txn_guid:` is the one line of the page that cannot be
        honoured in another book, and the posting made instead carries a
        guid GnuCash minted. The payment side has always said as much
        about `txn_guid:`; this side said nothing at all, so a reader
        comparing the two books met a transaction they had no way to know
        was new.
        """
        result = CliRunner().invoke(cli, [
            'import', str(elsewhere), str(printed),
            '--include-business-objects'])

        assert result.exit_code == 0, result.output
        assert 'posted_txn_guid' in result.output, result.output
        assert 'matches no transaction in this book' in result.output, \
            result.output
        assert 'INV-SPELL' in result.output, result.output

    def test_but_a_rebuild_in_the_books_own_ledger_says_nothing(
            self, tmp_path):
        """The same note, on a page being edited where it lives, would
        say something untrue.

        `gncInvoiceUnpost` destroys the posting transaction, so by the time
        a rebuild reads the file's `posted_txn_guid:` it names nothing —
        in the book that wrote it as much as in a stranger's. Said there,
        it tells a reader their own ledger names a transaction their book
        has not got, for an ordinary edit to a posted invoice, quoting a
        guid that was the book's own until this run destroyed it.
        """
        book = tmp_path / 'own.gnucash'
        assert CliRunner().invoke(cli, [
            'import', '--new', str(book), SOURCE,
            '--include-business-objects']).exit_code == 0

        out = tmp_path / 'ledger.txt'
        assert CliRunner().invoke(cli, [
            'export', str(book), str(out),
            '--include-business-objects']).exit_code == 0
        exported = out.read_text()
        assert 'posted_txn_guid' in exported, exported

        edited = tmp_path / 'edited.txt'
        edited.write_text(exported.replace(
            'invoice "INV-SPELL"',
            'invoice "INV-SPELL"\n\tnotes: "Corrected"', 1))
        runner = CliRunner()
        # Through the two steps the refusal names, since a posted invoice
        # takes a `payment:` block and nothing else.
        refused = runner.invoke(cli, [
            'import', str(book), str(edited), '--include-business-objects'])
        assert refused.exit_code != 0, refused.output
        assert runner.invoke(cli, ['unpost-invoices', str(book),
                                   'INV-SPELL']).exit_code == 0
        result = runner.invoke(cli, [
            'import', str(book), str(edited), '--include-business-objects'])

        assert result.exit_code == 0, result.output
        assert 'posted_txn_guid' not in result.output, result.output

    def test_nor_after_a_separate_unpost_of_the_books_own_page(
            self, tmp_path):
        """`unpost-invoices`, then import — the remedy the line-edit
        refusal names — and the page goes back on its own posting.

        The unpost destroyed the posting transaction in an earlier run, so
        by the time the import reads the ledger nothing in the book
        remembers it. What saves this is the ledger itself: an export is
        the whole book, so the posting transaction is in its transaction
        section under the same guid, it is created before the invoices
        are read, and `posted_txn_guid:` then names a transaction this
        book has — the one it always was.
        """
        book = tmp_path / 'own.gnucash'
        runner = CliRunner()
        assert runner.invoke(cli, [
            'import', '--new', str(book), SOURCE,
            '--include-business-objects']).exit_code == 0

        out = tmp_path / 'ledger.txt'
        assert runner.invoke(cli, [
            'export', str(book), str(out),
            '--include-business-objects']).exit_code == 0
        posting = _posting_guid_of(book, tmp_path, 'before.txt')

        unposted = runner.invoke(cli, ['unpost-invoices', str(book),
                                       'INV-SPELL'])
        assert unposted.exit_code == 0, unposted.output

        result = runner.invoke(cli, [
            'import', str(book), str(out), '--include-business-objects'])

        assert result.exit_code == 0, result.output
        assert 'posted_txn_guid' not in result.output, result.output
        # Back on the posting it was booked through, not a new one.
        assert _posting_guid_of(book, tmp_path, 'after.txt') == posting

    def test_the_export_names_this_books_transactions_not_the_printers(
            self, printed, elsewhere, tmp_path):
        """A guid that named nothing here must not survive into the export.

        The page arrives naming the source book's posting transaction
        and the source book's payment, and this book posts and pays under
        guids of its own. If the export writes back what the file said
        rather than what the book holds, the ledger it produces describes
        transactions that are not in it: importing that ledger anywhere
        finds nothing again, `find-transactions` on any of those guids
        answers nothing, and two books that agree about the money disagree
        about which transactions carry it.
        """
        printers = _guids_the_file_names(
            printed.read_text(),
            'posted_txn_guid', 'txn_guid', 'txn_split_guid')
        assert printers['posted_txn_guid'], printers

        result = CliRunner().invoke(cli, [
            'import', str(elsewhere), str(printed),
            '--include-business-objects'])
        assert result.exit_code == 0, result.output

        out = tmp_path / 'back.txt'
        assert CliRunner().invoke(cli, [
            'export', str(elsewhere), str(out),
            '--include-business-objects']).exit_code == 0
        text = out.read_text()

        for key, guids in printers.items():
            for guid in guids:
                assert guid not in text, (key, guid, text)

        held = _guids_the_book_holds(elsewhere)
        written = _guids_the_file_names(
            text, 'posted_txn_guid', 'txn_guid', 'txn_split_guid')
        for key, guids in written.items():
            assert guids, (key, text)
            for guid in guids:
                assert guid in held, (key, guid, sorted(held))

    def test_the_same_file_read_twice_changes_nothing(self, printed,
                                                      elsewhere, tmp_path):
        """The second read of an unedited page must be a no-op.

        Every payment block a printed page carries names a
        `txn_split_guid:` from the *source* book, and the payment this book
        made for it was created by `ApplyPayment` under guids GnuCash
        minted — so that name resolves to nothing here, by construction,
        for as long as the page exists.

        Read as "this block matches no payment", the page is a changed
        one: it is unposted, its lines rebuilt and posted again under a new
        transaction, and the book saved — every single time the same file
        is read. A page handed to someone else would move in their
        ledger each time they imported it.
        """
        first = CliRunner().invoke(cli, [
            'import', str(elsewhere), str(printed),
            '--include-business-objects'])
        assert first.exit_code == 0, first.output

        before = _posting_guid_of(elsewhere, tmp_path, 'first.txt')

        again = CliRunner().invoke(cli, [
            'import', str(elsewhere), str(printed),
            '--include-business-objects'])
        assert again.exit_code == 0, again.output

        assert 'INV-SPELL": unchanged' in again.output, again.output
        assert _posting_guid_of(elsewhere, tmp_path, 'second.txt') == before


def _posting_guid_of(book, tmp_path, name):
    """`posted_txn_guid:` as the export writes it — the posting transaction
    the page is booked through, which a rebuild replaces."""
    out = tmp_path / name
    assert CliRunner().invoke(cli, [
        'export', str(book), str(out),
        '--include-business-objects']).exit_code == 0
    for line in out.read_text().splitlines():
        if 'posted_txn_guid' in line:
            return line.strip()
    raise AssertionError(f'no posted_txn_guid in {out}')
