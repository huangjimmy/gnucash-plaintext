"""`--fx-rates`, `--prices` and `--price-source` on `balance-sheet`, `income-statement` and `report`.

Q-042: a rates file or a prices file is added to the book's price database for
the run and never saved, and GnuCash's report prices from it. No figure is
multiplied here. A rate is a price in the report's currency and may be written
as a fraction. `--price-source` is the report's own `Price Source` option.

Most tests use the CAD book of `test_the_statements_are_printed_by_customized_gnucash_reports.py`,
one fiscal year ending 2026-12-31, where at the year end:
- USD Bank holds 7,480.00 USD and 2,500.00 USD is still owed on the loan;
- HKD Bank holds 5,500.00 HKD;
- the book holds 12 NASDAQ:AMZN, bought at 200.00 USD;
- its own prices are USD in CAD at 1.42, CAD in HKD at 5.0 and AMZN in USD at 280.
"""

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.prices_in_a_book import prices_in
from tests.integration.text_report_pages import (
    FIXTURES,
    amount_of,
    block_of,
    block_total_of,
    book_from,
    key_of,
    shares_as_a_block_writes,
    under,
)

CAD_BOOK = 'a_cad_book_with_usd_hkd_and_shares_priced_in_its_price_database.txt'


YEAR_END = '2026-12-31'


def _balance_sheet(book, as_of, *flags):
    result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', as_of, *flags)
    assert result.exit_code == 0, result.output
    return result.output


class TestARatesFile:

    def test_a_rate_with_no_date_prices_the_moment_the_report_is_for(self, tmp_path):
        book = book_from(tmp_path, CAD_BOOK)
        before = prices_in(book)

        page = _balance_sheet(book, YEAR_END, '--fx-rates', str(FIXTURES / 'usd_at_one_fifty.yaml'))

        assert under(page, 'Assets:USD Bank') == {
            'account.commodity.mnemonic': 'USD',
            'share_price': '1.5',
            'value': '11220.00'}
        assert prices_in(book) == before

    def test_a_dated_rate_is_a_price_on_its_day(self, tmp_path):
        book = book_from(tmp_path, CAD_BOOK)
        before = prices_in(book)

        page = _balance_sheet(book, YEAR_END, '--fx-rates',
                              str(FIXTURES / 'usd_at_one_fifty_in_cad_on_december_31.yaml'))

        assert under(page, 'Assets:USD Bank')['share_price'] == '1.5'
        assert prices_in(book) == before

    def test_a_rate_may_be_a_fraction(self, tmp_path):
        """`HKD: 1/5` is exactly a fifth, and the page states the price it priced by."""
        book = book_from(tmp_path, CAD_BOOK)

        page = _balance_sheet(book, YEAR_END, '--fx-rates',
                              str(FIXTURES / 'hkd_at_one_fifth_as_a_fraction.yaml'))

        assert under(page, 'Assets:HKD Bank') == {
            'account.commodity.mnemonic': 'HKD',
            'share_price': '0.2',
            'value': '1100.00'}

    def test_the_income_statement_prices_from_it(self, tmp_path):
        book = book_from(tmp_path, CAD_BOOK)

        result = _run(CliRunner(), 'income-statement', str(book),
                      '--fiscal-year-end', YEAR_END,
                      '--fx-rates', str(FIXTURES / 'usd_at_one_fifty.yaml'))

        assert result.exit_code == 0, result.output
        # The gain taken on the shares is 480.00 USD, valued at the file's 1.50.
        assert under(result.output, 'Income:Realized Gains')['value'] == '720.00'
        assert key_of(result.output, 'total_revenue') == '9460.00 CAD'
        assert key_of(result.output, 'net_income') == '9160.00 CAD'

    def test_report_prices_both_statements_from_it(self, tmp_path):
        book = book_from(tmp_path, CAD_BOOK)

        result = _run(CliRunner(), 'report', str(book), 'income-statement', 'balance-sheet',
                      '--fiscal-year-end', YEAR_END,
                      '--fx-rates', str(FIXTURES / 'usd_at_one_fifty.yaml'))

        assert result.exit_code == 0, result.output
        assert 'net_income: 9160.00 CAD' in result.output, result.output
        assert 'share_price: "1.5"' in result.output, result.output

    def test_a_rate_replaces_the_books_own_price_that_day_for_the_run(self, tmp_path):
        """The HKD book prices USD at 7.80 HKD on 03-31; the file gives 7.70."""
        book = book_from(tmp_path, 'a_book_kept_in_hkd.txt')
        before = prices_in(book)

        page = _balance_sheet(book, '2026-03-31', '--fx-rates',
                              str(FIXTURES / 'usd_at_seven_seventy_in_hkd.yaml'))

        assert under(page, 'Assets:USD Bank') == {
            'account.commodity.mnemonic': 'USD',
            'share_price': '7.7',
            'value': '11550.00'}
        assert key_of(page, 'total_assets') == '37180.00 HKD'
        assert prices_in(book) == before

    def test_a_rate_into_a_currency_other_than_the_reports_is_refused(self, tmp_path):
        book = book_from(tmp_path, 'a_book_kept_in_hkd.txt')

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-03-31',
                      '--fx-rates', str(FIXTURES / 'usd_at_one_fifty_in_cad.yaml'))

        assert result.exit_code != 0, result.output
        assert 'USD/CAD' in result.output and 'HKD' in result.output, result.output

    def test_a_rate_that_is_not_a_number_is_refused(self, tmp_path):
        book = book_from(tmp_path, CAD_BOOK)
        rates = tmp_path / 'rates.yaml'
        rates.write_text('USD: cheap\n', encoding='utf-8')

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-01-25',
                      '--fx-rates', str(rates))

        assert result.exit_code != 0, result.output
        assert 'Traceback' not in result.output
        assert 'USD' in result.output and 'cheap' in result.output, result.output

    def test_a_file_that_is_not_yaml_is_refused(self, tmp_path):
        book = book_from(tmp_path, CAD_BOOK)
        rates = tmp_path / 'rates.yaml'
        rates.write_text('this: [is not: a rates file\n', encoding='utf-8')

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-01-25',
                      '--fx-rates', str(rates))

        assert result.exit_code != 0, result.output
        assert 'Traceback' not in result.output
        assert 'rates.yaml' in result.output, result.output


