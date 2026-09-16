"""A payment into a bank of another currency is refused for a figure it cannot use.

INV-USD-PAY is 100.00 USD, posted at 1.40 and paid into a CAD bank. The block
states how much USD it pays, and how much CAD the bank received or the rate
between the two. Each test changes one of those lines, and the import refuses
the invoice and says which figure is wrong.
"""

import pytest
from click.testing import CliRunner

from tests.integration.test_payment_exchange_rate import _import, _variant

PAID = 'tests/fixtures/fx_invoice_usd_paid_from_cad_bank.txt'


@pytest.mark.parametrize('old, new, said', [
    ('settled_amount: 137.00', 'settled_amount: many',
     "payment settled_amount 'many' is not a number"),
    # Quoted as the number the format reads, which drops the trailing zero.
    ('settled_amount: 137.00', 'settled_amount: -137.00',
     "payment settled_amount '-137.00' must be positive"),
    ('settled_amount: 137.00', 'share_price: "rate"',
     "payment share_price 'rate' is not a number"),
    ('settled_amount: 137.00', 'share_price: "-1.37"',
     "payment share_price '-1.37' must be positive"),
], ids=['settled-not-a-number', 'settled-negative', 'rate-not-a-number',
        'rate-negative'])
def test_the_invoice_is_refused(tmp_path, old, new, said):
    fixture = _variant(tmp_path, PAID, old, new)

    result = _import(CliRunner(), tmp_path / 'book.gnucash', fixture)

    assert result.exit_code != 0, result.output
    message = result.output + str(result.exception)
    assert said in message, message


def test_a_residual_with_nothing_to_take_is_refused(tmp_path):
    """137.00 CAD would leave 3.00 against the 140.00 the USD was posted at.
    140.00 leaves nothing, so the `$residual$` line has nothing to book."""
    fixture = _variant(tmp_path, PAID, 'settled_amount: 137.00',
                       'settled_amount: 140.00')

    result = _import(CliRunner(), tmp_path / 'book.gnucash', fixture)

    assert result.exit_code != 0, result.output
    message = result.output + str(result.exception)
    assert 'has nothing to take' in message, message
