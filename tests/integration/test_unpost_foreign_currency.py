"""Q-035: unposting a record whose cost basis something is measured against.

A posted record's A/R or A/P split *is* the cost basis, and unposting destroys
the posting transaction. Anything already measured against that basis would be
left naming a split the book no longer holds, and re-posting mints a new one
with the whole amount available again — so a sale of 40 of 100 USD silently
becomes 100 USD available, currency the book no longer has.

Refused, rather than warned about, because nothing downstream would notice.
"""

import re
import time
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

RATES = 'tests/fixtures/fx_rates_usd_dated.yaml'


def _run(runner, *args):
    # Two saves inside one second collide on the backup filename.
    time.sleep(1.1)
    return runner.invoke(cli, list(args))


def _balances(runner, book):
    result = runner.invoke(cli, ['fx-balances', str(book)])
    assert result.exit_code == 0, result.output
    return result.output


def _basis_guid(runner, book):
    return re.search(r'\b([0-9a-f]{32})\b', _balances(runner, book)).group(1)


def _basis_on(listing: str, account_fragment: str) -> str:
    """The guid of the cost basis sitting on the account whose name contains
    `account_fragment` — the listing is in no particular order."""
    for line in listing.splitlines():
        if account_fragment in line:
            match = re.search(r'\b([0-9a-f]{32})\b', line)
            if match:
                return match.group(1)
    raise AssertionError(f'no cost basis on {account_fragment!r} in:\n{listing}')


def test_unposting_an_invoice_whose_basis_was_sold_is_refused(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert _run(runner, 'import', '--new', str(book),
                'tests/fixtures/fx_usd_invoice_cad_income.txt',
                '--include-business-objects', '--fx-rates', RATES).exit_code == 0

    basis = _basis_guid(runner, book)
    sale = tmp_path / 'sale.txt'
    # The invoice is not paid yet, so the sale says so deliberately — this test
    # is about what unposting does to a basis in use, not about that rule.
    sale.write_text(
        Path('tests/fixtures/fx_sell_usd_partial.txt').read_text()
        .replace('{basis_a}', basis)
        .replace(f'cost_basis_split_guid: "{basis}"',
                 f'cost_basis_split_guid: "{basis}"\n\t\tcost_basis_force: true')
        .replace('share_price: "1.35"', 'share_price: "1.40"')
        .replace('value: "-54.00"', 'value: "-56.00"'))
    assert _run(runner, 'import', str(book), str(sale)).exit_code == 0
    assert 'Total USD basis balance: 60.00 USD' in _balances(runner, book)

    result = _run(runner, 'unpost-invoices', str(book), 'INV-USD-001')
    assert result.exit_code != 0, result.output
    message = result.output + str(result.exception)
    assert 'cost basis' in message, message
    assert 'Sell 40 USD' in message, message

    # And the basis is untouched: nothing was half-done.
    assert 'Total USD basis balance: 60.00 USD' in _balances(runner, book)


def test_unposting_a_bill_whose_basis_was_settled_is_refused(tmp_path):
    """The bill mirror: the A/P split is the basis, and settling it with USD
    cash measures against it."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert _run(runner, 'import', '--new', str(book),
                'tests/fixtures/fx_usd_bill_cad_expense.txt',
                '--include-business-objects', '--fx-rates', RATES).exit_code == 0

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
    assert _run(runner, 'import', str(book), str(buy)).exit_code == 0

    listing = _balances(runner, book)
    bill_basis = _basis_on(listing, 'Accounts Payable')
    cash_basis = _basis_on(listing, 'Assets:Bank:USD')
    settle = tmp_path / 'settle.txt'
    settle.write_text(
        Path('tests/fixtures/fx_settle_usd_bill_with_usd_cash.txt').read_text()
        .replace('{bill_basis}', bill_basis)
        .replace('{cash_basis}', cash_basis))
    assert _run(runner, 'import', str(book), str(settle)).exit_code == 0

    result = _run(runner, 'unpost-bills', str(book), 'BILL-USD-001')
    assert result.exit_code != 0, result.output
    message = result.output + str(result.exception)
    assert 'cost basis' in message, message
    assert 'Pay US vendor' in message, message


def test_an_untouched_cost_basis_still_unposts(tmp_path):
    """Nothing is measured against it, so destroying it breaks nothing."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert _run(runner, 'import', '--new', str(book),
                'tests/fixtures/fx_usd_invoice_cad_income.txt',
                '--include-business-objects', '--fx-rates', RATES).exit_code == 0

    result = _run(runner, 'unpost-invoices', str(book), 'INV-USD-001')
    assert result.exit_code == 0, result.output
    assert 'unposted' in result.output, result.output
    assert 'No foreign-currency cost bases found' in _balances(runner, book)


def test_a_single_currency_invoice_still_unposts(tmp_path):
    """No cost basis is involved at all, so the guard never fires."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert _run(runner, 'import', '--new', str(book),
                'tests/fixtures/business_objects.txt',
                '--include-business-objects').exit_code == 0

    result = _run(runner, 'unpost-invoices', str(book), 'INV-2026-001')
    assert result.exit_code == 0, result.output
    assert 'unposted' in result.output, result.output
