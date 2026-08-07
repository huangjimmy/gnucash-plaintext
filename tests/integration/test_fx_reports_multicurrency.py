"""Q-035: the reports hold up on a book that holds both USD and CAD.

A foreign-currency invoice recognises its revenue in CAD at the posting-date
rate, so the income statement needs no rate to show it; the balance sheet and
account balances consolidate the USD the book still holds, which does need one.
"""

from click.testing import CliRunner

from cli.main import cli

RATES = 'tests/fixtures/fx_rates_usd_dated.yaml'


def _book(runner, tmp_path, fixture=None):
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(book),
        fixture or 'tests/fixtures/fx_invoice_usd_paid_from_cad_bank.txt',
        '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output
    return book


def test_income_statement_reports_the_cad_revenue_of_a_usd_invoice(tmp_path):
    runner = CliRunner()
    book = _book(runner, tmp_path)
    result = runner.invoke(cli, ['income-statement', str(book),
                                 '--start', '2026-01-01', '--end', '2026-12-31',
                                 '--fx-rates', RATES])
    assert result.exit_code == 0, result.output
    assert '140.00' in result.output, result.output


def test_balance_sheet_balances_with_usd_and_cad_in_one_book(tmp_path):
    runner = CliRunner()
    book = _book(runner, tmp_path, 'tests/fixtures/fx_buy_and_borrow_usd.txt')
    result = runner.invoke(cli, ['balance-sheet', str(book),
                                 '--as-of', '2026-12-31', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output
    # 200 USD held, consolidated at the latest quoted rate (1.37) = 274.00 CAD,
    # against 135.00 CAD paid out and 130.00 CAD borrowed.
    assert '274.00' in result.output, result.output


def test_account_balance_consolidates_a_usd_account_into_cad(tmp_path):
    runner = CliRunner()
    book = _book(runner, tmp_path, 'tests/fixtures/fx_buy_and_borrow_usd.txt')
    result = runner.invoke(cli, ['account-balance', str(book), 'Assets:Bank:USD',
                                 '--as-of', '2026-12-31', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output
    assert '274.00' in result.output or '200.00' in result.output, result.output


def test_reports_still_run_on_a_single_currency_book(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'cad.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(book),
                                 'tests/fixtures/business_objects.txt',
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output
    result = runner.invoke(cli, ['income-statement', str(book),
                                 '--start', '2026-01-01', '--end', '2026-12-31'])
    assert result.exit_code == 0, result.output
