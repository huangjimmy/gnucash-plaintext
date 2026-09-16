"""What `export` writes for an invoice whose lot holds a split of nothing.

GnuCash's View → Lots offers every split in no lot, and "add split to lot"
calls `gnc_lot_add_split` inside the account's edit and runs no scrub
(`lv_add_split_to_lot_cb`, `gnucash/gnome/dialog-lot-viewer.c`). So a 0.00
receivable split can sit in a paid invoice's lot, until Check & Repair's
`gncScrubBusinessSplit` destroys it.

The probe builds that book the way the lot viewer does, then asks what the
export writes for INV-001, and whether the export reads back.

Measured on 5.10 and 3.4, 2026-09-15: the export writes a second `payment:`
block, `amount: 0.00` from `bank_account: "Assets:Bank"`, carrying the split's
`txn_guid:` and `txn_split_guid:`. Read back into its own book the invoice is
`unchanged`, and read into a new book it is created with no error.
`tests/integration/test_a_split_of_nothing_in_an_invoice_lot_is_exported_with_its_bank.py`
holds both.

Run inside an image, from the repository root:

    docker run --rm -v "$PWD:/workspace" -w /workspace gnucash-dev:latest \\
        python3 tests/research/what_a_split_of_nothing_in_an_invoice_lot_does_to_an_export_probe.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.getcwd())

from click.testing import CliRunner  # noqa: E402

# The suite's `_patch_session_save`: every save deletes the backup a save in
# the same second would collide with.
import tests.conftest  # noqa: E402,F401
from cli.main import cli  # noqa: E402
from infrastructure.gnucash.engine import load_gnc_engine  # noqa: E402
from infrastructure.gnucash.utils import qof_pointer  # noqa: E402
from repositories.gnucash_repository import GnuCashRepository  # noqa: E402
from services.foreign_currency import iter_splits  # noqa: E402
from services.gnucash_importer import _find_invoices_by_id  # noqa: E402
from tests.integration.test_find_orphan_payments import ACCOUNTS  # noqa: E402

INVOICE = 'tests/fixtures/q014_invoice_posted_paid.txt'
NOTHING = 'tests/fixtures/a_line_of_nothing_on_the_receivable.txt'


def main():
    lib = load_gnc_engine()
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, 'book.gnucash')
    source = os.path.join(folder, 'in.txt')
    with open(source, 'w') as ledger:
        ledger.write(ACCOUNTS + '\n' + Path(INVOICE).read_text() + '\n' +
                     Path(NOTHING).read_text())
    made = CliRunner().invoke(cli, ['import', '--new', path, source,
                                    '--include-business-objects'])
    print('import exit:', made.exit_code)

    repo = GnuCashRepository(path)
    repo.open()
    try:
        book = repo.book
        lot = _find_invoices_by_id(book, 'INV-001')[0].GetPostedLot()
        nothing = next(split for split in iter_splits(book)
                       if split.GetParent().GetDescription() == 'A line of nothing'
                       and split.GetAccount().GetName() == 'Accounts Receivable')
        account = nothing.GetAccount()
        account.BeginEdit()
        lib.gnc_lot_add_split(qof_pointer(lot), int(nothing.instance))
        account.CommitEdit()
        print('in the lot now:', nothing.GetLot() is not None)
        repo.save()
    finally:
        repo.close()

    out = os.path.join(folder, 'out.txt')
    exported = CliRunner().invoke(cli, ['export', path, out, '--include-business-objects'])
    print('export exit:', exported.exit_code)
    print(exported.output)
    if exported.exit_code == 0:
        text = Path(out).read_text()
        start = text.find('invoice "INV-001"')
        print(text[start:text.find('\n\n', start)])
        again = CliRunner().invoke(cli, ['import', path, out, '--include-business-objects'])
        print('the export read back into its own book, exit:', again.exit_code)
        print(again.output)
        fresh = os.path.join(folder, 'fresh.gnucash')
        rebuilt = CliRunner().invoke(cli, ['import', '--new', fresh, out,
                                           '--include-business-objects'])
        print('the export read into a new book, exit:', rebuilt.exit_code)
        print(rebuilt.output)


if __name__ == '__main__':
    main()
