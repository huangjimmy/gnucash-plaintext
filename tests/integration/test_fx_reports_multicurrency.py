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


def test_the_price_it_writes_is_dated_today_and_not_the_year_4753(tmp_path):
    """`account-balance --fx-rates` adds prices to the book, dated.

    Read back because nothing else does, and the date is the half a raw
    `gnc_price_set_time64` gets wrong: given epoch seconds, GnuCash 3.4 stores
    a date two thousand years out (CLAUDE.md finding 20). Nothing would have
    reported it — the duplicate check compares values, not dates, and a price
    dated 4753 wins `gnc_pricedb_lookup_latest` for good, so every later
    "as of" lookup in GnuCash reads it as today's rate.
    """
    from datetime import date, timedelta

    from gnucash.gnucash_core_c import gnc_pricedb_get_db, gnc_pricedb_lookup_latest

    from repositories.gnucash_repository import GnuCashRepository

    runner = CliRunner()
    today = date.today()
    book = _book(runner, tmp_path, 'tests/fixtures/fx_buy_and_borrow_usd.txt')
    written = runner.invoke(cli, ['account-balance', str(book), 'Assets:Bank:USD',
                                  '--as-of', '2026-12-31', '--fx-rates', RATES])
    assert written.exit_code == 0, written.output

    repo = GnuCashRepository(str(book))
    repo.open()
    try:
        table = repo.book.get_table()
        pricedb = gnc_pricedb_get_db(repo.book.instance)
        raw = gnc_pricedb_lookup_latest(
            pricedb,
            table.lookup('CURRENCY', 'USD').instance,
            table.lookup('CURRENCY', 'CAD').instance)
        assert raw is not None, 'no USD/CAD price was written'
        from gnucash import GncPrice
        when = GncPrice(instance=raw).get_time64()
    finally:
        repo.close()

    # Against the day the command ran rather than the day this line runs, so
    # a suite crossing midnight does not fail on the clock.
    assert when.date() in (today, today + timedelta(days=1)), (when, today)


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
