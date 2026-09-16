"""A payment an unpost left behind, which GnuCash then applied to another invoice, is no orphan.

`unpost-invoices INV-001` leaves its payment in the lot the invoice had, marked
as orphaned. GnuCash's own credit application (Process Payment, or an invoice's
automatic application) sees that lot as C001's credit and settles INV-002 with
it. The split it applies keeps its slots, the mark among them (CLAUDE.md
finding 10), but it now settles a posted invoice, so `find-orphan-payments` does
not list it.
"""

import gnucash.gnucash_core_c as gc
from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.utils import qof_instance
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import iter_splits
from services.gnucash_importer import _find_invoices_by_id, is_a_bank_paid_orphan
from tests.integration.test_find_orphan_payments import _import, _make_orphan_invoice

SECOND_INVOICE = 'tests/fixtures/a_second_invoice_for_the_customer_of_an_unposted_one.txt'


def test_it_is_not_listed(tmp_path):
    runner = CliRunner()
    book = _make_orphan_invoice(runner, tmp_path, 'q014_invoice_posted_paid',
                                'INV-001', 'unpost-invoices')
    posted = _import(runner, book, SECOND_INVOICE)
    assert posted.exit_code == 0, posted.output

    repo = GnuCashRepository(str(book))
    repo.open(SessionMode.NORMAL)
    try:
        second, = _find_invoices_by_id(repo.book, 'INV-002')
        second.AutoApplyPayments()
        repo.save()
        # Still marked, and now in a posted invoice's lot. Asked through
        # `qof_instance`, because `GetLot` hands back a raw pointer on some
        # builds and a wrapped lot on others (CLAUDE.md finding 17).
        applied = [split for split in iter_splits(repo.book)
                   if is_a_bank_paid_orphan(split) and split.GetLot() is not None
                   and gc.gncInvoiceGetInvoiceFromLot(qof_instance(split.GetLot()))]
        assert applied, 'GnuCash applied no marked split to INV-002'
    finally:
        repo.close()

    listed = runner.invoke(cli, ['find-orphan-payments', str(book)])

    assert listed.exit_code == 0, listed.output
    assert 'No orphan bank-side payment transactions found' in listed.output, listed.output
