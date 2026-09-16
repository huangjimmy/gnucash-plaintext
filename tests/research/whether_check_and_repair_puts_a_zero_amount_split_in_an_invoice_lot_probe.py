"""Whether GnuCash's Check & Repair leaves a split with no amount in an invoice's lot.

The export, `print-invoice` and `print-bill` read where a payment's money came
from by the sign of the settling split, and skip that reading where the split's
amount is zero. Nothing this tool writes puts such a split in a lot: a payment
of nothing is refused on import. So the question is whether GnuCash does.

The candidate is the realized gain. A USD invoice on a USD receivable in a CAD
book, posted at one rate and paid at another, closes its lot in USD while its
CAD values differ. GnuCash's lot scrub books that difference as a gains split
on the lot's own account, with a value and no amount. Check & Repair runs the
orphan, imbalance and business scrubs always, and the lot scrub only where
`GNC_AUTO_SCRUB_LOTS` is set, so the probe asks after each in turn.

Measured on 5.10 and 3.4, 2026-09-15: neither adds a split. The lot keeps its
two, the posting at 100.00 USD valued 100.00 and the settlement at −100.00 USD
valued −140.00 CAD, after the scrubs Check & Repair always runs and after the
lot scrub as well. GnuCash does put a 0.00 split in a lot another way: see
`what_a_split_of_nothing_in_an_invoice_lot_does_to_an_export_probe.py`.

Run inside an image, from the repository root:

    docker run --rm -v "$PWD:/workspace" -w /workspace gnucash-dev:latest \\
        python3 tests/research/whether_check_and_repair_puts_a_zero_amount_split_in_an_invoice_lot_probe.py
"""
import ctypes
import os
import sys
import tempfile

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

FIXTURE = 'tests/fixtures/fx_invoice_usd_paid_from_cad_bank.txt'
RATES = 'tests/fixtures/fx_rates_usd_dated.yaml'

PROGRESS = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_double)
say_nothing = PROGRESS(lambda message, percent: None)


def receivable_splits(book, heading):
    print(f'-- {heading}')
    for split in iter_splits(book):
        account = split.GetAccount()
        if 'Receivable' not in account.GetName():
            continue
        lot = split.GetLot()
        print('  ', split.GetParent().GetDescription(),
              'amount', split.GetAmount(), 'value', split.GetValue(),
              'lot', None if lot is None else hex(qof_pointer(lot)))


def scrub(path, heading, calls):
    repo = GnuCashRepository(path)
    repo.open()
    try:
        root = ctypes.c_void_p(qof_pointer(repo.book.get_root_account()))
        for call in calls:
            call(root)
        repo.save()
        receivable_splits(repo.book, heading)
    finally:
        repo.close()


def main():
    lib = load_gnc_engine()
    for name in ('xaccAccountTreeScrubOrphans', 'xaccAccountTreeScrubImbalance',
                 'gncScrubBusinessAccountTree'):
        getattr(lib, name).argtypes = [ctypes.c_void_p, PROGRESS]
        getattr(lib, name).restype = None
    lib.xaccAccountTreeScrubLots.argtypes = [ctypes.c_void_p]
    lib.xaccAccountTreeScrubLots.restype = None

    path = os.path.join(tempfile.mkdtemp(), 'fx.gnucash')
    made = CliRunner().invoke(cli, ['import', '--new', path, FIXTURE,
                                    '--include-business-objects', '--fx-rates', RATES])
    print('import exit:', made.exit_code)

    repo = GnuCashRepository(path)
    repo.open()
    try:
        receivable_splits(repo.book, 'as imported')
    finally:
        repo.close()

    scrub(path, 'after the scrubs Check & Repair always runs', [
        lambda root: lib.xaccAccountTreeScrubOrphans(root, say_nothing),
        lambda root: lib.xaccAccountTreeScrubImbalance(root, say_nothing),
        lambda root: lib.gncScrubBusinessAccountTree(root, say_nothing),
    ])
    scrub(path, 'after the lot scrub as well', [
        lambda root: lib.xaccAccountTreeScrubLots(root),
        lambda root: lib.gncScrubBusinessAccountTree(root, say_nothing),
    ])

    out = os.path.join(os.path.dirname(path), 'out.txt')
    exported = CliRunner().invoke(cli, ['export', path, out, '--include-business-objects'])
    print('export exit:', exported.exit_code, exported.output)
    with open(out) as ledger:
        text = ledger.read()
    start = text.find('\tpayment:')
    print(text[start:start + 400])


if __name__ == '__main__':
    main()
