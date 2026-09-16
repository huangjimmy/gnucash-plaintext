"""An edit giving a split an account the book has not got is refused, and says which.

The transaction of `a_cad_split_of_a_usd_quoted_entry.txt` is quoted in USD,
with 100.00 CAD parked on `Assets:Suspense CAD`, and its USD side is a cost
basis. Its block is read back with `--strategy update` and that account
misspelled. Measured on 5.10 and 3.4 before this: the edit was refused as one
moving what a cost basis rests on, and told to delete the transaction and
import it again, where the fresh import would then have said the account was
not found.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'
FIXTURE = Path('tests/fixtures/a_cad_split_of_a_usd_quoted_entry.txt')


def test_it_is_refused_and_the_split_stays(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    opened = runner.invoke(cli, ['import', '--new', str(book), ACCOUNTS])
    assert opened.exit_code == 0, opened.output
    made = runner.invoke(cli, ['import', str(book), str(FIXTURE)])
    assert made.exit_code == 0, made.output
    edited = tmp_path / 'edited.txt'
    edited.write_text(FIXTURE.read_text().replace(
        '\tAssets:Suspense CAD -100.00 CAD', '\tAssets:Suspence CAD -100.00 CAD'))

    result = runner.invoke(cli, ['import', str(book), str(edited), '--strategy', 'update'])

    assert result.exit_code != 0, result.output
    assert 'Account not found: Assets:Suspence CAD' in result.output, result.output
    out = tmp_path / 'out.txt'
    assert runner.invoke(cli, ['export', str(book), str(out)]).exit_code == 0
    assert 'Assets:Suspense CAD -100.00 CAD' in out.read_text()
