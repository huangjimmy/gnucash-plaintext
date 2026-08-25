"""What the engine allows when a split moves to an account of another currency.

Q-039 needs to take the split a bank transaction was parked against — a CAD
CAD account — and make it the receivable side of a USD settlement. Moving
the account is `xaccSplitSetAccount` and is already done. What is not done is
restating the figures, and two things have to be known before deciding how:

1. **Does `xaccTransSetCurrency` work on a committed transaction, and what does
   it do to the splits' values?** The entry ends up USD-only, so its currency
   should be USD; a transaction left in CAD would carry a USD-only entry whose
   values are quoted in a currency nothing in it uses.

2. **What is the moved split's value where the entry stays multi-currency** —
   a CAD wire fee beside a USD settlement? Value is in the transaction's
   currency, so it cannot simply equal the amount, and the entry has to balance.

Both are asked of the engine directly rather than through the importer, because
the answer decides what the importer should do. Nothing here is a test: it
prints what each build does.

Run:  ./scripts/run.sh latest bash -c 'python3 -m pip install -e . \
          --break-system-packages -q >/dev/null 2>&1; python3 \
          tests/research/restating_a_split_that_moves_between_currencies_probe.py'
"""

import sys
import tempfile
from fractions import Fraction
from pathlib import Path

import gnucash
from gnucash import Account, GncNumeric, Session, Split, Transaction

from infrastructure.gnucash.engine import load_gnc_engine
from infrastructure.gnucash.utils import get_account_full_name

ASSET = gnucash.ACCT_TYPE_ASSET
BANK = gnucash.ACCT_TYPE_BANK
RECEIVABLE = gnucash.ACCT_TYPE_RECEIVABLE
EXPENSE = gnucash.ACCT_TYPE_EXPENSE


def _num(whole, denom=1):
    return GncNumeric(int(whole), int(denom))


def _account(book, root, name, kind, commodity):
    account = Account(book)
    root.append_child(account)
    account.SetName(name)
    account.SetType(kind)
    account.SetCommodity(commodity)
    return account


def _rows(transaction):
    out = []
    for split in transaction.GetSplitList():
        account = split.GetAccount()
        out.append((
            get_account_full_name(account),
            account.GetCommodity().get_mnemonic(),
            Fraction(split.GetAmount().num(), split.GetAmount().denom()),
            Fraction(split.GetValue().num(), split.GetValue().denom()),
        ))
    return out


def _show(label, transaction):
    rows = _rows(transaction)
    total = sum(row[3] for row in rows)
    print(f'    {label} — currency {transaction.GetCurrency().get_mnemonic()}')
    for name, commodity, amount, value in rows:
        print(f'      {name:<26} amount {float(amount):>9.2f} {commodity}'
              f'   value {float(value):>9.2f}')
    print(f'      {"value sum":<26} {float(total):>16.2f}'
          f'   ({"balances" if total == 0 else "DOES NOT BALANCE"})')


def _book(path):
    session = Session(f'xml://{path}', gnucash.SessionOpenMode.SESSION_NEW_STORE)
    book = session.book
    table = book.get_table()
    cad = table.lookup('CURRENCY', 'CAD')
    usd = table.lookup('CURRENCY', 'USD')
    root = book.get_root_account()
    accounts = {
        'bank': _account(book, root, 'Bank USD', BANK, usd),
        'ar': _account(book, root, 'Receivable', RECEIVABLE, usd),
        'hold': _account(book, root, 'Due From Director', ASSET, cad),
        'fee': _account(book, root, 'Wire Fees', EXPENSE, cad),
    }
    return session, book, cad, usd, accounts


