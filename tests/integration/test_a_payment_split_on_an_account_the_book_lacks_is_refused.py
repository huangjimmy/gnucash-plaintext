"""A split a payment block adds, on an account the book does not hold, is refused.

`fx_invoice_usd_paid_from_cad_bank.txt` settles a USD invoice into a CAD bank
and books the difference with a `$residual$` split under the payment block.
Written to an account nobody opened, there is nowhere to book it, so the
import refuses the invoice and gives the account.
"""

from click.testing import CliRunner

from tests.integration.test_payment_exchange_rate import _import, _variant

PAID = 'tests/fixtures/fx_invoice_usd_paid_from_cad_bank.txt'


def test_the_invoice_is_refused(tmp_path):
    fixture = _variant(tmp_path, PAID, 'Income:FX Gain $residual$ CAD',
                       'Income:No Such Gain $residual$ CAD')

    result = _import(CliRunner(), tmp_path / 'book.gnucash', fixture)

    assert result.exit_code != 0, result.output
    message = result.output + str(result.exception)
    assert ("Account 'Income:No Such Gain' not found for a split on this invoice "
            "payment") in message, message
