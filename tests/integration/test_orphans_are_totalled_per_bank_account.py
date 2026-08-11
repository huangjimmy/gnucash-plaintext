"""An unpost warning totals the money it orphaned where the money is.

The warning exists so a reader can find what the unpost left behind, which
means the figure has to name an account somebody can go and look in. Summed
into one line, payments made from two accounts were reported as a single total
"in" whichever account came first — 100.00 in a chequing account holding 60.00
of it, with the other 40.00 named nowhere.

One account and several payments is still one line, because there is one place
to look — `test_unpost_invoice_bill.py` holds that half — and the per-account
breakdown is for when there is more than one.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

TWO_BANKS = str(Path('tests/fixtures/an_invoice_paid_from_two_banks.txt'))


@pytest.fixture
def two_banks(tmp_path):
    book = tmp_path / 'two_banks.gnucash'
    result = CliRunner().invoke(cli, [
        'import', '--new', str(book), TWO_BANKS, '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return book


def _unpost(book):
    return CliRunner().invoke(
        cli, ['unpost-invoices', str(book), 'INV-TWOBANK'])


class TestTwoAccounts:
    def test_each_account_is_totalled_on_its_own(self, two_banks):
        result = _unpost(two_banks)

        assert result.exit_code == 0, result.output
        assert 'Total orphaned per bank account:' in result.output, result.output
        assert 'CAD 60.00 in Assets:Bank' in result.output, result.output
        assert 'CAD 40.00 in Assets:Second Bank' in result.output, result.output

    def test_the_two_are_not_added_together(self, two_banks):
        """100.00 is the invoice, and is in neither account."""
        result = _unpost(two_banks)

        assert 'CAD 100.00 in' not in result.output, result.output
        assert 'Total orphaned: ' not in result.output, result.output

    def test_both_payments_are_still_listed_individually(self, two_banks):
        """The per-account total summarises the list; it does not replace it."""
        result = _unpost(two_banks)

        assert 'From the chequing account' in result.output, result.output
        assert 'From the other one' in result.output, result.output
