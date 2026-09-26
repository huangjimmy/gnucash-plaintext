"""Probe: what a stock bought or sold in foreign currency does to the cost bases.

Q-045 records a user's report and says nothing in it is measured. This measures
it, on both sides of the bases at once — a book that holds US dollars *and*
owes them, because a stock can be bought with borrowed currency and a loan can
be repaid out of what a sale brings in.

**The invariant.** Per currency and side, what the cost bases hold is what the
accounts hold: the asset-side bases against the bank, the liability-side bases
against the loan. A purchase that spends foreign currency has to draw its basis
down, and a sale that brings some in has to open one — otherwise the two part
company and every gain the balance sheet measures from the bases is measured
against a quantity the book does not have. That is the state
`a_cad_book_with_usd_hkd_and_shares_priced_in_its_price_database.txt` is in, and
what Q-044's `measured_from: gnucash_revaluation` fallback reports rather than
repairs.

Five cases, each on a book of its own so one refusal cannot change what the
next is asked:

1. shares bought with US dollars, the dollar split stating the asset basis guid;
2. the same purchase stating no guid — the ordinary transaction;
3. shares sold for US dollars — is a basis opened for what came in?
4. the loan repaid, the loan split stating the liability basis guid;
5. the same repayment stating no guid.

Nothing is asserted. What it prints is the invariant per case, which is what
the eventual tests have to assert.

    ./scripts/test.sh latest \\
        tests/research/whether_trading_a_stock_in_foreign_currency_moves_its_cost_basis_probe.py

`tests.conftest` is imported for its `_run`, and importing it also patches
`Session.save` to remove a backup file before writing one — GnuCash carries the
second in a backup's filename, so two saves inside one second otherwise fail
with ERR_FILEIO_BACKUP_ERROR, which exits 1 and reads like a refusal while the
import above it reports `Errors: 0`. A probe that shells out to the installed
command instead of running in this process does not get that patch, and meets
the error on every case.
"""

from fractions import Fraction

from click.testing import CliRunner

from services.foreign_currency import (
    cost_basis_items_by_currency_and_side,
    foreign_currency_account_balances,
)
from tests.conftest import _run

