"""A payment refused after its settlement drew a basis down changes nothing.

A settlement values itself against the cost basis it releases, so the drawdown
happens before the entry can be judged complete. What a refusal after that
point would have to give back is not one drawdown but everything the invoice
has done, so the import is abandoned rather than unwound: the book is left as
it was found and nothing else from that file is written either.

That is the opposite of the transaction path, where a refused transaction is
dropped and the rest of the file lands, and the difference is worth pinning —
it is what a reader sees when their good transaction did not import.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

RATES = 'tests/fixtures/fx_rates_usd_dated.yaml'
NO_GAIN_SPLIT = 'tests/fixtures/fx_invoice_usd_paid_from_cad_bank_no_gain_split.txt'

AN_ORDINARY_TRANSACTION = (
    '\n2026-05-05 * "An ordinary transaction in the same file"\n'
    '\tcurrency.mnemonic: "CAD"\n'
    '\tExpenses:Supplies 10.00 CAD\n'
    '\tAssets:Bank -10.00 CAD\n')


def test_the_bases_and_the_rest_of_the_file_are_left_alone(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_invoice_usd_overpaid_into_usd_bank.txt',
        '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output
    before = runner.invoke(cli, ['fx-balances', str(book)]).output
    assert 'Total USD basis balance: 200.00' in before, before

    failing = tmp_path / 'failing.txt'
    failing.write_text(Path(NO_GAIN_SPLIT).read_text() + AN_ORDINARY_TRANSACTION)
    refused = runner.invoke(cli, ['import', str(book), str(failing),
                                  '--include-business-objects', '--fx-rates', RATES])
    assert refused.exit_code != 0, refused.output
    assert 'realizes 3.00 CAD' in refused.output, refused.output

    # Both bases still hold everything they held.
    assert runner.invoke(cli, ['fx-balances', str(book)]).output == before

    # And the good transaction beside the refused invoice did not land: this
    # file imports whole or not at all.
    exported = tmp_path / 'out.txt'
    assert runner.invoke(cli, ['export', str(book), str(exported)]).exit_code == 0
    assert 'An ordinary transaction in the same file' not in exported.read_text()
