"""Q-035: deleting a sale returns what it took to the cost basis.

Undoing a sale is how a user corrects one — and how anyone trying the feature
out gets back to a clean state. The cost basis balance follows: it is derived
from what the book actually holds, so the moment the sale is gone the cost basis has
its currency back, and the stored KVP is rewritten to match.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import COST_BASIS_BALANCE_KEY, iter_splits, split_guid
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
    assert 'Total USD cost basis balance: 160.00 USD' in _balances(runner, book)

    exported = _export(runner, book, tmp_path / 'before.txt')
    sale_guid = re.search(
        r'2026-02-01 \* "Sell 40 USD"\n\tguid: "([0-9a-f]{32})"', exported)
    assert sale_guid, exported

    result = _run(runner, 'delete-transactions', str(book),
                  '--by-guid', sale_guid.group(1))
    assert result.exit_code == 0, result.output

    # The cost basis has its 40 USD back, in the listing and in the stored KVP.
    listing = _balances(runner, book)
    assert 'Total USD cost basis balance: 200.00 USD' in listing, listing
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
    assert 'Total USD cost basis balance: 100.00 USD' in _balances(runner, book)


def _a_book_with_a_sale(runner, tmp_path):
    """40 USD sold against the 100 USD bought at 1.35, beside 100 borrowed."""
    book = tmp_path / 'book.gnucash'
    assert _run(runner, 'import', '--new', str(book),
                'tests/fixtures/fx_buy_and_borrow_usd.txt').exit_code == 0
    bought = re.findall(r'Assets:Bank:USD 100\.00 USD\n\t+guid: "([0-9a-f]{32})"',
                        _export(runner, book, tmp_path / 'bases.txt'))[0]

    sale = tmp_path / 'sale.txt'
    sale.write_text(Path('tests/fixtures/fx_sell_usd_partial.txt').read_text()
                    .replace('{basis_a}', bought))
    assert _run(runner, 'import', str(book), str(sale)).exit_code == 0
    sale_guid = re.search(
        r'2026-02-01 \* "Sell 40 USD"\n\tguid: "([0-9a-f]{32})"',
        _export(runner, book, tmp_path / 'before.txt')).group(1)
    return book, bought, sale_guid


def _change_the_kvp_of(book, guid, change):
    """Rewrite one split's KVP, as a hand edit or an older tool leaves it."""
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        split = next(s for s in iter_splits(repo.book) if split_guid(s) == guid)
        transaction = split.GetParent()
        transaction.BeginEdit()
        set_custom_metadata(split, change(dict(get_custom_metadata(split))))
        transaction.CommitEdit()
        repo.save()
    finally:
        repo.close()


def _stored_balance(book, guid):
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        split = next(s for s in iter_splits(repo.book) if split_guid(s) == guid)
        return get_custom_metadata(split).get(COST_BASIS_BALANCE_KEY)
    finally:
        repo.close()


def test_a_sale_whose_cost_basis_is_gone_is_deleted_all_the_same(tmp_path):
    """GnuCash's own register deletes a purchase without asking what draws on it.

    The sale is left giving a guid the book no longer holds, so deleting it has
    nothing to give its currency back to. It is deleted all the same.
    """
    runner = CliRunner()
    book, bought, sale_guid = _a_book_with_a_sale(runner, tmp_path)

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        purchase = next(tx for tx in repo.get_all_transactions()
                        if any(split_guid(s) == bought for s in tx.GetSplitList()))
        repo.delete_transaction(purchase)
        repo.save()
    finally:
        repo.close()

    result = _run(runner, 'delete-transactions', str(book), '--by-guid', sale_guid)
    assert result.exit_code == 0, result.output

    assert 'Sell 40 USD' not in _export(runner, book, tmp_path / 'after.txt')
    assert 'Total USD cost basis balance: 100.00 USD' in _balances(runner, book)


def test_a_balance_that_will_not_parse_is_left_as_it_was(tmp_path):
    """Nothing is given back to a balance nobody can read.

    Opening the cost basis at its whole amount instead would put back currency
    that may have been sold, and overwrite the text `--verify-costs` reports.
    """
    runner = CliRunner()
    book, bought, sale_guid = _a_book_with_a_sale(runner, tmp_path)
    _change_the_kvp_of(book, bought,
                       lambda kvp: {**kvp, COST_BASIS_BALANCE_KEY: '60.00.00'})

    result = _run(runner, 'delete-transactions', str(book), '--by-guid', sale_guid)
    assert result.exit_code == 0, result.output

    assert _stored_balance(book, bought) == '60.00.00'


def test_a_cost_basis_with_no_balance_recorded_opens_with_all_it_brought_in(tmp_path):
    """A sale given back to a cost basis with no balance opens one.

    A book can hold a sale against a cost basis with no balance written on it,
    from a hand edit or an older tool. Deleting the sale opens the cost basis
    holding everything it brought in.
    """
    runner = CliRunner()
    book, bought, sale_guid = _a_book_with_a_sale(runner, tmp_path)
    _change_the_kvp_of(book, bought, lambda kvp: {
        key: value for key, value in kvp.items() if key != COST_BASIS_BALANCE_KEY})

    result = _run(runner, 'delete-transactions', str(book), '--by-guid', sale_guid)
    assert result.exit_code == 0, result.output

    assert _stored_balance(book, bought) == '100.00'


def test_a_purchase_whose_own_fee_draws_on_it_is_deleted_whole(tmp_path):
    """A split drawing on a cost basis in its own transaction does not hold it up.

    Deleting a cost basis is refused while another transaction measures
    against it. The bank's fee here draws on the purchase it is part of, so it
    goes in the same step and nothing is left giving that guid.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = _run(runner, 'import', '--new', str(book),
                  'tests/fixtures/fx_usd_bought_with_the_banks_fee_drawn_on_it.txt')
    assert result.exit_code == 0, result.output
    assert 'Errors:       0' in result.output, result.output
    assert 'Total USD cost basis balance: 99.00 USD' in _balances(runner, book)

    purchase = re.search(
        r'\* "Buy 100 USD at 1\.35, the bank keeping 1\.00 USD as its fee"\n'
        r'\tguid: "([0-9a-f]{32})"',
        _export(runner, book, tmp_path / 'before.txt')).group(1)
    result = _run(runner, 'delete-transactions', str(book), '--by-guid', purchase)
    assert result.exit_code == 0, result.output

    assert 'Buy 100 USD' not in _export(runner, book, tmp_path / 'after.txt')
