"""Q-035: `$residual$` — a split that takes what the others leave over.

An FX gain or loss is the difference between what a currency cost and what it
fetched, which the transaction already determines. Writing `$residual$` in
place of the amount books it, so nobody hand-computes a tax figure.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli


def _basis_on(listing: str, account_fragment: str) -> str:
    """The guid of the cost basis sitting on the account whose name contains
    `account_fragment`."""
    for line in listing.splitlines():
        if account_fragment in line:
            match = re.search(r'\b([0-9a-f]{32})\b', line)
            if match:
                return match.group(1)
    raise AssertionError(f'no cost basis on {account_fragment!r} in:\n{listing}')


def _book_with_usd(runner, tmp_path):
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(book),
                                 'tests/fixtures/fx_buy_and_borrow_usd.txt',
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return book


def _import(runner, book, fixture):
    return runner.invoke(cli, ['import', str(book), fixture])


def _export_text(runner, book, out):
    result = runner.invoke(cli, ['export', str(book), str(out)])
    assert result.exit_code == 0, result.output
    return out.read_text()


def test_residual_books_the_difference(tmp_path):
    """100 USD that cost 135.00 CAD, sold for 139.00: a 4.00 CAD gain lands on
    the named account rather than in GnuCash's own Imbalance account."""
    runner = CliRunner()
    book = _book_with_usd(runner, tmp_path)
    fixture = tmp_path / 'sale.txt'
    fixture.write_text(
        Path('tests/fixtures/fx_sell_usd_one_cost_basis.txt').read_text()
        .replace('\t\tcost_basis_split_guid: "{basis_guid}"\n', '')
        .replace('share_price: "1.40"', 'share_price: "1.35"')
        .replace('value: "-140.00"', 'value: "-135.00"'))
    result = _import(runner, book, str(fixture))
    assert result.exit_code == 0, result.output

    exported = _export_text(runner, book, tmp_path / 'out.txt')
    assert 'Income:FX Gain -4.00 CAD' in exported, exported
    assert 'Imbalance' not in exported, exported


def test_two_residuals_are_refused(tmp_path):
    runner = CliRunner()
    book = _book_with_usd(runner, tmp_path)
    result = _import(runner, book, 'tests/fixtures/fx_two_residuals.txt')
    message = result.output + str(result.exception)
    assert 'only one split' in message or 'two cannot be resolved' in message, message


def test_residual_on_an_already_balanced_transaction_is_refused(tmp_path):
    runner = CliRunner()
    book = _book_with_usd(runner, tmp_path)
    result = _import(runner, book,
                     'tests/fixtures/fx_residual_on_balanced_transaction.txt')
    message = result.output + str(result.exception)
    assert 'nothing to take' in message, message


def test_residual_on_an_account_in_another_currency_is_refused(tmp_path):
    runner = CliRunner()
    book = _book_with_usd(runner, tmp_path)
    result = _import(runner, book,
                     'tests/fixtures/fx_residual_on_foreign_account.txt')
    message = result.output + str(result.exception)
    assert '1:1' in message or 'USD account' in message, message


def test_settling_a_usd_bill_with_usd_cash_realizes_the_difference(tmp_path):
    """The bill-side mirror of a sale: no CAD is involved, both sides are USD,
    and the entry only balances once the 5.00 CAD difference between the two
    costs is booked."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(book),
                                 'tests/fixtures/fx_usd_bill_cad_expense.txt',
                                 '--include-business-objects',
                                 '--fx-rates', 'tests/fixtures/fx_rates_usd_dated.yaml'])
    assert result.exit_code == 0, result.output

    # Buy the USD that will settle it, at a cheaper rate than the bill booked.
    buy = tmp_path / 'buy.txt'
    buy.write_text(
        '2026-02-01 * "Buy 100 USD at 1.35"\n'
        '\tcurrency.mnemonic: "CAD"\n'
        '\tAssets:Bank:USD 100.00 USD\n'
        '\t\taccount.commodity.mnemonic: "USD"\n'
        '\t\tshare_price: "1.35"\n'
        '\t\tvalue: "135.00"\n'
        '\tAssets:Bank -135.00 CAD\n'
        '\t\taccount.commodity.mnemonic: "CAD"\n'
        '\t\tshare_price: "1"\n'
        '\t\tvalue: "-135.00"\n')
    assert _import(runner, book, str(buy)).exit_code == 0

    listing = runner.invoke(cli, ['fx-balances', str(book)])
    assert listing.exit_code == 0, listing.output
    # The listing is in no particular order, so each basis is picked by the
    # account it sits on: the bill's payable, and the cash bought to settle it.
    bill_basis = _basis_on(listing.output, 'Accounts Payable')
    cash_basis = _basis_on(listing.output, 'Assets:Bank:USD')

    settle = tmp_path / 'settle.txt'
    settle.write_text(
        Path('tests/fixtures/fx_settle_usd_bill_with_usd_cash.txt').read_text()
        .replace('{bill_basis}', bill_basis)
        .replace('{cash_basis}', cash_basis))
    result = _import(runner, book, str(settle))
    assert result.exit_code == 0, result.output
    assert 'error:' not in result.output, result.output

    exported = _export_text(runner, book, tmp_path / 'out.txt')
    assert 'Income:FX Gain -5.00 CAD' in exported, exported

    after = runner.invoke(cli, ['fx-balances', str(book)])
    assert 'Available USD: 0.00' in after.output, after.output
