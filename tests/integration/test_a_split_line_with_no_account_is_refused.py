"""A split line with no account is refused when the file is read.

A split line is an account, an amount and a commodity. One written with the
account left out — a tab and then `-50.00 CAD` — still matched the split
pattern, with an empty account, and an empty account name finds the book's
root account. Measured on 5.10: the transaction imported with `Errors: 0`,
under `--new` and under `--strategy update` alike, with a split on the root
account. After that the book could not be exported at all: "'Root Account' has
no commodity, and the transaction 'Deposit, sender unknown' on 2026-03-02 has
a split on it".
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

DEPOSIT = 'tests/fixtures/an_unidentified_deposit_on_the_receivable.txt'
ON_THE_RECEIVABLE = '\tAssets:Accounts Receivable -50.00 CAD\n'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _with_no_account(tmp_path):
    text = Path(DEPOSIT).read_text()
    assert ON_THE_RECEIVABLE in text, text
    ledger = tmp_path / 'no_account.txt'
    ledger.write_text(text.replace(ON_THE_RECEIVABLE, '\t-50.00 CAD\n'))
    return ledger


def test_a_new_book_is_not_made_from_it(tmp_path):
    result = _run('import', '--new', tmp_path / 'book.gnucash', _with_no_account(tmp_path))

    assert result.exit_code != 0, result.output
    assert 'nothing was imported' in result.output, result.output
    assert 'no account' in result.output, result.output


def test_an_update_leaves_the_split_on_its_account(tmp_path):
    book = tmp_path / 'book.gnucash'
    assert _run('import', '--new', book, DEPOSIT).exit_code == 0

    result = _run('import', book, _with_no_account(tmp_path), '--strategy', 'update')

    assert result.exit_code != 0, result.output
    assert 'no account' in result.output, result.output
    out = tmp_path / 'out.txt'
    exported = _run('export', book, out)
    assert exported.exit_code == 0, exported.output
    assert ON_THE_RECEIVABLE in out.read_text(), out.read_text()
