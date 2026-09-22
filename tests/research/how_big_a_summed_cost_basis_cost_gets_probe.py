"""Probe: how large does a currency's cost get once its cost bases are added up?

`services/gnucash_statements.py` writes that total into the report's Scheme
source verbatim, as `{cost.numerator}/{cost.denominator}`. So whatever exact
rational Python accumulated is what the report rounds, and `gnc-numeric-create`
takes two `gint64`: a numerator past 9223372036854775807 cannot be handed to
GnuCash's own rounding at all.

The question is whether an ordinary book gets there, and after how many cost
bases.

**An untouched cost basis cannot get there, and that is worth saying, because
it looks as though it should.** A cost is a value over an amount — 3,771.28 CAD
over 2,720.00 USD is 2773/2000 — an awkward fraction with a four-figure
denominator. But an untouched basis has a balance equal to its own amount, so
`balance * cost` cancels the division and gives back exactly the value it came
from: money, at two places. Summing money gives money. Measured on the five
earnings below, the running total never needed more than 21 bits.

**A basis drawn part of the way is the case that grows.** Once some of the
currency is spent the balance is no longer the amount, nothing cancels, and the
term keeps a denominator about the size of the original amount in cents.
Several such bases add by lowest common multiple, and that is what outgrows a
64-bit argument.

This measures both states: five earnings left alone, then part of each one
spent, reporting after every basis what the running numerator is, how many bits
it needs, and whether it has passed what the engine accepts.

Measured on GnuCash 5.10:

```
                        untouched          part drawn
    after 1 basis        17 bits            30 bits
    after 2              20                 42
    after 3              21                 57
    after 4              20                 69   past INT64_MAX
    after 5              19                 75   past INT64_MAX
```

Left alone, five bases never need more than 21 bits. Drawn on, the fourth
crosses what `gnc-numeric-create` accepts, and the total the report is handed
is 33127907093144872216827/2354926672531400000 — 14,067.49 CAD written in
seventy-five bits.

**GnuCash itself never holds such a number**, so the 64-bit argument is not a
defect of GnuCash's: a `gnc_numeric` is an int64 pair, every figure it stores
sits at its commodity's smallest unit, and its denominators stay at 100. This
one exists because these terms are added as exact rationals instead.

    ./scripts/test.sh latest   tests/research/how_big_a_summed_cost_basis_cost_gets_probe.py
    ./scripts/test.sh debian10 tests/research/how_big_a_summed_cost_basis_cost_gets_probe.py
"""

import datetime
from fractions import Fraction

from click.testing import CliRunner

from cli.main import cli

LEDGER = 'tests/fixtures/a_cad_book_billing_us_customers_five_times.txt'
AS_OF = datetime.date(2026, 12, 31)

USD_BANK = 'Assets:USD Bank'
CAD_BANK = 'Assets:CAD Bank'

INT64_MAX = 9223372036854775807

# What to draw off each basis, and the day it goes. Chosen to leave a balance
# that is neither the amount nor a round figure, which is the whole point: an
# untouched basis cancels its own division and stays small.
DRAWS = (
    ('2026-11-02', Fraction('333.33')),
    ('2026-11-03', Fraction('245.55')),
    ('2026-11-04', Fraction('1110.77')),
    ('2026-11-05', Fraction('87.29')),
    ('2026-11-06', Fraction('1562.83')),
)

# What the dollars fetch the day they are sold. One rate for all five, so the
# only thing varying between the disposals is the basis each draws on.
SOLD_AT = Fraction('1.41')


def _cents(value):
    """`value` at two places, rounded half up. Positive figures only.

    This picks the stated value of a disposal in a generated ledger — any legal
    cent figure would do — so it is arithmetic on exact Fractions rather than
    anything that should be mistaken for the money rounding the report performs.
    """
    scaled = value * 100
    whole = scaled.numerator // scaled.denominator
    if scaled - whole >= Fraction(1, 2):
        whole += 1
    return Fraction(whole, 100)


def _money(value):
    """An exact cents Fraction written the way a ledger states it."""
    cents = _cents(value)
    return f'{cents.numerator // cents.denominator}.{cents.numerator * 100 // cents.denominator % 100:02d}'


