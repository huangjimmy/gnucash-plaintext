"""A price block is refused for what it states, with the reason, and the book's prices are left alone.

Each block in the fixture states something GnuCash cannot record or this format
does not allow: a value dividing by zero or too large to store, a day that does
not exist, a time written neither as a date nor as a moment, a currency GnuCash
does not know, a namespace without a mnemonic, an existing price moved to another
commodity, a new price with no value, and a guid that is not one. Every one is
refused, counted, and said, and the rest of the file is still read.
"""

import re
from fractions import Fraction
from pathlib import Path

import pytest
from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.prices_in_a_book import prices_in

FIXTURES = Path('tests/fixtures')
AMZN_GUID = '4a1a4c0c7328491fbde9f8099ba280c8'


@pytest.fixture
def imported(tmp_path):
    book = tmp_path / 'book.gnucash'
    first = _run(CliRunner(), 'import', '--new', str(book),
                 str(FIXTURES / 'prices_of_a_currency_and_a_stock.txt'))
    assert first.exit_code == 0, first.output
    result = _run(CliRunner(), 'import', str(book),
                  str(FIXTURES / 'price_blocks_each_refused_for_what_they_state.txt'))
    return book, result


def test_every_block_is_refused_and_counted(imported):
    _book, result = imported

    assert result.exit_code == 1, result.output
    assert re.search(r'Prices:\s+0 created, 0 updated, 0 unchanged, 9 refused',
                     result.output), result.output


@pytest.mark.parametrize('reason', [
    'value: "1/0" divides by zero',
    'value: "99999999999999999999" is too large for GnuCash to store',
    'time: "2026-02-30" is not a date',
    'time: "yesterday" is neither a date',
    'XYZ is not a currency GnuCash knows',
    'commodity.namespace and commodity.mnemonic are stated together, or neither',
    "a price's commodity does not change",
    'a new price needs value',
    'not-a-guid',
])
def test_each_reason_is_printed(imported, reason):
    _book, result = imported

    assert reason in result.output, result.output


def test_the_books_prices_are_left_as_they_were(imported):
    book, _result = imported

    held = sorted((p.commodity, p.value) for p in prices_in(book))
    assert held == [('CURRENCY:USD', Fraction(13642, 10000)),
                    ('NASDAQ:AMZN', Fraction(21845, 100))], held