# A Canadian book with a cost basis on each side: 10,000.00 USD bought at 1.30
# and held, 5,000.00 USD borrowed at 1.30 and owed. The borrowing opens two —
# the dollars arriving in the bank, and the dollars owed on the loan.
THE_BOOK = '''\
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
2026-01-01 commodity HKD
\tmnemonic: "HKD"
\tfullname: "Hong Kong Dollar"
\tnamespace: "CURRENCY"
\tfraction: 100
2026-01-01 commodity JPY
\tmnemonic: "JPY"
\tfullname: "Japanese Yen"
\tnamespace: "CURRENCY"
\tfraction: 1
2026-01-01 commodity KRW
\tmnemonic: "KRW"
\tfullname: "South Korean Won"
\tnamespace: "CURRENCY"
\tfraction: 100
2026-01-01 commodity TWD
\tmnemonic: "TWD"
\tfullname: "New Taiwan Dollar"
\tnamespace: "CURRENCY"
\tfraction: 100
2026-01-01 commodity AAPL
\tmnemonic: "AAPL"
\tfullname: "Apple Inc"
\tnamespace: "NASDAQ"
\tfraction: 10000
2026-01-01 commodity AMZN
\tmnemonic: "AMZN"
\tfullname: "Amazon.com Inc"
\tnamespace: "NASDAQ"
\tfraction: 10000

2026-01-01 open Assets
\ttype: "Asset"
\tplaceholder: #True
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Bank
\ttype: "Bank"
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:USD Bank
\ttype: "Bank"
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "USD"
2026-01-01 open Assets:USD Savings
\ttype: "Bank"
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "USD"
2026-01-01 open Assets:HKD Bank
\ttype: "Bank"
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "HKD"
2026-01-01 open Assets:JPY Bank
\ttype: "Bank"
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "JPY"
2026-01-01 open Assets:KRW Bank
\ttype: "Bank"
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "KRW"
2026-01-01 open Assets:TWD Bank
\ttype: "Bank"
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "TWD"
2026-01-01 open Assets:AAPL
\ttype: "Stock"
\tcommodity.namespace: "NASDAQ"
\tcommodity.mnemonic: "AAPL"
2026-01-01 open Assets:AMZN
\ttype: "Stock"
\tcommodity.namespace: "NASDAQ"
\tcommodity.mnemonic: "AMZN"
2026-01-01 open Liabilities
\ttype: "Liability"
\tplaceholder: #True
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Liabilities:USD Loan
\ttype: "Liability"
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "USD"
2026-01-01 open Equity
\ttype: "Equity"
\tplaceholder: #True
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Equity:Opening balances
\ttype: "Equity"
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Income
\ttype: "Income"
\tplaceholder: #True
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Income:FX Gain
\ttype: "Income"
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"

price
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "USD"
\tcurrency.mnemonic: "CAD"
\ttime: "2026-01-02 12:00:00 +0000"
\tvalue: "13/10"
\tsource: "user:price-editor"

price
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "HKD"
\tcurrency.mnemonic: "CAD"
\ttime: "2026-01-02 12:00:00 +0000"
\tvalue: "1/6"
\tsource: "user:price-editor"

2026-01-02 * "Open the Canadian bank"
\tcurrency.mnemonic: "CAD"
\tAssets:Bank 20000.00 CAD
\tEquity:Opening balances -20000.00 CAD

2026-01-03 * "Buy 10,000.00 USD at 1.30"
\tcurrency.mnemonic: "CAD"
\tAssets:USD Bank 10000.00 USD
\t\taccount.commodity.mnemonic: "USD"
\t\tshare_price: "1.30000"
\t\tvalue: "13000.00"
\t\tcost_basis_balance: "10000.00"
\tAssets:Bank -13000.00 CAD

2026-01-04 * "Borrow 5,000.00 USD into the US dollar bank"
\tcurrency.mnemonic: "CAD"
\tAssets:USD Bank 5000.00 USD
\t\taccount.commodity.mnemonic: "USD"
\t\tshare_price: "1.30000"
\t\tvalue: "6500.00"
\tLiabilities:USD Loan -5000.00 USD
\t\taccount.commodity.mnemonic: "USD"
\t\tshare_price: "1.30000"
\t\tvalue: "-6500.00"
\t\tcost_basis_balance: "5000.00"
'''

BUY_WITH_USD = '''\
2026-02-03 * "Buy 20 AMZN at 200.00 USD, paid from the US dollar bank"
\tcurrency.mnemonic: "CAD"
\tAssets:AMZN 20 AMZN
\t\tshare_price: "260"
\t\tvalue: "5200.00"
\tAssets:USD Bank -4000.00 USD
\t\taccount.commodity.mnemonic: "USD"
\t\tshare_price: "1.30000"
\t\tvalue: "-5200.00"
'''

SELL_FOR_USD = '''\
2026-03-03 * "Sell 10 AMZN at 220.00 USD into the US dollar bank"
\tcurrency.mnemonic: "CAD"
\tAssets:USD Bank 2200.00 USD
\t\taccount.commodity.mnemonic: "USD"
\t\tshare_price: "1.30000"
\t\tvalue: "2860.00"
\tAssets:AMZN -10 AMZN
\t\tshare_price: "260"
\t\tvalue: "-2600.00"
\tIncome:FX Gain -260.00 CAD
'''

# The case that tells a spend from a move. Both of these net to zero if you
# just add the USD splits up — but one still holds every dollar it had, and the
# other has paid off 2,000 of debt with 2,000 of currency that is now gone,
# consuming a cost basis on each side.
TRANSFER_USD_TO_USD = '''\
2026-02-03 * "Move 4,000.00 USD from the chequing account to savings"
\tcurrency.mnemonic: "CAD"
\tAssets:USD Savings 4000.00 USD
\t\taccount.commodity.mnemonic: "USD"
\t\tshare_price: "1.30000"
\t\tvalue: "5200.00"
\tAssets:USD Bank -4000.00 USD
\t\taccount.commodity.mnemonic: "USD"
\t\tshare_price: "1.30000"
\t\tvalue: "-5200.00"
'''

