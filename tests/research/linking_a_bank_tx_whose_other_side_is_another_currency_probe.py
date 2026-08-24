"""Linking a bank transaction to a USD invoice's payment, where the bank
transaction's other side sits on a CAD account.

The shape a user reported. A USD 1000 invoice, A/R in USD, income in CAD, so
the posting converts:

    A/R                 +1000.00 USD   (value +1400.00 CAD)
    Income:Sales        -1400.00 CAD

The money then arrives in the USD bank, and at the time it is booked against a
CAD account — Due From Director — because nobody has yet worked out what it
was:

    Assets:Bank USD     +1000.00 USD   (value +1399.00 CAD)
    Due From Director   -1399.00 CAD

Later they work out that this *was* the invoice being paid. The 1399.00 CAD and
the 1.399 rate under it are scaffolding: there is no CAD in this settlement at
all. What the transaction should become is

    Assets:Bank USD     +1000.00 USD
    A/R                 -1000.00 USD

with the A/R split in the invoice's lot — a plain USD entry, no CAD, no rate.

**The link needs no exchange rate**, and none is asked for below. `--fx-rates`
appears once, in setup, and only because this probe *creates* the posting that
the reporter's book already has: a USD invoice booking to a CAD income account
converts, so minting it needs the USD/CAD rate for the posting date. Nothing
about linking the payment does.

So the link has to do three things to the CAD split, and this probe asks which
of them the import does:

1. move it to the A/R account                — `xaccSplitSetAccount`
2. restate its amount, -1399 CAD → -1000 USD — nothing does this
3. restate the transaction's currency, CAD → USD, and the bank split's value
   with it                                    — nothing does this

The function the payment block reaches calls only (1), so the question is what
the book holds once (2) and (3) are skipped: a -1399 amount reading as USD on a
USD account, or something the engine corrects on its own.

Two routes are measured, in the order a reader would try them:

  A. the `payment:` block naming `txn_guid:` + `txn_split_guid:`;
  B. restating the whole transaction under `--strategy update` first — new
     account, new amount, new transaction currency — and linking after.

Run:  ./scripts/run.sh latest bash -c 'python3 -m pip install -e . \
          --break-system-packages -q >/dev/null 2>&1; python3 \
          tests/research/linking_a_bank_tx_whose_other_side_is_another_currency_probe.py'
"""

import sys
import tempfile
import time
from fractions import Fraction
from pathlib import Path

from click.testing import CliRunner
from gnucash import Query, Transaction

from cli.main import cli
from infrastructure.gnucash.utils import get_account_full_name
from repositories.gnucash_repository import GnuCashRepository, SessionMode

BANK = 'Assets:Bank USD'
AR = 'Assets:Accounts Receivable'
DUE_FROM = 'Assets:Due From Director'

ACCOUNTS_AND_INVOICE = '''\
2026-01-01 commodity CAD
\tmnemonic: "CAD"
\tfullname: "Canadian Dollar"
\tnamespace: "CURRENCY"
\tfraction: 100
2026-01-01 commodity USD
\tmnemonic: "USD"
\tfullname: "US Dollar"
\tnamespace: "CURRENCY"
\tfraction: 100
2026-01-01 open Assets
\ttype: Asset
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Bank USD
\ttype: Bank
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "USD"
2026-01-01 open Assets:Accounts Receivable
\ttype: Accounts Receivable
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "USD"
2026-01-01 open Assets:Due From Director
\ttype: Asset
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Income
\ttype: Income
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Income:Sales
\ttype: Income
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"

customer "C-USD"
\tname: "Acme USA"
\tcurrency: USD
'''

INVOICE = '''\
invoice "INV-USD-1000"
\tcustomer_id: "C-USD"
\tcurrency: USD
\tdate_opened: 2026-02-01
\tentry:
\t\tdate: 2026-02-01
\t\tdescription: "Consulting"
\t\taccount: "Income:Sales"
\t\tquantity: 1
\t\tprice: 1000
\t\ttaxable: false
\t\ttax_included: false
\tposted:
\t\tdate: 2026-02-01
\t\tdue: 2026-03-03
\t\tar_account: "Assets:Accounts Receivable"
\t\tmemo: "INV-USD-1000"
\t\taccumulate: true
'''

