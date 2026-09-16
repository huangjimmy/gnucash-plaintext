"""A foreign payment appended to an invoice already settled becomes the customer's credit.

INV-USD-OVERCAD is paid 200.00 USD out of a CAD bank against 100.00 USD owed,
so its lot is closed and 100.00 USD is left as credit. A second payment block
of 50.00 USD for 68.50 CAD, declaring all of it as a prepayment, has no open
lot to join. Measured on 5.10:

- read with no split line, it is recorded as 50.00 USD more of the customer's
  credit;
- read with a `$residual$` split line, it is refused. Nothing realizes a
  difference on a payment that settles nothing, and there is no settlement
  entry to put the split on.
"""

from click.testing import CliRunner

from cli.main import cli

BOOK = 'tests/fixtures/fx_invoice_usd_overpaid_into_cad_bank.txt'
RATES = 'tests/fixtures/fx_rates_usd_dated.yaml'
SECOND = 'tests/fixtures/a_second_usd_payment_on_the_settled_overcad_invoice.txt'
SECOND_WITH_A_RESIDUAL = (
    'tests/fixtures/a_second_usd_payment_on_the_settled_overcad_invoice_with_a_residual.txt')
USD_BOOK = 'tests/fixtures/a_usd_invoice_paid_from_the_usd_bank.txt'
USD_SECOND = 'tests/fixtures/a_second_usd_payment_from_the_usd_bank_on_the_settled_invoice.txt'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _settled(tmp_path):
    book = tmp_path / 'book.gnucash'
    made = _run('import', '--new', book, BOOK, '--include-business-objects', '--fx-rates', RATES)
    assert made.exit_code == 0, made.output
    return book


def test_it_is_recorded_as_more_of_the_customers_credit(tmp_path):
    book = _settled(tmp_path)

    result = _run('import', book, SECOND, '--include-business-objects', '--fx-rates', RATES)

    assert result.exit_code == 0, result.output
    assert 'invoice "INV-USD-OVERCAD": updated' in result.output, result.output
    listed = _run('find-prepayments', book)
    assert 'Found 2 open pre-payment credits.' in listed.output, listed.output
    assert 'USD 50.00' in listed.output, listed.output
    assert 'Total credit available: USD 150.00' in listed.output, listed.output


def test_out_of_a_bank_in_the_invoices_own_currency_it_is_credit_too(tmp_path):
    """INV-USD paid in full out of a USD bank, then 50.00 USD more out of the
    same bank. The bank is foreign to the book, and the payment joins no lot,
    so there is no settlement for its cost basis to be weighed against: it is
    recorded as the customer's credit. Measured on 5.10."""
    book = tmp_path / 'book.gnucash'
    made = _run('import', '--new', book, USD_BOOK, '--include-business-objects',
                '--fx-rates', RATES)
    assert made.exit_code == 0, made.output

    result = _run('import', book, USD_SECOND, '--include-business-objects', '--fx-rates', RATES)

    assert result.exit_code == 0, result.output
    assert 'invoice "INV-USD": updated' in result.output, result.output
    listed = _run('find-prepayments', book)
    assert 'Total credit available: USD 50.00' in listed.output, listed.output


def test_a_residual_split_line_on_it_is_refused(tmp_path):
    book = _settled(tmp_path)

    result = _run('import', book, SECOND_WITH_A_RESIDUAL, '--include-business-objects',
                  '--fx-rates', RATES)

    assert result.exit_code != 0, result.output
    assert "the payment did not join the invoice's lot" in result.output, result.output
    listed = _run('find-prepayments', book)
    assert 'Total credit available: USD 100.00' in listed.output, listed.output
