"""A USD invoice booked to USD income is paid from a CAD bank, realizing nothing.

INV-USD-INC's line is on `Income:Sales USD`, so its posting is USD against USD
and states no cost in CAD. Paid from the CAD bank with `settled_amount:
137.00`, the payment is recorded and no realized difference is written, since
there is no cost to measure one against. A block giving a `$residual$` line
beside it is refused for the same reason, which
`test_payment_exchange_rate.py` covers. Measured on 5.10 and 3.8: the bank holds
137.00 CAD, the receivable is settled by 100.00 USD, and `fx-balances` finds no
cost basis.
"""

from click.testing import CliRunner

from cli.main import cli

RATES = 'tests/fixtures/fx_rates_usd_dated.yaml'
PAID = 'tests/fixtures/inv_usd_booked_to_usd_income_paid_from_the_cad_bank.txt'


def _done(*args):
    result = CliRunner().invoke(cli, [str(arg) for arg in args])
    assert result.exit_code == 0, result.output
    return result


def test_the_payment_is_recorded_and_nothing_is_realized(tmp_path):
    book = tmp_path / 'book.gnucash'
    _done('import', '--new', book, PAID, '--include-business-objects', '--fx-rates', RATES)

    out = tmp_path / 'out.txt'
    _done('export', book, out, '--include-business-objects')
    exported = out.read_text()
    payment = exported[exported.index('2026-02-25 * "US Customer"'):]
    payment = payment[:payment.index('\n\n')] if '\n\n' in payment else payment
    assert '\tAssets:Bank 137.00 CAD\n' in payment, payment
    assert '\tAssets:Accounts Receivable USD -100.00 USD\n' in payment, payment
    assert 'Income:FX Gain' not in payment, payment
    balances = _done('fx-balances', book, '--verify-costs')
    assert 'No foreign-currency cost bases found.' in balances.output, balances.output
