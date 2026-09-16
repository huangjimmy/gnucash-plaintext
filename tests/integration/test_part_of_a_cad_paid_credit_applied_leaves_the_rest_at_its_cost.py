"""Part of a CAD-paid credit applied to an invoice leaves the rest the customer's, at the cost it arrived at.

INV-USD-OVERCAD is paid 200.00 USD from a CAD bank against 100.00 USD owed, so
100.00 USD is C-US's credit, received at 1.37: its split is valued at 137.00
CAD. INV-USD-SMALL, for 40.00 USD, asks for any credit with
`auto_apply_credit: true` and takes 40.00 of it. 60.00 USD is left the
customer's, with 60.00 USD of cost basis balance.

Measured on 5.10: that is what the book reads. Measured on 4.13 before this
(CLAUDE.md finding 19): GnuCash's own application valued the credit at par,
and what was left read as 97.00 USD of credit valued at 97.00 CAD, with no cost
basis balance, at exit 0.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
RATES = FIXTURES / 'fx_rates_usd_dated.yaml'
OVERPAID = FIXTURES / 'fx_invoice_usd_overpaid_into_cad_bank.txt'
SMALL = FIXTURES / 'fx_usd_invoice_taking_part_of_a_cad_paid_credit.txt'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def test_sixty_usd_is_left_the_customers_at_its_cost(tmp_path):
    book = tmp_path / 'book.gnucash'
    made = _run('import', '--new', book, OVERPAID, '--include-business-objects',
                '--fx-rates', RATES)
    assert made.exit_code == 0, made.output

    result = _run('import', book, SMALL, '--include-business-objects', '--fx-rates', RATES)

    assert result.exit_code == 0, result.output
    credit = _run('find-prepayments', book)
    assert 'Total credit available: USD 60.00' in credit.output, credit.output
    balances = _run('fx-balances', book, '--verify-costs')
    assert 'Total USD cost basis balance: 100.00 USD' in balances.output, balances.output
    assert 'none recorded' not in balances.output, balances.output
    assert 'every cost agrees' in balances.output, balances.output
