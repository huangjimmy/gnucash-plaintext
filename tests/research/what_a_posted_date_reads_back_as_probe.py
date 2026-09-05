"""Probe: the date a transaction reads back with, given the seconds it was set.

The fuzzy matcher files a transaction under `(post date, positive amount)`, and
on GnuCash 3.4 every match test comes back `NEW` with no candidate — so one
half of that key differs. Its book is built the way the matcher's own tests
build one, with `SetDatePostedSecs(int(d.strftime('%s')))`, and this reads back
what the engine then reports.

    ./scripts/test.sh debian10 tests/research/what_a_posted_date_reads_back_as_probe.py
    ./scripts/test.sh latest   tests/research/what_a_posted_date_reads_back_as_probe.py
"""

import os
import tempfile
from datetime import date
from decimal import Decimal

from infrastructure.gnucash.utils import gnc_numeric_to_fraction_or_decimal

WANTED = date(2026, 4, 15)


def test_what_the_engine_reports(capsys):
    import gnucash
    from gnucash import Account, GncNumeric, Session, Transaction
    from gnucash import Split as GncSplit

    fd, path = tempfile.mkstemp(suffix='.gnucash')
    os.close(fd)
    os.unlink(path)
    try:
        from gnucash import SessionOpenMode
        session = Session(f'xml://{path}', SessionOpenMode.SESSION_NEW_STORE)
    except ImportError:
        session = Session(f'xml://{path}', is_new=True)

    book = session.book
    root = book.get_root_account()
    hkd = book.get_table().lookup('CURRENCY', 'HKD')

    def acct(name, type_, parent):
        a = Account(book)
        a.SetName(name)
        a.SetType(type_)
        a.SetCommodity(hkd)
        parent.append_child(a)
        return a

    bank = acct('Bank', gnucash.ACCT_TYPE_BANK, root)
    spend = acct('Spend', gnucash.ACCT_TYPE_EXPENSE, root)

    seconds = int(WANTED.strftime('%s'))
    tx = Transaction(book)
    tx.BeginEdit()
    tx.SetCurrency(hkd)
    tx.SetDatePostedSecs(seconds)
    for account, num in ((bank, 24710), (spend, -24710)):
        sp = GncSplit(book)
        sp.SetParent(tx)
        sp.SetAccount(account)
        sp.SetValue(GncNumeric(num, 100))
        sp.SetAmount(GncNumeric(num, 100))
    tx.CommitEdit()

    read_in_session = tx.GetDate()
    amounts = [Decimal(gnc_numeric_to_fraction_or_decimal(sp.GetAmount()))
               for sp in tx.GetSplitList()]
    session.save()
    session.end()

    from repositories.gnucash_repository import GnuCashRepository
    again = GnuCashRepository(path)
    again.open()
    try:
        reloaded = [t.GetDate() for t in again.get_all_transactions()]
    finally:
        again.close()
        if os.path.exists(path):
            os.unlink(path)

    with capsys.disabled():
        print()
        print(f'asked for            {WANTED}')
        print(f'seconds given        {seconds}')
        print(f'in session GetDate   {read_in_session!r}')
        print(f'in session .date()   {read_in_session.date()}')
        print(f'after reload         {[str(d) for d in reloaded]}')
        print(f'positive sum         {sum(a for a in amounts if a > 0)!r}')
        print(f'TZ                   {os.environ.get("TZ", "(unset)")}')
