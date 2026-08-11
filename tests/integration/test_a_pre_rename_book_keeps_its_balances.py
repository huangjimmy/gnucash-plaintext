"""A book written before the rename still knows what its bases have left.

`cost_basis_available` became `cost_basis_balance`. A book on disk carries the
old key and nothing else — and read only under the new name, every basis in it
looks like one no balance was ever written for.

That is not merely a display problem. The "no balance recorded" branch *writes*:
giving a sale back opens the basis at everything it brought in. So on a book
holding a 100.00 USD basis with 80.00 already sold, deleting one 40.00 sale —
the documented undo — would set the balance to 100.00, discarding both the
figure the book held and the 40.00 the other sale still accounts for. The book
then offers currency it has already sold, and `--verify-costs` cannot see it:
100.00 is not above what the basis acquired, and nothing reads the stale key.

So the old key is read as what it is, wherever the balance is read.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

BUY = 'tests/fixtures/fx_buy_and_borrow_usd.txt'


@pytest.fixture
def pre_rename_book(tmp_path):
    """A book whose bases carry the old key, with 20.00 left on one."""
    from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata
    from repositories.gnucash_repository import GnuCashRepository, SessionMode
    from services.foreign_currency import establishes_cost_basis, iter_splits

    book = tmp_path / 'old.gnucash'
    result = CliRunner().invoke(cli, [
        'import', '--new', str(book), BUY, '--include-business-objects'])
    assert result.exit_code == 0, result.output

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        moved = 0
        for split in iter_splits(repo.book):
            if not establishes_cost_basis(split):
                continue
            held = dict(get_custom_metadata(split) or {})
            held.pop('cost_basis_balance', None)
            # Part of it sold already, which is the figure that must survive.
            held['cost_basis_available'] = '20.00'
            transaction = split.GetParent()
            transaction.BeginEdit()
            set_custom_metadata(split, held)
            transaction.CommitEdit()
            moved += 1
        assert moved, 'expected a basis to rewrite'
        repo.save()
    finally:
        repo.close()
    return book


class TestWhatTheBookOffers:
    def test_the_old_key_is_read_as_the_balance(self, pre_rename_book):
        """20.00 apiece, not "none recorded" and not the full 100.00."""
        listed = CliRunner().invoke(cli, ['fx-balances', str(pre_rename_book)])

        assert listed.exit_code == 0, listed.output
        assert 'none recorded' not in listed.output, listed.output
        assert '20.00 USD' in listed.output, listed.output

    def test_the_total_is_what_is_left_not_what_arrived(self, pre_rename_book):
        listed = CliRunner().invoke(cli, ['fx-balances', str(pre_rename_book)])

        assert 'Total USD basis balance: 40.00 USD' in listed.output, listed.output
