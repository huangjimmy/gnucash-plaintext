"""A price is changed in place through its guid, and a key a block leaves out changes nothing.

README, "One price a day": when the book holds a price with the block's
`guid:`, `import` edits that price in place; the guid stays, even when `time:`
moves the price to another day; the run reports it `updated`.
"""

import re
from fractions import Fraction
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.prices_in_a_book import prices_in, utc

FIXTURES = Path('tests/fixtures')
AMZN_GUID = '4a1a4c0c7328491fbde9f8099ba280c8'


def _book_then(tmp_path, fixture):
    book = tmp_path / 'book.gnucash'
    first = _run(CliRunner(), 'import', '--new', str(book),
                 str(FIXTURES / 'prices_of_a_currency_and_a_stock.txt'))
    assert first.exit_code == 0, first.output
    result = _run(CliRunner(), 'import', str(book), str(FIXTURES / fixture))
    return book, result


def _amzn(book):
    return [p for p in prices_in(book) if p.commodity == 'NASDAQ:AMZN']


class TestAValueCorrected:
    FIXTURE = 'a_stocks_price_corrected_through_its_guid.txt'

    def test_it_is_reported_updated(self, tmp_path):
        _book, result = _book_then(tmp_path, self.FIXTURE)

        assert result.exit_code == 0, result.output
        assert re.search(r'Prices:\s+0 created, 1 updated, 0 unchanged, 0 refused',
                         result.output), result.output

    def test_the_value_is_the_new_one(self, tmp_path):
        book, _result = _book_then(tmp_path, self.FIXTURE)

        assert [p.value for p in _amzn(book)] == [Fraction(22000, 100)]

    def test_the_price_keeps_its_guid(self, tmp_path):
        book, _result = _book_then(tmp_path, self.FIXTURE)

        assert [p.guid for p in _amzn(book)] == [AMZN_GUID]

    def test_what_the_block_leaves_out_is_as_it_was(self, tmp_path):
        book, _result = _book_then(tmp_path, self.FIXTURE)
        (price,) = _amzn(book)

        assert (price.time, price.currency, price.source, price.type) == \
            (utc(2026, 1, 6, 21), 'USD', 'Finance::Quote', 'last')


class TestAPriceMovedToAnotherDay:
    FIXTURE = 'a_stocks_price_moved_to_another_day_through_its_guid.txt'

    def test_it_is_reported_updated(self, tmp_path):
        _book, result = _book_then(tmp_path, self.FIXTURE)

        assert result.exit_code == 0, result.output
        assert re.search(r'Prices:\s+0 created, 1 updated, 0 unchanged, 0 refused',
                         result.output), result.output

    def test_it_is_at_the_new_time(self, tmp_path):
        book, _result = _book_then(tmp_path, self.FIXTURE)

        assert [p.time for p in _amzn(book)] == [utc(2026, 1, 9, 21)]

    def test_it_is_still_the_same_price(self, tmp_path):
        """Moved, not replaced: one price, and its guid."""
        book, _result = _book_then(tmp_path, self.FIXTURE)

        assert [(p.guid, p.value) for p in _amzn(book)] == [(AMZN_GUID, Fraction(21845, 100))]


class TestADayAPriceIsMovedOffInTheSameFile:
    """A file that moves a price off a day may add a new price for that day.

    The new block is written first in the file; the move is what frees the day.
    """

    FIXTURE = 'the_amzn_price_moved_a_day_on_and_a_new_price_in_its_place.txt'

    def test_both_are_applied(self, tmp_path):
        _book, result = _book_then(tmp_path, self.FIXTURE)

        assert result.exit_code == 0, result.output
        assert re.search(r'Prices:\s+1 created, 1 updated, 0 unchanged, 0 refused',
                         result.output), result.output

    def test_the_moved_price_and_the_new_one_are_both_there(self, tmp_path):
        book, _result = _book_then(tmp_path, self.FIXTURE)

        prices = sorted(_amzn(book), key=lambda p: p.time)
        assert [(p.time, p.value) for p in prices] == [
            (utc(2026, 1, 6, 21), Fraction(21900, 100)),
            (utc(2026, 1, 8, 21), Fraction(21845, 100)),
        ]
        assert prices[1].guid == AMZN_GUID
        assert prices[0].guid != AMZN_GUID


class TestAPriceMovedOntoADayAnotherEditInTheFileFrees:
    """Two edits: the first moves a price onto a day the second moves a price off.

    The order of the blocks does not decide what is applied. The first block is
    read while its day is still taken; it waits for the edit that frees the day.
    """

    FIXTURE = 'the_amzn_price_moved_onto_a_day_another_edit_frees.txt'

    def _book_then(self, tmp_path):
        book, _first = _book_then(tmp_path, 'another_amzn_price_a_day_later.txt')
        assert _first.exit_code == 0, _first.output
        result = _run(CliRunner(), 'import', str(book), str(FIXTURES / self.FIXTURE))
        return book, result

    def test_both_are_applied(self, tmp_path):
        _book, result = self._book_then(tmp_path)

        assert result.exit_code == 0, result.output
        assert re.search(r'Prices:\s+0 created, 2 updated, 0 unchanged, 0 refused',
                         result.output), result.output

    def test_each_price_is_on_its_new_day(self, tmp_path):
        book, _result = self._book_then(tmp_path)

        assert [(p.guid, p.time) for p in _amzn(book)] == [
            (AMZN_GUID, utc(2026, 1, 7, 21)),
            ('5b2b5d1d8439402a96c7f910acb391d9', utc(2026, 1, 8, 21)),
        ]


class TestAnExistingPriceMovedToAnotherCurrency:
    """A price is of one commodity in one currency, and GnuCash files it under that pair."""

    FIXTURE = 'a_stocks_price_moved_to_another_currency_through_its_guid.txt'

    def test_it_is_refused(self, tmp_path):
        _book, result = _book_then(tmp_path, self.FIXTURE)

        assert result.exit_code == 1, result.output
        assert AMZN_GUID in result.output, result.output

    def test_the_price_keeps_its_currency(self, tmp_path):
        book, _result = _book_then(tmp_path, self.FIXTURE)

        assert [(p.guid, p.currency) for p in _amzn(book)] == [(AMZN_GUID, 'USD')]
