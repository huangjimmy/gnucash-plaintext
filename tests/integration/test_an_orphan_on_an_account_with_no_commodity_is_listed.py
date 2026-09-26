"""A payment an unpost left behind, whose bank split is on an account with no commodity, is listed.

GnuCash keeps an account with no commodity through a save and a reload, split
and all (tests/research/whether_a_reload_keeps_a_security_currency_or_an_account_with_no_commodity_probe.py),
so a book another program wrote can hold a payment on one. `find-orphan-payments`
states each payment's figure in the commodity of the account it is on, and this
account has none, so the figure is stated in the transaction's currency.
"""

from datetime import datetime

import gnucash
from click.testing import CliRunner
from gnucash import Account, GncNumeric

from cli.main import cli
from infrastructure.gnucash.utils import find_account, get_account_full_name
from repositories.gnucash_repository import GnuCashRepository, SessionMode

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'


def _a_payment_on_an_account_with_no_commodity(tmp_path, unposted_by_gnucash=True):
    """INV-BARE, 100.00 CAD, paid, with the payment's bank split then moved to
    `Holding`, an account with no commodity. Unposted by GnuCash itself, or,
    where asked, by `unpost-invoices`, which marks the settlement it leaves."""
    from gnucash.gnucash_business import Customer, Entry, Invoice

    book_path = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book_path), ACCOUNTS])
    assert made.exit_code == 0, made.output

    repo = GnuCashRepository(str(book_path))
    repo.open(SessionMode.NORMAL)
    try:
        book = repo.book
        cad = book.get_table().lookup('CURRENCY', 'CAD')
        root = book.get_root_account()
        customer = Customer(book, 'C-BARE', cad, 'Acme')
        invoice = Invoice(book, 'INV-BARE', cad, customer)
        invoice.SetDateOpened(datetime(2026, 1, 5))
        line = Entry(book, invoice)
        line.SetDate(datetime(2026, 1, 5))
        line.SetDescription('Service')
        line.SetQuantity(GncNumeric(1, 1))
        line.SetInvAccount(find_account(root, 'Income:Sales'))
        line.SetInvPrice(GncNumeric(10000, 100))
        invoice.PostToAccount(find_account(root, 'Assets:Accounts Receivable'),
                              datetime(2026, 1, 5), datetime(2026, 1, 5), '', True, False)
        invoice.ApplyPayment(None, find_account(root, 'Assets:Bank'),
                             GncNumeric(10000, 100), GncNumeric(1, 1),
                             datetime(2026, 1, 10), 'Deposit', '')
        if unposted_by_gnucash:
            invoice.Unpost(False)

        holding = Account(book)
        holding.BeginEdit()
        holding.SetName('Holding')
        holding.SetType(gnucash.ACCT_TYPE_ASSET)
        root.append_child(holding)
        holding.CommitEdit()

        bank_split = next(split for split in find_account(root, 'Assets:Bank').GetSplitList()
                          if get_account_full_name(split.GetAccount()) == 'Assets:Bank')
        payment = bank_split.GetParent()
        payment.BeginEdit()
        bank_split.SetAccount(holding)
        payment.CommitEdit()
        repo.save()
    finally:
        repo.close()
    if not unposted_by_gnucash:
        unposted = CliRunner().invoke(cli, ['unpost-invoices', str(book_path), 'INV-BARE'])
        assert unposted.exit_code == 0, unposted.output
    return book_path


def test_it_is_listed_in_its_transactions_currency(tmp_path):
    book = _a_payment_on_an_account_with_no_commodity(tmp_path)

    listed = CliRunner().invoke(cli, ['find-orphan-payments', str(book)])

    assert listed.exit_code == 0, listed.output
    assert 'Traceback' not in listed.output, listed.output
    assert 'Found 1 orphan bank-side payment transaction' in listed.output, listed.output
    assert 'CAD 100.00' in listed.output, listed.output
    assert 'Holding' in listed.output, listed.output


def test_one_unpost_invoices_marked_is_stated_against_its_receivable(tmp_path):
    """The figure is the settlement's own, on the receivable. `Holding` holds no
    currency, so it is stated as the account the money came through, and the
    figure is stated against the receivable. Measured on 5.10."""
    book = _a_payment_on_an_account_with_no_commodity(tmp_path, unposted_by_gnucash=False)

    listed = CliRunner().invoke(cli, ['find-orphan-payments', str(book)])

    assert listed.exit_code == 0, listed.output
    assert 'Traceback' not in listed.output, listed.output
    assert 'Found 1 orphan bank-side payment transaction' in listed.output, listed.output
    assert 'Assets:Accounts Receivable  CAD 100.00' in listed.output, listed.output
    assert 'paid through: Holding' in listed.output, listed.output