def _refused(tmp_path, book, text, flag='--fx-rates'):
    """What `balance-sheet` says when given `text` as a rates or prices file it refuses."""
    written = tmp_path / 'file.yaml'
    written.write_text(text, encoding='utf-8')
    result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', YEAR_END,
                  flag, str(written))
    assert result.exit_code != 0, result.output
    assert 'Traceback' not in result.output
    return result.output


def _priced(tmp_path, book, text, flag='--fx-rates'):
    """The balance sheet at the year end with `text` as a rates or prices file."""
    written = tmp_path / 'file.yaml'
    written.write_text(text, encoding='utf-8')
    return _balance_sheet(book, YEAR_END, flag, str(written))


class TestWhatARatesFileMayWrite:

    def test_a_date_may_be_quoted(self, tmp_path):
        book = book_from(tmp_path, CAD_BOOK)

        page = _priced(tmp_path, book, 'USD/CAD:\n  "2026-12-31": 1.50\n')

        assert under(page, 'Assets:USD Bank')['share_price'] == '1.5'

    def test_a_date_may_carry_a_time(self, tmp_path):
        book = book_from(tmp_path, CAD_BOOK)

        page = _priced(tmp_path, book, 'USD/CAD:\n  2026-12-31 12:00:00: 1.50\n')

        assert under(page, 'Assets:USD Bank')['share_price'] == '1.5'

    def test_a_rate_of_1_for_the_reports_own_currency_is_accepted(self, tmp_path):
        book = book_from(tmp_path, CAD_BOOK)

        page = _priced(tmp_path, book, 'CAD: 1\nUSD: 1.50\n')

        assert under(page, 'Assets:USD Bank')['share_price'] == '1.5'


