"""A document settled out of credit prints something that can be read back.

`print-invoice --format plaintext` carries the guids that make a printed
document re-importable, and this release documents and tests that path. It
holds for a document a bank paid.

A document settled out of an owner's credit has no bank side at all. The export
writes those as `from_credit: true` with no account; the renderers look through
the payment transaction for a non-AR/AP split, find none, and write
`bank_account: ""`. Re-importing that, `find_account(root, '')` answers with the
*root* account and the payment is refused for its account type — including by
the book the document was printed from.

The shared block writer exists because these were written three times and
drifted. This is the branch that was left out of it, and adding the guids made
the block look like a valid retarget while it is not one.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
ACCOUNTS = str(FIXTURES / 'q019_accounts.txt')


@pytest.fixture
def book_and_printed(tmp_path):
    """An invoice settled in full from a customer's standing credit."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(book),
                               ACCOUNTS]).exit_code == 0

    primer = tmp_path / 'primer.txt'
    primer.write_text((FIXTURES / 'credit_primer_invoice_150.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(primer),
                               '--include-business-objects']).exit_code == 0

    settled = tmp_path / 'settled.txt'
    settled.write_text(
        (FIXTURES / 'credit_two_invoices_both_flagged.txt').read_text())
    result = runner.invoke(cli, ['import', str(book), str(settled),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output

    printed = tmp_path / 'printed.txt'
    out = runner.invoke(cli, ['print-invoice', str(book), 'INV-MB-1',
                              '--format', 'plaintext', '-o', str(printed)])
    assert out.exit_code == 0, out.output
    return book, printed


class TestWhatItPrints:
    def test_it_does_not_name_an_empty_bank_account(self, book_and_printed):
        """`bank_account: ""` reads back as the root account."""
        _book, printed = book_and_printed

        assert 'bank_account: ""' not in printed.read_text(), printed.read_text()

    def test_it_says_the_credit_settled_it(self, book_and_printed):
        """Which is what happened, and what the export writes."""
        _book, printed = book_and_printed

        text = printed.read_text()
        assert 'from_credit: true' in text, text


class TestReadingItBack:
    def test_the_document_it_was_printed_from_accepts_it(self,
                                                         book_and_printed):
        """The narrowest case there is: its own book."""
        book, printed = book_and_printed

        result = CliRunner().invoke(cli, [
            'import', str(book), str(printed), '--include-business-objects'])

        assert result.exit_code == 0, result.output


class TestAgainstTheExport:
    def test_both_call_it_a_credit(self, book_and_printed, tmp_path):
        """One book, one account of how it was settled.

        The export said `from_credit: true`; the printed document said
        `bank_account: "Assets:Bank"`, with the date and memo of the
        transaction the *credit* had arrived through. Which command was asked
        decided what the document claimed had happened.
        """
        book, printed = book_and_printed
        out = tmp_path / 'out.txt'
        assert CliRunner().invoke(cli, [
            'export', str(book), str(out),
            '--include-business-objects']).exit_code == 0

        exported = out.read_text().split('invoice "INV-MB-1"')[1]
        exported = exported.split('\ninvoice ')[0]
        assert 'from_credit: true' in exported, exported
        assert 'bank_account:' not in exported, exported
        assert 'bank_account:' not in printed.read_text(), printed.read_text()
