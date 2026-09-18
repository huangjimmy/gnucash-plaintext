"""A disposal's gain counts whether the file declares it or works it out.

`$residual$` resolves to the negation of what the other splits come to, and the
import records which split took it in a `took_the_residual` KVP. That key is
the whole of the difference between the two ways of writing a disposal: the
accounts, the amounts and the values a file produces are the same either way.

So a writer who computes the figure themselves states it, and states the key
beside it. The key cannot be worked out afterwards, because a balanced
transaction gives every one of its splits the same arithmetic — the gain is the
negation of the other two, and so is the bank line, and so is the currency line
— and it cannot be read off the account either: 8.60 USD disposed of at a cost
of 11.99 paid an 11.92 bank charge beside 0.07 of exchange difference, both on
expense accounts.

These draw the same sale both ways and read the pages against each other.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.text_report_pages import key_of

BOUGHT = 'tests/fixtures/a_cad_book_that_bought_a_thousand_usd.txt'
DECLARED = 'tests/fixtures/the_thousand_usd_sold_at_a_higher_rate.txt'
WRITTEN_OUT = 'tests/fixtures/the_thousand_usd_sold_with_the_gain_written_out.txt'
AS_OF = '2026-12-31'


def _sold(runner, tmp_path, sale, name):
    """The purchase, then `sale` on top of it, in a book of its own."""
    book = tmp_path / f'{name}.gnucash'
    bought = _run(runner, 'import', '--new', str(book), BOUGHT)
    assert bought.exit_code == 0, bought.output

    listing = _run(runner, 'fx-balances', str(book))
    assert listing.exit_code == 0, listing.output
    found = re.search(r'\b([0-9a-f]{32})\b', listing.output)
    assert found, listing.output

    ledger = tmp_path / f'{name}.txt'
    ledger.write_text(
        Path(sale).read_text(encoding='utf-8').replace('{usd_basis}', found.group(1)),
        encoding='utf-8')
    landed = _run(runner, 'import', str(book), str(ledger))
    assert landed.exit_code == 0, landed.output
    return book


def _page(runner, book):
    drawn = _run(runner, 'balance-sheet', str(book), '--as-of', AS_OF)
    assert drawn.exit_code == 0, drawn.output
    return drawn.output


def _both(tmp_path):
    runner = CliRunner()
    return (_page(runner, _sold(runner, tmp_path, DECLARED, 'declared')),
            _page(runner, _sold(runner, tmp_path, WRITTEN_OUT, 'written_out')))


def test_the_gain_is_the_hundred_the_sale_made(tmp_path):
    """1,000.00 USD costing 1,300.00 CAD fetched 1,400.00."""
    declared, written_out = _both(tmp_path)

    assert key_of(declared, 'realized_gains_fx') == '100.00 CAD'
    assert key_of(written_out, 'realized_gains_fx') == '100.00 CAD'


def test_a_gain_written_out_is_counted(tmp_path):
    """The point of the key: without it the book would state 0.00."""
    _declared, written_out = _both(tmp_path)

    assert key_of(written_out, 'total_realized_gains') == '100.00 CAD'


def test_both_ways_draw_the_same_page(tmp_path):
    """Same accounts, same amounts, same values — so the same statement."""
    declared, written_out = _both(tmp_path)

    assert declared == written_out


def test_the_working_states_the_gain_either_way(tmp_path):
    """A figure counted without its working would be a figure taken on trust."""
    declared, written_out = _both(tmp_path)

    listed = [line.strip() for line in written_out.splitlines()
              if line.lstrip().startswith('#   ') and 'Income:FX Gain' in line]
    assert listed == ['#   2026-06-01 Income:FX Gain 100.00 CAD'], written_out
    assert listed == [line.strip() for line in declared.splitlines()
                      if line.lstrip().startswith('#   ') and 'Income:FX Gain' in line]
