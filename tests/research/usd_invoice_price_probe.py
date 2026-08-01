"""Probe: how does GnuCash value a foreign-currency invoice whose entry income
account is in another currency, and what API attaches the rate?

Run:  ./scripts/run.sh python3 tests/research/usd_invoice_price_probe.py

Questions:
  1. Which price-related functions exist on the SWIG Invoice class and in
     libgnc-engine.so?
  2. Posting a USD invoice (entry account = CAD income) to a USD A/R with NO
     rate attached — what does the engine write?
  3. Same, with a rate attached before posting.
"""

import ctypes
import os
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from gnucash import Account, GncNumeric, GncPrice, Session  # noqa: E402
from gnucash.gnucash_business import Customer, Entry, Invoice  # noqa: E402
from gnucash.gnucash_core_c import (  # noqa: E402
    ACCT_TYPE_BANK,
    ACCT_TYPE_INCOME,
    ACCT_TYPE_RECEIVABLE,
)

from infrastructure.gnucash.engine import load_gnc_engine  # noqa: E402


def hr(title):
    print()
    print('=' * 70)
    print(title)
    print('=' * 70)


def dump_price_api():
    hr('1. price-related API surface')
    print('SWIG Invoice attrs matching "price"/"Price":')
    for name in sorted(dir(Invoice)):
        if 'rice' in name:
            print('   Invoice.' + name)
    lib = load_gnc_engine()
    for fn in ('gncInvoiceSetPrice', 'gncInvoiceGetPrice',
               'gncInvoiceSetToChargeAmount', 'gncInvoicePostToAccount'):
        print(f'   libgnc-engine {fn}: {hasattr(lib, fn)}')


def build_book(path):
    session = Session(f'xml://{path}', is_new=True)
    book = session.book
    root = book.get_root_account()
    table = book.get_table()
    cad = table.lookup('CURRENCY', 'CAD')
    usd = table.lookup('CURRENCY', 'USD')

    def mk(name, parent, acct_type, commodity):
        a = Account(book)
        parent.append_child(a)
        a.SetName(name)
        a.SetType(acct_type)
        a.SetCommodity(commodity)
        return a

    assets = mk('Assets', root, ACCT_TYPE_BANK, cad)
    income = mk('Income', root, ACCT_TYPE_INCOME, cad)
    ar_usd = mk('AR-USD', assets, ACCT_TYPE_RECEIVABLE, usd)
    sales_cad = mk('Sales', income, ACCT_TYPE_INCOME, cad)

    cust = Customer(book, 'C-USD', usd)
    cust.SetName('US Customer')
    return session, book, ar_usd, sales_cad, usd, cust


def make_price(book, commodity, currency, num, denom):
    """A GNCPrice saying: 1 unit of `commodity` = num/denom units of `currency`."""
    price = GncPrice(book)
    price.set_commodity(commodity)
    price.set_currency(currency)
    price.set_value(GncNumeric(num, denom))
    try:
        price.set_time64(datetime(2026, 1, 5))
    except AttributeError:
        price.set_time(datetime(2026, 1, 5))
    price.set_source_string('user:xfer-dialog')
    price.set_typestr('last')
    return price


def post_invoice(book, inv_id, ar_usd, sales_cad, usd, cust, price=None):
    inv = Invoice(book, inv_id, usd, cust)
    inv.BeginEdit()
    inv.SetDateOpened(datetime(2026, 1, 5))
    entry = Entry(book)
    entry.BeginEdit()
    entry.SetDate(datetime(2026, 1, 5))
    entry.SetDescription('Consulting')
    entry.SetInvAccount(sales_cad)
    entry.SetQuantity(GncNumeric(1, 1))
    entry.SetInvPrice(GncNumeric(100, 1))
    entry.SetInvTaxable(False)
    inv.AddEntry(entry)
    entry.CommitEdit()
    if price is not None:
        inv.AddPrice(price)
        raw = price.get_value()
        print(f'   AddPrice: value={raw.num}/{raw.denom}')
    inv.PostToAccount(ar_usd, datetime(2026, 1, 5), datetime(2026, 2, 5),
                      f'memo {inv_id}', True, False)
    inv.CommitEdit()
    return inv


def dump_posting(inv, label):
    print(f'\n--- {label} ---')
    tx = inv.GetPostedTxn()
    if tx is None:
        print('   NO POSTING TRANSACTION (engine refused)')
        return
    print(f'   tx currency: {tx.GetCurrency().get_mnemonic()}')
    for sp in tx.GetSplitList():
        acct = sp.GetAccount()
        print(f'   {acct.GetName():12s} '
              f'amount={sp.GetAmount().to_double():10.4f} '
              f'{acct.GetCommodity().get_mnemonic()} '
              f'value={sp.GetValue().to_double():10.4f} '
              f'price={sp.GetSharePrice().to_double():.6f}')
    lot = inv.GetPostedLot()
    if lot is not None:
        print(f'   lot splits={len(lot.get_split_list())} '
              f'closed={lot.is_closed()}')


def main():
    dump_price_api()

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, 'probe.gnucash')
        session, book, ar_usd, sales_cad, usd, cust = build_book(path)

        hr('2. USD invoice, CAD income account, NO rate attached')
        inv1 = post_invoice(book, 'INV-NO-RATE', ar_usd, sales_cad, usd, cust)
        dump_posting(inv1, 'INV-NO-RATE')

        cad = book.get_table().lookup('CURRENCY', 'CAD')

        hr('3. price on the ACCOUNT commodity (CAD), 1 CAD = 100/140 USD')
        inv2 = post_invoice(book, 'INV-PRICE-CAD', ar_usd, sales_cad, usd, cust,
                            price=make_price(book, cad, usd, 100, 140))
        dump_posting(inv2, 'INV-PRICE-CAD')

        hr('4. price on the INVOICE commodity (USD), 1 USD = 140/100 CAD')
        inv3 = post_invoice(book, 'INV-PRICE-USD', ar_usd, sales_cad, usd, cust,
                            price=make_price(book, usd, cad, 140, 100))
        dump_posting(inv3, 'INV-PRICE-USD')

        session.end()
        session.destroy()


if __name__ == '__main__':
    main()
