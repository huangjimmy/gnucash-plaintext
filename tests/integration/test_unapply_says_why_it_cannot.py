"""`unapply-payment` names the reason when there is nothing it can peel.

The command moves money: a payment's receivable split leaves the invoice's lot
and lands on an account the reader named. So when it does not run, the reader
has to be able to tell which of several quite different situations they are in
— the invoice was never posted, it was posted and never paid, the `--txn` guid
names a transaction that is not one of its payments, or the id names more than
one record. Each is a different next step, and "unapply failed" is none of
them.

Every one of these leaves the book alone; `test_unapply_payment.py` holds the
cases where it does peel something.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli
from tests.integration.test_delete_invoice_bill import _create_duplicate_invoice

LEDGER = str(Path('tests/fixtures/invoices_in_each_state_to_unapply.txt'))
TO = 'Liabilities:Owed Back'
A_GUID_NAMING_NOTHING = 'deadbeefdeadbeefdeadbeefdeadbeef'


@pytest.fixture
def book(tmp_path):
    path = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(cli, [
        'import', '--new', str(path), LEDGER, '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return path


def _unapply(book, *args):
    return CliRunner().invoke(
        cli, ['unapply-payment', str(book), *args, '--to', TO])


class TestAnInvoiceNeverPosted:
    def test_it_is_refused(self, book):
        result = _unapply(book, 'INV-DRAFT')

        assert result.exit_code != 0, result.output

    def test_it_says_the_invoice_is_not_posted(self, book):
        """Not "no payments" — the next step is to post it, not to find one."""
        result = _unapply(book, 'INV-DRAFT')

        assert 'not posted' in result.output, result.output
        assert 'INV-DRAFT' in result.output, result.output


class TestAnInvoicePostedAndUnpaid:
    def test_it_is_refused(self, book):
        result = _unapply(book, 'INV-UNPAID')

        assert result.exit_code != 0, result.output

    def test_it_says_there_is_no_payment_rather_than_no_invoice(self, book):
        """The invoice is there and posted; what is missing is a payment."""
        result = _unapply(book, 'INV-UNPAID')

        assert 'no payments to unapply' in result.output, result.output
        assert 'INV-UNPAID' in result.output, result.output


class TestATxnGuidThatIsNotOneOfItsPayments:
    def test_it_is_refused(self, book):
        result = _unapply(book, 'INV-PAID', '--txn', A_GUID_NAMING_NOTHING)

        assert result.exit_code != 0, result.output

    def test_the_guid_that_did_not_match_is_named(self, book):
        result = _unapply(book, 'INV-PAID', '--txn', A_GUID_NAMING_NOTHING)

        assert A_GUID_NAMING_NOTHING in result.output, result.output

    def test_the_payments_it_does_have_are_named_too(self, book):
        """So the reader can pick one instead of going to look for the list."""
        result = _unapply(book, 'INV-PAID', '--txn', A_GUID_NAMING_NOTHING)

        assert 'payments: ' in result.output, result.output

    def test_the_payment_it_does_have_is_left_applied(self, book):
        """A refusal peels nothing, including the payments it did not name.

        Shown by peeling it afterwards: unapplying succeeds only against a
        payment that is still on the lot, so a run that answers `unapplied`
        here is the refusal having changed nothing.
        """
        _unapply(book, 'INV-PAID', '--txn', A_GUID_NAMING_NOTHING)

        after = _unapply(book, 'INV-PAID')

        assert after.exit_code == 0, after.output
        assert 'unapplied' in after.output, after.output


class TestAnIdTwoRecordsShare:
    @pytest.fixture
    def shared(self, book):
        _create_duplicate_invoice(book, dup_id='INV-PAID',
                                  customer_id='C-UNAPPLY', currency_code='CAD')
        return book

    def test_it_is_refused(self, shared):
        result = _unapply(shared, 'INV-PAID')

        assert result.exit_code != 0, result.output

    def test_it_says_to_name_the_guid_instead(self, shared):
        result = _unapply(shared, 'INV-PAID')

        assert 'matches multiple records' in result.output, result.output
        assert '--by-guid' in result.output, result.output
