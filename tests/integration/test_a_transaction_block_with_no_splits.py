"""A transaction block with no splits does not empty the transaction.

`--strategy update` edits a transaction in place from its block, and the block
is the source of truth for the splits: one absent from it is removed. That is
the model, and it is what lets a person delete a split by deleting a line.

The same question the invoice blocks raised: nothing tells "the writer
removed a split" from "the writer's file stops here". A block truncated after
its header — which still parses, since a transaction needs only its date, flag
and description — would leave the transaction with no splits at all, and a
transaction with no splits is a transaction with no money in it.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner
from gnucash import Query, Transaction

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository, SessionMode

FIXTURES = Path('tests/fixtures')
WHOLE = str(FIXTURES / 'a_transaction_to_be_cut_short.txt')
CUT = str(FIXTURES / 'a_transaction_block_cut_short.txt')


def _splits(book):
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        found = {}
        for raw in query.run():
            transaction = Transaction(instance=raw)
            found[transaction.GetDescription()] = len(
                transaction.GetSplitList())
        query.destroy()
        return found
    finally:
        repo.close()


@pytest.fixture
def book(tmp_path):
    path = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(cli, ['import', '--new', str(path), WHOLE])
    assert result.exit_code == 0, result.output
    assert _splits(path) == {'Lunch': 2}, _splits(path)
    return path


class TestATruncatedBlock:
    def _cut(self, book):
        return CliRunner().invoke(cli, [
            'import', str(book), CUT, '--strategy', 'update'])

    def test_it_does_not_leave_the_transaction_empty(self, book):
        self._cut(book)

        assert _splits(book).get('Lunch') != 0, _splits(book)

    def test_the_money_is_still_there(self, book):
        self._cut(book)

        assert _splits(book) == {'Lunch': 2}, _splits(book)
