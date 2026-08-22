"""A printed page read into a foreign book can then be edited there.

Reading one into a book that never held its transactions works: the guids name
nothing, so the payment is recorded from the block. The question this asks is
the run *after* that — the reader changes a field and imports again, which is
how every other block in this format is corrected.

That second run rebuilds the invoice, and rebuilding unposts it. An unpost
does not destroy the payment transaction; it orphans its splits and leaves the
bank split where it is. The payment then looks, to the duplicate-payment
guard, exactly like money the book already had — so the guard can fire on the
rebuild's own orphan and refuse the import, leaving the invoice half-built
and telling the reader to correct a guid in a file this tool generated.

The distinguishing fact is on the split: a bank split carrying
`orphaned_by_unpost` for this very record is the rebuild's own, not money the
book independently held.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

SOURCE = str(Path('tests/fixtures/a_payment_named_with_account.txt'))


def _transaction_count(book):
    from gnucash import Query

    from repositories.gnucash_repository import GnuCashRepository, SessionMode

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        count = len(list(query.run()))
        query.destroy()
        return count
    finally:
        repo.close()


@pytest.fixture
def elsewhere_holding_the_printed_invoice(tmp_path):
    """Another book, built from the printed page rather than the ledger."""
    source_book = tmp_path / 'source.gnucash'
    assert CliRunner().invoke(cli, [
        'import', '--new', str(source_book), SOURCE,
        '--include-business-objects']).exit_code == 0

    printed = tmp_path / 'printed.txt'
    assert CliRunner().invoke(cli, [
        'print-invoice', str(source_book), 'INV-SPELL',
        '--format', 'plaintext', '-o', str(printed)]).exit_code == 0

    elsewhere = tmp_path / 'elsewhere.gnucash'
    assert CliRunner().invoke(cli, [
        'import', '--new', str(elsewhere), SOURCE]).exit_code == 0
    first = CliRunner().invoke(cli, [
        'import', str(elsewhere), str(printed), '--include-business-objects'])
    assert first.exit_code == 0, first.output
    return elsewhere, printed


class TestCorrectingItThere:
    def test_the_edited_page_re_imports(
            self, elsewhere_holding_the_printed_invoice, tmp_path):
        """The ordinary way every page in this format is corrected."""
        elsewhere, printed = elsewhere_holding_the_printed_invoice
        edited = tmp_path / 'edited.txt'
        edited.write_text(printed.read_text().replace(
            '\tcurrency: CAD', '\tnotes: "Corrected after printing"\n\tcurrency: CAD',
            1))

        before = _transaction_count(elsewhere)

        result = CliRunner().invoke(cli, [
            'import', str(elsewhere), str(edited), '--include-business-objects'])

        assert result.exit_code == 0, result.output
        # And the correction corrects rather than pays again: the money moved
        # once, whatever the rebuild had to take apart to change a field.
        assert _transaction_count(elsewhere) == before
