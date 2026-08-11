"""One customer's two invoices, paid alike on one day, imported one at a time.

The duplicate-payment guard asks whether the book already holds the movement a
block describes, and excuses two things: money this process made, and money
settling *another* owner's document. Neither excuses this shape — one customer,
two invoices, and blocks that agree on the date, the figure, the account and
the memo, each naming a transaction no other book holds.

So the second run is refused for the first invoice's receipt, and that is
right: the two blocks are textually the same payment, and nothing in the file
says they are two movements. The same file against two *different* customers
imports, because there the remedy the refusal offers — retarget that movement
onto this document — is not an operation at all: customer A's receipt cannot
settle customer B's invoice, so the match can only be coincidence.

What the refusal owes the reader is which document the money it found already
settles. Without that, `2026-01-15 'Spelling Customer' for 100.00` reads as an
unattached deposit and the natural move is to go correct the guid to it —
taking the first invoice's payment away. With it, the answer is plainly to drop
`txn_guid:`, and that is what the message says.

`test_two_look_alike_payments_in_one_file` is the same shape inside one file,
where this run's own payments excuse each other, and
`test_two_look_alike_payments_in_separate_runs` is the two-owner version across
runs. This is the case between them.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
FIRST = str(FIXTURES / 'a_payment_named_with_account.txt')
SAME_MEMO = str(FIXTURES / 'a_second_document_of_the_same_owner.txt')
OWN_MEMO = str(
    FIXTURES / 'a_second_document_of_the_same_owner_with_its_own_memo.txt')


def _bank_amounts(book):
    from gnucash import Query, Transaction

    from repositories.gnucash_repository import GnuCashRepository, SessionMode

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        found = []
        for raw in query.run():
            for split in Transaction(instance=raw).GetSplitList():
                account = split.GetAccount()
                if account is None or account.get_full_name() != 'Assets.Bank':
                    continue
                found.append(str(split.GetAmount()))
        query.destroy()
        return sorted(found)
    finally:
        repo.close()


@pytest.fixture
def book_with_the_first(tmp_path):
    book = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(cli, ['import', '--new', str(book), FIRST,
                                      '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return book


class TestASecondBlockThatSaysNothingNew:
    """Same date, same figure, same account, same memo — refused."""

    def test_the_run_does_not_report_success(self, book_with_the_first):
        result = CliRunner().invoke(cli, [
            'import', str(book_with_the_first), SAME_MEMO,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output

    def test_the_money_is_not_entered_twice(self, book_with_the_first):
        CliRunner().invoke(cli, ['import', str(book_with_the_first), SAME_MEMO,
                                 '--include-business-objects'])

        assert _bank_amounts(book_with_the_first) == ['10000/100']

    def test_it_names_the_document_that_money_already_settles(
            self, book_with_the_first):
        """`invoice "INV-SPELL"` — which is what makes the remedy obvious."""
        result = CliRunner().invoke(cli, [
            'import', str(book_with_the_first), SAME_MEMO,
            '--include-business-objects'])

        assert 'already settling invoice "INV-SPELL"' in result.output, \
            result.output

    def test_it_offers_dropping_the_guid(self, book_with_the_first):
        result = CliRunner().invoke(cli, [
            'import', str(book_with_the_first), SAME_MEMO,
            '--include-business-objects'])

        assert 'drop `txn_guid:`' in result.output, result.output


class TestASecondBlockThatSaysWhichPaymentItIs:
    """The same invoice, its bank line carrying its own memo — imported."""

    def test_the_run_reports_success(self, book_with_the_first):
        result = CliRunner().invoke(cli, [
            'import', str(book_with_the_first), OWN_MEMO,
            '--include-business-objects'])

        assert result.exit_code == 0, result.output

    def test_both_payments_are_in_the_book(self, book_with_the_first):
        CliRunner().invoke(cli, ['import', str(book_with_the_first), OWN_MEMO,
                                 '--include-business-objects'])

        assert _bank_amounts(book_with_the_first) == ['10000/100', '10000/100']

    def test_the_second_invoice_reads_as_paid(self, book_with_the_first,
                                              tmp_path):
        """Not merely present: its own money, in its own lot."""
        CliRunner().invoke(cli, ['import', str(book_with_the_first), OWN_MEMO,
                                 '--include-business-objects'])

        exported = tmp_path / 'out.txt'
        out = CliRunner().invoke(cli, ['export', str(book_with_the_first),
                                       str(exported),
                                       '--include-business-objects'])
        assert out.exit_code == 0, out.output
        text = exported.read_text()
        block = text.split('invoice "INV-SPELL-2"')[1]
        assert 'payment:' in block, text
