"""Buying a foreign currency with the book's own imports into a book that uses trading accounts.

A GnuCash user switches trading accounts on in File → Properties → Accounts,
and GnuCash then records every multi-currency transaction with trading splits
of its own making. Committing such a transaction creates those splits, and on
GnuCash 4.8 one of them is in the transaction's split list before its account
is attached — so anything that walks the splits of a transaction it has just
committed meets a split with no account.

`record_cost_bases` does exactly that, to open a cost basis for currency the
book has just bought. Measured on 4.8 before `split_commodity` answered for
such a split: importing 10,000.00 USD bought for 13,000.00 CAD raised
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


HKD_PURCHASE = r'2025-06-08 \* "Buy 5,500\.00 HKD at 5\.5 per CAD"\n(?:\t[^\n]*\n)*'


def _exported(book, tmp_path):
    ledger = tmp_path / 'exported.txt'
    done = _run(CliRunner(), 'export', str(book), str(ledger))
    assert done.exit_code == 0, done.output
    return ledger.read_text()


def test_the_books_own_export_imports_back_into_it(tmp_path):
    """Its `Trading:CURRENCY:…` accounts are written with type `Trading`, GnuCash's own.

    The import did not know the type, and refused each of those accounts,
    so the book's own export imported back with four errors and exited 1.
    """
    book = a_book_using_trading_accounts(tmp_path, LEDGER)
    ledger = tmp_path / 'again.txt'
    ledger.write_text(_exported(book, tmp_path))

    result = _run(CliRunner(), 'import', str(book), str(ledger), '--strategy', 'update')

    assert result.exit_code == 0 and 'Errors:       0' in result.output, result.output
    assert 'Updated:      0' in result.output, result.output


def test_an_edit_to_a_purchase_is_balanced_by_gnucash(tmp_path):
    """The HKD purchase costs 1,100.00 CAD where it cost 1,000.00, its trading splits left as exported.

    Nothing draws on its cost basis, so the edit is read as new. The new
    version's values balance with the trading splits as they were, since the
    two trading splits' values cancel each other, and GnuCash sets them
    to the new figure when the edit is committed.
    """
    import re

    book = a_book_using_trading_accounts(tmp_path, LEDGER)
    text = _exported(book, tmp_path)
    block = re.search(HKD_PURCHASE, text).group(0)
    edited = (block.replace('value: "1000.00"', 'value: "1100.00"', 1)
              .replace('Assets:CAD Bank -1000.00 CAD', 'Assets:CAD Bank -1100.00 CAD'))
    edit = tmp_path / 'edit.txt'
    edit.write_text(text.replace(block, edited))

    result = _run(CliRunner(), 'import', str(book), str(edit), '--strategy', 'update')

    assert result.exit_code == 0 and 'Updated:      1' in result.output, result.output
    after = re.search(HKD_PURCHASE, _exported(book, tmp_path)).group(0)
    assert 'Trading:CURRENCY:CAD 1100.00 CAD' in after, after
    assert 'value: "-1100.00"' in after, after
    checked = _run(CliRunner(), 'fx-balances', str(book), '--verify-costs')
    assert 'every cost agrees with the figures it is derived from' in checked.output, checked.output


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
        multi-currency transactions in a CAD book, for which GnuCash creates
        trading splits.
        """
        book = a_book_using_trading_accounts(tmp_path, LEDGER)

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-12-31')

        assert result.exit_code == 0, result.output
        assert amount_of(result.output, 'Assets:USD Bank') == '7480.00 USD'
        assert amount_of(result.output, 'Assets:HKD Bank') == '5500.00 HKD'
        assert key_of(result.output, 'total_liabilities_and_equity') == '38532.80 CAD'