def question_one(tmp):
    """A two-split entry, CAD-quoted, whose other side becomes USD."""
    print()
    print('=' * 74)
    print('1. xaccTransSetCurrency on a committed transaction')
    print('=' * 74)

    session, book, cad, usd, acc = _book(tmp / 'one.gnucash')
    lib = load_gnc_engine()

    txn = Transaction(book)
    txn.BeginEdit()
    txn.SetCurrency(cad)
    txn.SetDescription('Money in')
    bank = Split(book)
    bank.SetParent(txn)
    bank.SetAccount(acc['bank'])
    bank.SetAmount(_num(1000))
    bank.SetValue(_num(1399))
    hold = Split(book)
    hold.SetParent(txn)
    hold.SetAccount(acc['hold'])
    hold.SetAmount(_num(-1399))
    hold.SetValue(_num(-1399))
    txn.CommitEdit()
    _show('as booked', txn)

    print()
    print('    move the parked split to the USD receivable, touching nothing else:')
    txn.BeginEdit()
    lib.xaccSplitSetAccount(int(hold.instance), int(acc['ar'].instance))
    txn.CommitEdit()
    _show('after the move alone', txn)

    print()
    print('    now restate the split and the transaction currency:')
    txn.BeginEdit()
    hold.SetAmount(_num(-1000))
    hold.SetValue(_num(-1000))
    bank.SetValue(_num(1000))
    txn.SetCurrency(usd)
    txn.CommitEdit()
    _show('after restating', txn)

    print()
    print('    …and after a save and a reload:')
    session.save()
    session.end()
    session.destroy()
    reopened = Session(f'xml://{tmp / "one.gnucash"}',
                       gnucash.SessionOpenMode.SESSION_NORMAL_OPEN)
    try:
        from gnucash import Query
        query = Query()
        query.search_for('Trans')
        query.set_book(reopened.book)
        for raw in query.run():
            back = Transaction(instance=raw)
            if back.GetDescription() == 'Money in':
                _show('reloaded', back)
                break
        query.destroy()
    finally:
        reopened.end()
        reopened.destroy()


def question_two(tmp):
    """A fee split keeps the entry multi-currency: what value must the
    moved split carry?"""
    print()
    print('=' * 74)
    print('2. a CAD fee beside the USD settlement')
    print('=' * 74)

    session, book, cad, usd, acc = _book(tmp / 'two.gnucash')
    lib = load_gnc_engine()

    txn = Transaction(book)
    txn.BeginEdit()
    txn.SetCurrency(cad)
    txn.SetDescription('Money in, net of a fee')
    bank = Split(book)
    bank.SetParent(txn)
    bank.SetAccount(acc['bank'])
    bank.SetAmount(_num(1000))
    bank.SetValue(_num(1399))
    fee = Split(book)
    fee.SetParent(txn)
    fee.SetAccount(acc['fee'])
    fee.SetAmount(_num(21))
    fee.SetValue(_num(21))
    hold = Split(book)
    hold.SetParent(txn)
    hold.SetAccount(acc['hold'])
    hold.SetAmount(_num(-1420))
    hold.SetValue(_num(-1420))
    txn.CommitEdit()
    _show('as booked', txn)

    print()
    print('    the settlement is 1000 USD; the fee is genuinely CAD, so the')
    print('    entry stays CAD-quoted and the moved split takes amount -1000')
    print('    USD with the value the balance demands (-1420 CAD):')
    txn.BeginEdit()
    lib.xaccSplitSetAccount(int(hold.instance), int(acc['ar'].instance))
    hold.SetAmount(_num(-1000))
    hold.SetValue(_num(-1420))
    txn.CommitEdit()
    _show('after', txn)
    print()
    print('    NOTE what that implies: the receivable split now says 1000 USD')
    print('    is worth 1420 CAD, a rate of 1.42, which nobody stated. Whether')
    print('    that is acceptable or has to be refused is the design question.')

    session.end()
    session.destroy()


def main():
    tmp = Path(tempfile.mkdtemp())
    question_one(tmp)
    question_two(tmp)
    return 0


if __name__ == '__main__':
    sys.exit(main())
