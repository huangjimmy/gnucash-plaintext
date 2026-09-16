"""A customer's credit on a receivable with no commodity is listed in its transaction's currency.

GnuCash keeps an account with no commodity through a save and a reload, split
and all (tests/research/whether_a_reload_keeps_a_security_currency_or_an_account_with_no_commodity_probe.py),
so a book another program wrote can hold a customer's credit on such a
receivable. `find-prepayments` states a credit in the commodity of the account
it is on. This one has none, so the credit is stated in the currency of the
transaction that paid it. Measured on 5.10: `CAD 50.00  in Receivable`.
"""

import ctypes
from datetime import datetime

import gnucash
from click.testing import CliRunner
from gnucash import Account, GncNumeric, Split, Transaction

from cli.main import cli
from infrastructure.gnucash.engine import load_gnc_engine
from infrastructure.gnucash.utils import qof_pointer
from repositories.gnucash_repository import GnuCashRepository, SessionMode


def _a_credit_on_a_receivable_with_no_commodity(tmp_path):
    """C001's 50.00 paid ahead into `Bank`, its receivable split on
    `Receivable`, which has no commodity, and in a lot attached to C001 as
    GnuCash's own payment leaves one."""
    from gnucash.gnucash_business import Customer

    lib = load_gnc_engine()
    path = tmp_path / 'book.gnucash'
    repo = GnuCashRepository(str(path))
    repo.open(SessionMode.NEW)
    try:
        book = repo.book
        cad = book.get_table().lookup('CURRENCY', 'CAD')
        root = book.get_root_account()

        def account(name, commodity, kind):
            made = Account(book)
            made.BeginEdit()
            made.SetName(name)
            made.SetType(kind)
            if commodity is not None:
                made.SetCommodity(commodity)
            root.append_child(made)
            made.CommitEdit()
            return made

        bank = account('Bank', cad, gnucash.ACCT_TYPE_BANK)
        receivable = account('Receivable', None, gnucash.ACCT_TYPE_RECEIVABLE)
        customer = Customer(book, 'C001', cad, 'Acme')

        transaction = Transaction(book)
        transaction.BeginEdit()
        transaction.SetCurrency(cad)
        transaction.SetDescription('Acme pays ahead')
        transaction.SetDatePostedSecs(datetime(2026, 1, 10, 12))
        credit = None
        for on, cents in ((bank, 5000), (receivable, -5000)):
            split = Split(book)
            split.SetParent(transaction)
            split.SetAccount(on)
            split.SetAmount(GncNumeric(cents, 100))
            split.SetValue(GncNumeric(cents, 100))
            if on is receivable:
                credit = split
        transaction.CommitEdit()

        receivable.BeginEdit()
        lot = lib.gnc_lot_new(int(book.instance))
        lib.xaccAccountInsertLot(int(receivable.instance), lot)
        lib.gnc_lot_add_split(lot, qof_pointer(credit))
        buffer = ctypes.create_string_buffer(256)
        owner = ctypes.cast(buffer, ctypes.c_void_p)
        lib.gncOwnerInitCustomer(owner, int(customer.instance))
        lib.gncOwnerAttachToLot(owner, lot)
        receivable.CommitEdit()
        repo.save()
    finally:
        repo.close()
    return path


def test_it_is_listed_in_its_transactions_currency(tmp_path):
    book = _a_credit_on_a_receivable_with_no_commodity(tmp_path)

    listed = CliRunner().invoke(cli, ['find-prepayments', str(book)])

    assert listed.exit_code == 0, listed.output
    assert 'Traceback' not in listed.output, listed.output
    assert 'Found 1 open pre-payment credit.' in listed.output, listed.output
    assert 'CAD 50.00  in Receivable' in listed.output, listed.output
