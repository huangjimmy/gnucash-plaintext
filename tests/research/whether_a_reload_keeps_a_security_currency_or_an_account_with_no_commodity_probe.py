"""Three things a book answers once it has been saved and read back.

Each decides whether a check in this tree can ever be reached by a command,
since every command reads its book from disk.

* **A transaction whose currency is a security.** Kept while the session that
  set it is open; after a save and a reload the transaction's currency is a
  currency again. So a `currency.namespace:` line in the export, and a
  validator error for a transaction with no currency, answer a state no book
  read from disk is in.
* **An account with no commodity, and a split on it.** GnuCash logs
  `Account "No Commodity" does not have a commodity!` from
  `xaccAccountScrubCommodity` and keeps the account anyway, still with no
  commodity and still holding its split, through the save and the reload.
  Nothing this tool writes makes one, but a book from elsewhere can hold one,
  so the commands that read an account's commodity have to answer for it.
* **The order transactions are listed in.** Entered March, then January, then
  February, `GnuCashRepository.get_all_transactions` lists them in date order,
  in the session and after the reload. So a check that the listed transactions
  are in date order finds nothing to report.

Measured on GnuCash 5.10 and 3.4, with the same answers:

    in session order: ['January', 'Priced in shares', 'Onto the account with no commodity', 'March']
    in session 'Priced in shares' currency: ('NASDAQ', 'USTECH')
    in session No Commodity account: None splits: 1
    reloaded order: ['January', 'Priced in shares', 'Onto the account with no commodity', 'March']
    reloaded 'Priced in shares' currency: ('CURRENCY', 'USD')
    reloaded No Commodity account: None splits: 1

Run inside an image, from the repository root:

    docker run --rm -v "$PWD:/workspace" -w /workspace gnucash-dev:latest \\
        python3 tests/research/whether_a_reload_keeps_a_security_currency_or_an_account_with_no_commodity_probe.py
"""
import os
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.getcwd())

import gnucash  # noqa: E402
from gnucash import Account, GncNumeric, Split, Transaction  # noqa: E402

from infrastructure.gnucash.utils import find_account  # noqa: E402
from repositories.gnucash_repository import GnuCashRepository, SessionMode  # noqa: E402


def report(label, repo):
    listed = repo.get_all_transactions()
    print(label, 'order:', [t.GetDescription() for t in listed])
    for t in listed:
        c = t.GetCurrency()
        print(label, repr(t.GetDescription()), 'currency:',
              None if c is None else (c.get_namespace(), c.get_mnemonic()))
    bare = find_account(repo.book.get_root_account(), 'No Commodity')
    print(label, 'No Commodity account:',
          'missing' if bare is None else
          (None if bare.GetCommodity() is None else bare.GetCommodity().get_mnemonic()),
          'splits:', 0 if bare is None else len(bare.GetSplitList()))


def main():
    path = os.path.join(tempfile.mkdtemp(), 'probe.gnucash')
    repo = GnuCashRepository(path)
    repo.open(SessionMode.NEW)
    book = repo.book
    table = book.get_table()
    usd = table.lookup('CURRENCY', 'USD')
    ustech = gnucash.GncCommodity(book, 'US Tech', 'NASDAQ', 'USTECH', 'USTECH', 10000)
    table.insert(ustech)
    root = book.get_root_account()

    def account(name, commodity, kind):
        a = Account(book)
        a.BeginEdit()
        a.SetName(name)
        a.SetType(kind)
        if commodity is not None:
            a.SetCommodity(commodity)
        root.append_child(a)
        a.CommitEdit()
        return a

    cash = account('USD Cash', usd, gnucash.ACCT_TYPE_BANK)
    stock = account('USTECH', ustech, gnucash.ACCT_TYPE_STOCK)
    opening = account('Opening', usd, gnucash.ACCT_TYPE_EQUITY)
    bare = account('No Commodity', None, gnucash.ACCT_TYPE_ASSET)

    def transaction(description, when, currency, lines):
        t = Transaction(book)
        t.BeginEdit()
        t.SetCurrency(currency)
        t.SetDescription(description)
        t.SetDatePostedSecs(when)
        for acct, amount, value in lines:
            s = Split(book)
            s.SetParent(t)
            s.SetAccount(acct)
            s.SetAmount(GncNumeric(amount, 100))
            s.SetValue(GncNumeric(value, 100))
        t.CommitEdit()

    transaction('March', datetime(2026, 3, 1, 12), usd,
                [(cash, 1000, 1000), (opening, -1000, -1000)])
    transaction('January', datetime(2026, 1, 1, 12), usd,
                [(cash, 500, 500), (opening, -500, -500)])
    transaction('Priced in shares', datetime(2026, 2, 1, 12), ustech,
                [(stock, 100, 100), (cash, -100, -100)])
    transaction('Onto the account with no commodity', datetime(2026, 2, 15, 12), usd,
                [(bare, 250, 250), (cash, -250, -250)])

    report('in session', repo)
    repo.save()
    repo.close()

    repo = GnuCashRepository(path)
    repo.open(SessionMode.READ_ONLY)
    report('reloaded', repo)
    repo.close()


main()
