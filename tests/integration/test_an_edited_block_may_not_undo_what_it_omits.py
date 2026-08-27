"""Two refusals that fire on re-importing an edited block, and what they say.

An invoice is rebuilt from its block, so what a block leaves out is not left
alone — it is unmade. Both of these are the same shape: an edit that reads as
an instruction to destroy something, where a truncated or half-corrected file
looks exactly the same.

Pinned with their messages because RELEASE_NOTES describes them to readers
whose ledgers imported yesterday and do not today, and a note describing a
refusal by its intent rather than its words sends them looking for text the
tool never prints.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
ACCOUNTS = str(FIXTURES / 'payment_roundtrip_accounts.txt')
SETUP = str(FIXTURES / 'a_customer_with_one_invoice.txt')


@pytest.fixture
def book_with_the_invoice(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(book),
                               ACCOUNTS]).exit_code == 0
    result = runner.invoke(cli, ['import', str(book), SETUP,
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return book


class TestABlockThatDroppedItsLines:
    """The invoice has entries; the file states none."""

    LEDGER = str(FIXTURES / 'an_invoice_block_with_its_lines_dropped.txt')

    def test_it_is_refused(self, book_with_the_invoice):
        result = CliRunner().invoke(cli, [
            'import', str(book_with_the_invoice), self.LEDGER,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert 'has no lines in this file and 1' in result.output, result.output
        assert 'would unpost it and leave it empty' in result.output, result.output

    def test_the_invoice_still_has_its_line(self, book_with_the_invoice,
                                            tmp_path):
        """Refused before anything was taken apart."""
        runner = CliRunner()
        runner.invoke(cli, ['import', str(book_with_the_invoice), self.LEDGER,
                            '--include-business-objects'])

        printed = tmp_path / 'printed.txt'
        result = runner.invoke(cli, [
            'print-invoice', str(book_with_the_invoice), 'INV-EDIT',
            '--format', 'plaintext', '-o', str(printed)])
        assert result.exit_code == 0, result.output
        assert 'price: 100' in printed.read_text(), printed.read_text()


class TestABlockThatDroppedItsSplits:
    """The same shape on an ordinary transaction, through `--strategy update`.

    A transaction block needs only its date, flag and description to parse, so
    a file cut short by a failed write still reads as one — and rebuilding from
    it took the money out: measured, the transaction was gone from the book
    entirely.
    """

    SETUP = str(FIXTURES / 'a_plain_transaction_to_edit.txt')
    LEDGER = str(FIXTURES / 'a_transaction_block_with_its_splits_dropped.txt')

    @pytest.fixture
    def book_with_the_transaction(self, tmp_path):
        runner = CliRunner()
        book = tmp_path / 'plain.gnucash'
        assert runner.invoke(cli, ['import', '--new', str(book),
                                   ACCOUNTS]).exit_code == 0
        result = runner.invoke(cli, ['import', str(book), self.SETUP])
        assert result.exit_code == 0, result.output
        return book

    def _cut_short(self, book, tmp_path):
        """The block naming that transaction, with its split lines gone."""
        runner = CliRunner()
        exported = tmp_path / 'whole.txt'
        assert runner.invoke(cli, ['export', str(book),
                                   str(exported)]).exit_code == 0
        # From under the transaction's own header. Accounts are exported first
        # and carry a `guid:` at the same one-tab depth, so the first in the
        # file is an account's and names nothing at transaction level.
        block = exported.read_text().split('* "Office supplies"')[1]
        guid = next(line.split('"')[1] for line in block.splitlines()
                    if line.startswith('\tguid: "'))
        ledger = tmp_path / 'cut.txt'
        ledger.write_text(Path(self.LEDGER).read_text().replace('TXN_GUID', guid))
        return runner.invoke(cli, ['import', str(book), str(ledger),
                                   '--strategy', 'update'])

    def test_it_is_refused(self, book_with_the_transaction, tmp_path):
        result = self._cut_short(book_with_the_transaction, tmp_path)

        assert result.exit_code != 0, result.output
        assert 'has no splits in this file and 2' in result.output, result.output
        assert 'would leave it with no money in it' in result.output, result.output

    def test_the_money_is_still_in_it(self, book_with_the_transaction, tmp_path):
        self._cut_short(book_with_the_transaction, tmp_path)

        exported = tmp_path / 'out.txt'
        assert CliRunner().invoke(cli, [
            'export', str(book_with_the_transaction),
            str(exported)]).exit_code == 0
        assert 'Expenses:Supplies 40.00 CAD' in exported.read_text()


class TestAnOwnerWhoseCurrencyWasEdited:
    """The book holds CAD invoices; the file says the owner is in USD."""

    LEDGER = str(FIXTURES / 'a_customer_whose_currency_was_edited.txt')

    def test_it_is_refused(self, book_with_the_invoice):
        result = CliRunner().invoke(cli, [
            'import', str(book_with_the_invoice), self.LEDGER,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert 'is in CAD in this book and the file says USD' in result.output, \
            result.output
        assert 'create the new ones under a customer in USD' in result.output, \
            result.output
