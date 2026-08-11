"""How an amount is *written* comes from its account, not from its currency.

GnuCash keeps a smallest unit per account as well as per commodity, and they
are not always the same — an expense account for fuel is commonly kept to
thousandths. This tool round-trips that setting as `commodity_scu:`, so a
figure on such an account is written back at the account's precision: 18.190,
not 18.19. Written at the currency's two places instead, the file states a
figure with a different denominator from the split's, and re-importing it is
refused for the mismatch — a book that cannot read its own export.

What the account's unit does *not* decide is whether a stated figure is
legal. A booked amount is judged against the currency: 18.190 passes because
it is 18.19, and 18.191 is refused however fine the account is (see
tests/integration/test_amount_must_fit_the_currency.py).
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