# Setup only. The posting converts (USD invoice, CAD income), so minting it
# needs a rate. The link measured further down needs none.
RATES = '''\
USD/CAD:
  2026-02-01: 1.40
'''

MONEY_IN = '''\
2026-02-25 * "Money in"
\tcurrency.mnemonic: "CAD"
\tAssets:Bank USD 1000.00 USD
\t\taccount.commodity.mnemonic: "USD"
\t\tshare_price: "1.399"
\t\tvalue: "1399.00"
\tAssets:Due From Director -1399.00 CAD
\t\taccount.commodity.mnemonic: "CAD"
\t\tshare_price: "1"
\t\tvalue: "-1399.00"
'''


def _run(runner, *args):
    # GnuCash refuses a second save inside the same second: its backup file is
    # named to the second and the collision surfaces as ERR_FILEIO_BACKUP_ERROR.
    time.sleep(1.1)
    return runner.invoke(cli, list(args))


def _transaction(book_path, description):
    """The named transaction's currency, and a row per split."""
    repo = GnuCashRepository(str(book_path))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        found = None
        for raw in query.run():
            transaction = Transaction(instance=raw)
            if transaction.GetDescription() != description:
                continue
            rows = []
            for split in transaction.GetSplitList():
                account = split.GetAccount()
                lot = split.GetLot()
                rows.append({
                    'account': get_account_full_name(account),
                    'commodity': account.GetCommodity().get_mnemonic(),
                    'amount': Fraction(split.GetAmount().num(),
                                       split.GetAmount().denom()),
                    'value': Fraction(split.GetValue().num(),
                                      split.GetValue().denom()),
                    'guid': split.GetGUID().to_string().replace('-', '').lower(),
                    'in_a_lot': lot is not None,
                })
            found = (transaction.GetCurrency().get_mnemonic(),
                     transaction.GetGUID().to_string().replace('-', '').lower(),
                     rows)
            break
        query.destroy()
        return found
    finally:
        repo.close()


def _show(label, currency, rows):
    print(f'  {label} — transaction currency {currency}')
    for row in rows:
        print(f'    {row["account"]:<32} amount {float(row["amount"]):>9.2f} '
              f'{row["commodity"]}   value {float(row["value"]):>9.2f} '
              f'{currency}   lot={row["in_a_lot"]}')


def _payment_ledger(txn_guid, split_guid=None):
    names_the_split = (f'\n\t\ttxn_split_guid: "{split_guid}"'
                       if split_guid else '')
    return INVOICE.rstrip('\n') + f'''
\tpayment:
\t\tdate: 2026-02-25
\t\tamount: 1000
\t\taccount: "{BANK}"
\t\ttxn_guid: "{txn_guid}"{names_the_split}
'''


