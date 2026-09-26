"""`export-prices` writes only prices, and `--start-date`, `--end-date` and `--latest N` keep the ones asked for.

README, "Only the prices: `export-prices`": the file holds price blocks and the
commodity declarations they use, and imports on its own. Each option works on
its own, none requires another, and any of them can be passed together:
`--start-date` keeps no price before that day, `--end-date` none after it, and
`--latest N` the N most recent prices of each commodity in each currency,
counting back from `--end-date` or from today, where each direction counts
separately and a pair with fewer than N prices since `--start-date` writes the
ones it has. N is 1 or more.

The book's prices are all at 12:00 UTC, so the day a price falls on is the
same in every timezone a test container runs in.
"""

from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.prices_in_a_book import add_prices, price_blocks, prices_in, utc


def _price(commodity, currency, year, month, day, value):
    return {'commodity': commodity, 'currency': currency, 'time': utc(year, month, day, 12),
            'value': value, 'source': 'user:price-editor', 'type': 'last'}


PRICES = [
    _price('CURRENCY:USD', 'CAD', 2026, 1, 2, '1.36'),
    _price('CURRENCY:USD', 'CAD', 2026, 1, 5, '1.37'),
    _price('CURRENCY:USD', 'CAD', 2026, 1, 9, '1.38'),
    _price('CURRENCY:CAD', 'USD', 2026, 1, 3, '0.73'),
    _price('NASDAQ:AMZN', 'USD', 2026, 1, 6, '218.45'),
    _price('NASDAQ:AMZN', 'USD', 2026, 1, 7, '220.10'),
    _price('CURRENCY:EUR', 'CAD', 2026, 1, 8, '1.51'),
    _price('CURRENCY:EUR', 'CAD', 2099, 1, 1, '1.60'),
]

EVERY_PRICE = {
    ('USD', 'CAD', '2026-01-02'), ('USD', 'CAD', '2026-01-05'), ('USD', 'CAD', '2026-01-09'),
    ('CAD', 'USD', '2026-01-03'),
    ('AMZN', 'USD', '2026-01-06'), ('AMZN', 'USD', '2026-01-07'),
    ('EUR', 'CAD', '2026-01-08'), ('EUR', 'CAD', '2099-01-01'),
}


def _book(tmp_path):
    book = tmp_path / 'book.gnucash'
    add_prices(book, PRICES)
    return book


def _exported(tmp_path, *options):
    book = _book(tmp_path)
    out = tmp_path / 'prices.txt'
    result = _run(CliRunner(), 'export-prices', str(book), str(out), *options)
    assert result.exit_code == 0, result.output
    return book, out


def _kept(tmp_path, *options):
    _book_path, out = _exported(tmp_path, *options)
    return {(b['commodity.mnemonic'], b['currency.mnemonic'], b['time'][:10])
            for b in price_blocks(out.read_text())}


class TestTheFile:
    def test_it_holds_every_price_with_no_option(self, tmp_path):
        assert _kept(tmp_path) == EVERY_PRICE

    def test_it_declares_the_commodity_a_price_uses(self, tmp_path):
        _book_path, out = _exported(tmp_path)

        # Spelled as `export` spells a commodity that is not a currency.
        assert any(line.endswith(' commodity NASDAQ.AMZN') for line in out.read_text().splitlines())

    def test_it_holds_no_account_and_no_transaction(self, tmp_path):
        _book_path, out = _exported(tmp_path)
        lines = out.read_text().splitlines()

        assert not [line for line in lines if ' open ' in line or ' * ' in line]

    def test_it_imports_into_a_fresh_book_as_the_same_prices(self, tmp_path):
        book, out = _exported(tmp_path)
        fresh = tmp_path / 'fresh.gnucash'

        result = _run(CliRunner(), 'import', '--new', str(fresh), str(out))

        assert result.exit_code == 0, result.output
        assert prices_in(fresh) == prices_in(book)


class TestEachOptionOnItsOwn:
    def test_start_date_keeps_nothing_before_it(self, tmp_path):
        assert _kept(tmp_path, '--start-date', '2026-01-05') == {
            ('USD', 'CAD', '2026-01-05'), ('USD', 'CAD', '2026-01-09'),
            ('AMZN', 'USD', '2026-01-06'), ('AMZN', 'USD', '2026-01-07'),
            ('EUR', 'CAD', '2026-01-08'), ('EUR', 'CAD', '2099-01-01'),
        }

    def test_end_date_keeps_nothing_after_it(self, tmp_path):
        assert _kept(tmp_path, '--end-date', '2026-01-03') == {
            ('USD', 'CAD', '2026-01-02'), ('CAD', 'USD', '2026-01-03'),
        }

    def test_latest_1_is_each_pairs_most_recent_up_to_today(self, tmp_path):
        """EUR's 2099 price is after today, so it is not among the latest."""
        assert _kept(tmp_path, '--latest', '1') == {
            ('USD', 'CAD', '2026-01-09'), ('CAD', 'USD', '2026-01-03'),
            ('AMZN', 'USD', '2026-01-07'), ('EUR', 'CAD', '2026-01-08'),
        }

    def test_each_direction_counts_separately(self, tmp_path):
        kept = _kept(tmp_path, '--latest', '1')

        assert {('USD', 'CAD', '2026-01-09'), ('CAD', 'USD', '2026-01-03')} <= kept


class TestOptionsTogether:
    def test_start_and_end_date_keep_the_range(self, tmp_path):
        assert _kept(tmp_path, '--start-date', '2026-01-03', '--end-date', '2026-01-06') == {
            ('USD', 'CAD', '2026-01-05'), ('CAD', 'USD', '2026-01-03'),
            ('AMZN', 'USD', '2026-01-06'),
        }

    def test_latest_counts_back_from_end_date(self, tmp_path):
        assert _kept(tmp_path, '--latest', '2', '--end-date', '2026-01-06') == {
            ('USD', 'CAD', '2026-01-02'), ('USD', 'CAD', '2026-01-05'),
            ('CAD', 'USD', '2026-01-03'), ('AMZN', 'USD', '2026-01-06'),
        }

    def test_latest_with_start_date_writes_fewer_where_fewer_are_left(self, tmp_path):
        assert _kept(tmp_path, '--latest', '5', '--start-date', '2026-01-05') == {
            ('USD', 'CAD', '2026-01-05'), ('USD', 'CAD', '2026-01-09'),
            ('AMZN', 'USD', '2026-01-06'), ('AMZN', 'USD', '2026-01-07'),
            ('EUR', 'CAD', '2026-01-08'),
        }

    def test_all_three(self, tmp_path):
        assert _kept(tmp_path, '--latest', '1', '--start-date', '2026-01-04',
                     '--end-date', '2026-01-06') == {
            ('USD', 'CAD', '2026-01-05'), ('AMZN', 'USD', '2026-01-06'),
        }


class TestLatestBelowOne:
    def test_zero_is_refused(self, tmp_path):
        book = _book(tmp_path)

        result = _run(CliRunner(), 'export-prices', str(book), str(tmp_path / 'p.txt'),
                      '--latest', '0')

        assert result.exit_code != 0, result.output
        assert '--latest' in result.output, result.output

    def test_a_negative_number_is_refused(self, tmp_path):
        book = _book(tmp_path)

        result = _run(CliRunner(), 'export-prices', str(book), str(tmp_path / 'p.txt'),
                      '--latest', '-1')

        assert result.exit_code != 0, result.output
        assert '--latest' in result.output, result.output
