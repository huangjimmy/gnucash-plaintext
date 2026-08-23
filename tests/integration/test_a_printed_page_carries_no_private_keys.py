"""What the customer receives says who they are, not what is written about them.

`print-invoice` produces a page for the recipient — it carries `# Issued
by:` and inlines the tax tables so they can check the rates. `export` produces
the book in text, for this tool to read back.

Both render an owner, and the owner block gained the custom-key dump so that
`export` round-trips keys the format has no setter for. The printed page
took it too, and a key like `credit_rating` is the book owner's note about the
customer, not a fact about the invoice.

The round trip does not need it there. A printed block that omits a key leaves
it alone on re-import — the merge writes only the keys a block names — so the
page can say less without losing anything.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

LEDGER = str(Path('tests/fixtures/a_customer_with_a_private_note.txt'))


@pytest.fixture
def book(tmp_path):
    gnc = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(cli, ['import', '--new', str(gnc), LEDGER,
                                      '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return gnc


class TestWhatThePrintedInvoiceSays:
    def _printed(self, book, tmp_path):
        out = tmp_path / 'printed.txt'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), 'INV-PRIVATE',
            '--format', 'plaintext', '-o', str(out)])
        assert result.exit_code == 0, result.output
        return out.read_text()

    def test_it_does_not_carry_the_book_owners_note(self, book, tmp_path):
        text = self._printed(book, tmp_path)

        assert 'credit_rating' not in text, text
        assert 'chase early' not in text, text

    def test_it_still_says_who_the_customer_is(self, book, tmp_path):
        """Enough to be a page, which is what it is for."""
        text = self._printed(book, tmp_path)

        assert 'Private Note Customer' in text, text
        assert 'INV-PRIVATE' in text, text


class TestWhatTheExportSays:
    def test_the_key_is_there_because_the_book_has_to_come_back(self, book,
                                                                tmp_path):
        out = tmp_path / 'out.txt'
        assert CliRunner().invoke(cli, [
            'export', str(book), str(out),
            '--include-business-objects']).exit_code == 0

        assert 'credit_rating: "poor - chase early"' in out.read_text()

    def test_and_it_survives_a_rebuild(self, book, tmp_path):
        out = tmp_path / 'out.txt'
        assert CliRunner().invoke(cli, [
            'export', str(book), str(out),
            '--include-business-objects']).exit_code == 0
        rebuilt = tmp_path / 'rebuilt.gnucash'
        assert CliRunner().invoke(cli, [
            'import', '--new', str(rebuilt), str(out),
            '--include-business-objects']).exit_code == 0

        again = tmp_path / 'again.txt'
        assert CliRunner().invoke(cli, [
            'export', str(rebuilt), str(again),
            '--include-business-objects']).exit_code == 0
        assert 'credit_rating: "poor - chase early"' in again.read_text()


class TestPrintingItDoesNotLoseIt:
    def test_the_key_is_still_on_the_customer_after_a_printed_re_import(
            self, book, tmp_path):
        """The page says less, and re-reading it takes nothing away."""
        printed = tmp_path / 'printed.txt'
        assert CliRunner().invoke(cli, [
            'print-invoice', str(book), 'INV-PRIVATE',
            '--format', 'plaintext', '-o', str(printed)]).exit_code == 0
        result = CliRunner().invoke(cli, [
            'import', str(book), str(printed), '--include-business-objects'])
        assert result.exit_code == 0, result.output

        out = tmp_path / 'after.txt'
        assert CliRunner().invoke(cli, [
            'export', str(book), str(out),
            '--include-business-objects']).exit_code == 0
        assert 'credit_rating: "poor - chase early"' in out.read_text()
