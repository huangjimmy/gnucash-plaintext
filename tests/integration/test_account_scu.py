"""An amount's precision comes from its account, not only from its currency.

GnuCash keeps a smallest unit per account as well as per commodity, and they
are not always the same: fuel at 1.819 a litre needs a third decimal that a
Canadian dollar does not have. This tool round-trips that setting as
`commodity_scu:`, so an amount stated at the account's precision has to
survive being validated on the way in and written on the way out.

Judging either against the currency's hundredths refuses 18.190 as an amount
CAD cannot hold, and rounds it away on export — on an account that holds it.
"""

from click.testing import CliRunner

from cli.main import cli

FIXTURE = 'tests/fixtures/account_with_finer_scu.txt'


def test_an_amount_at_the_accounts_own_precision_round_trips(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(book), FIXTURE])
    assert result.exit_code == 0, result.output

    exported = tmp_path / 'out.txt'
    result = runner.invoke(cli, ['export', str(book), str(exported)])
    assert result.exit_code == 0, result.output
    text = exported.read_text()

    assert 'commodity_scu: 1000' in text, text
    assert 'Expenses:Fuel 18.190 CAD' in text, text
    assert 'Assets:Bank -18.190 CAD' in text, text

    # A split in the transaction's own currency has one figure, not two, so no
    # `value:` line belongs on it. Writing the value at the currency's unit
    # while the amount used the account's finer one produced `value: "18.19"`
    # against an amount of 18.190 — half a thousandth apart, re-imported that
    # way every generation.
    assert 'value: "18.19"' not in text, text
    assert 'value:' not in text, text

    # And it survives a second pass, which is what a round-trip has to mean.
    again = tmp_path / 'again.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(again), str(exported)])
    assert result.exit_code == 0, result.output
