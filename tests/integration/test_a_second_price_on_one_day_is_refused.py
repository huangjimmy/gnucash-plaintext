"""A second price for a commodity in a currency on a day already priced is refused, not swapped in.

README, "One price a day": GnuCash keeps at most one price for a commodity in
a currency on one day, and its own call to add a price quietly deletes the
other one (Q-041, table 4). So `import` refuses a block that would leave two
prices on one day — a new price, two in one file, or an edit moving a price
onto such a day — and the refusal lists the price already there: its guid,
time and source.

The same holds for the two the other way round: GnuCash keeps one price a day
for USD in CAD and CAD in USD together (Q-041, table 1).
"""

import re
from fractions import Fraction
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.prices_in_a_book import as_written, day_neutral, prices_in, utc

FIXTURES = Path('tests/fixtures')
AMZN_GUID = '4a1a4c0c7328491fbde9f8099ba280c8'
NEXT_DAYS_AMZN_GUID = '5b2b5d1d8439402a96c7f910acb391d9'


def _book(tmp_path, *more):
    book = tmp_path / 'book.gnucash'
    first = _run(CliRunner(), 'import', '--new', str(book),
                 str(FIXTURES / 'prices_of_a_currency_and_a_stock.txt'))
    assert first.exit_code == 0, first.output
    for fixture in more:
        result = _run(CliRunner(), 'import', str(book), str(FIXTURES / fixture))
        assert result.exit_code == 0, result.output
    return book


def _usd(book):
    return [p for p in prices_in(book) if p.commodity == 'CURRENCY:USD']


def _usd_and_cad(book):
    """Every price of USD and CAD, whichever way round, as (commodity, currency, time)."""
    return [(p.commodity, p.currency, p.time) for p in prices_in(book)
            if {p.commodity, f'CURRENCY:{p.currency}'} == {'CURRENCY:USD', 'CURRENCY:CAD'}]


class TestASecondRateOnTheDayAlreadyPriced:
    FIXTURE = 'a_second_usd_rate_on_the_day_already_priced.txt'

    def test_it_is_refused(self, tmp_path):
        book = _book(tmp_path)

        result = _run(CliRunner(), 'import', str(book), str(FIXTURES / self.FIXTURE))

        assert result.exit_code == 1, result.output
        assert re.search(r'Prices:\s+0 created, 0 updated, 0 unchanged, 1 refused',
                         result.output), result.output

    def test_the_refusal_lists_the_price_already_there(self, tmp_path):
        book = _book(tmp_path)
        (existing,) = _usd(book)

        result = _run(CliRunner(), 'import', str(book), str(FIXTURES / self.FIXTURE))

        assert existing.guid in result.output, result.output
        assert as_written(day_neutral(2026, 1, 2)) in result.output, result.output
        assert 'user:price-editor' in result.output, result.output

    def test_the_price_already_there_is_kept(self, tmp_path):
        book = _book(tmp_path)

        _run(CliRunner(), 'import', str(book), str(FIXTURES / self.FIXTURE))

        assert [p.value for p in _usd(book)] == [Fraction('1.3642')]


class TestTwoRatesOnOneDayInOneFile:
    FIXTURE = 'two_usd_rates_on_one_day.txt'

    def test_both_are_refused(self, tmp_path):
        book = _book(tmp_path)

        result = _run(CliRunner(), 'import', str(book), str(FIXTURES / self.FIXTURE))

        assert result.exit_code == 1, result.output
        assert re.search(r'Prices:\s+0 created, 0 updated, 0 unchanged, 2 refused',
                         result.output), result.output

    def test_neither_is_stored(self, tmp_path):
        book = _book(tmp_path)

        _run(CliRunner(), 'import', str(book), str(FIXTURES / self.FIXTURE))

        assert [p.time for p in _usd(book)] == [day_neutral(2026, 1, 2)]


class TestAnEditMovingAPriceOntoADayAlreadyPriced:
    FIXTURE = 'the_amzn_price_moved_onto_the_next_days_price.txt'

    def test_it_is_refused(self, tmp_path):
        book = _book(tmp_path, 'another_amzn_price_a_day_later.txt')

        result = _run(CliRunner(), 'import', str(book), str(FIXTURES / self.FIXTURE))

        assert result.exit_code == 1, result.output
        assert NEXT_DAYS_AMZN_GUID in result.output, result.output

    def test_both_prices_stay_where_they_were(self, tmp_path):
        book = _book(tmp_path, 'another_amzn_price_a_day_later.txt')

        _run(CliRunner(), 'import', str(book), str(FIXTURES / self.FIXTURE))

        assert [(p.guid, p.time) for p in prices_in(book) if p.commodity == 'NASDAQ:AMZN'] == [
            (AMZN_GUID, utc(2026, 1, 6, 21)),
            (NEXT_DAYS_AMZN_GUID, utc(2026, 1, 7, 21)),
        ]