class TestWhatARatesFileIsRefusedFor:

    def test_giving_no_prices(self, tmp_path):
        book = book_from(tmp_path, CAD_BOOK)

        assert 'gives no prices' in _refused(tmp_path, book, '# nothing here\n')

    def test_a_key_with_nothing_after_its_slash(self, tmp_path):
        book = book_from(tmp_path, CAD_BOOK)

        assert 'neither a commodity' in _refused(tmp_path, book, 'USD/: 1.50\n')

    def test_a_currency_with_no_dated_prices(self, tmp_path):
        book = book_from(tmp_path, CAD_BOOK)

        assert 'gives no dated prices' in _refused(tmp_path, book, 'USD/CAD: {}\n')

    def test_a_date_that_is_not_a_date(self, tmp_path):
        book = book_from(tmp_path, CAD_BOOK)

        output = _refused(tmp_path, book, 'USD/CAD:\n  "25/01/2026": 1.50\n')

        assert '25/01/2026' in output and 'YYYY-MM-DD' in output, output

    def test_a_price_of_zero(self, tmp_path):
        book = book_from(tmp_path, CAD_BOOK)

        assert 'more than zero' in _refused(tmp_path, book, 'USD: 0\n')

    def test_a_rate_other_than_1_for_the_reports_own_currency(self, tmp_path):
        book = book_from(tmp_path, CAD_BOOK)

        assert 'its price in itself is 1' in _refused(tmp_path, book, 'CAD: 2\n')

    def test_a_file_that_is_not_utf_8(self, tmp_path):
        """A file saved as Latin-1 with one accented character in a comment.

        PyYAML reads the stream itself, so the decode fails inside
        `safe_load` — and a `UnicodeDecodeError` is a `ValueError`, which
        neither the YAML arm nor the `OSError` arm around it catches.
        """
        book = book_from(tmp_path, CAD_BOOK)
        written = tmp_path / 'file.yaml'
        written.write_bytes('USD: 1.50  # caf\xe9\n'.encode('latin-1'))

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-01-25',
                      '--fx-rates', str(written))

        assert result.exit_code != 0, result.output
        assert 'Traceback' not in result.output, result.output
        assert 'file.yaml' in result.output and 'UTF-8' in result.output, result.output

    def test_two_rates_for_one_currency_on_one_day(self, tmp_path):
        """An undated rate lands on the day the report is for — where the dated one is.

        GnuCash keeps one price a day for a pair, and the source these are
        given outranks the book's own, so the second to be added displaces the
        first. Which survived would be decided by the order they were written
        in, and the page's figures with it.
        """
        book = book_from(tmp_path, CAD_BOOK)

        output = _refused(tmp_path, book, 'USD: 1.50\nUSD/CAD:\n  2026-12-31: 1.45\n')

        assert 'one price a day' in output, output
        assert 'USD' in output and 'depend on' in output, output

    def test_two_rates_for_one_currency_on_different_days_are_fine(self, tmp_path):
        """The refusal is about one day, not about giving a currency twice."""
        book = book_from(tmp_path, CAD_BOOK)

        page = _priced(tmp_path, book,
                       'USD: 1.50\nUSD/CAD:\n  2026-01-05: 1.45\n')

        assert under(page, 'Assets:USD Bank')['share_price'] == '1.5'


