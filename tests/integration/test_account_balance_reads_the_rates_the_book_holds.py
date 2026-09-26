"""`account-balance` reads the rates the book holds, and writes a rates file's rates once.

Without a rates file, a balance in more than one currency is converted at the
latest rate the book's price database holds for each. With one, its rates are
written to the book, each only where the book does not already hold that rate,
and a currency GnuCash does not know is passed over.
"""

from fractions import Fraction

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.prices_in_a_book import prices_in


def _balance(*args):
    return _run(CliRunner(), 'account-balance', *args)


def test_a_balance_in_two_currencies_is_converted_at_the_rate_the_book_holds(
        tmp_path, temp_gnucash_account_balance):
    book = temp_gnucash_account_balance
    rated = _run(CliRunner(), 'import', book, 'tests/fixtures/an_hkd_rate_in_cad.txt')
    assert rated.exit_code == 0, rated.output

    result = _balance(book, '--as-of', '2024-12-31')

    assert result.exit_code == 0, result.output
    # 3420.00 CAD in the chequing account and 8700.00 HKD at 0.17.
    assert '\tAssets:Bank  4899.00 CAD' in result.output, result.output
    assert '\tAssets:Bank:HKD  8700.00 HKD' in result.output, result.output


def test_a_rates_file_written_twice_leaves_one_price(tmp_path, temp_gnucash_account_balance):
    book = temp_gnucash_account_balance
    rates = tmp_path / 'rates.yaml'
    rates.write_text('HKD: 0.17\n')

    for _ in range(2):
        result = _balance(book, '--as-of', '2024-12-31', '--fx-rates', str(rates))
        assert result.exit_code == 0, result.output

    held = [p for p in prices_in(book) if p.commodity == 'CURRENCY:HKD']
    assert len(held) == 1, held


def test_a_rates_file_stating_another_rate_is_the_rate_the_balance_is_converted_at(
        tmp_path, temp_gnucash_account_balance):
    """The book already holds 0.17 for HKD, and the file now says 0.18: the
    balance is converted at 0.18, and that is the latest rate the book holds."""
    book = temp_gnucash_account_balance
    rates = tmp_path / 'rates.yaml'
    rates.write_text('HKD: 0.17\n')
    first = _balance(book, '--as-of', '2024-12-31', '--fx-rates', str(rates))
    assert first.exit_code == 0, first.output

    rates.write_text('HKD: 0.18\n')
    result = _balance(book, '--as-of', '2024-12-31', '--fx-rates', str(rates))

    assert result.exit_code == 0, result.output
    # 3420.00 CAD in the chequing account and 8700.00 HKD at 0.18.
    assert '\tAssets:Bank  4986.00 CAD' in result.output, result.output
    held = [p for p in prices_in(book) if p.commodity == 'CURRENCY:HKD']
    latest = max(held, key=lambda price: price.time)
    assert latest.value == Fraction(18, 100), held


def test_a_currency_gnucash_does_not_know_is_passed_over(tmp_path, temp_gnucash_account_balance):
    book = temp_gnucash_account_balance
    rates = tmp_path / 'rates.yaml'
    rates.write_text('HKD: 0.17\nXYZ: 2\n')

    result = _balance(book, '--as-of', '2024-12-31', '--fx-rates', str(rates))

    assert result.exit_code == 0, result.output
    assert not [p for p in prices_in(book) if 'XYZ' in p.commodity]


def test_an_account_under_a_parent_the_book_holds_is_still_looked_for_by_its_whole_path(
        temp_gnucash_account_balance):
    result = _balance(temp_gnucash_account_balance, 'Assets:Bank:Savings',
                      '--as-of', '2024-12-31')

    assert result.exit_code != 0, result.output
    assert 'Assets:Bank:Savings' in result.output, result.output


def test_shares_have_no_rate_to_read(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    made = _run(runner, 'import', '--new', str(book), 'tests/fixtures/foreign_security_book.txt')
    assert made.exit_code == 0, made.output
    rated = _run(runner, 'import', str(book), 'tests/fixtures/a_usd_rate_in_cad.txt')
    assert rated.exit_code == 0, rated.output

    result = _balance(str(book), 'Assets', '--as-of', '2024-12-31')

    assert result.exit_code != 0, result.output
    assert 'USTECH' in result.output, result.output
