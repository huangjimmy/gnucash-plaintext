"""A printed document whose payment converted currency.

A USD invoice settled into an HKD bank moved two figures — 100.00 USD off the
receivable and 780.00 HKD into the bank — and one of them cannot be worked out
from the other. The plaintext format has `settled_amount:` / `share_price:` for
exactly that, and a `payment:` block that states neither is refused when the
payment has to be made rather than pointed at.

That refusal is what a printed document meets in a book that never held the
deposit, and this pins it: the run stops and says which figure is missing. It
is the honest answer for a document handed to somebody else — the block is a
record of a settlement, and the rate it converted at is not on the page.

Read back into its own book the guids resolve and no rate is needed, which is
the case `print-invoice` exists for.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
LEDGER = str(FIXTURES / 'fx_usd_invoice_settled_into_an_hkd_bank.txt')
RATES = str(FIXTURES / 'fx_rates_usd_and_hkd.yaml')


@pytest.fixture
def source_and_printed(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'source.gnucash'
    built = runner.invoke(cli, ['import', '--new', str(book), LEDGER,
                                '--include-business-objects',
                                '--fx-rates', RATES])
    assert built.exit_code == 0, built.output

    out = tmp_path / 'printed.txt'
    printed = runner.invoke(cli, ['print-invoice', str(book), '*',
                                  '--format', 'plaintext', '-o', str(out)])
    assert printed.exit_code == 0, printed.output
    return book, out


class TestReadBackIntoItsOwnBook:
    def test_it_is_accepted(self, source_and_printed):
        """The guids resolve, so the settlement is pointed at, not remade."""
        book, printed = source_and_printed

        result = CliRunner().invoke(cli, [
            'import', str(book), str(printed), '--include-business-objects',
            '--fx-rates', RATES])

        assert result.exit_code == 0, result.output


class TestReadIntoABookThatNeverHeldTheSettlement:
    def test_it_is_refused_rather_than_settled_at_a_guess(
            self, source_and_printed, tmp_path):
        _book, printed = source_and_printed
        fresh = tmp_path / 'fresh.gnucash'
        runner = CliRunner()
        assert runner.invoke(cli, ['import', '--new', str(fresh), LEDGER,
                                   '--fx-rates', RATES]).exit_code == 0

        result = runner.invoke(cli, [
            'import', str(fresh), str(printed), '--include-business-objects',
            '--fx-rates', RATES])

        assert result.exit_code != 0, result.output
        assert 'settled_amount' in result.output, result.output
