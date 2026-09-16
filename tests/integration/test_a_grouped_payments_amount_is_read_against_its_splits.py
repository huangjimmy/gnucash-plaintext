"""A payment made of several splits is weighed by what its splits hold.

`a_payment_giving_two_settling_splits.txt` pays INV-USD-001 with two receivable
splits of one transaction, 60.00 and 40.00 USD. Each split states its own
figure, so the block needs no `amount:` to be applied, and where it states one
the figure has to be a number the splits can be weighed against.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from tests.integration.test_linking_a_split_not_on_the_receivable import (  # noqa: F401
    AR,
    NAMES_TWO_SPLITS,
    TWO_SPLITS,
    _each_split_of,
    book,
)


def _paid_in_two(book, tmp_path, old, new):
    assert CliRunner().invoke(cli, ['import', str(book), TWO_SPLITS]).exit_code == 0
    ledger = tmp_path / 'payment.txt'
    text = Path(NAMES_TWO_SPLITS).read_text()
    assert old in text, text
    ledger.write_text(text.replace(old, new))
    return CliRunner().invoke(cli, ['import', str(book), str(ledger),
                                    '--include-business-objects'])


def test_an_amount_that_is_not_a_number_is_refused(book, tmp_path):
    result = _paid_in_two(book, tmp_path, '    amount: 100\n', '    amount: abc\n')

    assert result.exit_code != 0, result.output
    assert "payment amount must be a number, got 'abc'" in result.output, result.output


def test_a_block_stating_no_amount_is_applied_from_its_splits(book, tmp_path):
    result = _paid_in_two(book, tmp_path, '    amount: 100\n', '')

    assert result.exit_code == 0, result.output
    rows = _each_split_of(book, 'Money in, two lines')
    receivables = [row for row in rows if row['account'] == AR]
    assert sorted(row['amount'] for row in receivables) == [-60, -40], rows
    assert all(row['in_a_lot'] for row in receivables), receivables
