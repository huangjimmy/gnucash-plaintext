"""Q-035: a refused sale leaves nothing behind.

The importer reports a failed transaction and carries on with the rest of the
file, so a sale the ledger rejects must not survive in the book — otherwise a
file of 49 good transactions plus one bad sale saves the bad one too, with no
drawdown against any basis to show for it.

Every check also runs before any balance is written, so a sale measured against
several bases never lowers one of them and then fails on the next.
"""

import re
import time
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli


def _run(runner, *args):
    time.sleep(1.1)
    return runner.invoke(cli, list(args))


def _balances(runner, book, *extra):
    result = runner.invoke(cli, ['fx-balances', str(book), *extra])
    assert result.exit_code == 0, result.output
    return result.output


def _export(runner, book, path):
    result = runner.invoke(cli, ['export', str(book), str(path)])
    assert result.exit_code == 0, result.output
    return path.read_text()


def _book(runner, tmp_path):
    book = tmp_path / 'book.gnucash'
    assert _run(runner, 'import', '--new', str(book),
                'tests/fixtures/fx_buy_and_borrow_usd.txt',
                '--include-business-objects').exit_code == 0
    basis = re.search(r'\b([0-9a-f]{32})\b', _balances(runner, book)).group(1)
    return book, basis


def _filled(tmp_path, fixture, basis, name):
    path = tmp_path / name
    path.write_text(Path(fixture).read_text().replace('{basis_a}', basis))
    return str(path)


def test_a_refused_sale_is_not_saved_while_the_rest_of_the_file_is(tmp_path):
    runner = CliRunner()
    book, basis = _book(runner, tmp_path)

    path = _filled(tmp_path, 'tests/fixtures/fx_good_txn_and_refused_sale.txt',
                   basis, 'mixed.txt')
    result = _run(runner, 'import', str(book), path)
    assert 'exceeds its basis balance' in result.output, result.output

    exported = _export(runner, book, tmp_path / 'after.txt')
    assert 'Buy 25 more USD at 1.36' in exported, exported     # the good one landed
    assert 'Sell 150 USD' not in exported, exported            # the refused one did not

    listing = _balances(runner, book)
    assert 'Total USD basis balance: 225.00 USD' in listing, listing     # 200 + 25, none sold


def test_a_sale_across_bases_lowers_none_of_them_when_it_is_refused(tmp_path):
    """Two splits naming the same basis pass individually and fail together, so
    the total is what is checked — and nothing is written before it is."""
    runner = CliRunner()
    book, basis = _book(runner, tmp_path)

    path = _filled(tmp_path, 'tests/fixtures/fx_sell_two_splits_one_basis_over.txt',
                   basis, 'double.txt')
    result = _run(runner, 'import', str(book), path)
    assert 'exceeds its basis balance' in result.output, result.output

    listing = _balances(runner, book)
    assert 'Total USD basis balance: 200.00 USD' in listing, listing
    assert '40.00 USD' not in listing, listing                 # not lowered by 60

    exported = _export(runner, book, tmp_path / 'after.txt')
    assert 'Sell 120 USD' not in exported, exported


def test_available_only_lists_bases_with_something_left(tmp_path):
    runner = CliRunner()
    book, basis = _book(runner, tmp_path)

    sale = tmp_path / 'sale.txt'
    sale.write_text(Path('tests/fixtures/fx_sell_usd_one_cost_basis.txt').read_text()
                    .replace('{basis_guid}', basis)
                    .replace('share_price: "1.40"', 'share_price: "1.35"')
                    .replace('value: "-140.00"', 'value: "-135.00"'))
    assert _run(runner, 'import', str(book), str(sale)).exit_code == 0

    listing = _balances(runner, book, '--with-balance-only')
    assert 'Borrow 100 USD' in listing, listing        # still has its 100
    assert basis not in listing, listing               # exhausted, so hidden
