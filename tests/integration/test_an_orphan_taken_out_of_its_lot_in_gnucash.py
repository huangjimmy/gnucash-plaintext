"""A settlement an unpost orphaned, then taken out of its lot in GnuCash.

`unpost-invoices` leaves the payment's receivable split in the lot the invoice
had, and marks it as orphaned. That lot is what still says whose the money is.
GnuCash's lot viewer can take the split out of it, and put it in a new lot,
which has no owner. After either, nothing in the book says whose the money
is: the export writes the payment with no `owner:` line, and
`find-orphan-payments` still runs to the end.
"""

import ctypes

import pytest
from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.engine import load_gnc_engine
from infrastructure.gnucash.utils import qof_pointer
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import iter_splits
from services.gnucash_importer import is_a_bank_paid_orphan
from tests.integration.test_find_orphan_payments import _make_orphan_invoice


def _take_the_orphan_out_of_its_lot(book, into_a_new_lot):
    """What GnuCash's lot viewer does: the split leaves its lot, and, where
    asked, goes into a new lot on the same account."""
    repo = GnuCashRepository(str(book))
    repo.open(SessionMode.NORMAL)
    try:
        lib = load_gnc_engine()
        lib.gnc_lot_remove_split.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.gnc_lot_remove_split.restype = None
        lib.gnc_lot_new.argtypes = [ctypes.c_void_p]
        lib.gnc_lot_new.restype = ctypes.c_void_p
        lib.xaccAccountInsertLot.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.xaccAccountInsertLot.restype = None
        lib.gnc_lot_add_split.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.gnc_lot_add_split.restype = None

        orphan, = [split for split in iter_splits(repo.book)
                   if is_a_bank_paid_orphan(split)]
        transaction = orphan.GetParent()
        transaction.BeginEdit()
        lib.gnc_lot_remove_split(qof_pointer(orphan.GetLot()), int(orphan.instance))
        if into_a_new_lot:
            lot = lib.gnc_lot_new(int(repo.book.instance))
            lib.xaccAccountInsertLot(int(orphan.GetAccount().instance), lot)
            lib.gnc_lot_add_split(lot, int(orphan.instance))
        transaction.CommitEdit()
        repo.save()
    finally:
        repo.close()


def _the_orphans_lot_has_an_owner(book):
    """None where the orphan is in no lot."""
    lib = load_gnc_engine()
    repo = GnuCashRepository(str(book))
    repo.open(SessionMode.READ_ONLY)
    try:
        orphan, = [split for split in iter_splits(repo.book)
                   if is_a_bank_paid_orphan(split)]
        lot = orphan.GetLot()
        if lot is None:
            return None
        owner = ctypes.create_string_buffer(256)
        return lib.gncOwnerGetOwnerFromLot(
            ctypes.c_void_p(qof_pointer(lot)),
            ctypes.cast(owner, ctypes.c_void_p)) == 1
    finally:
        repo.close()


@pytest.mark.parametrize('into_a_new_lot', [False, True],
                         ids=['in-no-lot', 'in-a-lot-with-no-owner'])
def test_the_export_writes_no_owner_for_it(tmp_path, into_a_new_lot):
    runner = CliRunner()
    book = _make_orphan_invoice(runner, tmp_path, 'q014_invoice_posted_paid',
                                'INV-001', 'unpost-invoices')
    _take_the_orphan_out_of_its_lot(book, into_a_new_lot)
    assert _the_orphans_lot_has_an_owner(book) is (False if into_a_new_lot else None)
    out = tmp_path / 'out.txt'

    exported = runner.invoke(cli, ['export', str(book), str(out)])
    listed = runner.invoke(cli, ['find-orphan-payments', str(book)])

    assert exported.exit_code == 0, exported.output
    assert 'owner:' not in out.read_text(), out.read_text()
    assert listed.exit_code == 0, listed.output