# The same two trades stated wholly in US dollars, which is how a book that
# trades on a US exchange actually writes them — the transaction's currency is
# USD and no split carries a figure in the book's own. Q-044 measured that
# shape: "every one of those in a transaction stated wholly in US dollars, so
# not one of them states that cost basis's guid and the basis is never drawn
# down."
BUY_STATED_IN_USD = '''\
2026-02-03 * "Buy 20 AMZN at 200.00 USD"
\tcurrency.mnemonic: "USD"
\tAssets:AMZN 20 AMZN
\t\tshare_price: "200"
\t\tvalue: "4000.00"
\tAssets:USD Bank -4000.00 USD
'''

SELL_STATED_IN_USD = '''\
2026-03-03 * "Sell 10 AMZN at 220.00 USD"
\tcurrency.mnemonic: "USD"
\tAssets:USD Bank 2200.00 USD
\tAssets:AMZN -10 AMZN
\t\tshare_price: "200"
\t\tvalue: "-2000.00"
\tIncome:FX Gain -200.00 USD
'''

# Currency leaving the book with nothing to argue about: 1,000 USD sold for
# Canadian dollars, no guid stated. If anything refuses a disposal that does not
# say which basis it came out of, it refuses this.
SELL_USD_FOR_CAD = '''\
2026-02-03 * "Sell 1,000.00 USD for Canadian dollars at 1.30"
\tcurrency.mnemonic: "CAD"
\tAssets:Bank 1300.00 CAD
\tAssets:USD Bank -1000.00 USD
\t\taccount.commodity.mnemonic: "USD"
\t\tshare_price: "1.30000"
\t\tvalue: "-1300.00"
'''

# Neither side is the book's own currency. 1,000 USD goes out and 7,800 HKD
# comes in, at 1.30 CAD/USD and 6 HKD/CAD — so 1,300.00 CAD either way. The US
# dollars have left the book as surely as if they had been sold for Canadian
# ones, and the Hong Kong dollars have arrived as surely as if they had been
# bought with them.
SELL_USD_FOR_HKD = '''\
2026-02-03 * "Sell 1,000.00 USD for 7,800.00 HKD"
\tcurrency.mnemonic: "CAD"
\tAssets:HKD Bank 7800.00 HKD
\t\taccount.commodity.mnemonic: "HKD"
\t\tshare_price: "0.16667"
\t\tvalue: "1300.00"
\tAssets:USD Bank -1000.00 USD
\t\taccount.commodity.mnemonic: "USD"
\t\tshare_price: "1.30000"
\t\tvalue: "-1300.00"
'''

# 1,000.00 USD — 1,300.00 CAD — turned into each of these in one transaction.
# Neither side is the book's own currency in any of them, and the commodity
# arriving is counted to a different number of places each time: a yen divides
# into 1, a won and a Taiwan dollar into 100, a share into 10,000. What the
# cost basis records has to be right in all of them, and the figure it records
# the cost in is Canadian dollars throughout.
EXCHANGES = (
    ('JPY', 'Assets:JPY Bank', '130000', '0.01'),
    ('HKD', 'Assets:HKD Bank', '7800.00', '0.16667'),
    ('KRW', 'Assets:KRW Bank', '1300000.00', '0.001'),
    ('TWD', 'Assets:TWD Bank', '31200.00', '0.04167'),
    ('AMZN', 'Assets:AMZN', '5.0000', '260.00'),
    ('AAPL', 'Assets:AAPL', '10.0000', '130.00'),
)


