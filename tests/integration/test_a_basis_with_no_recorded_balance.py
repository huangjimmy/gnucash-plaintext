"""Q-035: a cost basis with no recorded balance has none, not a full one.

A split written in the GnuCash GUI, or by an import that predates this feature,
carries no `cost_basis_balance` KVP. Reading its amount as its balance would
re-open currency that may already have been sold, so it reads as `none
recorded`, is refused as a sale's basis, and is given a balance only when the
user says so.

The split with no recorded balance is produced by clearing the KVP on a real
book — the state a GUI-made book is in — rather than by mocking anything.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import COST_BASIS_BALANCE_KEY, iter_splits
from tests.conftest import _run


def _balances(runner, book, *extra):
    result = runner.invoke(cli, ['fx-balances', str(book), *extra])
    assert result.exit_code == 0, result.output
    return result.output


def _forget_recorded_balances(book_path):
    """Strip the KVP from every split that carries one, leaving the splits
    exactly as a book this tool never touched would have them."""
    repo = GnuCashRepository(str(book_path))
    repo.open(mode=SessionMode.NORMAL)
    try:
        for split in iter_splits(repo.book):
            metadata = dict(get_custom_metadata(split))
            if COST_BASIS_BALANCE_KEY not in metadata:
                continue
            del metadata[COST_BASIS_BALANCE_KEY]
            transaction = split.GetParent()
            transaction.BeginEdit()
            set_custom_metadata(split, metadata or {'plaintext': 'cleared'})
            transaction.CommitEdit()
        repo.save()
    finally:
        repo.close()


def _book_with_no_recorded_balance(runner, tmp_path):
    book = tmp_path / 'book.gnucash'
    assert _run(runner, 'import', '--new', str(book),
                'tests/fixtures/fx_buy_and_borrow_usd.txt',
                '--include-business-objects').exit_code == 0
    _forget_recorded_balances(book)
    return book


def _sale_against(tmp_path, basis, name='sale.txt'):
    path = tmp_path / name
    path.write_text(Path('tests/fixtures/fx_sell_usd_partial.txt').read_text()
                    .replace('{basis_a}', basis))
    return str(path)


def test_a_basis_with_no_recorded_balance_says_so(tmp_path):
    runner = CliRunner()
    book = _book_with_no_recorded_balance(runner, tmp_path)

    listing = _balances(runner, book)
    assert 'none recorded' in listing, listing
    assert 'Total USD basis balance' not in listing, listing
    assert 'cost_basis_balance' in listing, listing


def test_selling_against_a_basis_with_no_recorded_balance_is_refused(tmp_path):
    runner = CliRunner()
    book = _book_with_no_recorded_balance(runner, tmp_path)
    basis = re.search(r'\b([0-9a-f]{32})\b', _balances(runner, book)).group(1)

    result = _run(runner, 'import', str(book), _sale_against(tmp_path, basis))
    message = result.output + str(result.exception)
    assert 'no balance recorded' in message, message
    assert 'cost_basis_balance' in message, message


def test_stating_the_balance_in_a_file_gives_the_basis_one(tmp_path):
    """The mechanism that already exists: a balance written on the split in an
    import file is authoritative, and the basis is sellable from then on."""
    runner = CliRunner()
    book = _book_with_no_recorded_balance(runner, tmp_path)
    basis = re.search(r'\b([0-9a-f]{32})\b', _balances(runner, book)).group(1)

    # `--strategy update` matches the transaction by its own guid, so take that
    # from the book too.
    exported = tmp_path / 'before.txt'
    assert runner.invoke(cli, ['export', str(book), str(exported)]).exit_code == 0
    tx_guid = re.search(
        r'2026-01-10 \* "Buy 100 USD at 1\.35"\n\tguid: "([0-9a-f]{32})"',
        exported.read_text()).group(1)

    stated = tmp_path / 'state_balance.txt'
    stated.write_text(
        '2026-01-10 * "Buy 100 USD at 1.35"\n'
        f'\tguid: "{tx_guid}"\n'
        '\tcurrency.mnemonic: "CAD"\n'
        '\tAssets:Bank:USD 100.00 USD\n'
        f'\t\tguid: "{basis}"\n'
        '\t\taccount.commodity.mnemonic: "USD"\n'
        '\t\tshare_price: "1.35"\n'
        '\t\tvalue: "135.00"\n'
        '\t\tcost_basis_balance: "100.00"\n'
        '\tAssets:Bank -135.00 CAD\n'
        '\t\taccount.commodity.mnemonic: "CAD"\n'
        '\t\tshare_price: "1"\n'
        '\t\tvalue: "-135.00"\n')
    result = _run(runner, 'import', str(book), str(stated), '--strategy', 'update')
    assert result.exit_code == 0, result.output

    listing = _balances(runner, book)
    basis_row = next(line for line in listing.splitlines() if basis in line)
    assert 'none recorded' not in basis_row, listing
    assert '100.00 USD     100.00 USD' in basis_row, listing
    # The basis nothing stated a balance for is untouched.
    assert 'none recorded' in listing, listing


def test_an_update_does_not_quietly_write_a_balance(tmp_path):
    """Editing a description must not decide how much of a basis is left.

    A basis with no recorded balance is one this tool never wrote one for —
    made in the GUI, or predating the feature — so how much of its currency
    has already been sold is not known. Opening it at its full amount would
    offer currency that may be long gone, which is the whole reason the state
    exists rather than a default of "all of it".

    Re-importing that book with a corrected description passes the edit guard,
    correctly: prose cannot change what a basis holds. What it must not do is
    write a balance on the way past.
    """
    runner = CliRunner()
    book = _book_with_no_recorded_balance(runner, tmp_path)
    assert 'none recorded' in _balances(runner, book)

    exported = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(exported)).exit_code == 0
    edited = tmp_path / 'edited.txt'
    text = exported.read_text()
    assert 'Buy 100 USD at 1.35' in text, text
    edited.write_text(text.replace('Buy 100 USD at 1.35', 'Buy 100 USD at 1.35 (wire)'))

    assert _run(runner, 'import', str(book), str(edited),
                '--strategy', 'update').exit_code == 0

    listing = _balances(runner, book)
    assert 'none recorded' in listing, (
        'an edit that cannot change what a basis holds gave it a balance '
        f'anyway:\n{listing}')
