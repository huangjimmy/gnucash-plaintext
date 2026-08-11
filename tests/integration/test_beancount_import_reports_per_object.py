"""One object a beancount file cannot build does not cost the whole ledger.

`import-beancount` creates commodities, then accounts, then transactions, and
each is attempted on its own: what fails is recorded and the run carries on.
Nothing exercised that (T-009) — every test imported a file this tool had just
written, so the per-object handlers, and the two "not found in GnuCash"
refusals a failed account leaves behind, were never run.

The file is reached the way it is reached in life: exported from GnuCash and
then edited by hand, which is the entire purpose of exporting to beancount.
Its account carries a type GnuCash has no such thing as — the kind of thing a
search-and-replace across a ledger leaves behind — and a transaction posts to
that account.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
EDITED = str(FIXTURES / 'beancount_edited_by_hand.beancount')


class TestAnEditedFile:
    def test_the_bad_account_is_named_and_the_rest_still_lands(self, tmp_path):
        book = tmp_path / 'rebuilt.gnucash'
        result = CliRunner().invoke(cli, ['import-beancount', str(book), EDITED])

        assert result.exit_code == 1, result.output
        # Four of five accounts, and the transaction that does not touch the
        # fifth — the run is not abandoned at the first failure.
        assert 'Accounts:     4' in result.output
        assert 'Transactions: 1' in result.output
        assert 'Failed to create account Expenses:Broken' in result.output
        assert "Unknown account type 'NOT-AN-ACCOUNT-TYPE'" in result.output

    def test_a_transaction_posting_to_it_says_which_account_is_missing(self,
                                                                       tmp_path):
        """The second failure follows from the first, and reads as its own.

        The account is in the file's mapping — it has an `open` directive —
        and not in the book, because creating it failed a moment ago. Naming
        the account is what tells the reader the two are the same problem.
        """
        book = tmp_path / 'rebuilt.gnucash'
        result = CliRunner().invoke(cli, ['import-beancount', str(book), EDITED])

        assert 'Failed to create transaction' in result.output
        assert 'Account Expenses:Broken not found in GnuCash' in result.output

    def test_nothing_is_saved_when_anything_failed(self, tmp_path):
        """The counts are what got built in memory; the disk keeps none of it.

        The save happens only on a clean run, so a file that reports errors
        never writes the four accounts and one transaction the summary counts
        — and the empty book that used to be left in their place is taken
        away too, because the command refuses to write over an existing path
        and would otherwise have blocked its own retry.

        Worth pinning either way: the summary counts and what is on disk say
        different things, and only one of them is the book they open next.
        """
        book = tmp_path / 'rebuilt.gnucash'
        result = CliRunner().invoke(cli, ['import-beancount', str(book), EDITED])

        assert result.exit_code == 1, result.output
        assert 'Accounts:     4' in result.output, result.output
        assert not book.exists(), 'a failed import left a book behind'


class TestTheTransactionItCouldNotFinish:
    """The failed one attaches a split before it refuses, and must not stay.

    `Assets:Bank -20.00` goes on the transaction, and the posting after it
    names an account creating it had just failed. Abandoned there, the entry
    stays in the open book carrying that one split — GnuCash writes no
    transaction whose edit was never committed, so the saved file looks clean
    and only the session shows it.

    The command never saves a run that reported errors, so this is invisible
    through the CLI. It is not invisible to the run itself: the rest of the
    import reads the same open book.
    """

    def test_no_half_built_transaction_is_left_in_the_session(self, tmp_path):
        from gnucash import Query, Transaction

        from repositories.gnucash_repository import (
            GnuCashRepository,
            SessionMode,
        )
        from use_cases.import_beancount import ImportBeancountUseCase

        book = tmp_path / 'session.gnucash'
        assert CliRunner().invoke(cli, [
            'import', '--new', str(book),
            'tests/fixtures/account_with_finer_scu.txt']).exit_code == 0

        repo = GnuCashRepository(str(book))
        repo.open(mode=SessionMode.NORMAL)
        try:
            result = ImportBeancountUseCase(repo).import_from_file(EDITED)
            assert result.has_errors(), 'the fixture is supposed to fail'

            query = Query()
            query.search_for('Trans')
            query.set_book(repo.book)
            names = [Transaction(instance=raw).GetDescription()
                     for raw in query.run()]
            query.destroy()

            assert 'Posts to the account that could not be made' not in names, (
                names)
            assert 'This one is fine' in names, names
        finally:
            repo.close()
