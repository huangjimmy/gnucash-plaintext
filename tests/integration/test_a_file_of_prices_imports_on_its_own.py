"""A file holding nothing but prices imports on its own, and imported again changes nothing.

README, "Prices" and "Importing prices": `import` applies every price block a
file holds, with no flag and no other command; `time:` is a moment, and a bare
date is stored at the time GnuCash's transfer dialog and CSV price import give
a date; `value:` is exact; a block without a `guid:` that states exactly a
price the book holds is `unchanged`; an unchanged file imported again does not
save the book.
"""

import re
from fractions import Fraction
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.prices_in_a_book import day_neutral, prices_in, utc

FIXTURES = Path('tests/fixtures')
PRICES = FIXTURES / 'prices_of_a_currency_and_a_stock.txt'
AMZN_GUID = '4a1a4c0c7328491fbde9f8099ba280c8'


def _imported(tmp_path):
    book = tmp_path / 'book.gnucash'
    result = _run(CliRunner(), 'import', '--new', str(book), str(PRICES))
    return book, result


def _summary(output, created, updated, unchanged, refused):
    return re.search(rf'Prices:\s+{created} created, {updated} updated, '
                     rf'{unchanged} unchanged, {refused} refused', output)


def _the_one(book, commodity):
    return next(p for p in prices_in(book) if p.commodity == commodity)


class TestTheImport:
    def test_it_succeeds(self, tmp_path):
        _book, result = _imported(tmp_path)

        assert result.exit_code == 0, result.output

    def test_the_summary_counts_both_prices_created(self, tmp_path):
        _book, result = _imported(tmp_path)

        assert _summary(result.output, 2, 0, 0, 0), result.output

    def test_the_book_holds_both_prices(self, tmp_path):
        book, result = _imported(tmp_path)

        assert len(prices_in(book)) == 2, result.output


class TestTheStocksPrice:
    def test_it_keeps_the_guid_its_block_gives(self, tmp_path):
        book, _result = _imported(tmp_path)

        assert _the_one(book, 'NASDAQ:AMZN').guid == AMZN_GUID

    def test_it_is_stored_at_the_moment_its_block_gives(self, tmp_path):
        book, _result = _imported(tmp_path)

        assert _the_one(book, 'NASDAQ:AMZN').time == utc(2026, 1, 6, 21)

    def test_its_value_is_exact_and_in_its_currency(self, tmp_path):
        book, _result = _imported(tmp_path)
        price = _the_one(book, 'NASDAQ:AMZN')

        assert (price.value, price.currency) == (Fraction(21845, 100), 'USD')

    def test_its_source_and_type_are_its_blocks(self, tmp_path):
        book, _result = _imported(tmp_path)
        price = _the_one(book, 'NASDAQ:AMZN')

        assert (price.source, price.type) == ('Finance::Quote', 'last')


class TestTheRateGivenOnlyADate:
    def test_it_is_stored_at_gnucashs_time_for_that_date(self, tmp_path):
        book, _result = _imported(tmp_path)

        assert _the_one(book, 'CURRENCY:USD').time == day_neutral(2026, 1, 2)

    def test_its_decimal_value_is_exact(self, tmp_path):
        book, _result = _imported(tmp_path)

        assert _the_one(book, 'CURRENCY:USD').value == Fraction('1.3642')

    def test_gnucash_gives_it_a_guid(self, tmp_path):
        book, _result = _imported(tmp_path)
        guid = _the_one(book, 'CURRENCY:USD').guid

        assert re.fullmatch(r'[0-9a-f]{32}', guid) and guid != '0' * 32, guid


class TestImportingTheSameFileAgain:
    def test_both_prices_are_unchanged(self, tmp_path):
        book, _first = _imported(tmp_path)

        again = _run(CliRunner(), 'import', str(book), str(PRICES))

        assert again.exit_code == 0, again.output
        assert _summary(again.output, 0, 0, 2, 0), again.output

    def test_the_book_is_not_saved_again(self, tmp_path):
        book, _first = _imported(tmp_path)
        before = book.read_bytes()

        again = _run(CliRunner(), 'import', str(book), str(PRICES))

        assert 'Nothing to import' in again.output, again.output
        assert book.read_bytes() == before

    def test_no_second_price_appears(self, tmp_path):
        book, _first = _imported(tmp_path)

        _run(CliRunner(), 'import', str(book), str(PRICES))

        assert len(prices_in(book)) == 2


class TestAPriceOfACommodityNobodyDeclared:
    def test_it_is_refused(self, tmp_path):
        book, _first = _imported(tmp_path)

        result = _run(CliRunner(), 'import', str(book),
                      str(FIXTURES / 'a_price_of_a_stock_the_book_does_not_have.txt'))

        assert result.exit_code == 1, result.output
        assert 'NASDAQ:MSFT' in result.output, result.output

    def test_nothing_is_added(self, tmp_path):
        book, _first = _imported(tmp_path)

        _run(CliRunner(), 'import', str(book),
             str(FIXTURES / 'a_price_of_a_stock_the_book_does_not_have.txt'))

        assert [p.commodity for p in prices_in(book)] == ['CURRENCY:USD', 'NASDAQ:AMZN']
