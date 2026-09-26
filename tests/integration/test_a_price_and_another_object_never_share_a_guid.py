"""A price and any other object in a book never share a guid.

GnuCash keeps a guid unique across every kind of object in a book, and a book
where two objects hold one guid is corrupt (`_guid_in_use_anywhere`). A price
is one of those objects: a `price` block stating a guid another object holds is
refused, and so is a block of another kind stating a price's guid.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.prices_in_a_book import prices_in

FIXTURES = Path('tests/fixtures')
TRANSACTION_GUID = '8a8b8c8d8e8f40418243844586878889'
AMZN_GUID = '4a1a4c0c7328491fbde9f8099ba280c8'


class TestAPriceStatingATransactionsGuid:
    FIXTURE = 'a_price_stating_the_transactions_guid.txt'

    def _book(self, tmp_path):
        book = tmp_path / 'book.gnucash'
        first = _run(CliRunner(), 'import', '--new', str(book),
                     str(FIXTURES / 'a_transaction_with_its_guid.txt'))
        assert first.exit_code == 0, first.output
        return book

    def test_it_is_refused(self, tmp_path):
        book = self._book(tmp_path)

        result = _run(CliRunner(), 'import', str(book), str(FIXTURES / self.FIXTURE))

        assert result.exit_code == 1, result.output
        assert re.search(r'Prices:\s+0 created, 0 updated, 0 unchanged, 1 refused',
                         result.output), result.output
        assert f'guid {TRANSACTION_GUID} is already used by an existing transaction' in \
            result.output, result.output

    def test_no_price_is_created(self, tmp_path):
        book = self._book(tmp_path)

        _run(CliRunner(), 'import', str(book), str(FIXTURES / self.FIXTURE))

        assert prices_in(book) == []


class TestACustomerStatingAPricesGuid:
    FIXTURE = 'a_customer_stating_the_amzn_prices_guid.txt'

    def _book(self, tmp_path):
        book = tmp_path / 'book.gnucash'
        first = _run(CliRunner(), 'import', '--new', str(book),
                     str(FIXTURES / 'prices_of_a_currency_and_a_stock.txt'))
        assert first.exit_code == 0, first.output
        return book

    def test_it_is_refused(self, tmp_path):
        book = self._book(tmp_path)

        result = _run(CliRunner(), 'import', str(book), str(FIXTURES / self.FIXTURE),
                      '--include-business-objects')

        assert result.exit_code != 0, result.output
        assert f'guid {AMZN_GUID} is already used by an existing price' in result.output, \
            result.output

    def test_the_price_keeps_its_guid(self, tmp_path):
        book = self._book(tmp_path)

        _run(CliRunner(), 'import', str(book), str(FIXTURES / self.FIXTURE),
             '--include-business-objects')

        assert [p.guid for p in prices_in(book) if p.commodity == 'NASDAQ:AMZN'] == [AMZN_GUID]