class TestARateOnADayItsInverseAlreadyHas:
    """CAD in USD on the day the book prices USD in CAD."""

    FIXTURE = 'a_cad_in_usd_rate_on_the_day_already_priced_the_other_way.txt'

    def test_it_is_refused(self, tmp_path):
        book = _book(tmp_path)

        result = _run(CliRunner(), 'import', str(book), str(FIXTURES / self.FIXTURE))

        assert result.exit_code == 1, result.output
        assert re.search(r'Prices:\s+0 created, 0 updated, 0 unchanged, 1 refused',
                         result.output), result.output

    def test_the_refusal_lists_the_price_already_there(self, tmp_path):
        book = _book(tmp_path)
        (existing,) = _usd(book)

        result = _run(CliRunner(), 'import', str(book), str(FIXTURES / self.FIXTURE))

        assert existing.guid in result.output, result.output

    def test_the_usd_in_cad_price_is_kept(self, tmp_path):
        book = _book(tmp_path)

        _run(CliRunner(), 'import', str(book), str(FIXTURES / self.FIXTURE))

        assert _usd_and_cad(book) == [('CURRENCY:USD', 'CAD', day_neutral(2026, 1, 2))]


class TestARateAndItsInverseOnOneDayInOneFile:
    FIXTURE = 'a_usd_rate_and_its_inverse_on_one_day.txt'

    def test_both_are_refused(self, tmp_path):
        book = _book(tmp_path)

        result = _run(CliRunner(), 'import', str(book), str(FIXTURES / self.FIXTURE))

        assert result.exit_code == 1, result.output
        assert re.search(r'Prices:\s+0 created, 0 updated, 0 unchanged, 2 refused',
                         result.output), result.output

    def test_neither_is_stored(self, tmp_path):
        book = _book(tmp_path)

        _run(CliRunner(), 'import', str(book), str(FIXTURES / self.FIXTURE))

        assert _usd_and_cad(book) == [('CURRENCY:USD', 'CAD', day_neutral(2026, 1, 2))]


class TestAnEditMovingARateOntoADayItsInverseHas:
    FIXTURE = 'the_cad_in_usd_rate_moved_onto_the_usd_in_cad_day.txt'

    def test_it_is_refused(self, tmp_path):
        book = _book(tmp_path, 'a_cad_in_usd_rate_a_few_days_later.txt')
        (usd_in_cad,) = _usd(book)

        result = _run(CliRunner(), 'import', str(book), str(FIXTURES / self.FIXTURE))

        assert result.exit_code == 1, result.output
        assert usd_in_cad.guid in result.output, result.output

    def test_both_prices_stay_where_they_were(self, tmp_path):
        book = _book(tmp_path, 'a_cad_in_usd_rate_a_few_days_later.txt')

        _run(CliRunner(), 'import', str(book), str(FIXTURES / self.FIXTURE))

        assert sorted(_usd_and_cad(book), key=lambda row: row[2]) == [
            ('CURRENCY:USD', 'CAD', day_neutral(2026, 1, 2)),
            ('CURRENCY:CAD', 'USD', utc(2026, 1, 5, 18)),
        ]


class TestTwoEditsSwappingTheDaysOfTwoPrices:
    """Each moves onto the day the other still holds, so neither can be applied first."""

    FIXTURE = 'the_two_amzn_prices_swapping_days.txt'

    def test_both_are_refused(self, tmp_path):
        book = _book(tmp_path, 'another_amzn_price_a_day_later.txt')

        result = _run(CliRunner(), 'import', str(book), str(FIXTURES / self.FIXTURE))

        assert result.exit_code == 1, result.output
        assert re.search(r'Prices:\s+0 created, 0 updated, 0 unchanged, 2 refused',
                         result.output), result.output

    def test_both_prices_stay_where_they_were(self, tmp_path):
        book = _book(tmp_path, 'another_amzn_price_a_day_later.txt')

        _run(CliRunner(), 'import', str(book), str(FIXTURES / self.FIXTURE))

        assert [(p.guid, p.time) for p in prices_in(book) if p.commodity == 'NASDAQ:AMZN'] == [
            (AMZN_GUID, utc(2026, 1, 6, 21)),
            (NEXT_DAYS_AMZN_GUID, utc(2026, 1, 7, 21)),
        ]
