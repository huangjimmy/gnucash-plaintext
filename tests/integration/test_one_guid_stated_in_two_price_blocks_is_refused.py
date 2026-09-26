"""Two `price` blocks in one file stating one guid are both refused.

A guid is one price. Two new prices stating one guid would both take it, and the
book would hold two prices under one guid; two edits of one price would both be
applied, and the order of the blocks would decide which one the price keeps.
So every block stating a guid another block in the same file states is refused,
before anything is applied.
"""

import re
from fractions import Fraction
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.prices_in_a_book import prices_in

FIXTURES = Path('tests/fixtures')
NEW_GUID = '9c9d9e9f40414243a4a5a6a7a8a9aaab'
AMZN_GUID = '4a1a4c0c7328491fbde9f8099ba280c8'


def _book_then(tmp_path, fixture):
    book = tmp_path / 'book.gnucash'
    first = _run(CliRunner(), 'import', '--new', str(book),
                 str(FIXTURES / 'prices_of_a_currency_and_a_stock.txt'))
    assert first.exit_code == 0, first.output
    result = _run(CliRunner(), 'import', str(book), str(FIXTURES / fixture))
    return book, result


class TestTwoNewPricesStatingOneGuid:
    FIXTURE = 'two_new_prices_stating_one_guid.txt'

    def test_both_are_refused(self, tmp_path):
        _book, result = _book_then(tmp_path, self.FIXTURE)

        assert result.exit_code == 1, result.output
        assert re.search(r'Prices:\s+0 created, 0 updated, 0 unchanged, 2 refused',
                         result.output), result.output
        assert f'this file states guid {NEW_GUID} in 2 price blocks' in result.output, result.output

    def test_no_price_takes_the_guid(self, tmp_path):
        book, _result = _book_then(tmp_path, self.FIXTURE)

        assert [p for p in prices_in(book) if p.guid == NEW_GUID] == []


class TestTwoEditsOfOnePrice:
    FIXTURE = 'the_amzn_price_set_to_two_values_through_its_guid.txt'

    def test_both_are_refused(self, tmp_path):
        _book, result = _book_then(tmp_path, self.FIXTURE)

        assert result.exit_code == 1, result.output
        assert re.search(r'Prices:\s+0 created, 0 updated, 0 unchanged, 2 refused',
                         result.output), result.output
        assert f'this file states guid {AMZN_GUID} in 2 price blocks' in result.output, result.output

    def test_the_price_keeps_its_value(self, tmp_path):
        book, _result = _book_then(tmp_path, self.FIXTURE)

        assert [(p.guid, p.value) for p in prices_in(book) if p.commodity == 'NASDAQ:AMZN'] == [
            (AMZN_GUID, Fraction(21845, 100)),
        ]
