"""A mistyped guid is refused whichever way the block states the conversion.

`settled_amount:` and `share_price:` are the two documented spellings of one
fact — how much of the bank's currency a payment moved. The refusal that offers
them names both, so a reader picks either.

The duplicate-payment guard compares the block's figure against the bank
split's, and read only `settled_amount:`. A block spelling it as a rate carries
`amount:` in the *invoice's* currency, so 100 was compared against a bank
split of 780.00 HKD, matched nothing, and the guard declined to fire — the
mistyped guid then minted a second 780.00 HKD transaction for money that had
moved once, and the run exited 0.

One file, two answers, decided by which word the writer used. The same defect
as `account:` against `bank_account:` on the adjacent key, which
`test_both_spellings_read_the_same.py` pins.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
ACCOUNTS = str(FIXTURES / 'fx_usd_invoice_settled_into_an_hkd_bank.txt')
BY_RATE = FIXTURES / 'fx_usd_invoice_settled_into_hkd_by_rate.txt'
RATES = 'tests/fixtures/fx_rates_usd_and_hkd.yaml'
WRONG = 'deadbeefdeadbeefdeadbeefdeadbeef'


def _transaction_count(book):
    from gnucash import Query

    from repositories.gnucash_repository import GnuCashRepository, SessionMode

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        count = len(list(query.run()))
        query.destroy()
        return count
    finally:
        repo.close()


@pytest.fixture
def book_holding_the_hkd_settlement(tmp_path):
    """A book where the 780.00 HKD has already moved, once."""
    book = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(cli, [
        'import', '--new', str(book), ACCOUNTS,
        '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output
    return book


class TestASecondInvoiceNamingThatMovementWithAMistypedGuid:
    """A hand-written block against a book that already holds the money."""

    def _import_by_rate(self, book, tmp_path):
        ledger = tmp_path / 'by_rate.txt'
        ledger.write_text(BY_RATE.read_text().replace('TXN_GUID', WRONG))
        return CliRunner().invoke(cli, [
            'import', str(book), str(ledger),
            '--include-business-objects', '--fx-rates', RATES])

    def test_the_run_does_not_report_success(
            self, book_holding_the_hkd_settlement, tmp_path):
        result = self._import_by_rate(book_holding_the_hkd_settlement, tmp_path)

        assert result.exit_code != 0, result.output
        assert 'already has' in result.output, result.output

    def test_the_money_is_not_moved_a_second_time(
            self, book_holding_the_hkd_settlement, tmp_path):
        book = book_holding_the_hkd_settlement
        before = _transaction_count(book)

        self._import_by_rate(book, tmp_path)

        assert _transaction_count(book) == before