def _exchange(mnemonic, account, quantity, price):
    """1,000.00 USD out, `quantity` of `mnemonic` in, 1,300.00 CAD either way."""
    kind = 'NASDAQ' if mnemonic in ('AMZN', 'AAPL') else 'CURRENCY'
    arriving = (f'\t{account} {quantity} {mnemonic}\n'
                f'\t\taccount.commodity.mnemonic: "{mnemonic}"\n'
                f'\t\tshare_price: "{price}"\n'
                f'\t\tvalue: "1300.00"\n') if kind == 'CURRENCY' else (
        f'\t{account} {quantity} {mnemonic}\n'
        f'\t\tshare_price: "{price}"\n'
        f'\t\tvalue: "1300.00"\n')
    return (f'2026-02-03 * "Turn 1,000.00 USD into {quantity} {mnemonic}"\n'
            f'\tcurrency.mnemonic: "CAD"\n'
            f'{arriving}'
            f'\tAssets:USD Bank -1000.00 USD\n'
            f'\t\taccount.commodity.mnemonic: "USD"\n'
            f'\t\tshare_price: "1.30000"\n'
            f'\t\tvalue: "-1300.00"\n')


REPAY_THE_LOAN = '''\
2026-02-03 * "Repay 2,000.00 USD of the loan out of the US dollar bank"
\tcurrency.mnemonic: "CAD"
\tLiabilities:USD Loan 2000.00 USD
\t\taccount.commodity.mnemonic: "USD"
\t\tshare_price: "1.30000"
\t\tvalue: "2600.00"
\tAssets:USD Bank -2000.00 USD
\t\taccount.commodity.mnemonic: "USD"
\t\tshare_price: "1.30000"
\t\tvalue: "-2600.00"
'''


def _with_guid(ledger, account, guid):
    """The same ledger with `cost_basis_split_guid:` under that account's split.

    The key goes at the end of that split's own block, which is the run of
    doubly-indented lines after the account line.
    """
    lines = ledger.splitlines()
    at = next(i for i, line in enumerate(lines) if line.startswith(f'\t{account} '))
    end = at + 1
    while end < len(lines) and lines[end].startswith('\t\t'):
        end += 1
    lines.insert(end, f'\t\tcost_basis_split_guid: "{guid}"')
    return '\n'.join(lines) + '\n'


def _book(runner, tmp_path, name):
    ledger = tmp_path / f'{name}.txt'
    ledger.write_text(THE_BOOK, encoding='utf-8')
    book = tmp_path / f'{name}.gnucash'
    made = _run(runner, 'import', '--new', str(book), str(ledger))
    assert made.exit_code == 0, made.output
    return book


def _bases(book):
    """Every cost basis of the book, by side, read the way the sheet reads them."""
    from repositories.gnucash_repository import GnuCashRepository, SessionMode
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        from datetime import date
        rows = list(cost_basis_items_by_currency_and_side(repo.book, date(2026, 12, 31)))
        holdings = list(foreign_currency_account_balances(repo.book))
    finally:
        repo.close()
    return rows, holdings


def _invariant(label, book):
    """Per currency and side: what the bases hold against what the accounts do.

    **Per currency**, never added across them. US dollars and Hong Kong dollars
    in one total is a quantity of nothing — the same fault the balance sheet's
    own block avoids by stating no `cost_basis_balance` above the commodity
    groups. A run that exchanged one foreign currency for another otherwise
    reads as a single figure that went up, hiding that one currency's bases are
    now adrift and the other's are not.
    """
    rows, holdings = _bases(book)
    print(f'  {label}')

    for code in sorted({r['currency'] for r in rows} | {h['currency'] for h in holdings}):
        mine = [r for r in rows if r['currency'] == code]
        theirs = [h for h in holdings if h['currency'] == code]
        for side, sign in (('asset', 1), ('liability', -1)):
            basis = sum((r['balance'] for r in mine if r['side'] == side), Fraction(0))
            accounts = sign * sum((h['balance'] for h in theirs
                                   if sign * h['balance'] > 0), Fraction(0))
            if basis == 0 and accounts == 0:
                continue
            verdict = 'agree' if basis == accounts else 'DISAGREE'
            print(f'    {code} {side:<9}  bases {float(basis):12,.2f}'
                  f'   accounts {float(accounts):12,.2f}   {verdict}')

    # Each basis on its own, because a total hides which ones there are: a sum
    # that rose says nothing about whether a basis opened for the currency a
    # sale brought in, or an existing one grew.
    # With the cost, which is the half that has to be in the book's own
    # currency however far the transaction is from it: a US dollar sold for
    # Hong Kong dollars in a Canadian book records what those HKD cost in CAD,
    # and the CAD figure is the `value:` the splits carry.
    for row in rows:
        cost = row['cost']
        print(f'      {row["currency"]} {row["side"]:<9} {float(row["balance"]):12,.2f}'
              f'  at {float(cost):.5f} CAD  = {float(row["balance"] * cost):10,.2f} CAD'
              f'  {row["account"]}')


