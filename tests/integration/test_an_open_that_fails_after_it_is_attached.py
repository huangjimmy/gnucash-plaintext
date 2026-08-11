"""An `open` that is refused must leave no account behind, and must be said.

An account is refused for things that are only knowable once it is being
built: a `guid:` another object already holds, a guid that is not one, a
`commodity_scu:` the setter will not take. Attached to the tree before those
are applied, a refusal left the account in the book without whatever the
failing step would have set.

That is invisible on the `--include-business-objects` path, which creates the
accounts in a pass of its own and leaves reporting to the transaction pass —
and the transaction pass finds the account already there, so it has nothing to
report. `Errors: 0`, exit 0, and a book holding an account that was refused.

The same file without the flag says `Failed to create account …` and exits 1,
which is the one file, two answers this tool is not supposed to give.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository, SessionMode

LEDGER = str(Path('tests/fixtures/an_open_whose_guid_is_already_taken.txt'))
BAD_UNIT = str(Path('tests/fixtures/an_open_whose_unit_the_setter_refuses.txt'))


def _accounts(book):
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        return sorted(a.get_full_name()
                      for a in repo.book.get_root_account().get_descendants())
    finally:
        repo.close()


@pytest.mark.parametrize('flags', [[], ['--include-business-objects']])
class TestBothPathsAnswerTheSameWay:
    def test_the_refusal_is_reported(self, tmp_path, flags):
        book = tmp_path / 'book.gnucash'
        result = CliRunner().invoke(
            cli, ['import', '--new', str(book), LEDGER, *flags])

        assert 'Assets:Bank' in result.output, result.output
        assert 'already used' in result.output, result.output

    def test_the_run_does_not_report_success(self, tmp_path, flags):
        book = tmp_path / 'book.gnucash'
        result = CliRunner().invoke(
            cli, ['import', '--new', str(book), LEDGER, *flags])

        assert result.exit_code != 0, result.output

    def test_the_refused_account_is_not_in_the_book(self, tmp_path, flags):
        """Attached first, it stayed — with a guid it had just been refused."""
        book = tmp_path / 'book.gnucash'
        CliRunner().invoke(cli, ['import', '--new', str(book), LEDGER, *flags])

        if book.exists():
            assert 'Assets.Bank' not in _accounts(book), _accounts(book)

    def test_the_accounts_that_are_fine_still_land(self, tmp_path, flags):
        book = tmp_path / 'book.gnucash'
        CliRunner().invoke(cli, ['import', '--new', str(book), LEDGER, *flags])

        if book.exists():
            assert 'Assets.Chequing' in _accounts(book), _accounts(book)


@pytest.mark.parametrize('flags', [[], ['--include-business-objects']])
class TestARefusalDoesNotClaimTheGuid:
    """A refused account must not leave its `guid:` taken.

    The guid is claimed before the rest of the account is built, and a claimed
    guid is in the book's collection whether or not the account was ever
    attached. So a refusal further down left it taken, and the pass that
    retried the same directive reported a collision with an account the book
    does not contain — naming a guid, where the line actually at fault is the
    one the setter refused.
    """

    def test_the_refusal_is_about_what_is_wrong(self, tmp_path, flags):
        book = tmp_path / 'unit.gnucash'
        result = CliRunner().invoke(
            cli, ['import', '--new', str(book), BAD_UNIT, *flags])

        assert result.exit_code != 0, result.output
        assert 'Assets:Fuel' in result.output, result.output
        assert 'already used' not in result.output, result.output
