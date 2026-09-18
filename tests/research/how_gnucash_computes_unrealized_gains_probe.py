"""The two figures GnuCash's Balance Sheet subtracts to get Unrealized Gains.

`balance-sheet.scm` computes the figure as

    asset-balance − liability-balance
      − (gnc:accounts-get-comm-total-assets assets+liabilities get-total-value-fn)

    (define (get-total-value-fn account)
      (gnc:account-get-comm-value-at-date account reportdate #f))

so there are two collectors per account: the **balance**, in the account's own
commodity, and the sum of its splits' **values**, each value stated in its own
transaction's currency. Both are converted at the report price and subtracted.

This prints both, per account, so the subtraction can be done by hand against
what GnuCash's own page states. Run it against a book and a price:

    python3 tests/research/how_gnucash_computes_unrealized_gains_probe.py <book> <USD price in the book's currency>
"""

import sys
from fractions import Fraction

from infrastructure.gnucash.utils import get_account_full_name
from repositories.gnucash_repository import GnuCashRepository, SessionMode


def _frac(number) -> Fraction:
    return Fraction(number.num(), number.denom())


def _every_account(account):
    for child in account.get_children():
        yield child
        yield from _every_account(child)


def main(path: str, price: str) -> None:
    rate = Fraction(price)
    repo = GnuCashRepository(path)
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        balances: dict = {}
        values: dict = {}
        for account in _every_account(repo.book.get_root_account()):
            name = get_account_full_name(account)
            if not name.startswith(("Assets", "Liabilities")):
                continue
            held = account.GetCommodity().get_mnemonic()
            balance = _frac(account.GetBalance())
            by_currency: dict = {}
            for split in account.GetSplitList():
                currency = split.GetParent().GetCurrency().get_mnemonic()
                by_currency[currency] = (by_currency.get(currency, Fraction(0))
                                         + _frac(split.GetValue()))
            print(f"{name}")
            print(f"    balance      {float(balance):>12.4f} {held}")
            for currency, total in sorted(by_currency.items()):
                print(f"    split values {float(total):>12.4f} {currency}")
            balances[held] = balances.get(held, Fraction(0)) + balance
            for currency, total in by_currency.items():
                values[currency] = values.get(currency, Fraction(0)) + total
    finally:
        repo.close()

    def converted(totals: dict) -> Fraction:
        return sum((amount * rate if currency == "USD" else amount)
                   for currency, amount in totals.items())

    print()
    print(f"balance collector    { {k: str(v) for k, v in balances.items()} }")
    print(f"value collector      { {k: str(v) for k, v in values.items()} }")
    print(f"balances at {price}   {float(converted(balances)):.4f}")
    print(f"values at {price}     {float(converted(values)):.4f}")
    print(f"difference           {float(converted(balances) - converted(values)):.4f}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
