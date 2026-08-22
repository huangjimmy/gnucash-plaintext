"""A book from the shipped release re-imports its own ledger unchanged.

`notes:` and `billing_id:` became bill *fields*; the shipped release filed them
in the slot beside the object, so `GetNotes()` on such a bill is empty. The
comparison that decides whether a bill matches its file reads the field.

For a book written before this change that answers "different" on every run,
whatever the file says — and a posted bill judged different is rebuilt, which
means unposting it. On a foreign-currency bill whose settlement drew a cost
basis down, unposting is refused outright:

    bill 'BILL-…' cannot be unposted: its cost basis is what 1 transaction(s)
    measure against …

so the ledger cannot be imported at all, and the only way out — deleting the
`notes:` line from a file this tool wrote — is not in the message. The address
keys met this first and got a fallback through `held_value`; the bill's own
text is twenty lines away in the same file and did not.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner
from gnucash import Query
from gnucash import gnucash_business as gb

from cli.main import cli
from infrastructure.gnucash.kvp import set_custom_metadata
from repositories.gnucash_repository import GnuCashRepository, SessionMode

FIXTURES = Path('tests/fixtures')
LEDGER = str(FIXTURES / 'fx_usd_bill_with_notes_settled_from_an_hkd_bank.txt')
RATES = 'tests/fixtures/fx_rates_usd_and_hkd.yaml'
NOTES = 'Parts for the March build'


@pytest.fixture
def book_from_the_shipped_release(tmp_path):
    """The same book, with the bill's notes where the old version put them."""
    book = tmp_path / 'legacy.gnucash'
    result = CliRunner().invoke(cli, [
        'import', '--new', str(book), LEDGER,
        '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        query = Query()
        query.search_for('gncInvoice')
        query.set_book(repo.book)
        moved = 0
        for raw in query.run():
            bill = gb.Bill(instance=raw)
            if bill.GetID() != 'BILL-USD-FROM-HKD':
                continue
            bill.BeginEdit()
            bill.SetNotes('')
            set_custom_metadata(bill, {'notes': NOTES})
            bill.CommitEdit()
            moved += 1
        query.destroy()
        assert moved == 1, f'expected one bill, moved {moved}'
        repo.save()
    finally:
        repo.close()
    return book


class TestEditingALineOfIt:
    def test_says_what_the_obstacle_is(self, book_from_the_shipped_release,
                                       tmp_path):
        """The cost basis, not the posting.

        A file changing a posted bill's lines is refused and told to
        run `unpost-bills` first — but this bill cannot be unposted at all,
        because its settlement is what a cost basis measures against, so
        that command refuses too and for a reason the first message never
        mentioned. Two hops to the truth, and the first one wrong.
        """
        edited = tmp_path / 'edited.txt'
        edited.write_text(
            Path(LEDGER).read_text(encoding='utf-8').replace(
                'description: "Parts"', 'description: "Parts, revised"'),
            encoding='utf-8')

        result = CliRunner().invoke(cli, [
            'import', str(book_from_the_shipped_release), str(edited),
            '--include-business-objects', '--fx-rates', RATES])

        assert result.exit_code != 0, result.output
        message = str(result.output) + str(result.exception)
        assert 'cost basis' in message, message
        assert 'unpost-bills' not in message, message


class TestReadingItsOwnLedgerAgain:
    def test_it_is_not_refused(self, book_from_the_shipped_release):
        result = CliRunner().invoke(cli, [
            'import', str(book_from_the_shipped_release), LEDGER,
            '--include-business-objects', '--fx-rates', RATES])

        assert result.exit_code == 0, result.output
        assert 'cannot be unposted' not in result.output, result.output

    def test_the_note_is_on_the_field_afterwards(self,
                                                 book_from_the_shipped_release):
        """Migrated, not merely tolerated — the next run has nothing to do."""
        book = book_from_the_shipped_release
        CliRunner().invoke(cli, ['import', str(book), LEDGER,
                                 '--include-business-objects',
                                 '--fx-rates', RATES])

        repo = GnuCashRepository(str(book))
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            query = Query()
            query.search_for('gncInvoice')
            query.set_book(repo.book)
            found = [gb.Bill(instance=raw).GetNotes() for raw in query.run()
                     if gb.Bill(instance=raw).GetID() == 'BILL-USD-FROM-HKD']
            query.destroy()
        finally:
            repo.close()
        assert found == [NOTES], found

    def test_the_third_run_has_nothing_left_to_do(self,
                                                  book_from_the_shipped_release):
        """The migration finishes, rather than happening every run.

        Moving the note is a change to the book, so the run that does it has
        to save — reported `unchanged`, it happened in memory and was dropped
        on session end, and the next run did it again. Once saved, the run
        after finds the field set and the slot empty.
        """
        book = book_from_the_shipped_release
        runner = CliRunner()
        for _ in range(2):
            assert runner.invoke(cli, [
                'import', str(book), LEDGER, '--include-business-objects',
                '--fx-rates', RATES]).exit_code == 0

        third = runner.invoke(cli, ['import', str(book), LEDGER,
                                    '--include-business-objects',
                                    '--fx-rates', RATES])

        assert third.exit_code == 0, third.output
        assert 'Changes saved' not in third.output, third.output
