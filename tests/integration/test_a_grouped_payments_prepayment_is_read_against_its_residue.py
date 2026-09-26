"""A payment made of several splits states what it leaves over as a figure the book holds.

`money_arriving_for_two_splits_and_a_residue.txt` brings 150.00 USD in against
three receivable splits: 60.00 and 40.00 that settle INV-USD-001, and 50.00
left over. `a_payment_stating_two_splits_beside_a_residue.txt` applies the first
two. A `prepayment:` on that block says how much is left over, so it has to be
a number, and the number the third split holds.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli
from tests.integration.test_linking_a_split_not_on_the_receivable import (  # noqa: F401
    NAMES_TWO_BESIDE_A_RESIDUE,
    TWO_SPLITS_AND_A_RESIDUE,
    book,
)


@pytest.mark.parametrize('prepayment, said', [
    ('abc', "prepayment field must be a number, got 'abc'"),
    ('40', 'prepayment: 40'),
], ids=['not-a-number', 'not-the-residue'])
def test_the_invoice_is_refused(book, tmp_path, prepayment, said):
    assert CliRunner().invoke(
        cli, ['import', str(book), TWO_SPLITS_AND_A_RESIDUE]).exit_code == 0
    ledger = tmp_path / 'payment.txt'
    text = Path(NAMES_TWO_BESIDE_A_RESIDUE).read_text()
    assert '    amount: 100\n' in text, text
    ledger.write_text(text.replace(
        '    amount: 100\n', f'    amount: 100\n    prepayment: {prepayment}\n'))

    result = CliRunner().invoke(cli, ['import', str(book), str(ledger),
                                      '--include-business-objects'])

    assert result.exit_code != 0, result.output
    assert said in result.output, result.output
