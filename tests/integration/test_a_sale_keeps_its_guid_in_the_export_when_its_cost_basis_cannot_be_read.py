"""A sale keeps its cost basis guid in the export when that cost basis cannot be read.

The export leaves a sale's `cost_basis_split_guid:` out only where the cost
basis it gives was an owner's credit this book has since spent. Where the cost
basis's own cost will not parse, whether it is a cost basis at all cannot be
answered, so it is not taken for a spent credit: the guid is written, and the
ledger carries both the disposal and the figure `--verify-costs` reports, where
each can be corrected.
"""

from pathlib import Path

from click.testing import CliRunner

from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import iter_splits, split_guid
from tests.conftest import _run

BILL = 'tests/fixtures/fx_usd_bill_cad_expense.txt'
BORROW = 'tests/fixtures/usd_borrowed_into_the_bank_at_a_stated_cost.txt'
SALE = 'tests/fixtures/fx_sell_usd_partial.txt'
RATES = 'tests/fixtures/fx_rates_usd_dated.yaml'


def test_the_guid_is_written(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    made = _run(runner, 'import', '--new', str(book), BILL,
                '--include-business-objects', '--fx-rates', RATES)
    assert made.exit_code == 0, made.output
    borrowed = _run(runner, 'import', str(book), BORROW)
    assert 'Errors:       0' in borrowed.output, borrowed.output

    listing = _run(runner, 'fx-balances', str(book)).output
    rows = [line.split()[1] for line in listing.splitlines() if 'Assets:Bank:USD' in line]
    assert len(rows) == 1, listing
    basis = rows[0]
    sale = tmp_path / 'sale.txt'
    sale.write_text(Path(SALE).read_text().replace('{basis_a}', basis))
    sold = _run(runner, 'import', str(book), str(sale))
    assert 'Errors:       0' in sold.output, sold.output

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        split = next(s for s in iter_splits(repo.book) if split_guid(s) == basis)
        transaction = split.GetParent()
        transaction.BeginEdit()
        set_custom_metadata(split, {**get_custom_metadata(split), 'cost_basis_cost': 'oops'})
        transaction.CommitEdit()
        repo.save()
    finally:
        repo.close()

    out = tmp_path / 'out.txt'
    exported = _run(runner, 'export', str(book), str(out))
    assert exported.exit_code == 0, exported.output
    assert f'cost_basis_split_guid: "{basis}"' in out.read_text(), out.read_text()
