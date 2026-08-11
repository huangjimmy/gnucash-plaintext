"""Two customers paying alike on one day, imported one run at a time.

The duplicate-payment guard compares a block against what the book already
holds — date, figure, direction, account, memo — and `_PAYMENTS_THIS_RUN_MADE`
excuses only the payments this process made. So two documents whose payments
agree on every one of those fields are told apart within one file and not
across two runs.

`test_two_look_alike_payments_in_one_file` covers the same-file half. This is
the other, and it is the likelier one: documents arrive as they are printed,
one file at a time.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
FIRST = str(FIXTURES / 'a_payment_named_with_account.txt')
SECOND = str(FIXTURES / 'a_second_document_paid_the_same_day.txt')


def _bank_transactions(book):
    from gnucash import Query, Transaction

    from repositories.gnucash_repository import GnuCashRepository, SessionMode

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
                if account is None or account.get_full_name() != 'Assets.Bank':
                    continue
                found.append(str(split.GetAmount()))
        query.destroy()
        return sorted(found)
    finally:
        repo.close()


@pytest.fixture
def book_with_the_first(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(book), FIRST,
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return book


class TestTheSecondDocumentInItsOwnRun:
    def test_it_is_not_refused_for_the_first_ones_money(self, book_with_the_first,
                                                        tmp_path):
        """Different documents, different money, whatever the fields agree on."""
        result = CliRunner().invoke(cli, [
            'import', str(book_with_the_first), SECOND,
            '--include-business-objects'])

        assert result.exit_code == 0, result.output

    def test_both_payments_are_in_the_book(self, book_with_the_first):
        CliRunner().invoke(cli, ['import', str(book_with_the_first), SECOND,
                                 '--include-business-objects'])

        assert _bank_transactions(book_with_the_first) == ['10000/100',
                                                           '10000/100']
