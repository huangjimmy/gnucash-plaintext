"""The older of two CAD-paid credits settles an invoice the size of it whole, and the other is left.

C-US overpays two USD invoices from a CAD bank, a day apart, and each
overpayment leaves 100.00 USD of credit, received at 1.37 and valued at 137.00
CAD. A 100.00 USD invoice then asks for any credit with `auto_apply_credit:
true`. The older credit covers it exactly, so it is attached whole rather than
divided, and the newer one is left the customer's, untouched.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
RATES = FIXTURES / 'fx_rates_usd_dated.yaml'
OVERPAID = FIXTURES / 'fx_invoice_usd_overpaid_into_cad_bank.txt'
TAKING_CREDIT = FIXTURES / 'fx_usd_invoice_taking_part_of_a_cad_paid_credit.txt'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _done(*args):
    result = _run(*args)
    assert result.exit_code == 0, result.output
    return result


def test_the_older_credit_is_spent_and_the_newer_one_is_left(tmp_path):
    book = tmp_path / 'book.gnucash'
    _done('import', '--new', book, OVERPAID, '--include-business-objects', '--fx-rates', RATES)
    second = tmp_path / 'second.txt'
    second.write_text(OVERPAID.read_text()
                      .replace('INV-USD-OVERCAD', 'INV-USD-OVERCAD-2')
                      .replace('date: 2026-02-25', 'date: 2026-02-26'))
    _done('import', book, second, '--include-business-objects', '--fx-rates', RATES)
    whole = tmp_path / 'whole.txt'
    whole.write_text(TAKING_CREDIT.read_text().replace('price: 40', 'price: 100'))

    _done('import', book, whole, '--include-business-objects', '--fx-rates', RATES)

    credit = _run('find-prepayments', book)
    assert 'Found 1 open pre-payment credit.' in credit.output, credit.output
    assert 'Total credit available: USD 100.00' in credit.output, credit.output
    assert 'Payment for INV-USD-OVERCAD-2' in credit.output, credit.output
    balances = _run('fx-balances', book, '--verify-costs')
    assert 'none recorded' not in balances.output, balances.output
    assert 'every cost agrees' in balances.output, balances.output
