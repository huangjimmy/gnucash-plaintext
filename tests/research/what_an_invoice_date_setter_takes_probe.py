"""Probe: what `gncInvoiceSetDatePosted` wants, version by version.

A posted invoice round-trips its `date:` and `due:` on GnuCash 4 and 5 and
comes back as 5373-05-01 and 6710-05-01 on 3.4. Both are written as plain
epoch seconds — `int(dt.timestamp())` through `_datetime_to_time64` — so this
asks which spellings that build accepts, and what each reads back as.

Every spelling is tried on an invoice of its own, and the answer is whatever
`gncInvoiceGetDatePosted` reports afterwards.

    ./scripts/test.sh debian10 tests/research/what_an_invoice_date_setter_takes_probe.py
    ./scripts/test.sh latest   tests/research/what_an_invoice_date_setter_takes_probe.py
"""

from datetime import datetime

import pytest

WANTED = datetime(2026, 1, 5)


def _a_book(tmp_path):
    from gnucash import Session
    path = str(tmp_path / 'book.gnucash')
    try:
        from gnucash import SessionOpenMode
        session = Session(f'xml://{path}', SessionOpenMode.SESSION_NEW_STORE)
    except ImportError:
        session = Session(f'xml://{path}', is_new=True)
    return session


def test_which_spelling_a_date_takes(tmp_path, capsys):
    import gnucash.gnucash_core_c as gc

    # Both from `gnucash_business`, not the package — finding 13.
    from gnucash.gnucash_business import Customer, Invoice

    session = _a_book(tmp_path)
    book = session.book
    usd = book.get_table().lookup('CURRENCY', 'USD')

    lines = []

    def attempt(label, write):
        tag = label.replace(' ', '')[:6]
        customer = Customer(book, f'C-{tag}', usd)
        customer.SetName('Probe')
        invoice = Invoice(book, f'INV-{tag}', usd, customer)
        try:
            write(invoice)
        except Exception as e:
            lines.append((label, f'raised {type(e).__name__}: {e}'[:70]))
            return
        try:
            got = gc.gncInvoiceGetDatePosted(invoice.instance)
            lines.append((label, f'{got!r}  ({type(got).__name__})'))
        except Exception as e:
            lines.append((label, f'read raised {type(e).__name__}: {e}'[:70]))

    attempt('epoch seconds',
            lambda inv: gc.gncInvoiceSetDatePosted(inv.instance,
                                                   int(WANTED.timestamp())))
    if hasattr(Invoice, 'SetDatePosted'):
        attempt('SetDatePosted(datetime)',
                lambda inv: inv.SetDatePosted(WANTED))
        attempt('SetDatePosted(seconds)',
                lambda inv: inv.SetDatePosted(int(WANTED.timestamp())))
    else:
        lines.append(('SetDatePosted', 'the Invoice class has no such method'))

    session.end()

    with capsys.disabled():
        print()
        print(f'wanted {WANTED}  ({int(WANTED.timestamp())} seconds)')
        for label, answer in lines:
            print(f'  {label:<26} {answer}')
    pytest.skip('probe: it reports rather than asserting')
