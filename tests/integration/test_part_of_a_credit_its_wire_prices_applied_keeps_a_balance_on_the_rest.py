"""Part of a credit its wire prices, applied, leaves the rest a balance and no stored cost.

A 200.00 USD wire from the CAD bank, entered in USD, overpays INV-USD-WIRE for
100.00 USD, and the import divides it. The 100.00 USD credit left over is
valued at 100.00 USD. Its cost, 1.37, is read from the CAD bank split, so only
its cost basis balance is stored.

INV-USD-SMALL for 40.00 USD then asks for any credit with `auto_apply_credit:
true`. The credit's value equals its amount, so GnuCash applies it and carves
the 60.00 left into a new split. That split takes a balance of 60.00 and no
cost of its own: none was stored on the credit to carry across.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
RATES = FIXTURES / 'fx_rates_usd_dated.yaml'
ACCOUNTS = FIXTURES / 'usd_invoicing_accounts_with_a_cad_bank_and_a_usd_bank.txt'
WIRE = FIXTURES / 'inv_usd_wire_overpaid_from_the_cad_bank_entered_in_usd.txt'
TAKING_CREDIT = FIXTURES / 'fx_usd_invoice_taking_part_of_a_cad_paid_credit.txt'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _done(*args):
    result = _run(*args)
    assert result.exit_code == 0, result.output
    return result


def test_the_60_00_left_is_a_cost_basis_at_1_37_with_a_balance_of_60_00(tmp_path):
    book = tmp_path / 'book.gnucash'
    ledger = tmp_path / 'in.txt'
    ledger.write_text(ACCOUNTS.read_text() + '\n' + WIRE.read_text())
    _done('import', '--new', book, ledger, '--include-business-objects', '--fx-rates', RATES)

    _done('import', book, TAKING_CREDIT, '--include-business-objects', '--fx-rates', RATES)

    credit = _run('find-prepayments', book)
    assert 'Total credit available: USD 60.00' in credit.output, credit.output
    balances = _run('fx-balances', book, '--verify-costs')
    assert balances.exit_code == 0, balances.output
    assert re.search(r'Assets:Accounts Receivable USD\s+1\.37 CAD/USD\s+60\.00 USD\s+60\.00 USD',
                     balances.output), balances.output
    assert 'Total USD cost basis balance: 200.00 USD' in balances.output, balances.output
    exported = tmp_path / 'out.txt'
    _done('export', book, exported, '--include-business-objects')
    assert 'cost_basis_cost' not in exported.read_text(), exported.read_text()
