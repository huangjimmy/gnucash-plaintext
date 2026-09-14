"""A `price` block giving a key a price does not take is refused, and the key is listed.

A transaction, a split or a business object keeps a key it does not read as
custom metadata, and the next export shows it. A price has no custom metadata,
so a key `import` does not read would be dropped: a correction written under a
misspelled key would be lost, with the price reported unchanged.
"""

import re
from fractions import Fraction
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.prices_in_a_book import prices_in

FIXTURES = Path('tests/fixtures')
AMZN_GUID = '4a1a4c0c7328491fbde9f8099ba280c8'


def _book_then(tmp_path, fixture):
    book = tmp_path / 'book.gnucash'
    first = _run(CliRunner(), 'import', '--new', str(book),
                 str(FIXTURES / 'prices_of_a_currency_and_a_stock.txt'))
    assert first.exit_code == 0, first.output
    result = _run(CliRunner(), 'import', str(book), str(FIXTURES / fixture))
    return book, result


class TestACorrectionUnderAMisspelledKey:
    FIXTURE = 'the_amzn_price_corrected_under_a_misspelled_key.txt'

    def test_it_is_refused_and_the_key_is_listed(self, tmp_path):
        _book, result = _book_then(tmp_path, self.FIXTURE)

        assert result.exit_code == 1, result.output
        assert re.search(r'Prices:\s+0 created, 0 updated, 0 unchanged, 1 refused',
                         result.output), result.output
        assert 'valeu' in result.output, result.output

    def test_the_price_keeps_its_value(self, tmp_path):
        book, _result = _book_then(tmp_path, self.FIXTURE)

        assert [(p.guid, p.value) for p in prices_in(book) if p.commodity == 'NASDAQ:AMZN'] == [
            (AMZN_GUID, Fraction(21845, 100)),
        ]


class TestANewPriceWithAKeyAPriceDoesNotTake:
    FIXTURE = 'a_new_usd_rate_with_a_key_a_price_does_not_take.txt'

    def test_it_is_refused_and_the_key_is_listed(self, tmp_path):
        _book, result = _book_then(tmp_path, self.FIXTURE)

        assert result.exit_code == 1, result.output
        assert re.search(r'Prices:\s+0 created, 0 updated, 0 unchanged, 1 refused',
                         result.output), result.output
        assert 'currency.namespace' in result.output, result.output

    def test_no_price_is_created(self, tmp_path):
        book, _result = _book_then(tmp_path, self.FIXTURE)

        assert len([p for p in prices_in(book) if p.commodity == 'CURRENCY:USD']) == 1