def test_what_trading_a_stock_in_foreign_currency_does(tmp_path):
    runner = CliRunner()

    print('\n=== 0. the book as built, before any trade')
    _invariant('two cost bases, one each side', _book(runner, tmp_path, 'start'))

    # Each case gets a book of its own, and its ledger is built once that book
    # exists: a cost basis guid is made fresh on every import, so one taken
    # from another book matches nothing here and the refusal would be about
    # that instead of about what is being asked.
    cases = (
        ('1. shares bought with USD, the dollar split stating the asset basis guid',
         'buy_guid', lambda g: _with_guid(BUY_WITH_USD, 'Assets:USD Bank', g('asset'))),
        ('2. the same purchase stating no guid',
         'buy_plain', lambda g: BUY_WITH_USD),
        ('3. shares sold for USD — is a basis opened for what came in?',
         'sell', lambda g: BUY_WITH_USD + '\n' + SELL_FOR_USD),
        ('4. the loan repaid, the loan split stating the liability basis guid',
         'repay_guid',
         lambda g: _with_guid(REPAY_THE_LOAN, 'Liabilities:USD Loan', g('liability'))),
        ('5. the same repayment stating no guid',
         'repay_plain', lambda g: REPAY_THE_LOAN),
        ('6. 4,000 USD moved between two USD accounts, no guid — nothing is spent',
         'transfer', lambda g: TRANSFER_USD_TO_USD),
        ('7. shares bought, the transaction stated wholly in USD',
         'buy_usd', lambda g: BUY_STATED_IN_USD),
        ('8. shares bought and sold, both stated wholly in USD',
         'sell_usd', lambda g: BUY_STATED_IN_USD + '\n' + SELL_STATED_IN_USD),
        ('9. 1,000 USD sold for CAD, no guid — plain currency going out',
         'sell_cad', lambda g: SELL_USD_FOR_CAD),
        ('10. 1,000 USD sold for 7,800 HKD — neither side the book\'s own currency',
         'usd_hkd', lambda g: SELL_USD_FOR_HKD),
    ) + tuple(
        (f'{11 + n}. 1,000.00 USD turned into {quantity} {mnemonic}',
         f'pair_{mnemonic.lower()}',
         (lambda m=mnemonic, a=account, q=quantity, p=price:
          lambda g: _exchange(m, a, q, p))())
        for n, (mnemonic, account, quantity, price) in enumerate(EXCHANGES)
    )

    for label, book_name, build in cases:
        print(f'\n=== {label}')
        book = _book(runner, tmp_path, book_name)
        rows, _ = _bases(book)

        def guid_of(side, rows=rows):
            return next(r['guid'] for r in rows if r['side'] == side
                        and (side == 'liability' or r['account'].endswith('USD Bank')))

        applied = tmp_path / f'{book_name}_case.txt'
        applied.write_text(build(guid_of), encoding='utf-8')
        result = _run(runner, 'import', str(book), str(applied))

        print(f'  exit {result.exit_code}')
        for line in result.output.splitlines():
            if any(word in line for word in ('Error', 'error', 'refus', 'Errors:')):
                print(f'  | {line.strip()}')
        _invariant('after', book)
