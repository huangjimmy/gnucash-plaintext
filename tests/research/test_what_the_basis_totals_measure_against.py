"""Probe: Σ(basis balances) against the book's own holdings, per currency.

`--verify-costs` checks each basis against the ledger it came from, one basis
at a time. The question this probe asks is the book-wide one: for each foreign
currency, does the sum of its bases' balances equal what the book holds in
that currency?

Four readings of "what the book holds" were computed over the same books, to
find which — if any — the totals follow:

* **all** — every split whose account is denominated in that currency
* **cash** — asset and liability accounts only, excluding receivable/payable
* **owed-in** — cash, plus receivable/payable counted in their normal
  direction only (what an invoice owes the book, not what the book owes back)
* **in-less-sold** — what every basis brought in, less every split naming one

Measured:

```
                                    bases       all      cash   owed-in  in-less-sold
buy and borrow                 USD 200.00    200.00 ✓  200.00 ✓  200.00 ✓  200.00 ✓
invoice overpaid into USD bank USD 200.00    100.00    200.00 ✓  300.00    200.00 ✓
invoice overpaid into CAD bank USD 100.00   -100.00      0.00    100.00 ✓  100.00 ✓
bill overpaid from USD bank    USD 200.00   -100.00   -200.00   -100.00    200.00 ✓
invoice settled into HKD bank  HKD 780.00    780.00 ✓  780.00 ✓  780.00 ✓  780.00 ✓
                               USD   0.00      0.00 ✓    0.00 ✓  100.00      0.00 ✓
bill settled from HKD bank     USD   0.00      0.00 ✓    0.00 ✓  100.00      0.00 ✓
prepayment arriving as CAD     USD 100.00   -100.00      0.00      0.00    100.00 ✓
```

**No account-balance reading matches.** Currency that exists only as an
obligation is the reason: a customer's credit is money the book holds *and*
owes back, so the receivable nets it away while the bank still shows it; a
prepayment taken in CAD leaves the book holding no USD at all, and its basis is
the only record that 100.00 USD is owed. Summing account balances asks a
different question, and `docs/multi-currency.md` says so — an account balance
and a basis balance are separate quantities.

**The ledger reading matches on every shape.** What the bases hold between
them equals what they brought in less what the splits naming them took, per
currency — two sides written by different mechanisms (a KVP on one, the
transactions themselves on the other), so they can disagree, which is what
makes it worth checking.
"""

from fractions import Fraction

import pytest
from click.testing import CliRunner

from cli.main import cli

RATES = 'tests/fixtures/fx_rates_usd_dated.yaml'
BOTH = 'tests/fixtures/fx_rates_usd_and_hkd.yaml'

LEDGERS = [
    ('buy and borrow', 'tests/fixtures/fx_buy_and_borrow_usd.txt', RATES),
    ('invoice overpaid into a USD bank',
     'tests/fixtures/fx_invoice_usd_overpaid_into_usd_bank.txt', RATES),
    ('invoice overpaid into a CAD bank',
     'tests/fixtures/fx_invoice_usd_overpaid_into_cad_bank.txt', RATES),
    ('bill overpaid from a USD bank',
     'tests/fixtures/fx_bill_usd_overpaid_from_usd_bank.txt', RATES),
    ('invoice settled into an HKD bank',
     'tests/fixtures/fx_usd_invoice_settled_into_an_hkd_bank.txt', BOTH),
    ('bill settled from an HKD bank',
     'tests/fixtures/fx_usd_bill_settled_from_an_hkd_bank.txt', BOTH),
    ('prepayment arriving as CAD',
     'tests/fixtures/fx_prepayment_arriving_as_cad.txt', None),
]


