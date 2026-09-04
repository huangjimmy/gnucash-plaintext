"""Deleting the transaction that established a cost basis is refused while
something still measures against it.

A cost basis is not a record beside the split — it *is* the split, named by
its guid. So deleting the transaction that brought the currency in destroys
the thing every sale of that currency points at, and the sales are left naming
a guid the book no longer holds: `fx-balances` can no longer say what they
cost, the export writes those guids out, and re-importing the file fails on
them. Nothing gives that currency back either, because the basis it would go
back to is gone.

The mirror of the unpost guard. Unposting an invoice destroys its A/R split
the same way, and that has been refused all along while a sale measures
against it; this is the other way the same split can be destroyed, and it is
refused for the same reason and with the same remedy — remove the sales first,
which gives their currency back, and then the basis is free to go.

Deleting a *sale* is the ordinary direction and stays ordinary:
`test_cost_basis_restored_on_delete.py` covers it.
"""

import re
from pathlib import Path

import pytest
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


@pytest.fixture
def book_with_a_sale(tmp_path):
    """200 USD bought and borrowed, 40 of it sold against one basis.

    Returns (book, purchase_guid) — the transaction whose split is the basis
    the sale measures against.
    """
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

    # The purchase whose split is that basis. `fx-balances` lists the bought
    # 100 first and the sale prices itself at 1.35, so the basis the sale
    # measures against is the one this transaction established.
    exported = _export(runner, book, tmp_path / 'before.txt')
    purchase = re.search(
        r'2026-01-10 \* "Buy 100 USD at 1\.35"\n\tguid: "([0-9a-f]{32})"',
        exported)
    assert purchase, exported
    assert basis in exported, exported
    return book, purchase.group(1), basis


class TestItIsRefused:
    def test_the_deletion_does_not_go_through(self, book_with_a_sale):
        book, purchase, _basis = book_with_a_sale
        runner = CliRunner()

        result = _run(runner, 'delete-transactions', str(book),
                      '--by-guid', purchase)

        assert result.exit_code != 0, result.output

    def test_it_says_a_cost_basis_is_what_stops_it(self, book_with_a_sale):
        book, purchase, _basis = book_with_a_sale
        runner = CliRunner()

        result = _run(runner, 'delete-transactions', str(book),
                      '--by-guid', purchase)

        assert 'cost basis' in result.output, result.output

    def test_the_sale_holding_it_is_named(self, book_with_a_sale):
        """A book of hundreds gives the reader nothing to act on otherwise —
        the remedy is to delete those first, so they have to be findable."""
        book, purchase, _basis = book_with_a_sale
        runner = CliRunner()

        result = _run(runner, 'delete-transactions', str(book),
                      '--by-guid', purchase)

        assert 'Sell 40 USD' in result.output, result.output
        assert '40.00 USD' in result.output, result.output


class TestNothingIsLost:
    def test_the_purchase_is_still_there(self, book_with_a_sale):
        book, purchase, _basis = book_with_a_sale
        runner = CliRunner()
        _run(runner, 'delete-transactions', str(book), '--by-guid', purchase)

        assert purchase in _export(runner, book, book.parent / 'after.txt')

    def test_the_basis_still_has_what_it_had(self, book_with_a_sale):
        book, purchase, _basis = book_with_a_sale
        runner = CliRunner()
        _run(runner, 'delete-transactions', str(book), '--by-guid', purchase)

        assert 'Total USD basis balance: 160.00 USD' in _balances(runner, book)


class TestOnceTheSaleIsGone:
    def test_the_purchase_can_then_be_deleted(self, book_with_a_sale):
        """Which is what the refusal tells the reader to do."""
        book, purchase, _basis = book_with_a_sale
        runner = CliRunner()
        exported = _export(runner, book, book.parent / 'first.txt')
        sale_guid = re.search(
            r'2026-02-01 \* "Sell 40 USD"\n\tguid: "([0-9a-f]{32})"', exported)
        assert sale_guid, exported

        assert _run(runner, 'delete-transactions', str(book),
                    '--by-guid', sale_guid.group(1)).exit_code == 0

        result = _run(runner, 'delete-transactions', str(book),
                      '--by-guid', purchase)
        assert result.exit_code == 0, result.output
