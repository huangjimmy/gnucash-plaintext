"""Correcting a printed page and reading it back must not duplicate money.

`print-invoice --format plaintext` and `print-bill` write a page block, and
a page block is what `import` reads — so a reader who prints one, fixes a
typo in it and imports it is doing the ordinary thing. The renderers were
written for a different purpose ("for human consumption, not re-importing full
lot structure") and left out the two guids that make a re-import relink what
the book already has: `posted_txn_guid:` on the posted block and `txn_guid:` on
each payment.

Measured: a bill printed, its notes corrected, and imported back left the bank
holding **two** 400.00 payments where one had been made — the rebuild orphaned
the original and made another — with the run reporting success.

The export has carried both guids all along, for exactly this reason. What the
two writers disagreed about is now one function, so a printed page is a
page like any other.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner
from gnucash import Query, Transaction

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository, SessionMode

FIXTURES = Path('tests/fixtures')
ACCOUNTS = str(FIXTURES / 'q019_accounts.txt')
BILLS = str(FIXTURES / 'two_bills_to_print.txt')


def _bank_splits(book):
    """Every split on the bank account, as (date, amount)."""
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        found = []
        for raw in query.run():
            transaction = Transaction(instance=raw)
            for split in transaction.GetSplitList():
                account = split.GetAccount()
                if account is not None and \
                        account.get_full_name() == 'Assets.Bank':
                    found.append((
                        transaction.GetDate().strftime('%Y-%m-%d'),
                        f'{split.GetAmount().num()}/{split.GetAmount().denom()}'))
        query.destroy()
        return sorted(found)
    finally:
        repo.close()


@pytest.fixture
def book(tmp_path):
    path = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(path), ACCOUNTS])
    assert made.exit_code == 0, made.output
    filled = CliRunner().invoke(cli, [
        'import', str(path), BILLS, '--include-business-objects'])
    assert filled.exit_code == 0, filled.output
    return path


def _printed(book, tmp_path):
    out = tmp_path / 'printed.txt'
    result = CliRunner().invoke(cli, [
        'print-bill', str(book), 'BILL-PRINT-001', '--format', 'plaintext',
        '--output', str(out)])
    assert result.exit_code == 0, result.output
    return out


class TestCorrectingAPrintedBill:
    def _corrected(self, book, tmp_path):
        printed = _printed(book, tmp_path)
        printed.write_text(printed.read_text().replace(
            'Two taxes and a payment', 'Two taxes and a payment (corrected)'))
        runner = CliRunner()
        # The bill is posted in this book, and a posted bill takes a
        # `payment:` block and nothing else — so the correction goes
        # through the two steps the refusal names.
        refused = runner.invoke(cli, [
            'import', str(book), str(printed), '--include-business-objects'])
        assert refused.exit_code != 0, refused.output
        assert 'unpost-bills' in refused.output, refused.output
        assert runner.invoke(cli, ['unpost-bills', str(book),
                                   'BILL-PRINT-001']).exit_code == 0

        result = runner.invoke(cli, [
            'import', str(book), str(printed), '--include-business-objects'])
        assert result.exit_code == 0, result.output
        return result

    def test_the_payment_is_not_duplicated(self, book, tmp_path):
        before = _bank_splits(book)
        assert len(before) == 1, before

        self._corrected(book, tmp_path)

        assert _bank_splits(book) == before, (_bank_splits(book), before)

    def test_the_correction_landed(self, book, tmp_path):
        """So the test above is not passing because nothing happened."""
        self._corrected(book, tmp_path)

        printed = _printed(book, tmp_path)
        assert '(corrected)' in printed.read_text(), printed.read_text()


class TestWhatThePrintedBlockCarries:
    def test_it_names_the_posting_transaction(self, book, tmp_path):
        """Without it a re-import posts again instead of relinking."""
        text = _printed(book, tmp_path).read_text()

        assert 'posted_txn_guid:' in text, text

    def test_it_names_each_payment_transaction(self, book, tmp_path):
        text = _printed(book, tmp_path).read_text()

        assert 'txn_guid:' in text.split('payment:')[1], text