def _holdings(book_path):
    """The three readings of what the book holds, per currency."""
    from gnucash import Query, Transaction
    from gnucash.gnucash_core_c import ACCT_TYPE_PAYABLE, ACCT_TYPE_RECEIVABLE

    from repositories.gnucash_repository import GnuCashRepository, SessionMode
    from services.foreign_currency import (
        BASE_CURRENCY,
        cost_basis_balance_of,
        cost_basis_guid_of,
        establishes_cost_basis,
        iter_splits,
        split_commodity,
    )

    readings = {'all': {}, 'cash': {}, 'owed-in': {}, 'bases': {},
                'in-less-sold': {}}
    repo = GnuCashRepository(str(book_path))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        for raw in query.run():
            for split in Transaction(instance=raw).GetSplitList():
                currency = split_commodity(split)
                if not currency or currency == BASE_CURRENCY:
                    continue
                account = split.GetAccount()
                if account.GetCommodity().get_namespace() != 'CURRENCY':
                    continue
                amount = Fraction(split.GetAmount().num(),
                                  split.GetAmount().denom())
                kind = account.GetType()
                readings['all'][currency] = (
                    readings['all'].get(currency, Fraction(0)) + amount)
                if kind in (ACCT_TYPE_RECEIVABLE, ACCT_TYPE_PAYABLE):
                    normal = amount > 0 if kind == ACCT_TYPE_RECEIVABLE else amount < 0
                    if normal:
                        readings['owed-in'][currency] = (
                            readings['owed-in'].get(currency, Fraction(0))
                            + abs(amount))
                    continue
                readings['cash'][currency] = (
                    readings['cash'].get(currency, Fraction(0)) + amount)
                readings['owed-in'][currency] = (
                    readings['owed-in'].get(currency, Fraction(0)) + amount)
        query.destroy()

        # What the ledger says on its own, with no `cost_basis_balance` read at
        # all: every
        # basis's own amount, less every split that names one — which is what
        # a drawdown records, written on the selling split by the file.
        for split in iter_splits(repo.book):
            currency = split_commodity(split)
            if not currency or currency == BASE_CURRENCY:
                continue
            amount = Fraction(split.GetAmount().num(), split.GetAmount().denom())
            if cost_basis_guid_of(split):
                readings['in-less-sold'][currency] = (
                    readings['in-less-sold'].get(currency, Fraction(0))
                    - abs(amount))
                continue
            if not establishes_cost_basis(split):
                continue
            readings['in-less-sold'][currency] = (
                readings['in-less-sold'].get(currency, Fraction(0)) + abs(amount))
            balance = cost_basis_balance_of(split)
            if balance is None:
                continue
            readings['bases'][currency] = (
                readings['bases'].get(currency, Fraction(0)) + balance)
    finally:
        repo.close()
    return readings


@pytest.mark.parametrize('name,ledger,rates', LEDGERS,
                         ids=[entry[0] for entry in LEDGERS])
def test_the_ledger_reading_is_the_one_that_matches(name, ledger, rates, tmp_path):
    """Only `in-less-sold` agrees with the totals, on all seven shapes."""
    book = tmp_path / 'probe.gnucash'
    args = ['import', '--new', str(book), ledger, '--include-business-objects']
    if rates:
        args += ['--fx-rates', rates]
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == 0, f'{name}: {result.output}'

    readings = _holdings(book)
    assert readings['bases'], f'{name}: no basis with a balance to compare'
    for currency, total in sorted(readings['bases'].items()):
        assert readings['in-less-sold'].get(currency) == total, (
            f'{name}: the {currency} bases hold {total} between them, while '
            f'the ledger says {readings["in-less-sold"].get(currency)} '
            f'arrived less what was sold')

    # And through the check that ships, on the same seven books. The
    # measurement above is this file's own arithmetic; a warning that fires on
    # correct books is worse than no warning, and only the real function can
    # say whether it does.
    assert _what_the_check_says(book) == [], name


def _what_the_check_says(book_path):
    from repositories.gnucash_repository import GnuCashRepository, SessionMode
    from services.foreign_currency import currency_totals_that_disagree

    repo = GnuCashRepository(str(book_path))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        return currency_totals_that_disagree(repo.book)
    finally:
        repo.close()
