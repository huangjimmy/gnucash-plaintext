"""An update moving a split to an account the book does not have is refused.

`import --strategy update` puts a split on the account its block states. An
account is created by an `open` directive, never by a transaction, so a block
stating one the book lacks is a mistyped name or a missing `open`. It is refused
before the transaction is edited, and the split stays where it was.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

DEPOSIT = 'tests/fixtures/an_unidentified_deposit_on_the_receivable.txt'
ON_THE_RECEIVABLE = '\tAssets:Accounts Receivable -50.00 CAD\n'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def test_it_is_refused_and_the_split_stays(tmp_path):
    book = tmp_path / 'book.gnucash'
    made = _run('import', '--new', book, DEPOSIT)
    assert made.exit_code == 0, made.output
    text = Path(DEPOSIT).read_text()
    assert ON_THE_RECEIVABLE in text, text
    moved = tmp_path / 'moved.txt'
    moved.write_text(text.replace(ON_THE_RECEIVABLE, '\tAssets:Nowhere -50.00 CAD\n'))

    result = _run('import', book, moved, '--strategy', 'update')

    assert result.exit_code != 0, result.output
    assert 'Account not found: Assets:Nowhere' in result.output, result.output
    out = tmp_path / 'out.txt'
    assert _run('export', book, out).exit_code == 0
    assert 'Assets:Accounts Receivable -50.00 CAD' in out.read_text()
