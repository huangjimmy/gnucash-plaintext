"""A sale states what the currency it sells cost, to the cent the book holds.

Valuing the currency at its basis is what makes the residual split the gain or
the loss: the currency leaves at cost, the other splits say what it fetched,
and the difference is what was made on it. A value that is not the basis puts
part of the gain in the wrong place, quietly.

`basis_cost × quantity` can land between cents — 33.00 USD held at a stated
1.405 costs 46.365 CAD — and no split can hold that, so GnuCash books what it
rounds to, 46.37, away from zero. The check used to allow anything within half
a cent of the unrounded figure, which accepted 46.36 as readily as the 46.37
the book holds. The rounding is performed now and the comparison is exact.
"""

import re
import time
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

BOUGHT = 'tests/fixtures/fx_sell_part_of_a_lot_bought_at_a_three_decimal_rate.txt'
SOLD = 'tests/fixtures/fx_sell_part_of_a_lot_at_its_basis.txt'


def _run(runner, *args):
    time.sleep(1.1)
    return runner.invoke(cli, list(args))


def _a_book_holding_100_usd(runner, tmp_path, name):
    """100.00 USD bought for 140.50 CAD, and the guid of the basis it opened."""
    book = tmp_path / name
    assert _run(runner, 'import', '--new', str(book), BOUGHT).exit_code == 0

    listing = runner.invoke(cli, ['fx-balances', str(book)])
    assert listing.exit_code == 0, listing.output
    return book, re.search(r'\b([0-9a-f]{32})\b', listing.output).group(1)


def _sale_valued(tmp_path, basis, value='-46.37'):
    """The sale fixture, against `basis`, stating `value` for what it cost."""
    path = tmp_path / f'sale{value}.txt'
    path.write_text(
        Path(SOLD).read_text(encoding='utf-8')
        .replace('{basis_guid}', basis)
        .replace('value: "-46.37"', f'value: "{value}"'),
        encoding='utf-8')
    return str(path)


def test_the_cent_below_what_the_basis_makes_it_worth_is_refused(tmp_path):
    """33 × 1.405 is 46.365, which the book holds as 46.37. A file saying
    46.36 was accepted while the check forgave half a cent."""
    runner = CliRunner()
    book, basis = _a_book_holding_100_usd(runner, tmp_path, 'under.gnucash')

    result = _run(runner, 'import', str(book),
                  _sale_valued(tmp_path, basis, '-46.36'))

    assert result.exit_code != 0, result.output
    assert '46.37' in result.output, result.output
    assert basis in result.output, result.output

    exported = tmp_path / 'after.txt'
    assert _run(runner, 'export', str(book), str(exported)).exit_code == 0
    assert 'Sell 33 USD' not in exported.read_text(), exported.read_text()


def test_and_the_figure_the_book_holds_is_accepted(tmp_path):
    """The other side of it: comparing exactly must not refuse the figure the
    engine itself books for that sale."""
    runner = CliRunner()
    book, basis = _a_book_holding_100_usd(runner, tmp_path, 'exact.gnucash')

    result = _run(runner, 'import', str(book),
                  _sale_valued(tmp_path, basis, '-46.37'))

    assert result.exit_code == 0, result.output
    exported = tmp_path / 'after.txt'
    assert _run(runner, 'export', str(book), str(exported)).exit_code == 0
    text = exported.read_text()
    assert 'Sell 33 USD' in text, text
    # Valued at its basis, so the residual carries the loss: 46.00 fetched
    # for currency that cost 46.37.
    assert 'Income:FX Gain 0.37 CAD' in text, text
