"""Buying a foreign currency with the book's own imports into a book that uses trading accounts.

A GnuCash user switches trading accounts on in File → Properties → Accounts,
and GnuCash then records every multi-currency transaction with trading splits
of its own making. Committing such a transaction creates those splits, and on
GnuCash 4.8 one of them is in the transaction's split list before its account
is attached — so anything that walks the splits of a transaction it has just
committed meets a split with no account.

`record_cost_bases` does exactly that, to open a cost basis for currency the
book has just bought. Measured on 4.8 before `split_commodity` answered for
such a split: importing 10,000.00 USD bought for 13,000.00 CAD gave
`'NoneType' object has no attribute 'GetCommodity'`, the import exited 1, and
the book was saved anyway — two transactions of the ledger missing, with the
rest imported.

The same ledger into the same book imports at exit 0 on 3.4, 3.8, 4.4, 4.13,
5.5, 5.10, 5.13, 5.14, 5.15 and 5.16, which is why this is run on every build
rather than gated to one.
"""

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.text_report_pages import (
    FIXTURES,
    a_book_using_trading_accounts,
    amount_of,
    key_of,
)

LEDGER = 'a_cad_book_with_usd_hkd_and_shares_priced_in_its_price_database.txt'


class TestAForeignPurchaseFundedFromTheBooksOwnCurrency:

    def test_every_transaction_of_the_ledger_is_imported(self, tmp_path):
        """The two purchases GnuCash makes trading splits for are among them."""
        book = a_book_using_trading_accounts(tmp_path)

        result = _run(CliRunner(), 'import', str(book), str(FIXTURES / LEDGER))

        assert result.exit_code == 0, result.output
        assert 'GetCommodity' not in result.output, result.output
        assert 'Errors:       0' in result.output, result.output

    def test_what_the_purchases_bought_is_on_the_balance_sheet(self, tmp_path):
        """10,000.00 USD bought at 1.30 and 5,500.00 HKD bought at 5.5 per CAD.

        Both are funded from the CAD bank, which is what makes them
        multi-currency transactions in a CAD book and gives GnuCash trading
        splits to create.
        """
        book = a_book_using_trading_accounts(tmp_path, LEDGER)

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-12-31')

        assert result.exit_code == 0, result.output
        assert amount_of(result.output, 'Assets:USD Bank') == '7480.00 USD'
        assert amount_of(result.output, 'Assets:HKD Bank') == '5500.00 HKD'
        assert key_of(result.output, 'total_liabilities_and_equity') == '38532.80 CAD'
