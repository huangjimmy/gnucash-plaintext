"""A retarget block carries no date or amount, and must not be read for them.

`txn_guid:` names a movement the book already holds, so the block does not
restate it — `bank_account:` and the guid are the whole of it, and every
round-trip fixture in this suite writes one that way.

The comparison that decides whether a payment block matches a split in the lot
learned to fall through to the block's own fields when the guid resolves to
nothing, so that a printed invoice could be re-read in a book that never held
its transactions. That fall-through reads `date:` and `amount:` — which a
retarget block is not required to state, and usually does not.

Reached with two payment blocks and the named transaction gone: every block is
tried against every split, so the bare one is compared against the other
payment's split, its guid matches neither that transaction nor anything in the
book, and the fields it never carried are read.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
ACCOUNTS = str(FIXTURES / 'payment_roundtrip_accounts.txt')
DEPOSIT = str(FIXTURES / 'a_loose_deposit_to_retarget.txt')
LEDGER = FIXTURES / 'an_invoice_with_a_bare_retarget_and_a_payment.txt'


def _the_deposit_guid(book):
    from gnucash import Query, Transaction

    from repositories.gnucash_repository import GnuCashRepository, SessionMode

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        for raw in query.run():
            transaction = Transaction(instance=raw)
            if transaction.GetDescription() == 'Part payment from Acme':
                guid = transaction.GetGUID().to_string()
                query.destroy()
                return guid
        query.destroy()
    finally:
        repo.close()
    raise AssertionError('the deposit is not in the book')


@pytest.fixture
def book_and_ledger(tmp_path):
    """The invoice settled by both blocks, and the file that did it."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(book),
                               ACCOUNTS]).exit_code == 0
    assert runner.invoke(cli, ['import', str(book), DEPOSIT]).exit_code == 0

    deposit = _the_deposit_guid(book)
    ledger = tmp_path / 'ledger.txt'
    ledger.write_text(LEDGER.read_text().replace('TXN_GUID', deposit))
    result = runner.invoke(cli, ['import', str(book), str(ledger),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return book, ledger, deposit


class TestWhenTheNamedTransactionIsGone:
    """The retargeted deposit is deleted, and the same ledger read again."""

    def _reimport_without_it(self, book_and_ledger):
        book, ledger, deposit = book_and_ledger
        runner = CliRunner()
        removed = runner.invoke(cli, ['delete-transactions', str(book),
                                      '--by-guid', deposit])
        assert removed.exit_code == 0, removed.output
        return runner.invoke(cli, ['import', str(book), str(ledger),
                                   '--include-business-objects'])

    def test_it_is_not_asked_for_a_field_it_never_had(self, book_and_ledger):
        """`date:` is not a required field of a retarget block."""
        result = self._reimport_without_it(book_and_ledger)

        assert "required field 'date'" not in result.output, result.output
        assert 'Traceback' not in result.output, result.output

    def test_it_is_told_what_is_actually_wrong(self, book_and_ledger):
        """The guid names nothing, which is the reader's own deletion.

        The block states no date and no amount, so it describes no movement to
        record from — there is nothing to fall back on and nothing to guess,
        and saying so names the one thing that changed.
        """
        result = self._reimport_without_it(book_and_ledger)

        assert result.exit_code != 0, result.output
        assert 'not found in book' in result.output, result.output
        assert book_and_ledger[2] in result.output, result.output
