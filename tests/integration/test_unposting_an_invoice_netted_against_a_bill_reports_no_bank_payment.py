"""Unposting an invoice netted against a bill reports no bank-side payment.

GnuCash lets a person settle an invoice against a bill: a General Journal entry
moving 100.00 from the customer's receivable to the vendor's payable, typed as
a payment in the receivable register, with each split put in its record's lot
from View > Lots. The test builds that book with the same calls.

No split of that entry is off a receivable or a payable, so it holds no bank
split, and unposting the invoice orphans no money in a bank. Measured: on 3.8
and 4.4 the entry kept its payment type, and `unpost-invoices INV-NET` listed it
as an orphaned bank-side payment with a blank account and 0.00, said the money
still showed in the bank, and advised deleting it, while it still settled
BILL-NET. On 5.10 GnuCash reads the entry back as a link, deletes it with the
posting, and nothing was listed.
"""

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.engine import load_gnc_engine
from infrastructure.gnucash.utils import qof_pointer
from repositories.gnucash_repository import GnuCashRepository
from services.foreign_currency import iter_splits
from services.gnucash_importer import _find_bills_by_id, _find_invoices_by_id

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'
NETTED = 'tests/fixtures/an_invoice_and_a_bill_netted_by_a_payment_entry.txt'


def _done(*args):
    result = CliRunner().invoke(cli, [str(arg) for arg in args])
    assert result.exit_code == 0, result.output
    return result


def _a_book_with_the_entry_in_both_lots(tmp_path):
    book = tmp_path / 'book.gnucash'
    _done('import', '--new', book, ACCOUNTS)
    _done('import', book, NETTED, '--include-business-objects')

    lib = load_gnc_engine()
    repo = GnuCashRepository(str(book))
    repo.open()
    try:
        lots = {'Accounts Receivable': _find_invoices_by_id(repo.book, 'INV-NET')[0].GetPostedLot(),
                'Accounts Payable': _find_bills_by_id(repo.book, 'BILL-NET')[0].GetPostedLot()}
        entry = [split for split in iter_splits(repo.book)
                 if split.GetParent().GetDescription()
                 == 'Net what Acme owes against what is owed to Acme']
        assert len(entry) == 2, entry
        for split in entry:
            account = split.GetAccount()
            account.BeginEdit()
            lib.gnc_lot_add_split(qof_pointer(lots[account.GetName()]), int(split.instance))
            account.CommitEdit()
            assert split.GetLot() is not None
        repo.save()
    finally:
        repo.close()
    return book


def test_the_unpost_lists_no_bank_side_payment(tmp_path):
    book = _a_book_with_the_entry_in_both_lots(tmp_path)

    result = _done('unpost-invoices', book, 'INV-NET')

    assert 'INV-NET' in result.output and 'unposted' in result.output, result.output
    assert 'bank-side payment' not in result.output, result.output