def main():
    runner = CliRunner()
    tmp = Path(tempfile.mkdtemp())
    book = tmp / 'book.gnucash'

    def write(name, text):
        path = tmp / name
        path.write_text(text, encoding='utf-8')
        return str(path)

    print('=' * 78)
    print('SETUP — the reporter\'s book')
    print('=' * 78)

    result = _run(runner, 'import', '--new', str(book),
                  write('accounts.txt', ACCOUNTS_AND_INVOICE + '\n' + INVOICE),
                  '--include-business-objects',
                  '--fx-rates', write('rates.yaml', RATES))
    print(f'  accounts + posted invoice   exit {result.exit_code}')
    if result.exit_code != 0:
        print(result.output)
        return 1

    result = _run(runner, 'import', str(book), write('money.txt', MONEY_IN))
    print(f'  the bank transaction        exit {result.exit_code}')
    if result.exit_code != 0:
        print(result.output)
        return 1

    currency, txn_guid, rows = _transaction(book, 'Money in')
    print()
    _show('as booked', currency, rows)
    due = next(r for r in rows if r['account'] == DUE_FROM)

    print()
    print('=' * 78)
    print('ROUTE A1 — payment block naming the split outright')
    print('=' * 78)
    print(f'  txn_guid:       {txn_guid}')
    print(f'  txn_split_guid: {due["guid"]}   (the Due From Director split)')
    print()

    result = _run(runner, 'import', str(book),
                  write('link1.txt', _payment_ledger(txn_guid, due['guid'])),
                  '--include-business-objects')
    print(f'  exit {result.exit_code}')
    for line in result.output.splitlines():
        print(f'    {line}')

    after = _transaction(book, 'Money in')
    if after is not None:
        print()
        _show('after', after[0], after[2])

    print()
    print('=' * 78)
    print('ROUTE A2 — payment block naming only the transaction')
    print('=' * 78)
    print('  The importer picks the side that is not the bank and moves it to')
    print('  A/R. Which is the Due From Director split, in CAD.')
    print()

    result = _run(runner, 'import', str(book),
                  write('link2.txt', _payment_ledger(txn_guid)),
                  '--include-business-objects')
    print(f'  exit {result.exit_code}')
    for line in result.output.splitlines():
        print(f'    {line}')

    after = _transaction(book, 'Money in')
    if after is not None:
        print()
        _show('after', after[0], after[2])
        total = sum(row['value'] for row in after[2])
        print(f'    value sum {float(total):>9.2f} {after[0]}'
              f'   (0.00 = the entry balances)')

    print()
    print('=' * 78)
    print('ROUTE A3 — the same link where the two figures happen to match')
    print('=' * 78)
    print('  A fresh book, identical but for the invoice: USD 1399, against the')
    print('  same CAD -1399 split. The overpayment check compares the two bare')
    print('  numbers, so this one gets past it — and what it books is what the')
    print('  move does to a cross-currency split when nothing stops it.')
    print()

    book2 = tmp / 'book2.gnucash'
    matched = INVOICE.replace('INV-USD-1000', 'INV-USD-1399') \
                     .replace('price: 1000', 'price: 1399')
    result = _run(runner, 'import', '--new', str(book2),
                  write('accounts2.txt', ACCOUNTS_AND_INVOICE + '\n' + matched),
                  '--include-business-objects',
                  '--fx-rates', write('rates.yaml', RATES))
    if result.exit_code != 0:
        print(result.output)
        return 1
    result = _run(runner, 'import', str(book2), write('money.txt', MONEY_IN))
    if result.exit_code != 0:
        print(result.output)
        return 1

    currency2, txn2, rows2 = _transaction(book2, 'Money in')
    _show('as booked', currency2, rows2)

    link = matched.rstrip('\n') + f'''
\tpayment:
\t\tdate: 2026-02-25
\t\tamount: 1399
\t\taccount: "{BANK}"
\t\ttxn_guid: "{txn2}"
'''
    result = _run(runner, 'import', str(book2), write('link3.txt', link),
                  '--include-business-objects')
    print(f'\n  exit {result.exit_code}')
    for line in result.output.splitlines():
        print(f'    {line}')

    after2 = _transaction(book2, 'Money in')
    if after2 is not None:
        print()
        _show('after', after2[0], after2[2])
        total = sum(row['value'] for row in after2[2])
        print(f'    value sum {float(total):>9.2f} {after2[0]}'
              f'   (0.00 = the entry balances)')
        moved = [r for r in after2[2] if r['account'] == AR]
        if moved:
            row = moved[0]
            print()
            print(f'    the moved split now reads {float(row["amount"]):.2f} '
                  f'{row["commodity"]} on a {row["commodity"]} account,')
            print('    where the money it stood for was 1399.00 CAD.')

    print()
    print('  What the reporter wants instead:')
    print(f'    {BANK:<32} amount   1000.00 USD   value   1000.00 USD')
    print(f'    {AR:<32} amount  -1000.00 USD   value  -1000.00 USD   lot=True')
    print('    transaction currency USD — no CAD anywhere, no rate')

    return 0


if __name__ == '__main__':
    sys.exit(main())
