"""Ask a book whether its share purchase was costed by derivation or by carrying.

Q-046 says the cost of spent currency travels onto what it bought. Two paths can
put a book-currency cost on a share split, and they look the same afterwards:

* `derived_cost_of` reads it out of the transaction, which can answer whenever
  any split of that transaction carries a figure in the book's own currency —
  including a fee split that is not the shares;
* `carry_the_cost_to_what_it_bought` writes it from the cost basis the currency
  left, which runs only where the transaction states no such figure at all.

This prints, for each split of the account passed, which of the two the book is
in — so a fixture meant to exercise the carrying can be checked rather than
assumed.

    ./scripts/run.sh latest python3 tests/research/how_a_share_purchase_gets_its_cost_probe.py <book> <account name>
"""

import sys

import tests.conftest  # noqa: F401  (patches Session.save so a probe can reopen)
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import (
    _is_a_holding_arriving_uncosted,
    derived_cost_of,
    iter_splits,
    stated_cost_of,
)


def main(path, wanted):
    repo = GnuCashRepository(path)
    repo.open(SessionMode.READ_ONLY)
    try:
        for split in iter_splits(repo.book):
            account = split.GetAccount()
            if account is None or account.GetName() != wanted:
                continue
            transaction = split.GetParent()
            print(f'{transaction.GetDate().date()}  {transaction.GetDescription()}')
            print(f'    derived_cost_of    = {derived_cost_of(split)}')
            print(f'    stated_cost_of     = {stated_cost_of(split)}')
            print(f'    arriving uncosted  = {_is_a_holding_arriving_uncosted(split)}')
    finally:
        repo.close()


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
