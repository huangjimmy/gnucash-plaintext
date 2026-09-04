"""Q-035: deleting a sale returns what it took to the cost basis.

Undoing a sale is how a user corrects one — and how anyone trying the feature
out gets back to a clean state. The basis balance follows: it is derived
from what the book actually holds, so the moment the sale is gone the basis has
its currency back, and the stored KVP is rewritten to match.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from tests.conftest import _run


def _balances(runner, book):
    result = runner.invoke(cli, ['fx-balances', str(book)])
    assert result.exit_code == 0, result.output
    return result.output


def _export(runner, book, path):
    result = runner.invoke(cli, ['export', str(book), str(path)])
    assert result.exit_code == 0, result.output
    return path.read_text()


def test_deleting_a_sale_gives_the_currency_back(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert _run(runner, 'import', '--new', str(book),
                'tests/fixtures/fx_buy_and_borrow_usd.txt',
                '--include-business-objects').exit_code == 0
    basis = re.search(r'\b([0-9a-f]{32})\b', _balances(runner, book)).group(1)

    sale = tmp_path / 'sale.txt'
    sale.write_text(Path('tests/fixtures/fx_sell_usd_partial.txt').read_text()
                    .replace('{basis_a}', basis))
    assert _run(runner, 'import', str(book), str(sale)).exit_code == 0
    assert 'Total USD basis balance: 160.00 USD' in _balances(runner, book)

    exported = _export(runner, book, tmp_path / 'before.txt')
    sale_guid = re.search(
        r'2026-02-01 \* "Sell 40 USD"\n\tguid: "([0-9a-f]{32})"', exported)
    assert sale_guid, exported

    result = _run(runner, 'delete-transactions', str(book),
                  '--by-guid', sale_guid.group(1))
    assert result.exit_code == 0, result.output

    # The basis has its 40 USD back, in the listing and in the stored KVP.
    listing = _balances(runner, book)
    assert 'Total USD basis balance: 200.00 USD' in listing, listing
    assert '60.00 USD' not in listing, listing

    after = _export(runner, book, tmp_path / 'after.txt')
    assert 'cost_basis_balance: "100.00"' in after, after
    assert 'Sell 40 USD' not in after, after


def test_the_basis_is_sellable_again_after_the_delete(tmp_path):
    """The whole amount can be sold once the earlier sale is gone — the book,
    not a stale number, decides what is available."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert _run(runner, 'import', '--new', str(book),
                'tests/fixtures/fx_buy_and_borrow_usd.txt',
                '--include-business-objects').exit_code == 0
    basis = re.search(r'\b([0-9a-f]{32})\b', _balances(runner, book)).group(1)

    sale = tmp_path / 'sale.txt'
    sale.write_text(Path('tests/fixtures/fx_sell_usd_partial.txt').read_text()
                    .replace('{basis_a}', basis))
    assert _run(runner, 'import', str(book), str(sale)).exit_code == 0

    exported = _export(runner, book, tmp_path / 'before.txt')
    sale_guid = re.search(
        r'2026-02-01 \* "Sell 40 USD"\n\tguid: "([0-9a-f]{32})"', exported).group(1)
    assert _run(runner, 'delete-transactions', str(book),
                '--by-guid', sale_guid).exit_code == 0

    full = tmp_path / 'full_sale.txt'
    full.write_text(Path('tests/fixtures/fx_sell_usd_one_cost_basis.txt').read_text()
                    .replace('{basis_guid}', basis)
                    .replace('share_price: "1.40"', 'share_price: "1.35"')
                    .replace('value: "-140.00"', 'value: "-135.00"'))
    result = _run(runner, 'import', str(book), str(full))
    assert result.exit_code == 0, result.output
    assert 'error:' not in result.output, result.output
    assert 'Total USD basis balance: 100.00 USD' in _balances(runner, book)