def _bases(book_path):
    """Every cost basis of the book, walked the way the totals walk it."""
    from repositories.gnucash_repository import GnuCashRepository, SessionMode
    from services.foreign_currency import (
        cost_basis_balance_of,
        cost_of,
        establishes_cost_basis,
        iter_splits,
        split_commodity,
        split_guid,
    )

    found = []
    repo = GnuCashRepository(str(book_path))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        for split in iter_splits(repo.book):
            if not establishes_cost_basis(split):
                continue
            if split.GetParent().GetDate().date() > AS_OF:
                continue
            balance = cost_basis_balance_of(split)
            if balance is None:
                continue
            amount = Fraction(split.GetAmount().num(), split.GetAmount().denom())
            found.append({
                'guid': split_guid(split),
                'account': split.GetAccount().get_full_name(),
                'currency': split_commodity(split),
                'side': 'asset' if amount > 0 else 'liability',
                'amount': amount,
                'balance': balance,
                'cost': cost_of(split),
            })
    finally:
        repo.close()
    return found


def _totals(book_path):
    """Per currency and side, the balance and the cost the balance sheet prints.

    Added up from the rows here rather than read from a function of its own,
    because that is how the report reaches the figure: the page lists every
    basis and its totals are the rows added together.
    """
    from repositories.gnucash_repository import GnuCashRepository, SessionMode
    from services.foreign_currency import cost_basis_items_by_currency_and_side

    repo = GnuCashRepository(str(book_path))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        rows = cost_basis_items_by_currency_and_side(repo.book, AS_OF)
    finally:
        repo.close()

    totals: dict = {}
    for row in rows:
        sides = totals.setdefault(row['currency'], {})
        held, spent = sides.get(row['side'], (Fraction(0), Fraction(0)))
        sign = 1 if row['side'] == 'asset' else -1
        sides[row['side']] = (held + sign * row['balance'],
                              spent + sign * row['balance'] * row['cost'])
    return totals


def _report(label, bases, totals):
    print()
    print(f'==== {label} ====')
    print(f'{len(bases)} cost bases')
    for basis in bases:
        state = 'untouched' if basis['balance'] == basis['amount'] else 'part drawn'
        print(f'  {basis["account"]}: amount {_money(basis["amount"])} '
              f'{basis["currency"]}, balance {_money(basis["balance"])}, '
              f'cost {basis["cost"].numerator}/{basis["cost"].denominator}  ({state})')

    print()
    print('  added one at a time, the way the totals are built:')
    running = Fraction(0)
    for index, basis in enumerate(bases, start=1):
        running += basis['balance'] * basis['cost']
        over = 'OVER INT64' if running.numerator > INT64_MAX else 'ok'
        print(f'    after {index}: numerator {running.numerator.bit_length():4} bits, '
              f'denominator {running.denominator.bit_length():4} bits   {over}')

    print()
    print('  what the report is handed:')
    for currency, sides in sorted(totals.items()):
        for side, (_quantity, cost) in sorted(sides.items()):
            over = 'OVER INT64' if cost.numerator > INT64_MAX else 'ok'
            print(f'    {currency} {side}: cost is {float(cost):.2f} CAD, '
                  f'numerator {cost.numerator.bit_length()} bits   {over}')
            print(f'      {cost.numerator}/{cost.denominator}')


def test_how_big_the_cost_gets(tmp_path, capsys):
    book = tmp_path / 'probe.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), LEDGER])
    assert made.exit_code == 0, made.output

    untouched = _bases(book)
    with capsys.disabled():
        _report('five earnings banked, nothing spent', untouched, _totals(book))

    # Draw part of each basis, valued at what that basis cost, with the
    # difference against what the dollars fetched taken by the residual.
    blocks = []
    for (when, draw), basis in zip(DRAWS, untouched):
        assert basis['balance'] >= draw, (basis, draw)
        blocks.append(
            f'{when} * "Dollars sold against the basis opened for {_money(basis["amount"])}"\n'
            f'\tcurrency.mnemonic: "CAD"\n'
            f'\t{USD_BANK} -{_money(draw)} USD\n'
            f'\t\taccount.commodity.mnemonic: "USD"\n'
            f'\t\tshare_price: "{basis["cost"].numerator}/{basis["cost"].denominator}"\n'
            f'\t\tvalue: "-{_money(draw * basis["cost"])}"\n'
            f'\t\tcost_basis_split_guid: "{basis["guid"]}"\n'
            f'\t{CAD_BANK} {_money(draw * SOLD_AT)} CAD\n'
            f'\tIncome:FX Gain $residual$ CAD\n')

    ledger = tmp_path / 'spend.txt'
    ledger.write_text('\n'.join(blocks), encoding='utf-8')
    spent = CliRunner().invoke(cli, ['import', str(book), str(ledger)])
    assert spent.exit_code == 0, spent.output

    with capsys.disabled():
        _report('part of each basis spent', _bases(book), _totals(book))
        print()
        print(f'INT64_MAX is {INT64_MAX}, {INT64_MAX.bit_length()} bits')
