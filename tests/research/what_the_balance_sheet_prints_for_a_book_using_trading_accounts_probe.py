"""What the balance sheet prints for a book that uses trading accounts, on this build (Q-042).

A GnuCash user switches trading accounts on in File → Properties → Accounts →
"Use Trading Accounts", and GnuCash then records every multi-currency
transaction with trading splits. Nothing in gnucash-plaintext sets the option,
so this makes such a book directly:

1. a new book, with `Accounts / Use Trading Accounts` set to `t`, saved;
2. `tests/fixtures/a_cad_book_with_usd_hkd_and_shares_priced_in_its_price_database.txt`
   imported into it.

Then it prints whether the engine reads the option as on, which Trading
accounts the book holds, the plaintext balance sheet at the fiscal year end,
and the lines of GnuCash's shipped Balance Sheet page that mention trading.

The year end is the date to ask at. The book buys its US dollars in May 2025,
its Hong Kong dollars in June and its shares in August, each at the price it
pays, so a page drawn before those holdings are repriced carries no gain of
either kind. The prices that move them are dated 2026.

Run: ./scripts/run.sh <tag> env PYTHONPATH=/workspace python3 tests/research/what_the_balance_sheet_prints_for_a_book_using_trading_accounts_probe.py
"""

import re
import tempfile
from pathlib import Path

from click.testing import CliRunner
from gnucash import ACCT_TYPE_BANK, ACCT_TYPE_TRADING, Account

# The suite's `_patch_session_save`: every save deletes the backup a save in
# the same second would collide with.
import tests.conftest  # noqa: F401
from cli.main import cli
from infrastructure.gnucash.kvp import get_book_string_option, write_book_string_option
from repositories.gnucash_repository import GnuCashRepository, SessionMode

FIXTURE = 'tests/fixtures/a_cad_book_with_usd_hkd_and_shares_priced_in_its_price_database.txt'


def main():
    work = Path(tempfile.mkdtemp())
    book = work / 'trading.gnucash'

    repo = GnuCashRepository(str(book))
    repo.open(SessionMode.NEW)
    write_book_string_option(repo.book, 'Accounts', 'Use Trading Accounts', 't')
    # A new book holding nothing but a book option writes no file when saved,
    # as one holding nothing but prices does (Q-041), so it is given an
    # account: a top-level CAD bank, which keeps the book kept in CAD.
    petty_cash = Account(repo.book)
    petty_cash.BeginEdit()
    petty_cash.SetName('Petty Cash')
    petty_cash.SetType(ACCT_TYPE_BANK)
    petty_cash.SetCommodity(repo.book.get_table().lookup('CURRENCY', 'CAD'))
    repo.book.get_root_account().append_child(petty_cash)
    petty_cash.CommitEdit()
    repo.save()
    repo.close()

    imported = CliRunner().invoke(cli, ['import', str(book), FIXTURE])
    print('import exit', imported.exit_code, imported.output.strip().splitlines()[-1:])

    repo = GnuCashRepository(str(book))
    repo.open(SessionMode.READ_ONLY)
    try:
        print('option read back:', get_book_string_option(repo.book, 'Accounts', 'Use Trading Accounts'))
        print('book.use_trading_accounts():', repo.book.use_trading_accounts())
        trading = [account.get_full_name() for account in repo.book.get_root_account().get_descendants()
                   if account.GetType() == ACCT_TYPE_TRADING]
        print('trading accounts:', trading)
    finally:
        repo.close()

    text = CliRunner().invoke(cli, ['balance-sheet', str(book), '--as-of', '2026-12-31'])
    print('--- plaintext balance sheet, exit', text.exit_code)
    print(text.output)

    html = work / 'page.html'
    shipped = CliRunner().invoke(cli, ['balance-sheet', str(book), '--as-of', '2026-12-31',
                                       '--output-format', 'html', '--output', str(html)])
    print('--- GnuCash Balance Sheet page, exit', shipped.exit_code)
    if html.exists():
        page = html.read_text(encoding='utf-8')
        for match in re.finditer(r'Trading[^<]*', page):
            print('  ', match.group(0))
        for match in re.finditer(r'C\$[0-9,.-]+', page):
            print('  ', match.group(0), end='')
        print()


if __name__ == '__main__':
    main()
