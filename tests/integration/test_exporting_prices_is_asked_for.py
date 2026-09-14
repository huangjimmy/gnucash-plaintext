"""`export` writes a book's prices only when asked, into the same file, before the blocks that follow them.

README, "Export and import prices": prices are left out of `export` unless
asked for, as business objects are; `--include-prices` writes them into the
same ledger, after the commodities and accounts they refer to and before
business objects and transactions; each `time:` is written in full, in UTC.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.prices_in_a_book import add_prices, price_blocks, utc

FIXTURES = Path('tests/fixtures')

PRICES = [
    {'commodity': 'CURRENCY:USD', 'currency': 'CAD', 'time': utc(2026, 1, 2, 12),
     'value': '1.36', 'source': 'user:price-editor', 'type': 'last'},
    {'commodity': 'NASDAQ:AMZN', 'currency': 'USD', 'time': utc(2026, 1, 6, 21),
     'value': '218.45', 'source': 'Finance::Quote', 'type': 'last'},
]


def _book(tmp_path):
    book = tmp_path / 'book.gnucash'
    result = _run(CliRunner(), 'import', '--new', str(book),
                  str(FIXTURES / 'a_usd_bank_a_deposit_and_a_customer.txt'),
                  '--include-business-objects')
    assert result.exit_code == 0, result.output
    add_prices(book, PRICES)
    return book


def _export(tmp_path, *flags):
    book = _book(tmp_path)
    ledger = tmp_path / 'ledger.txt'
    result = _run(CliRunner(), 'export', str(book), str(ledger), *flags)
    assert result.exit_code == 0, result.output
    return ledger.read_text().splitlines()


def _first(lines, pattern):
    return next(i for i, line in enumerate(lines) if re.search(pattern, line))


def _last(lines, pattern):
    return max(i for i, line in enumerate(lines) if re.search(pattern, line))


class TestWithoutTheFlag:
    def test_no_price_is_written(self, tmp_path):
        lines = _export(tmp_path)

        assert 'price' not in lines

    def test_nor_with_business_objects(self, tmp_path):
        lines = _export(tmp_path, '--include-business-objects')

        assert 'price' not in lines


class TestWithIncludePrices:
    def test_every_price_is_written(self, tmp_path):
        lines = _export(tmp_path, '--include-prices')

        assert len(price_blocks('\n'.join(lines))) == 2

    def test_prices_come_after_the_commodities_and_accounts(self, tmp_path):
        lines = _export(tmp_path, '--include-prices')

        assert _first(lines, r'^price$') > _last(lines, r'^\d{4}-\d{2}-\d{2} (open|commodity) ')

    def test_prices_come_before_the_transactions(self, tmp_path):
        lines = _export(tmp_path, '--include-prices')

        assert _last(lines, r'^price$') < _first(lines, r'^\d{4}-\d{2}-\d{2} \* ')

    def test_prices_come_before_the_business_objects(self, tmp_path):
        lines = _export(tmp_path, '--include-prices', '--include-business-objects')

        assert _last(lines, r'^price$') < _first(lines, r'^customer "C-001"$')

    def test_each_time_is_written_in_full_in_utc(self, tmp_path):
        lines = _export(tmp_path, '--include-prices')

        times = sorted(b['time'] for b in price_blocks('\n'.join(lines)))

        assert times == ['2026-01-02 12:00:00 +0000', '2026-01-06 21:00:00 +0000']


class TestWithIncludePricesAndADateRange:
    """README: `--start-date` and `--end-date` keep the prices inside the range, as they keep the transactions."""

    def test_a_price_before_the_range_is_left_out(self, tmp_path):
        lines = _export(tmp_path, '--include-prices',
                        '--start-date', '2026-01-03', '--end-date', '2026-01-31')

        times = sorted(b['time'] for b in price_blocks('\n'.join(lines)))

        assert times == ['2026-01-06 21:00:00 +0000']

    def test_a_price_after_the_range_is_left_out(self, tmp_path):
        lines = _export(tmp_path, '--include-prices',
                        '--start-date', '2026-01-01', '--end-date', '2026-01-05')

        times = sorted(b['time'] for b in price_blocks('\n'.join(lines)))

        assert times == ['2026-01-02 12:00:00 +0000']

    def test_a_start_date_on_its_own_leaves_out_the_prices_before_it(self, tmp_path):
        lines = _export(tmp_path, '--include-prices', '--start-date', '2026-01-03')

        times = sorted(b['time'] for b in price_blocks('\n'.join(lines)))

        assert times == ['2026-01-06 21:00:00 +0000']

    def test_an_end_date_on_its_own_leaves_out_the_prices_after_it(self, tmp_path):
        lines = _export(tmp_path, '--include-prices', '--end-date', '2026-01-05')

        times = sorted(b['time'] for b in price_blocks('\n'.join(lines)))

        assert times == ['2026-01-02 12:00:00 +0000']


class TestBothDatesAreIncluded:
    """README: `--start-date` and `--end-date` keep a price dated on either day."""

    def test_a_price_dated_on_the_end_date_is_kept(self, tmp_path):
        lines = _export(tmp_path, '--include-prices', '--end-date', '2026-01-06')

        times = sorted(b['time'] for b in price_blocks('\n'.join(lines)))

        assert times == ['2026-01-02 12:00:00 +0000', '2026-01-06 21:00:00 +0000']

    def test_a_price_dated_on_the_start_date_is_kept(self, tmp_path):
        lines = _export(tmp_path, '--include-prices', '--start-date', '2026-01-02')

        times = sorted(b['time'] for b in price_blocks('\n'.join(lines)))

        assert times == ['2026-01-02 12:00:00 +0000', '2026-01-06 21:00:00 +0000']


class TestADateThatIsNotOne:
    def test_it_is_refused_and_no_file_is_written(self, tmp_path):
        book = _book(tmp_path)
        ledger = tmp_path / 'ledger.txt'

        result = _run(CliRunner(), 'export', str(book), str(ledger),
                      '--include-prices', '--start-date', '2026/01/03')

        assert result.exit_code != 0
        assert '--start-date 2026/01/03' in result.output
        assert not ledger.exists()