class TestAPricesFile:

    def test_a_security_is_priced_in_the_currency_the_book_prices_it_in(self, tmp_path):
        """AMZN: 250 is 250 USD, the currency of the book's AMZN prices; GnuCash converts it at 1.42."""
        book = book_from(tmp_path, CAD_BOOK)
        before = prices_in(book)

        page = _balance_sheet(book, YEAR_END, '--prices', str(FIXTURES / 'amzn_at_250.yaml'))

        assert amount_of(page, 'Assets:AMZN') == shares_as_a_block_writes('12', 'AMZN'), page
        assert under(page, 'Assets:AMZN') == {
            'account.commodity.mnemonic': 'AMZN',
            'share_price': '355',
            'value': '4260.00'}
        assert prices_in(book) == before

    def test_a_security_the_book_has_no_price_for_is_priced_in_the_currency_it_was_bought_in(
            self, tmp_path):
        """ACME and VGRO were each bought for 500.00 CAD, and the book prices neither."""
        book = book_from(tmp_path, 'all_account_types_book.txt')

        page = _balance_sheet(book, '2024-12-31', '--prices', str(FIXTURES / 'security_prices.yaml'))

        assert amount_of(page, 'Assets:Brokerage:ACME') == shares_as_a_block_writes('10', 'ACME'), page
        assert under(page, 'Assets:Brokerage:ACME')['value'] == '600.00'
        assert amount_of(page, 'Assets:Brokerage:VGRO') == shares_as_a_block_writes('20', 'VGRO'), page
        assert under(page, 'Assets:Brokerage:VGRO')['value'] == '600.00'
        # Both securities are held in CAD, so none of the 200.00 is an
        # exchange movement: all of it is the two share prices moving.
        assert block_total_of(page, 'unrealized_gains_assets_fx') == 0
        assert key_of(page, 'unrealized_gains_liabilities_fx') == '0.00 CAD'
        assert key_of(page, 'unrealized_gains_fx') == '0.00 CAD'
        # Both securities in full, a stock and a fund, each bought for 500.00
        # CAD and each worth 600.00 at the file's prices.
        assert block_of(page, 'unrealized_gains_other') == '\n'.join((
            '\t\tsecurities: # security, fund, etc',
            '\t\t\tsecurity:',
            '\t\t\t\tcommodity.namespace: "NASDAQ"',
            '\t\t\t\tcommodity.mnemonic: "ACME"',
            '\t\t\t\tquantity: 10.0000',
            '\t\t\t\tshare_price: 60 # what price-fn gives for this commodity',
            '\t\t\t\taccounts:',
            '\t\t\t\t\taccount:',
            '\t\t\t\t\t\tguid: <guid>',
            '\t\t\t\t\t\tname: "Assets:Brokerage:ACME"',
            '\t\t\t\t\t\tbalance: 10.0000',
            '\t\t\t\t\t\tsplits:',
            '\t\t\t\t\t\t\tsplit_amount 10.0000 | value 500.00 CAD',
            "\t\t\t\tvalue: 600.00 # the holding converted at the sheet's price",
            "\t\t\t\tcost_value: 500.00 # its splits' values, converted",
            '\t\t\t\tunrealized_gains_other: 100.00 # value - cost_value',
            '\t\t\tsecurity:',
            '\t\t\t\tcommodity.namespace: "FUND"',
            '\t\t\t\tcommodity.mnemonic: "VGRO"',
            '\t\t\t\tquantity: 20.0000',
            '\t\t\t\tshare_price: 30 # what price-fn gives for this commodity',
            '\t\t\t\taccounts:',
            '\t\t\t\t\taccount:',
            '\t\t\t\t\t\tguid: <guid>',
            '\t\t\t\t\t\tname: "Assets:Brokerage:VGRO"',
            '\t\t\t\t\t\tbalance: 20.0000',
            '\t\t\t\t\t\tsplits:',
            '\t\t\t\t\t\t\tsplit_amount 20.0000 | value 500.00 CAD',
            "\t\t\t\tvalue: 600.00 # the holding converted at the sheet's price",
            "\t\t\t\tcost_value: 500.00 # its splits' values, converted",
            '\t\t\t\tunrealized_gains_other: 100.00 # value - cost_value',
            "\t\tvalue: 1200.00 # sum of each security's value",
            "\t\tcost_value: 1000.00 # sum of each security's cost_value",
            '\t\tunrealized_gains_other: 200.00 # value - cost_value')), page
        assert key_of(page, 'total_unrealized_gains') == '200.00 CAD'

    def test_a_security_the_book_does_not_hold_is_refused(self, tmp_path):
        book = book_from(tmp_path, CAD_BOOK)
        prices = tmp_path / 'prices.yaml'
        prices.write_text('NOPE: 5\n', encoding='utf-8')

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-01-25',
                      '--prices', str(prices))

        assert result.exit_code != 0, result.output
        assert 'NOPE' in result.output, result.output


class TestWhatAPricesFileMayWriteAndIsRefusedFor:

    def test_a_security_price_may_give_its_currency(self, tmp_path):
        book = book_from(tmp_path, CAD_BOOK)

        page = _priced(tmp_path, book, 'AMZN/USD: 250\n', '--prices')

        assert amount_of(page, 'Assets:AMZN') == shares_as_a_block_writes('12', 'AMZN')
        assert under(page, 'Assets:AMZN')['value'] == '4260.00'

    def test_a_security_price_in_a_currency_gnucash_does_not_know(self, tmp_path):
        book = book_from(tmp_path, CAD_BOOK)

        assert 'XYZ' in _refused(tmp_path, book, 'AMZN/XYZ: 250\n', '--prices')

    def test_a_security_the_book_holds_under_two_namespaces(self, tmp_path):
        book = book_from(tmp_path, 'a_cad_book_with_securities_a_prices_file_cannot_price_alone.txt')

        output = _refused(tmp_path, book, 'AMZN: 250\n', '--prices')

        assert 'NASDAQ:AMZN' in output and 'NEO:AMZN' in output, output

    def test_a_security_the_book_neither_prices_nor_trades(self, tmp_path):
        book = book_from(tmp_path, 'a_cad_book_with_securities_a_prices_file_cannot_price_alone.txt')

        output = _refused(tmp_path, book, 'SHOP: 100\n', '--prices')

        assert 'SHOP/USD' in output, output


