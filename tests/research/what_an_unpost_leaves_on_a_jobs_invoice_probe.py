"""What an unpost leaves behind on an invoice owned by a job, not by a customer.

GnuCash's Business menu makes jobs, and an invoice can be for a job. This tool
has no word for a job, so two questions decide whether its orphan listings and
its export can meet one:

* Does `unpost-invoices` reach such an invoice at all? It finds invoices by
  owner type, and a job's invoice may report its own type or its customer's.
* If it does, whose is the lot the unpost leaves the payment in? GnuCash puts
  the invoice's owner back on that lot, which may be the job.

Run inside an image, from the repository root:

    docker run --rm -v "$PWD:/workspace" -w /workspace gnucash-dev:latest \\
        python3 tests/research/what_an_unpost_leaves_on_a_jobs_invoice_probe.py
"""
import ctypes
import os
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.getcwd())

import gnucash  # noqa: E402
from gnucash import Account, GncNumeric  # noqa: E402
from gnucash.gnucash_business import Customer, Entry, Invoice, Job  # noqa: E402

from infrastructure.gnucash.engine import load_gnc_engine  # noqa: E402
from infrastructure.gnucash.utils import qof_pointer  # noqa: E402
from repositories.gnucash_repository import GnuCashRepository, SessionMode  # noqa: E402
from services.foreign_currency import iter_splits  # noqa: E402
from services.gnucash_importer import (  # noqa: E402
    _find_invoices_by_id,
    is_a_bank_paid_orphan,
)
from use_cases.unpost_business_objects import UnpostInvoicesUseCase  # noqa: E402


def lot_owner(lib, lot):
    buffer = ctypes.create_string_buffer(256)
    owner = ctypes.cast(buffer, ctypes.c_void_p)
    if lib.gncOwnerGetOwnerFromLot(ctypes.c_void_p(qof_pointer(lot)), owner) != 1:
        return 'no owner'
    return (lib.gncOwnerGetType(owner),
            lib.gncOwnerGetID(owner).decode('utf-8', errors='replace'))


def main():
    lib = load_gnc_engine()
    path = os.path.join(tempfile.mkdtemp(), 'job.gnucash')
    repo = GnuCashRepository(path)
    repo.open(SessionMode.NEW)
    try:
        book = repo.book
        cad = book.get_table().lookup('CURRENCY', 'CAD')
        root = book.get_root_account()

        def account(name, kind):
            made = Account(book)
            made.BeginEdit()
            made.SetName(name)
            made.SetType(kind)
            made.SetCommodity(cad)
            root.append_child(made)
            made.CommitEdit()
            return made

        receivable = account('Receivable', gnucash.ACCT_TYPE_RECEIVABLE)
        bank = account('Bank', gnucash.ACCT_TYPE_BANK)
        income = account('Income', gnucash.ACCT_TYPE_INCOME)

        customer = Customer(book, 'C-JOB', cad, 'Customer With A Job')
        job = Job(book, 'J-1', customer, 'A job')
        invoice = Invoice(book, 'INV-JOB', cad, job)
        invoice.SetDateOpened(datetime(2026, 1, 5))
        line = Entry(book, invoice)
        line.SetDate(datetime(2026, 1, 5))
        line.SetDescription('Work')
        line.SetQuantity(GncNumeric(1, 1))
        line.SetInvAccount(income)
        line.SetInvPrice(GncNumeric(10000, 100))
        invoice.PostToAccount(receivable, datetime(2026, 1, 5), datetime(2026, 1, 5),
                              '', True, False)
        invoice.ApplyPayment(None, bank, GncNumeric(10000, 100), GncNumeric(1, 1),
                             datetime(2026, 1, 10), 'Paid', '')
        repo.save()

        print('invoice GetOwnerType:', invoice.GetOwnerType())
        print('posted lot owner before unpost:', lot_owner(lib, invoice.GetPostedLot()))
        print('found by _find_invoices_by_id:', len(_find_invoices_by_id(book, 'INV-JOB')))

        results = UnpostInvoicesUseCase(book).execute(['INV-JOB'])
        print('unpost-invoices status:', [r.status for r in results])
        repo.save()

        for split in iter_splits(book):
            if split.GetAccount().GetName() != 'Receivable':
                continue
            lot = split.GetLot()
            print('receivable split', split.GetAmount(),
                  'marked bank-paid orphan:', is_a_bank_paid_orphan(split),
                  'lot owner:', None if lot is None else lot_owner(lib, lot))
    finally:
        repo.close()

    # And what the two commands that read such a settlement say about it.
    from click.testing import CliRunner

    from cli.main import cli

    out = os.path.join(os.path.dirname(path), 'out.txt')
    exported = CliRunner().invoke(cli, ['export', path, out])
    print('export exit:', exported.exit_code)
    with open(out) as ledger:
        for text in ledger.read().split('\n\n'):
            if 'Receivable' in text and '* "' in text:
                print(text)
    listed = CliRunner().invoke(cli, ['find-orphan-payments', path])
    print('find-orphan-payments exit:', listed.exit_code)
    print(listed.output)


if __name__ == '__main__':
    main()
