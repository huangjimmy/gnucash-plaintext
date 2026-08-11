"""A printed `payment:` block states what the export's does, or neither does.

`print-invoice --format plaintext` writes a block that can be read back — that
is what the guids in it are for — so the figures in it are figures another book
will act on. The export refuses a payment amount its currency cannot hold; the
renderer rounded the same amount and printed it.

On a receivable kept to a tenth of a cent, a settling split of 30.005 CAD:
`export --include-business-objects` refuses, naming the figure, while
`print-invoice` succeeded and wrote `amount: 30.00`. Read into a book that
never held the transaction, that block makes a payment for a figure the source
book never had.

The block writer is one function so a mistake in it is a mistake everywhere;
the amount was still worked out by each caller, which is how the two came to
disagree. `num:` is the same divergence with the opposite sign — the export
writes a cheque number and the printed block dropped it.
"""

import os

import pytest
from click.testing import CliRunner

from cli.main import cli
from tests.integration.test_export_refuses_what_it_cannot_write import (
    _book_with_a_sub_cent_payment,
)


@pytest.fixture
def book_with_a_sub_cent_payment():
    path = _book_with_a_sub_cent_payment()
    yield path
    if os.path.exists(path):
        os.unlink(path)


class TestPrintingIt:
    def test_it_does_not_write_a_figure_the_book_cannot_hold(
            self, book_with_a_sub_cent_payment, tmp_path):
        out = tmp_path / 'printed.txt'
        result = CliRunner().invoke(cli, [
            'print-invoice', book_with_a_sub_cent_payment, 'INV-FINE-OVER',
            '--format', 'plaintext', '-o', str(out)])

        if result.exit_code == 0:
            assert 'amount: 30.00\n' not in out.read_text(), out.read_text()
        else:
            assert '30.005' in result.output, result.output

    def test_it_answers_the_way_the_export_answers(
            self, book_with_a_sub_cent_payment, tmp_path):
        """One book, one figure, one answer — whichever command is asked."""
        runner = CliRunner()
        exported = runner.invoke(cli, [
            'export', book_with_a_sub_cent_payment,
            str(tmp_path / 'out.txt'), '--include-business-objects'])
        printed = runner.invoke(cli, [
            'print-invoice', book_with_a_sub_cent_payment, 'INV-FINE-OVER',
            '--format', 'plaintext', '-o', str(tmp_path / 'printed.txt')])

        assert (exported.exit_code == 0) == (printed.exit_code == 0), (
            exported.output, printed.output)


class TestTheChequeNumber:
    """`num:` is on the payment the export writes; the printed block dropped
    it, and a printed document read into a fresh book makes the payment from
    that block."""

    LEDGER = 'tests/fixtures/payment_roundtrip_accounts.txt'

    def test_it_is_printed_too(self, tmp_path):
        runner = CliRunner()
        book = tmp_path / 'num.gnucash'
        assert runner.invoke(cli, ['import', '--new', str(book),
                                   self.LEDGER]).exit_code == 0
        ledger = tmp_path / 'doc.txt'
        ledger.write_text(_INVOICE_WITH_A_CHEQUE_NUMBER)
        result = runner.invoke(cli, ['import', str(book), str(ledger),
                                     '--include-business-objects'])
        assert result.exit_code == 0, result.output

        out = tmp_path / 'printed.txt'
        assert runner.invoke(cli, [
            'print-invoice', str(book), 'INV-NUM',
            '--format', 'plaintext', '-o', str(out)]).exit_code == 0

        assert 'num: "000123"' in out.read_text(), out.read_text()


_INVOICE_WITH_A_CHEQUE_NUMBER = '''\
customer "C-NUM"
\tname: "Cheque Customer"
\tcurrency: CAD

invoice "INV-NUM"
\tcustomer_id: "C-NUM"
\tcurrency: CAD
\tdate_opened: 2026-01-01
\tentry:
\t\tdate: 2026-01-01
\t\tdescription: "A line"
\t\taccount: "Income:Sales"
\t\tquantity: 1
\t\tprice: 100
\t\ttaxable: false
\t\ttax_included: false
\tposted:
\t\tdate: 2026-01-01
\t\tdue: 2026-01-31
\t\tar_account: "Assets:Accounts Receivable"
\t\tmemo: "Invoice INV-NUM"
\t\taccumulate: true
\tpayment:
\t\tdate: 2026-01-15
\t\tamount: 100
\t\tbank_account: "Assets:Bank"
\t\tmemo: "Paid"
\t\tnum: "000123"
'''
