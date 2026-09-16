"""A price's source and type are exported and imported exactly as the book holds them.

README, "`source:` and `type:` belong to the price": a book's prices were put
there by GnuCash — Finance::Quote, the transfer dialog, a price nobody gave a
type — and `export --include-prices` writes each source and type as the book
holds it; the ledger imported into a fresh book gives the same prices back,
guid included. gnucash-plaintext never gives a price a source: a block with
none leaves GnuCash's default, `invalid`. A source GnuCash does not define is
refused, because GnuCash would silently store it as `invalid` (Q-041, table 5).
"""

import re
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.prices_in_a_book import add_prices, price_blocks, prices_in, utc

FIXTURES = Path('tests/fixtures')

PRICES_GNUCASH_WROTE = [
    {'commodity': 'NASDAQ:AMZN', 'currency': 'USD', 'time': utc(2026, 1, 6, 21),
     'value': '21845/100', 'source': 'Finance::Quote', 'type': 'last'},
    {'commodity': 'CURRENCY:USD', 'currency': 'CAD', 'time': utc(2026, 1, 5, 10, 59),
     'value': '100/73', 'source': 'user:xfer-dialog', 'type': 'transaction'},
    {'commodity': 'CURRENCY:HKD', 'currency': 'CAD', 'time': utc(2026, 1, 7, 12),
     'value': '17/100'},
]


def _exported(tmp_path):
    book = tmp_path / 'book.gnucash'
    add_prices(book, PRICES_GNUCASH_WROTE)
    ledger = tmp_path / 'ledger.txt'
    result = _run(CliRunner(), 'export', str(book), str(ledger), '--include-prices')
    assert result.exit_code == 0, result.output
    return book, ledger


def _block(ledger, mnemonic):
    return next(b for b in price_blocks(ledger.read_text()) if b['commodity.mnemonic'] == mnemonic)


class TestTheExport:
    def test_a_quotes_source_and_type_are_written(self, tmp_path):
        _book, ledger = _exported(tmp_path)

        block = _block(ledger, 'AMZN')

        assert (block['source'], block['type']) == ('Finance::Quote', 'last')

    def test_a_transfer_dialogs_source_and_type_are_written(self, tmp_path):
        _book, ledger = _exported(tmp_path)

        block = _block(ledger, 'USD')

        assert (block['source'], block['type']) == ('user:xfer-dialog', 'transaction')

    def test_a_price_with_no_source_is_written_with_gnucashs_default(self, tmp_path):
        _book, ledger = _exported(tmp_path)

        assert _block(ledger, 'HKD')['source'] == 'invalid'

    def test_a_price_with_no_type_gets_no_type_line(self, tmp_path):
        _book, ledger = _exported(tmp_path)

        assert 'type' not in _block(ledger, 'HKD')


class TestTheLedgerImportedIntoAFreshBook:
    def test_it_gives_the_same_prices_back(self, tmp_path):
        book, ledger = _exported(tmp_path)
        fresh = tmp_path / 'fresh.gnucash'

        result = _run(CliRunner(), 'import', '--new', str(fresh), str(ledger))

        assert result.exit_code == 0, result.output
        assert prices_in(fresh) == prices_in(book)


class TestAPriceGivenAnotherSourceAndType:
    FIXTURE = 'a_price_given_another_source_and_type.txt'

    def test_both_are_updated_and_nothing_else_moves(self, tmp_path):
        book, ledger = _exported(tmp_path)
        before = next(p for p in prices_in(book) if p.commodity == 'CURRENCY:USD')
        edit = tmp_path / 'edit.txt'
        edit.write_text((FIXTURES / self.FIXTURE).read_text()
                        .replace('{guid}', _block(ledger, 'USD')['guid']))

        result = _run(CliRunner(), 'import', str(book), str(edit))

        assert result.exit_code == 0, result.output
        assert re.search(r'Prices:\s+0 created, 1 updated, 0 unchanged, 0 refused',
                         result.output), result.output
        after = next(p for p in prices_in(book) if p.commodity == 'CURRENCY:USD')
        assert (after.source, after.type) == ('user:price-editor', 'bid')
        assert (after.currency, after.time, after.value) == (
            before.currency, before.time, before.value)


class TestAPriceWithNoSourceAndNoType:
    FIXTURE = 'a_price_with_no_source_and_no_type.txt'

    def test_it_keeps_gnucashs_default_source_and_no_type(self, tmp_path):
        book = tmp_path / 'book.gnucash'

        result = _run(CliRunner(), 'import', '--new', str(book), str(FIXTURES / self.FIXTURE))

        assert result.exit_code == 0, result.output
        assert [(p.source, p.type) for p in prices_in(book)] == [('invalid', None)]


class TestASourceGnuCashDoesNotDefine:
    FIXTURE = 'a_price_with_a_source_gnucash_does_not_define.txt'

    def test_it_is_refused_quoting_the_source(self, tmp_path):
        book = tmp_path / 'book.gnucash'
        add_prices(book, [])

        result = _run(CliRunner(), 'import', str(book), str(FIXTURES / self.FIXTURE))

        assert result.exit_code == 1, result.output
        assert 'my-spreadsheet' in result.output, result.output

    def test_no_price_is_stored(self, tmp_path):
        book = tmp_path / 'book.gnucash'
        add_prices(book, [])

        _run(CliRunner(), 'import', str(book), str(FIXTURES / self.FIXTURE))

        assert prices_in(book) == []
