"""A divided credit's loose half is its owner's, whatever lot the settlement beside it is in.

C-JOB's job invoice INV-JOB is paid 150.00 against 100.00, and GnuCash puts the
50.00 left in a credit lot of C-JOB's. C-JOB's invoice INV-C2 spends it with
`from_credit:`, which divides it: 30.00 settles INV-C2 and 20.00 stays C-JOB's.
`unpost-invoices INV-C2`, then View → Lots, leave the 30.00 in no lot.

The one payment then holds three receivable splits: INV-JOB's settlement, the
loose 30.00 and the 20.00 credit. The credit gives the loose half its owner.
The settlement says nothing either way, in each lot GnuCash lets it be in:
INV-JOB's own lot; the lot `unpost-invoices INV-JOB` leaves, whose owner is the
job, which is neither a customer nor a vendor; and a lot with no owner, which
View → Lots makes. Measured on 5.10.

So C-OTHER's invoice claiming the loose 30.00 is refused as C-JOB's money in
all three.
"""

import ctypes
from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.engine import load_gnc_engine
from infrastructure.gnucash.utils import get_account_full_name, qof_pointer
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import iter_splits
from tests.integration.test_a_jobs_orphaned_payment_keeps_its_customer import (
    _a_jobs_invoice_paid_and_unposted,
)

FIXTURES = Path('tests/fixtures')


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _done(*args):
    result = _run(*args)
    assert result.exit_code == 0, result.output


def _filled(tmp_path, name, txn_guid, split_guid):
    path = tmp_path / name
    path.write_text((FIXTURES / name).read_text()
                    .replace('TXN_GUID', txn_guid).replace('SPLIT_GUID', split_guid))
    return path


def _the_split(repo, amount):
    return next(split for split in iter_splits(repo.book)
                if get_account_full_name(split.GetAccount()) == 'Receivable'
                and str(split.GetAmount()) == amount)


def _the_payment_split(book, amount):
    """(transaction guid, split guid, where it is) of the payment's receivable
    split carrying `amount`."""
    lib = load_gnc_engine()
    repo = GnuCashRepository(str(book))
    repo.open(SessionMode.READ_ONLY)
    try:
        split = _the_split(repo, amount)
        lot = split.GetLot()
        if lot is None:
            where = 'no lot'
        elif lib.gncInvoiceGetInvoiceFromLot(qof_pointer(lot)):
            where = 'an invoice lot'
        else:
            buffer = ctypes.create_string_buffer(256)
            owner = ctypes.cast(buffer, ctypes.c_void_p)
            found = lib.gncOwnerGetOwnerFromLot(ctypes.c_void_p(qof_pointer(lot)), owner)
            where = (f'a lot of owner type {lib.gncOwnerGetType(owner)}' if found == 1
                     else 'a lot with no owner')
        return (split.GetParent().GetGUID().to_string(),
                split.GetGUID().to_string(), where)
    finally:
        repo.close()


def _out_of_its_lot(book, amount, into_a_new_lot):
    """The payment's receivable split carrying `amount` taken out of its lot,
    and where asked put in a new lot, as View → Lots does it."""
    lib = load_gnc_engine()
    lib.gnc_lot_remove_split.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.gnc_lot_remove_split.restype = None
    repo = GnuCashRepository(str(book))
    repo.open()
    try:
        split = _the_split(repo, amount)
        account = split.GetAccount()
        account.BeginEdit()
        lib.gnc_lot_remove_split(qof_pointer(split.GetLot()), qof_pointer(split))
        if into_a_new_lot:
            lot = lib.gnc_lot_new(int(repo.book.instance))
            lib.xaccAccountInsertLot(int(account.instance), lot)
            lib.gnc_lot_add_split(lot, qof_pointer(split))
        account.CommitEdit()
        repo.save()
    finally:
        repo.close()


@pytest.mark.parametrize('settlement, where', [
    ('in its invoice lot', 'an invoice lot'),
    ("in the job's lot", 'a lot of owner type 3'),
    ('in a lot with no owner', 'a lot with no owner'),
], ids=['in-its-invoice-lot', 'in-the-jobs-lot', 'in-a-lot-with-no-owner'])
def test_another_customers_claim_on_it_is_refused(tmp_path, settlement, where):
    book = _a_jobs_invoice_paid_and_unposted(tmp_path, paid_cents=15000, unpost=False)
    txn_guid, credit, _ = _the_payment_split(book, '-5000/100')
    _done('import', book, _filled(tmp_path, 'a_job_customers_invoice_dividing_its_credit.txt',
                                  txn_guid, credit), '--include-business-objects')
    _done('unpost-invoices', book, 'INV-C2')
    _out_of_its_lot(book, '-3000/100', into_a_new_lot=False)
    if settlement != 'in its invoice lot':
        _done('unpost-invoices', book, 'INV-JOB')
    if settlement == 'in a lot with no owner':
        _out_of_its_lot(book, '-10000/100', into_a_new_lot=True)
    assert _the_payment_split(book, '-10000/100')[2] == where
    _, loose, loose_where = _the_payment_split(book, '-3000/100')
    assert loose_where == 'no lot'

    claim = _run('import', book,
                 _filled(tmp_path, 'another_customer_claims_the_loose_half_of_a_divided_credit.txt',
                         txn_guid, loose),
                 '--include-business-objects')

    assert claim.exit_code != 0, claim.output
    assert "customer C-JOB's money" in claim.output, claim.output
