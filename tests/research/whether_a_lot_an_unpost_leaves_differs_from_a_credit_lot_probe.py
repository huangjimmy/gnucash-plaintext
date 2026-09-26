"""Whether a lot an unpost leaves behind differs from a lot holding an owner's credit.

CLAUDE.md finding 10 records that the two agree on every fact it asked about:
both stay in the account's lot list, neither is linked to an invoice, and both
carry the owner. This asks two more facts of each, after a save and a reload:

- does the lot hold a `gncInvoice` slot, which posting writes and unposting
  empties rather than removes (`qof_instance_has_slot`);
- what is the lot's title, which posting sets to the invoice's type and id.

Three books, each built through GnuCash's own calls:

  overpaid   INV-OVER for 100.00 paid 150.00, so GnuCash settles it and puts
             50.00 in a credit lot
  unposted   INV-GUI for 100.00 paid 100.00, then unposted with `Unpost(False)`
  two        INV-A and INV-B for 100.00 each; INV-A paid 200.00, the 100.00 over
             applied to INV-B by `AutoApplyPayments`, then INV-B unposted

Run on one build:

    docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \\
        -v "$PWD":/workspace -w /workspace gnucash-dev:<tag> bash -c \\
        'python3 -m pip install -e ".[dev]" --user -q --break-system-packages \\
         || python3 -m pip install -e ".[dev]" --user -q; \\
         python3 tests/research/whether_a_lot_an_unpost_leaves_differs_from_a_credit_lot_probe.py'

Each line prints a payment split on the receivable: its amount, whether its lot is
linked to an invoice now, whether the lot holds a `gncInvoice` slot, and the
lot's title.
"""

import ctypes
import tempfile
from datetime import datetime
from pathlib import Path

from click.testing import CliRunner

# The suite's `_patch_session_save`: every save deletes the backup a save in
# the same second would collide with.
import tests.conftest  # noqa: F401
from cli.main import cli
from infrastructure.gnucash.engine import load_gnc_engine
from infrastructure.gnucash.utils import find_account, qof_pointer
from repositories.gnucash_repository import GnuCashRepository, SessionMode

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'


def _build(path, scenario):
    from gnucash import GncNumeric
    from gnucash.gnucash_business import Customer, Entry, Invoice

    result = CliRunner().invoke(cli, ['import', '--new', path, ACCOUNTS])
    assert result.exit_code == 0, result.output
    repo = GnuCashRepository(path)
    repo.open(SessionMode.NORMAL)
    try:
        book = repo.book
        cad = book.get_table().lookup('CURRENCY', 'CAD')
        root = book.get_root_account()
        customer = Customer(book, 'C001', cad, 'Acme')

        def invoice(number):
            record = Invoice(book, number, cad, customer)
            record.SetDateOpened(datetime(2026, 1, 5))
            line = Entry(book, record)
            line.SetDate(datetime(2026, 1, 5))
            line.SetDescription('Service')
            line.SetQuantity(GncNumeric(1, 1))
            line.SetInvAccount(find_account(root, 'Income:Sales'))
            line.SetInvPrice(GncNumeric(10000, 100))
            record.PostToAccount(find_account(root, 'Assets:Accounts Receivable'),
                                 datetime(2026, 1, 5), datetime(2026, 1, 5), '', True, False)
            return record

        def pay(record, cents):
            record.ApplyPayment(None, find_account(root, 'Assets:Bank'), GncNumeric(cents, 100),
                                GncNumeric(1, 1), datetime(2026, 1, 10), '', '')

        if scenario == 'overpaid':
            pay(invoice('INV-OVER'), 15000)
        elif scenario == 'unposted':
            record = invoice('INV-GUI')
            pay(record, 10000)
            record.Unpost(False)
        else:
            first, second = invoice('INV-A'), invoice('INV-B')
            pay(first, 20000)
            second.AutoApplyPayments()
            second.Unpost(False)
        repo.save()
    finally:
        repo.close()


def _facts(path):
    lib = load_gnc_engine()
    for name, restype, argtypes in (
            ('xaccSplitGetLot', ctypes.c_void_p, [ctypes.c_void_p]),
            ('gnc_lot_get_title', ctypes.c_char_p, [ctypes.c_void_p]),
            ('gncInvoiceGetInvoiceFromLot', ctypes.c_void_p, [ctypes.c_void_p]),
            ('qof_instance_has_slot', ctypes.c_bool, [ctypes.c_void_p, ctypes.c_char_p])):
        function = getattr(lib, name, None)
        if function is None:
            print(f'  {name} is not in this build')
            continue
        function.restype = restype
        function.argtypes = argtypes
    repo = GnuCashRepository(path)
    repo.open(SessionMode.READ_ONLY)
    try:
        receivable = find_account(repo.book.get_root_account(), 'Assets:Accounts Receivable')
        for split in receivable.GetSplitList():
            if split.GetParent().GetTxnType() != 'P':
                continue
            lot = lib.xaccSplitGetLot(qof_pointer(split))
            if not lot:
                print(f'  {split.GetAmount().to_string():>12}  no lot')
                continue
            print(f'  {split.GetAmount().to_string():>12}'
                  f'  linked to an invoice: {bool(lib.gncInvoiceGetInvoiceFromLot(lot))!s:5}'
                  f'  gncInvoice slot: {lib.qof_instance_has_slot(lot, b"gncInvoice")!s:5}'
                  f'  title: {lib.gnc_lot_get_title(lot)!r}')
    finally:
        repo.close()


with tempfile.TemporaryDirectory() as directory:
    for scenario in ('overpaid', 'unposted', 'two'):
        path = str(Path(directory) / f'{scenario}.gnucash')
        _build(path, scenario)
        print(scenario)
        _facts(path)
