"""A book written before the rename must still export into a readable file.

`cost_basis_available:` became `cost_basis_balance:`, and a file stating the
old key is refused by name — otherwise nothing would read it and the basis
would re-open at everything it brought in, handing back currency the file
records as sold.

Books already on disk carry the old KVP. The exporter writes every custom slot
key it does not recognise, so it wrote that one straight back out: a file this
tool produced, exit 0, no warning, which this tool then refuses to read. The
one route out of such a book led to a file that could not be read back in.

`cost_basis_cost` already had exactly this treatment — it is filtered on the
way out for exactly this reason, in a comment eight lines above.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

BUY = 'tests/fixtures/fx_buy_and_borrow_usd.txt'


def _rename_key_back(book):
    """Put the pre-rename key on the basis split, as an older version left it."""
    from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata
    from repositories.gnucash_repository import GnuCashRepository, SessionMode
    from services.foreign_currency import establishes_cost_basis, iter_splits

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        moved = 0
        for split in iter_splits(repo.book):
            if not establishes_cost_basis(split):
                continue
            held = dict(get_custom_metadata(split) or {})
            if 'cost_basis_balance' not in held:
                continue
            held['cost_basis_available'] = held.pop('cost_basis_balance')
            transaction = split.GetParent()
            transaction.BeginEdit()
            set_custom_metadata(split, held)
            transaction.CommitEdit()
            moved += 1
        assert moved, 'expected at least one basis to rename'
        repo.save()
    finally:
        repo.close()
    return book


@pytest.fixture
def pre_rename_book(tmp_path):
    book = tmp_path / 'old.gnucash'
    result = CliRunner().invoke(cli, [
        'import', '--new', str(book), BUY, '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return _rename_key_back(book)


class TestTheExport:
    def test_it_does_not_write_the_old_key(self, pre_rename_book, tmp_path):
        out = tmp_path / 'out.txt'
        result = CliRunner().invoke(cli, ['export', str(pre_rename_book), str(out)])

        assert result.exit_code == 0, result.output
        assert 'cost_basis_available' not in out.read_text(), out.read_text()

    def test_what_it_writes_reads_back(self, pre_rename_book, tmp_path):
        """The only route out of such a book has to lead somewhere."""
        out = tmp_path / 'out.txt'
        assert CliRunner().invoke(
            cli, ['export', str(pre_rename_book), str(out)]).exit_code == 0

        back = tmp_path / 'back.gnucash'
        result = CliRunner().invoke(cli, ['import', '--new', str(back), str(out)])

        assert result.exit_code == 0, result.output
        assert 'Errors:       0' in result.output, result.output
