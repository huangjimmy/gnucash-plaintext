"""Whether a rate added to the price database in memory, never saved, is the rate GnuCash's Balance Sheet uses (Q-042).

The book is `tests/fixtures/a_cad_book_with_usd_hkd_and_shares_priced_in_its_price_database.txt`,
imported to the path given as the first argument. It prices USD in CAD at 1.30
on 2025-05-05, 1.35 on 2026-03-31, 1.38 on 2026-07-15 and 1.42 on 2026-12-31,
all at 12:00 UTC, and holds 7,480.00 USD in Assets:USD Bank from 2026-09-30 on.

Each case opens the book read-only, adds USD in CAD 1.50 at the end of the
report date (the moment the report is for), source `user:price-editor`,
renders the Balance Sheet in CAD, prints what the page says about the USD bank
account, and closes without saving:

1. as of 2026-11-30: the book has no USD price that day;
2. as of 2026-12-31: the book already has USD in CAD 1.42 that day;
3. as of 2026-12-30: the book's nearest USD price is 12-31 at 12:00, twelve
   hours after the end of the day.

Then the book's prices are listed, to show nothing was saved.

Run: ./scripts/run.sh <tag> env PYTHONPATH=/workspace python3 tests/research/a_rates_file_as_prices_probe.py <book>
"""

import sys
from datetime import date

from infrastructure.gnucash.engine import GncNumericC, load_gnc_engine
from infrastructure.gnucash.utils import qof_pointer
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.gnucash_statements import render_balance_sheet
from tests.integration.prices_in_a_book import prices_in


def add_in_memory(book, commodity_mnemonic, currency_mnemonic, moment, num, denom):
    lib = load_gnc_engine()
    table = book.get_table()
    book_pointer = qof_pointer(book)
    price = lib.gnc_price_create(book_pointer)
    lib.gnc_price_begin_edit(price)
    lib.gnc_price_set_commodity(price, qof_pointer(table.lookup('CURRENCY', commodity_mnemonic)))
    lib.gnc_price_set_currency(price, qof_pointer(table.lookup('CURRENCY', currency_mnemonic)))
    lib.gnc_price_set_time64(price, moment)
    lib.gnc_price_set_value(price, GncNumericC(num, denom))
    lib.gnc_price_set_source_string(price, b'user:price-editor')
    lib.gnc_price_set_typestr(price, b'last')
    lib.gnc_price_commit_edit(price)
    added = lib.gnc_pricedb_add_price(lib.gnc_pricedb_get_db(book_pointer), price)
    lib.gnc_price_unref(price)
    return bool(added)


def usd_bank_line(page):
    """The `Assets:USD Bank` line and the keys written under it.

    The page is a block: the account line states what the account holds, and
    its `share_price:` and `value:` sit under it, a tab further in. Matching a
    bare `USD Bank` finds nothing at all, the line carrying the account's whole
    path.
    """
    lines = page.splitlines()
    for index, line in enumerate(lines):
        if line.strip().startswith('Assets:USD Bank '):
            said = [line.strip()]
            for nested in lines[index + 1:]:
                if not nested.startswith('\t\t'):
                    break
                said.append(nested.strip())
            return '; '.join(said)
    return '(no Assets:USD Bank line)'


def main():
    path = sys.argv[1]
    lib = load_gnc_engine()
    print(f'GnuCash {lib.gnc_version().decode()}')
    for as_of in (date(2026, 11, 30), date(2026, 12, 31), date(2026, 12, 30)):
        repo = GnuCashRepository(path)
        repo.open(SessionMode.READ_ONLY)
        try:
            moment = lib.gnc_dmy2time64_end(as_of.day, as_of.month, as_of.year)
            added = add_in_memory(repo.book, 'USD', 'CAD', moment, 15, 10)
            page = render_balance_sheet(repo.session, 'CAD', as_of)
            print(f'as of {as_of}: added={added}; {usd_bank_line(page)}')
        finally:
            repo.close()
    print('prices in the book afterwards:')
    for price in prices_in(path):
        print(f'  {price.commodity} in {price.currency} {price.time} {price.value} {price.source}')


if __name__ == '__main__':
    main()
