"""A grouped payment block stating a split on an income account is refused.

INV-USD-001's block states two splits of one transaction with a `Transaction`
block: 60.00 on the receivable and 40.00 on `Income:Other USD`. A payment may
take a split off an account money passes through, and never off an income
account for an invoice, because that takes the sale off the profit and loss.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
BOOK = FIXTURES / 'fx_usd_invoice_cad_income.txt'
RATES = FIXTURES / 'fx_rates_usd_dated.yaml'
WITH_INCOME = FIXTURES / 'money_arriving_as_a_receivable_split_and_an_income_split.txt'
STATES_BOTH = FIXTURES / 'a_payment_stating_two_settling_splits.txt'
INCOME_SPLIT = '8192a3b4c5d6e7f80912233445566778'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _done(*args):
    result = _run(*args)
    assert result.exit_code == 0, result.output


def test_it_is_refused_stating_that_split_and_its_account(tmp_path):
    book = tmp_path / 'book.gnucash'
    _done('import', '--new', book, BOOK, '--include-business-objects', '--fx-rates', RATES)
    _done('import', book, WITH_INCOME)

    result = _run('import', book, STATES_BOTH, '--include-business-objects', '--fx-rates', RATES)

    assert result.exit_code != 0, result.output
    assert (f"PaymentSplit '{INCOME_SPLIT}' is on 'Income:Other USD'"
            in result.output), result.output