class TestThePriceSource:

    def test_gnucash_prices_at_the_price_nearest_in_time_by_default(self, tmp_path):
        """Nearest in time, a later price included.

        On 2026-01-12 the book's USD prices are 1.30 of 2025-05-05, some eight
        months behind, and 1.35 of 2026-03-31, under three months ahead. The
        later one is nearer, so it is the one the report prices by.
        """
        book = book_from(tmp_path, CAD_BOOK)

        page = _balance_sheet(book, '2026-01-12')

        assert amount_of(page, 'Assets:USD Bank') == '10000.00 USD'
        assert under(page, 'Assets:USD Bank') == {
            'account.commodity.mnemonic': 'USD',
            'share_price': '1.35',
            'value': '13500.00'}

    def test_a_price_source_given_on_the_command_is_the_reports(self, tmp_path):
        """The most recent price is the 1.42 of 2026-12-31, a year after the report date."""
        book = book_from(tmp_path, CAD_BOOK)

        page = _balance_sheet(book, '2026-01-12', '--price-source', 'pricedb-latest')

        assert under(page, 'Assets:USD Bank') == {
            'account.commodity.mnemonic': 'USD',
            'share_price': '1.42',
            'value': '14200.00'}

    def test_a_source_that_prices_by_averaging_is_not_a_choice(self, tmp_path):
        """GnuCash's report offers `average-cost` and `weighted-average`; these statements do not.

        Neither reads a price: each divides the total value that moved a
        commodity by the total amount, so the figure it would put on a line is
        a ratio no transaction was entered at. They are not choices here, and
        get the same answer as any other value that is not one.
        """
        book = book_from(tmp_path, CAD_BOOK)

        for source in ('average-cost', 'weighted-average'):
            result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', YEAR_END,
                          '--price-source', source)

            assert result.exit_code != 0, result.output
            assert 'Traceback' not in result.output, result.output
            assert source in result.output and 'pricedb-nearest' in result.output, result.output

    def test_it_is_not_a_choice_for_gnucash_own_page_either(self, tmp_path):
        """The same answer whichever page is asked for, so one rule holds for the command."""
        book = book_from(tmp_path, CAD_BOOK)
        page = tmp_path / 'sheet.html'

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', YEAR_END,
                      '--price-source', 'average-cost',
                      '--output-format', 'html', '--output', str(page))

        assert result.exit_code != 0, result.output
        assert 'average-cost' in result.output, result.output
        assert not page.exists(), 'no page is written for a source that is not a choice'

    def test_a_price_source_that_is_not_a_choice_is_refused_with_the_choices(self, tmp_path):
        book = book_from(tmp_path, CAD_BOOK)

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-01-03',
                      '--price-source', 'cheapest')

        assert result.exit_code != 0, result.output
        assert 'cheapest' in result.output and 'pricedb-nearest' in result.output, result.output

    def test_the_income_statement_refuses_a_price_source_that_is_not_a_choice(self, tmp_path):
        book = book_from(tmp_path, CAD_BOOK)

        result = _run(CliRunner(), 'income-statement', str(book), '--start', '2026-01-01',
                      '--end', '2026-01-25', '--price-source', 'cheapest')

        assert result.exit_code != 0, result.output
        assert 'cheapest' in result.output and 'pricedb-nearest' in result.output, result.output

    def test_report_refuses_a_price_source_that_is_not_a_choice(self, tmp_path):
        book = book_from(tmp_path, CAD_BOOK)

        result = _run(CliRunner(), 'report', str(book), 'income-statement', 'balance-sheet',
                      '--start', '2026-01-01', '--end', '2026-01-25', '--price-source', 'cheapest')

        assert result.exit_code != 0, result.output
        assert 'cheapest' in result.output and 'pricedb-nearest' in result.output, result.output
