"""An `open` line whose account name has an empty part is refused.

`open ""` states no name, and `open Assets::Savings` states an empty one between
two colons. Each is refused with the line's name, the rest of the file is still
imported, and the book gains no account without a name. The same holds with
`--include-business-objects`, which also checks each account's
`open_prepayment:` summary.
"""

import pytest
from click.testing import CliRunner

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository, SessionMode

FIXTURE = 'tests/fixtures/accounts_opened_with_an_empty_name.txt'


def _names(book):
    repo = GnuCashRepository(str(book))
    repo.open(SessionMode.READ_ONLY)
    try:
        return sorted(account.get_full_name()
                      for account in repo.book.get_root_account().get_descendants())
    finally:
        repo.close()


@pytest.mark.parametrize('flags', [[], ['--include-business-objects']])
def test_each_is_refused_and_the_rest_is_imported(tmp_path, flags):
    book = tmp_path / 'book.gnucash'

    result = CliRunner().invoke(cli, ['import', '--new', str(book), FIXTURE, *flags])

    assert result.exit_code != 0, result.output
    assert "Failed to create account : an account needs a name, and '' has none" in result.output
    assert ("Failed to create account Assets::Savings: an account needs a name, "
            "and 'Assets::Savings' has an empty part") in result.output
    assert 'Traceback' not in result.output
    assert _names(book) == ['Assets', 'Assets.Bank']
