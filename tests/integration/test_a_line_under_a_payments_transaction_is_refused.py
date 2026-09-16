"""A line under a payment's `Transaction` other than a `PaymentSplit` is refused.

The `PaymentSplit` lines under a `Transaction "..."` give the splits the
payment applies, and nothing else there is read. Measured on 5.10: a split line
written there, `Assets:Bank 100.00 CAD`, parsed with no error, and the payment
applied only the `PaymentSplit` beside it, with the line read by nobody. It is
refused when the file is read, as a block under a transaction is.
"""

from click.testing import CliRunner

from cli.main import cli

GROUPED = 'tests/fixtures/a_payment_transaction_holding_a_split_line.txt'


def test_the_file_is_refused_giving_the_line(tmp_path):
    result = CliRunner().invoke(cli, ['import', '--new', str(tmp_path / 'book.gnucash'),
                                      GROUPED, '--include-business-objects'])

    assert result.exit_code != 0, result.output
    assert 'nothing was imported' in result.output, result.output
    assert 'Error processing line 36' in result.output, result.output
    assert 'PaymentSplit' in result.output, result.output
