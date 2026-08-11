"""A printed document reads into a book that never held its transactions.

`print-invoice --format plaintext` writes `posted_txn_guid:` on the `posted:`
block and `txn_guid:` / `txn_split_guid:` on each payment, naming the *source*
book's transactions. Read back into the same book those relink, which is what
stops a re-import posting and paying a second time.

Read into a different book they resolve to nothing — by construction, since
that book never held them. That is the case the printing exists for: handing
a document to somebody who does not have your ledger. The payment side has
explicit handling for it; the posted side has none, and nothing covered it.

If an unresolvable `posted_txn_guid:` refuses or mis-links, a printed document
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


@pytest.fixture
def elsewhere(tmp_path):
    """Another book with the same chart of accounts and nothing else.

    A printed document is the document, not a chart of accounts — so the
    accounts come from the ledger, and the transactions the document's guids
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
