"""Deleting the transaction that established a cost basis makes what drew on it pending.

A cost basis is the split, found by its guid, so deleting the transaction
that brought the currency in destroys the cost basis every sale of that
currency drew on. The delete is not refused for it: which cost basis each
such sale draws on instead may not be known yet, and the user is not made to
choose one before the delete goes through. Each is written
`cost_basis_split_guid: $pending$`, the command lists them, and the user
states the cost basis each draws on when they know (Q-054).

`fx_buy_and_borrow_usd.txt`: 100.00 USD bought at 1.35 and 100.00 USD
borrowed at 1.30, and 40.00 USD sold against the purchase's cost basis.

Deleting a *sale* is the ordinary direction: `test_cost_basis_restored_on_delete.py`
covers it.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run

BOUGHT = '0d0d0d0d0d0d0d0d0d0d0d0d0d0d0135'
BORROWED = '0d0d0d0d0d0d0d0d0d0d0d0d0d0d0130'


def _book_with_a_sale(tmp_path):
    """The book, the purchase's transaction guid, and the sale's."""
    book = tmp_path / 'book.gnucash'
    assert _run(CliRunner(), 'import', '--new', str(book),
                'tests/fixtures/fx_buy_and_borrow_usd.txt',
                '--include-business-objects').exit_code == 0
    sale = tmp_path / 'sale.txt'
    sale.write_text(Path('tests/fixtures/fx_sell_usd_partial.txt').read_text()
                    .replace('{basis_a}', BOUGHT))
    assert _run(CliRunner(), 'import', str(book), str(sale)).exit_code == 0

    exported = tmp_path / 'before.txt'
    assert _run(CliRunner(), 'export', str(book), str(exported)).exit_code == 0
    text = exported.read_text()
    purchase = re.search(r'2026-01-10 \* "Buy 100 USD at 1\.35"\n\tguid: "([0-9a-f]{32})"', text)
    the_sale = re.search(r'2026-02-01 \* "Sell 40 USD"\n\tguid: "([0-9a-f]{32})"', text)
    assert purchase and the_sale, text
    return book, purchase.group(1), the_sale.group(1)


def _listing(book):
    costs = _run(CliRunner(), 'fx-balances', str(book), '--verify-costs')
    assert costs.exit_code == 0 and 'warning' not in costs.output, costs.output
    return costs.output


def test_the_delete_goes_through_and_lists_the_sale_made_pending(tmp_path):
    book, purchase, _ = _book_with_a_sale(tmp_path)

    done = _run(CliRunner(), 'delete-transactions', str(book), '--by-guid', purchase)

    assert done.exit_code == 0, done.output
    assert '1 disposal(s) drew on its cost basis and are now pending' in done.output, done.output
    assert "2026-02-01 'Sell 40 USD' (40.00 USD)" in done.output, done.output


def test_the_purchase_s_cost_basis_is_gone_and_the_sale_is_pending(tmp_path):
    book, purchase, _ = _book_with_a_sale(tmp_path)

    _run(CliRunner(), 'delete-transactions', str(book), '--by-guid', purchase)

    listed = _listing(book)
    assert BOUGHT not in listed, listed
    assert re.search(rf'{BORROWED}.*100\.00 USD\s+100\.00 USD\s+asset', listed), listed
    assert '1 disposal(s) pending their cost basis: 40.00 USD.' in listed, listed


def test_a_sale_deleted_in_the_same_run_as_its_purchase_is_not_listed_as_pending(tmp_path):
    book, purchase, sale = _book_with_a_sale(tmp_path)

    done = _run(CliRunner(), 'delete-transactions', str(book), '--by-guid', purchase, sale)

    assert done.exit_code == 0, done.output
    assert 'pending' not in done.output, done.output
    listed = _listing(book)
    assert 'pending their cost basis' not in listed, listed


def test_a_fee_drawing_on_its_own_transaction_s_arrival_is_not_listed_as_pending(tmp_path):
    book, _, _ = _book_with_a_sale(tmp_path)
    assert _run(CliRunner(), 'import', str(book),
                'tests/fixtures/a_wire_whose_fee_draws_on_its_own_arrival.txt').exit_code == 0

    done = _run(CliRunner(), 'delete-transactions', str(book), '--by-guid',
                '0d0d0d0d0d0d0d0d0d0d0d0d0d0d7200')

    assert done.exit_code == 0, done.output
    assert 'pending' not in done.output, done.output
    listed = _listing(book)
    assert '0d0d0d0d0d0d0d0d0d0d0d0d0d0d0140' not in listed, listed
    assert 'pending their cost basis' not in listed, listed


def test_the_user_then_states_the_borrowing_s_cost_basis_on_the_sale(tmp_path):
    book, purchase, sale = _book_with_a_sale(tmp_path)
    _run(CliRunner(), 'delete-transactions', str(book), '--by-guid', purchase)

    restated = tmp_path / 'restated.txt'
    restated.write_text(
        '2026-02-01 * "Sell 40 USD"\n'
        f'\tguid: "{sale}"\n'
        '\tcurrency.mnemonic: "CAD"\n'
        '\tAssets:Bank:USD -40.00 USD\n'
        '\t\taccount.commodity.mnemonic: "USD"\n'
        '\t\tshare_price: "1.30"\n'
        '\t\tvalue: "-52.00"\n'
        f'\t\tcost_basis_split_guid: "{BORROWED}"\n'
        '\tAssets:Bank 55.60 CAD\n'
        '\t\taccount.commodity.mnemonic: "CAD"\n'
        '\t\tshare_price: "1"\n'
        '\t\tvalue: "55.60"\n'
        '\tIncome:FX Gain $residual$ CAD\n'
        '\t\taccount.commodity.mnemonic: "CAD"\n')
    done = _run(CliRunner(), 'import', '--strategy', 'update', str(book), str(restated))

    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    listed = _listing(book)
    assert 'pending their cost basis' not in listed, listed
    assert re.search(rf'{BORROWED}.*100\.00 USD\s+60\.00 USD\s+asset', listed), listed
    integrity = _run(CliRunner(), '--verify-integrity', str(book))
    assert integrity.exit_code == 0, integrity.output
