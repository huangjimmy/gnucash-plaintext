"""A sale may draw on a receivable no invoice holds.

A sale against a receivable is refused until the invoice it belongs to is
collected, and whether it was is read off that invoice's lot. A debit entered
straight onto the receivable, as an opening balance is, belongs to no invoice
and sits in no lot, so there is nothing to read: the sale is measured against
it like any other cost basis.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run


def test_the_sale_is_measured_against_it(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = _run(runner, 'import', '--new', str(book),
                  'tests/fixtures/fx_a_usd_receivable_no_invoice_holds.txt')
    assert result.exit_code == 0, result.output
    assert 'Errors:       0' in result.output, result.output

    listing = _run(runner, 'fx-balances', str(book)).output
    receivable = re.search(r'\b([0-9a-f]{32})\b', listing).group(1)
    sale = tmp_path / 'sale.txt'
    sale.write_text(Path('tests/fixtures/fx_sell_usd_partial.txt').read_text()
                    .replace('{basis_a}', receivable))

    result = _run(runner, 'import', str(book), str(sale))
    assert result.exit_code == 0, result.output
    assert 'Errors:       0' in result.output, result.output

    listing = _run(runner, 'fx-balances', str(book)).output
    assert 'Total USD cost basis balance: 60.00 USD' in listing, listing
