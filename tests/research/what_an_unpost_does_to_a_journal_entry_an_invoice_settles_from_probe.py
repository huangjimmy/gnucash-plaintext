"""What unposting an invoice does to a journal entry whose credit the invoice spent.

C001's credit is made by a journal entry with no bank split: the receivable
against itself, one split standing as C001's. INV-001 spends it with
`from_credit:`. `gncInvoiceUnpost` deletes every transaction in the invoice's
lot that `xaccTransGetTxnType` reads as a link (`TXN_TYPE_LINK`), and the
question is whether it reads this entry as one.

The probe goes straight to the engine, `Unpost(False)` on the record, past
`unpost-invoices`, which refuses this book. It prints each transaction's type
and splits before and after.

Measured 2026-09-15:

| GnuCash | the entry's type | after the unpost |
|---|---|---|
| 3.4, 3.8, 4.4, 4.8 | `\\x00` | kept; the credit is C001's again |
| 4.13, 5.5, 5.10, 5.13, 5.14, 5.15, 5.16 | `L` | deleted, and C001's credit with it |

From 4.13 the type is worked out from the splits: a split on a
receivable in a lot with an invoice or an owner, and no split off the
receivables and payables, is a link. Stating `txn_type: P` on the entry does
not survive a save there, and on 3.4 it does and the unpost lists the entry as
an orphaned bank payment of 0.00.

Taking the settlement off first with `unlink` or `unapply-payment` keeps the
entry on 5.10, but leaves its credit split in no lot, so the credit is no
longer listed as C001's.

Run from the repository root:

    docker run --rm -v "$PWD:/workspace" -w /workspace gnucash-dev:latest \\
        python3 tests/research/what_an_unpost_does_to_a_journal_entry_an_invoice_settles_from_probe.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.getcwd())

from click.testing import CliRunner  # noqa: E402
from gnucash import gnucash_core_c as gc  # noqa: E402

# The suite's `_patch_session_save`: every save deletes the backup a save in
# the same second would collide with.
import tests.conftest  # noqa: E402,F401
from cli.main import cli  # noqa: E402
from repositories.gnucash_repository import GnuCashRepository  # noqa: E402
from services.foreign_currency import iter_splits  # noqa: E402
from services.gnucash_importer import _find_invoices_by_id  # noqa: E402

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'
CREDIT = 'tests/fixtures/a_customers_credit_made_by_a_journal_entry.txt'
INVOICE = 'tests/fixtures/an_invoice_spending_the_journal_entrys_credit.txt'


def every_transaction(book, heading):
    """Each transaction in the book once, with its type and its splits."""
    print(f'-- {heading}')
    seen = set()
    for split in iter_splits(book):
        txn = split.GetParent()
        guid = txn.GetGUID().to_string()
        if guid in seen:
            continue
        seen.add(guid)
        print('  ', repr(txn.GetDescription()),
              'txn_type', repr(gc.xaccTransGetTxnType(txn.instance)))
        for each in txn.GetSplitList():
            print('     ', each.GetAccount().GetName(), each.GetAmount(),
                  'in a lot:', each.GetLot() is not None)


def main():
    path = os.path.join(tempfile.mkdtemp(), 'book.gnucash')
    for args in (['import', '--new', path, ACCOUNTS],
                 ['import', path, CREDIT, '--include-business-objects'],
                 ['import', path, INVOICE, '--include-business-objects']):
        made = CliRunner().invoke(cli, args)
        print('$', args[0], args[-2] if args[-1].startswith('--') else args[-1],
              '->', made.exit_code)

    repo = GnuCashRepository(path)
    repo.open()
    try:
        every_transaction(repo.book, 'before the unpost')
        _find_invoices_by_id(repo.book, 'INV-001')[0].Unpost(False)
        every_transaction(repo.book, 'after the unpost')
        repo.save()
    finally:
        repo.close()

    listed = CliRunner().invoke(cli, ['find-prepayments', path])
    print(listed.output)


if __name__ == '__main__':
    main()
