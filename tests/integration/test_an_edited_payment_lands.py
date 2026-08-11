"""Correcting a payment in the ledger and importing again must land.

A payment block says when the money moved, how much, from which account, what
the memo on it reads and what number the cheque carried. The comparison that
answers "does the book already say this?" reads each of those, and a field
left out is one a person can correct in the ledger, import, and see reported
`unchanged` — the payment in the book keeps the old figure, and nothing says
so.

The amount is the one that shows what that costs: a payment corrected from
100.00 to 60.00 leaves the invoice part paid, and a book that ignored the
correction says it is settled.
"""

from fractions import Fraction
from pathlib import Path

import pytest
from click.testing import CliRunner
from gnucash import Query
from gnucash import gnucash_business as gb

from cli.main import cli
from infrastructure.gnucash.utils import numeric_to_fraction
from repositories.gnucash_repository import GnuCashRepository, SessionMode

FIXTURES = Path('tests/fixtures')
BEFORE = str(FIXTURES / 'invoice_payments_before_an_edit.txt')
AFTER = str(FIXTURES / 'invoice_payments_after_an_edit.txt')


def _payment_of(book, invoice_id):
    """The bank side of the payment that settled one invoice."""
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('gncInvoice')
        query.set_book(repo.book)
        found = None
        for raw in query.run():
            invoice = gb.Invoice(instance=raw)
            if invoice.GetID() != invoice_id:
                continue
            lot = invoice.GetPostedLot()
            posting = invoice.GetPostedTxn()
            for split_raw in lot.get_split_list():
                from gnucash import Split
                split = Split(instance=split_raw)
                transaction = split.GetParent()
                if transaction.GetGUID().to_string() == \
                        posting.GetGUID().to_string():
                    continue
                bank = next(
                    s for s in transaction.GetSplitList()
                    if s.GetAccount().get_full_name() == 'Assets.Bank')
                found = {
                    'date': transaction.GetDate().strftime('%Y-%m-%d'),
                    'amount': abs(numeric_to_fraction(bank.GetAmount())),
                    'memo': bank.GetMemo() or '',
                    'num': transaction.GetNum() or '',
                }
        query.destroy()
        assert found is not None, f'no payment on {invoice_id}'
        return found
    finally:
        repo.close()


@pytest.fixture
def book(tmp_path):
    path = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(cli, [
        'import', '--new', str(path), BEFORE, '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return path


@pytest.fixture
def edited(book):
    result = CliRunner().invoke(cli, [
        'import', str(book), AFTER, '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return book


class TestEachFieldOfAPayment:
    def test_the_date_is_the_edited_one(self, edited):
        assert _payment_of(edited, 'PAY-DATE')['date'] == '2026-01-20', \
            _payment_of(edited, 'PAY-DATE')

    def test_the_amount_is_the_edited_one(self, edited):
        """Which leaves the invoice part paid rather than settled."""
        assert _payment_of(edited, 'PAY-AMOUNT')['amount'] == Fraction(60), \
            _payment_of(edited, 'PAY-AMOUNT')

    def test_the_memo_is_the_edited_one(self, edited):
        assert _payment_of(edited, 'PAY-MEMO')['memo'] == 'Settled by cheque', \
            _payment_of(edited, 'PAY-MEMO')

    def test_the_number_is_the_edited_one(self, edited):
        assert _payment_of(edited, 'PAY-NUM')['num'] == 'CHQ-7', \
            _payment_of(edited, 'PAY-NUM')


class TestWhatIsNotEdited:
    def test_the_other_fields_of_that_payment_stay(self, edited):
        payment = _payment_of(edited, 'PAY-NUM')

        assert payment['date'] == '2026-01-15', payment
        assert payment['amount'] == Fraction(100), payment

    def test_importing_the_same_file_twice_changes_nothing(self, book):
        again = CliRunner().invoke(cli, [
            'import', str(book), BEFORE, '--include-business-objects'])

        assert again.exit_code == 0, again.output
        assert 'unchanged' in again.output, again.output
