"""A credit spent at another cost than its record's, received from a CAD bank or spent by `auto_apply_credit:`.

The scenario tests spend a credit received into a US dollar bank, whose
transaction GnuCash wrote in US dollars. A credit received from the CAD bank
came in under a transaction already stated in Canadian dollars, so it is
restated in place: C-FX's 100.00 USD credit, carried at 137.00 CAD, spent on
an invoice posted at 1.42 CAD/USD loses 5.00 CAD on the block's
`Income:FX Gain $residual$ CAD` line.

`auto_apply_credit: true` has no line to state that account on, so where the
credit it would spend realizes a difference it is refused.
"""

from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.test_a_credit_handed_back_by_an_unpost_is_checked import (
    _a_cad_paid_credit,
    _the_overpaying_transaction,
)
from tests.integration.test_applied_credit_carries_its_basis import SECOND_INVOICE
from tests.scenario.test_a_credit_spent_on_an_invoice_realizes_what_the_two_costs_differ_by import (
    AT_1_32,
    WITH_THE_LINE,
    _exported,
    _overpaid,
    _sheet,
    _spend_the_credit,
)

FIXTURES = Path('tests/fixtures')
AT_1_42 = FIXTURES / 'fx_rates_usd_1_42_cad_per_usd_on_2026_03_01.yaml'


def test_a_cad_paid_credit_spent_at_1_42_loses_5_00_cad_in_its_own_transaction(tmp_path):
    runner = CliRunner()
    book, credit = _a_cad_paid_credit(runner, tmp_path)
    spend = tmp_path / 'spend.txt'
    spend.write_text(
        (FIXTURES / 'fx_invoice_spending_a_cad_paid_credit_whole_with_an_income_fx_gain_residual_line.txt')
        .read_text()
        .replace('TXN_GUID', _the_overpaying_transaction(book))
        .replace('SPLIT_GUID', credit))

    done = _run(runner, 'import', str(book), str(spend),
                '--include-business-objects', '--fx-rates', str(AT_1_42))

    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    ledger = tmp_path / 'exported.txt'
    assert _run(runner, 'export', str(book), str(ledger)).exit_code == 0
    assert '\tIncome:FX Gain 5.00 CAD\n' in ledger.read_text(), ledger.read_text()
    checked = _run(runner, '--verify-integrity', str(book))
    assert checked.exit_code == 0, checked.output


def test_a_book_rebuilt_from_its_export_realizes_the_difference_once(tmp_path):
    """The export of a book whose credit gained 5.00 CAD, imported into a new book.

    The credit's transaction comes back stated in CAD, the credit's split at
    the invoice's 132.00 CAD and the gain on its own split, and the invoice's
    `from_credit:` block spends that split again. At the invoice's cost it
    realizes nothing more, so the new book holds the one gain split and the
    same realized figure.
    """
    book = _overpaid(tmp_path, AT_1_32)
    spent = _spend_the_credit(book, tmp_path, WITH_THE_LINE, AT_1_32)
    assert spent.exit_code == 0, spent.output
    ledger = tmp_path / 'again.txt'
    ledger.write_text(_exported(book, tmp_path))
    rebuilt = tmp_path / 'rebuilt.gnucash'

    done = _run(CliRunner(), 'import', '--new', str(rebuilt), str(ledger),
                '--include-business-objects', '--fx-rates', str(AT_1_32))

    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    assert _exported(rebuilt, tmp_path).count('\tIncome:FX Gain -5.00 CAD\n') == 1
    assert _sheet(rebuilt, AT_1_32)['total_realized_gains'] == '5.00 CAD'
    checked = _run(CliRunner(), '--verify-integrity', str(rebuilt))
    assert checked.exit_code == 0, checked.output


def test_auto_apply_credit_spending_a_credit_at_another_cost_is_refused(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    made = _run(runner, 'import', '--new', str(book),
                str(FIXTURES / 'fx_invoice_usd_overpaid_into_usd_bank.txt'),
                '--include-business-objects', '--fx-rates', str(AT_1_42))
    assert made.exit_code == 0, made.output
    on_disk = book.read_bytes()
    ledger = tmp_path / 'second.txt'
    ledger.write_text(SECOND_INVOICE)

    done = _run(runner, 'import', '--atomic', str(book), str(ledger),
                '--include-business-objects', '--fx-rates', str(AT_1_42))

    assert done.exit_code != 0, done.output
    assert ('invoice INV-USD-SECOND: `auto_apply_credit: true` spends a credit carried '
            'at another cost than the invoice was posted at, which realizes -2.00 CAD, '
            'and nothing in the invoice says where that belongs.') in done.output, done.output
    assert book.read_bytes() == on_disk
