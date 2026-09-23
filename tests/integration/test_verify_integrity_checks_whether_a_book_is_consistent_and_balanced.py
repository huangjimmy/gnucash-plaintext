"""`--verify-integrity` draws the statements of a finished book and reads them against each other.

Two spellings, one check. On its own it takes a book nobody is changing; given
before a command that writes, it runs once that command has saved and reopens
the book from disk — the book the next command will read, rather than a session
a failed save never wrote.

What it asks is not what `validate` asks. `validate` reads the ledger;
this reads the figures the book produces: that the balance sheet balances, that
the income statement over the book's whole life accounts for the retained
earnings, that every income and expense account is kept in the book's own
currency, and that no cost basis holds more of a currency than the accounts do.
`fx-balances --verify-costs` runs alongside, so one pass reports everything.
"""

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata
from infrastructure.gnucash.utils import find_account
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import (
    COST_BASIS_BALANCE_KEY,
    find_split_by_guid,
    split_guid,
)
from tests.conftest import _run
from tests.integration.text_report_pages import FIXTURES, book_from

BALANCED = 'a_broker_fee_two_us_loans_and_part_of_the_shares_sold.txt'
AN_EXPENSE_IN_US_DOLLARS = 'a_cad_book_with_usd_hkd_and_shares_priced_in_its_price_database.txt'
NO_TRANSACTION = 'a_book_whose_top_level_accounts_are_in_two_currencies.txt'
OVERSTATED = 'a_cost_basis_stating_more_than_the_accounts_hold.txt'
A_DISGUISED_CLOSING = 'income_written_as_a_closing_entry.txt'


def _leave_a_balance_on_a_canadian_split(book):
    """Write a cost basis balance onto a split in the book's own currency.

    No file can state one there — `import` refuses a balance on a base-currency
    split — so the book is put in that state the way a book already in it got
    there: written straight onto the split.
    """
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        account = find_account(repo.book.get_root_account(), 'Assets:CAD Bank')
        split = account.GetSplitList()[0]
        transaction = split.GetParent()
        transaction.BeginEdit()
        metadata = dict(get_custom_metadata(split))
        metadata[COST_BASIS_BALANCE_KEY] = '1.00'
        set_custom_metadata(split, metadata)
        transaction.CommitEdit()
        guid = split_guid(split)
        repo.save()
    finally:
        repo.close()
    return guid


class TestOnItsOwn:
    def test_a_book_that_holds_together_is_said_to(self, tmp_path):
        checked = CliRunner().invoke(
            cli, ['--verify-integrity', str(book_from(tmp_path, BALANCED))])

        assert checked.exit_code == 0, checked.output
        assert 'The book is consistent and balanced.' in checked.output, checked.output

    def test_it_says_what_it_looked_at(self, tmp_path):
        """Each check by name, so a reader knows what a clean report covers."""
        checked = CliRunner().invoke(
            cli, ['--verify-integrity', str(book_from(tmp_path, BALANCED))])

        assert checked.exit_code == 0, checked.output
        for looked_at in (
                "checked: every income and expense account is kept in the "
                "book's own currency",
                'checked: the balance sheet as of 2028-12-31 balances',
                "checked: the income statement's net income is the sheet's "
                'retained earnings and what closing entries moved into equity',
                'checked: no cost basis holds more of a currency than the accounts do',
                'checked: every cost basis agrees with the ledger it comes from'):
            assert f'  {looked_at}' in checked.output.splitlines(), checked.output

    def test_the_statements_are_drawn_to_the_last_transaction(self, tmp_path):
        """So every transaction the book holds is on the page it is checked from."""
        checked = CliRunner().invoke(
            cli, ['--verify-integrity', str(book_from(tmp_path, BALANCED))])

        assert '  as of 2028-12-31, in CAD' in checked.output.splitlines(), checked.output

    def test_a_date_of_its_own_is_taken(self, tmp_path):
        """And everything is read to it, the accounts as well as the cost bases.

        This book repays a loan and sells 7 of its 10 shares in December. Read
        whole against cost bases read to 30 June, it reported the bases holding
        1,010.00 USD it no longer owed and 10 shares where 3 were left — two
        findings on a book that is correct at either date.
        """
        checked = CliRunner().invoke(
            cli, ['--verify-integrity', str(book_from(tmp_path, BALANCED)),
                  '--as-of', '2028-06-30'])

        assert checked.exit_code == 0, checked.output
        assert '  as of 2028-06-30, in CAD' in checked.output.splitlines(), checked.output
        assert 'The book is consistent and balanced.' in checked.output, checked.output

    def test_a_currency_of_its_own_is_taken(self, tmp_path):
        """The statements are then in that currency, and cannot be read against the book.

        The book's income and expense accounts are kept in Canadian dollars, its
        own currency, which is what the rule asks of them — so they are not a
        finding. Drawn in US dollars, both statements convert them at the rate
        of the page's own date, and the sheet cannot balance on the book's own
        figures; that is the reader's choice of currency, not a fault in the
        book, so the two comparisons are listed as not checked.
        """
        checked = CliRunner().invoke(
            cli, ['--verify-integrity', str(book_from(tmp_path, BALANCED)),
                  '--currency', 'USD'])

        assert '  as of 2028-12-31, in USD' in checked.output.splitlines(), checked.output
        assert ("  not checked: the balance sheet and the income statement: drawn "
                "in USD, and the book is kept in CAD, so every income and expense "
                "account is converted at the rate of the page's own date. Check "
                "the book in CAD.") in checked.output.splitlines(), checked.output
        assert 'not kept in' not in checked.output, checked.output
        assert checked.exit_code == 0, checked.output

    def test_a_book_stating_no_currency_of_its_own_takes_the_one_given(self, tmp_path):
        """Its top-level accounts are in two currencies, so `--currency` stands for its own."""
        checked = CliRunner().invoke(
            cli, ['--verify-integrity', str(book_from(tmp_path, NO_TRANSACTION)),
                  '--as-of', '2026-12-31', '--currency', 'CAD'])

        assert checked.exit_code == 0, checked.output
        assert ("  checked: every income and expense account is kept in the "
                "book's own currency") in checked.output.splitlines(), checked.output

    def test_a_book_holding_no_transaction_says_so_rather_than_passing_quietly(self, tmp_path):
        """Neither statement can be drawn, so the report says which checks did not run."""
        checked = CliRunner().invoke(
            cli, ['--verify-integrity', str(book_from(tmp_path, NO_TRANSACTION))])

        assert checked.exit_code == 0, checked.output
        assert ('  not checked: the book holds no transaction, so neither '
                'statement was drawn') in checked.output.splitlines(), checked.output


class TestWhatItCannotCheck:
    """Two ways a statement cannot be drawn. Each is reported, not passed over."""

    def test_a_book_whose_currency_nothing_states(self, tmp_path):
        """Its top-level accounts are in two currencies, so no report can be drawn.

        Given a date of its own the check gets as far as asking which currency,
        and says what the balance sheet itself says. The cost bases are still
        read, because they need no currency — a balance is a count of units.
        """
        checked = CliRunner().invoke(
            cli, ['--verify-integrity', str(book_from(tmp_path, NO_TRANSACTION)),
                  '--as-of', '2026-12-31'])

        assert checked.exit_code == 0, checked.output
        assert '  as of 2026-12-31' in checked.output.splitlines(), checked.output
        assert 'not checked: neither statement was drawn:' in checked.output
        assert "top-level accounts are held in CAD, USD" in checked.output, checked.output
        assert ('  checked: every cost basis agrees with the ledger it comes '
                'from') in checked.output.splitlines(), checked.output

    def test_a_currency_gnucash_does_not_know(self, tmp_path):
        """Refused as `balance-sheet --currency QQQ` refuses it, on every build.

        Handed to GnuCash unchecked, the two generations disagreed: 5.x
        refused to render, and 3.4 to 4.13 drew both pages in QQQ and
        reported the book balanced.
        """
        checked = CliRunner().invoke(
            cli, ['--verify-integrity', str(book_from(tmp_path, BALANCED)),
                  '--currency', 'QQQ'])

        assert checked.exit_code == 0, checked.output
        assert ('  not checked: neither statement was drawn: --currency QQQ: '
                'GnuCash knows no currency QQQ.') in checked.output.splitlines(), \
            checked.output
        assert 'the balance sheet as of' not in checked.output, checked.output


class TestABookItCatches:
    """A cost basis standing for currency the accounts no longer hold.

    The ledger states `cost_basis_balance: "1000.00"` on a purchase of 1,000.00
    USD and then sells 400.00 of them against it. A stated balance is what that
    cost basis holds once the file has landed, so the statement stands, and
    nothing refuses it as it lands — the figure is inside what the split brought
    in, which is all the rule on a stated balance asks.
    """

    def test_the_book_imports_cleanly(self, tmp_path):
        """Which is the point: the ledger is not what is wrong."""
        made = CliRunner().invoke(
            cli, ['import', '--new', str(tmp_path / 'book.gnucash'),
                  str(FIXTURES / OVERSTATED)])

        assert made.exit_code == 0, made.output
        assert 'Errors:       0' in made.output, made.output

    def test_the_check_reports_what_is_offered_against_what_is_held(self, tmp_path):
        checked = CliRunner().invoke(
            cli, ['--verify-integrity', str(book_from(tmp_path, OVERSTATED))])

        assert checked.exit_code == 1, checked.output
        assert '1 thing(s) are wrong with this book:' in checked.output, checked.output
        assert ('the USD cost bases on the asset side hold 1,000.00, and the '
                'book holds 600.00') in checked.output, checked.output

    def test_it_says_what_such_a_book_would_do(self, tmp_path):
        checked = CliRunner().invoke(
            cli, ['--verify-integrity', str(book_from(tmp_path, OVERSTATED))])

        assert ('A cost basis standing for currency that is gone offers what '
                'cannot be sold') in checked.output, checked.output

    def test_the_two_statements_disagree_where_income_is_written_as_a_closing_entry(
            self, tmp_path):
        """GnuCash's Income Statement leaves a closing entry out and the sheet keeps it in.

        So 500.00 of ordinary income described `Closing Entries` is inside
        `retained_earnings` and outside `net_income`, on a book that balances.
        Neither page is wrong on its own terms, and reading one against the
        other is the only thing that says so.
        """
        checked = CliRunner().invoke(
            cli, ['--verify-integrity', str(book_from(tmp_path, A_DISGUISED_CLOSING))])

        assert checked.exit_code == 1, checked.output
        assert ('the income statement for the whole book states net_income '
                '2,000.00, and the balance sheet states retained_earnings '
                '2,500.00') in checked.output, checked.output

    def test_a_balance_left_on_a_split_that_is_no_cost_basis_is_reported(self, tmp_path):
        """`verify_cost_bases` runs in the same pass, so one command reports everything.

        The balance is written straight onto a Canadian split, which is what an
        earlier version of this tool left behind and what the GnuCash GUI can be
        made to hold: a split in the book's own currency holds no foreign
        currency to have a cost, so it is no cost basis whatever is stored on it.
        """
        book = book_from(tmp_path, BALANCED)
        guid = _leave_a_balance_on_a_canadian_split(book)

        checked = CliRunner().invoke(cli, ['--verify-integrity', str(book)])

        assert checked.exit_code == 1, checked.output
        assert guid in checked.output, checked.output
        assert 'Assets:CAD Bank' in checked.output, checked.output


CARRIED = 'shares_bought_in_a_transaction_stating_no_canadian_figure.txt'


def _misstate_the_shares_cost(book):
    """Write 60 CAD a share where the dollars that paid for them cost 52.00.

    The purchase states no Canadian figure, so the cost is carried from the
    dollars and stored on the split — the only figure there is. No file can
    write a different one: `import` works it out from the dollars. So the book
    is put in that state the way a book edited elsewhere gets there, written
    straight onto the split.
    """
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        split = find_split_by_guid(repo.book, 'b2b2b2b2b2b2b2b2b2b2b2b2b2b20002')
        transaction = split.GetParent()
        transaction.BeginEdit()
        metadata = dict(get_custom_metadata(split))
        metadata['cost_basis_cost'] = '60 CAD/USD_TECH'
        set_custom_metadata(split, metadata)
        transaction.CommitEdit()
        repo.save()
    finally:
        repo.close()


class TestABookWhosePageDoesNotBalance:
    """A cost the shares are measured from that is not what they cost.

    The page measures the shares still held from their cost basis, so a cost
    written wrong moves `total_unrealized_gains` and nothing else, and the page
    no longer balances.
    """

    def test_the_check_says_the_sheet_does_not_balance_and_exits_one(self, tmp_path):
        book = book_from(tmp_path, CARRIED)
        _misstate_the_shares_cost(book)

        checked = CliRunner().invoke(cli, ['--verify-integrity', str(book)])

        assert checked.exit_code == 1, checked.output
        # 30 USD_TECH still held, costed 8.00 a share above what they cost:
        # 240.00 of unrealized gain gone from equity, and nothing from assets.
        assert ('the balance sheet does not balance: it states 14,900.00 of '
                'assets against 14,660.00 of liabilities and equity') \
            in checked.output, checked.output


class TestABookClosedWithCloseBooks:
    """Closing entries move a year's profit out of income into equity.

    The income statement leaves every one out, so over the book's whole life
    it states all the profit ever made; the sheet's `retained_earnings` is only
    what is not closed yet. So the two are compared with what the closing
    entries moved added back, and a closed book is not reported as wrong.
    """

    def _closed(self, tmp_path):
        book = book_from(tmp_path, BALANCED)
        closed = _run(CliRunner(), 'close-books', str(book),
                      '--closing-date', '2028-12-31')
        assert closed.exit_code == 0, closed.output
        return book

    def test_a_book_closed_at_its_last_transaction_is_consistent(self, tmp_path):
        checked = CliRunner().invoke(cli, ['--verify-integrity', str(self._closed(tmp_path))])

        assert checked.exit_code == 0, checked.output
        assert 'The book is consistent and balanced.' in checked.output, checked.output

    def test_a_close_after_the_date_checked_moves_nothing_yet(self, tmp_path):
        """Checked at 2028-06-30, the December close has not happened."""
        checked = CliRunner().invoke(cli, ['--verify-integrity', str(self._closed(tmp_path)),
                                           '--as-of', '2028-06-30'])

        assert checked.exit_code == 0, checked.output
        assert 'The book is consistent and balanced.' in checked.output, checked.output

    def test_a_book_that_traded_after_the_close_is_consistent(self, tmp_path):
        book = self._closed(tmp_path)
        later = tmp_path / 'later.txt'
        later.write_text('2029-01-15 * "Shares sold for more than they cost, in 2029"\n'
                         '\tcurrency.mnemonic: "CAD"\n'
                         '\tAssets:CAD Bank 500.00 CAD\n'
                         '\tIncome:Realized Gains -500.00 CAD\n')
        imported = _run(CliRunner(), 'import', str(book), str(later))
        assert 'Errors:       0' in imported.output, imported.output

        checked = CliRunner().invoke(cli, ['--verify-integrity', str(book)])

        assert checked.exit_code == 0, checked.output
        assert 'The book is consistent and balanced.' in checked.output, checked.output


class TestOnACommandThatWrites:
    def test_the_check_runs_after_the_import_has_saved(self, tmp_path):
        book = tmp_path / 'book.gnucash'

        done = CliRunner().invoke(
            cli, ['--verify-integrity', 'import', '--new', str(book),
                  str(FIXTURES / BALANCED)])

        assert done.exit_code == 0, done.output
        assert 'Errors:       0' in done.output, done.output
        assert 'The book is consistent and balanced.' in done.output, done.output
        assert done.output.index('Errors:       0') < \
            done.output.index('Integrity check'), done.output

    def test_a_book_the_check_catches_ends_the_run(self, tmp_path):
        """`Expenses:Interest` in US dollars is a book gnucash-plaintext does not support.

        The import itself is clean — the ledger says nothing wrong — and the
        check is what refuses, so the run exits 1 with the finding printed and
        a closing line saying how many things are wrong.
        """
        book = tmp_path / 'book.gnucash'

        done = CliRunner().invoke(
            cli, ['--verify-integrity', 'import', '--new', str(book),
                  str(FIXTURES / AN_EXPENSE_IN_US_DOLLARS)])

        assert done.exit_code == 1, done.output
        assert 'Errors:       0' in done.output, done.output
        assert 'Expenses:Interest (USD)' in done.output, done.output
        assert ('this command left the book with 1 thing(s) wrong with it, '
                'each printed above') in done.output, done.output

    def test_such_a_book_has_its_net_income_left_unchecked_and_says_so(self, tmp_path):
        """A US dollar expense has no one rate, so there is no figure to compare."""
        book = tmp_path / 'book.gnucash'

        done = CliRunner().invoke(
            cli, ['--verify-integrity', 'import', '--new', str(book),
                  str(FIXTURES / AN_EXPENSE_IN_US_DOLLARS)])

        assert ("  not checked: the income statement's net income against the "
                "sheet's retained earnings: the income and expense accounts "
                "above are not kept in CAD") in done.output.splitlines(), done.output

    def test_the_book_is_found_behind_the_input_flag_too(self, tmp_path):
        """`import` takes its book positionally or behind `-i/--input`, and the
        check reads whichever the run used."""
        book = tmp_path / 'book.gnucash'

        done = CliRunner().invoke(
            cli, ['--verify-integrity', 'import', '--new', '-i', str(book),
                  '-f', str(FIXTURES / BALANCED)])

        assert done.exit_code == 0, done.output
        assert 'The book is consistent and balanced.' in done.output, done.output

    def test_a_dry_run_writes_nothing_and_is_not_checked(self, tmp_path):
        """A clean dry run of `import-beancount -o new.gnucash` leaves no book, and is no failure."""
        book = tmp_path / 'book.gnucash'

        done = CliRunner().invoke(
            cli, ['--verify-integrity', 'import-beancount', '-o', str(book),
                  '-i', str(FIXTURES / 'beancount_postings_written_by_hand.beancount'),
                  '--dry-run'])

        assert done.exit_code == 0, done.output
        assert ('--verify-integrity: a dry run writes nothing, so there is '
                'nothing to check.') in done.output, done.output

    def test_the_book_behind_an_exports_input_flag_is_checked(self, tmp_path):
        """`export`, `export-transaction`, `validate` and `export-beancount`
        take the book behind `-i/--input` as `input_file`, where `import` keeps
        its ledger — so the check reads `input_file` only as that option."""
        book = book_from(tmp_path, BALANCED)

        done = CliRunner().invoke(
            cli, ['--verify-integrity', 'export', '-i', str(book),
                  '-o', str(tmp_path / 'out.txt')])

        assert done.exit_code == 0, done.output
        assert 'The book is consistent and balanced.' in done.output, done.output

    def test_a_book_the_command_never_saved_is_reported_not_raised(self, tmp_path):
        """An import that saves nothing leaves no book to reopen.

        The import's own refusal is what the reader needs; the check says it
        found no book rather than ending the run with a traceback.
        """
        book = tmp_path / 'book.gnucash'
        ledger = tmp_path / 'ledger.txt'
        ledger.write_text('2026-01-01 * "Opening"\n\tAssets:Nowhere 1.00 QQQ\n')

        done = CliRunner().invoke(
            cli, ['--verify-integrity', 'import', '--new', str(book), str(ledger)])

        assert done.exit_code == 1, done.output
        assert isinstance(done.exception, SystemExit), repr(done.exception)
        assert ('Error: the book could not be checked: There is no file at '
                'that path.') in done.output, done.output

    def test_a_command_that_only_reads_is_checked_too(self, tmp_path):
        """`export` writes no book, so the check reports on the one it read."""
        book = book_from(tmp_path, BALANCED)

        done = CliRunner().invoke(
            cli, ['--verify-integrity', 'export', str(book),
                  str(tmp_path / 'out.txt')])

        assert done.exit_code == 0, done.output
        assert 'The book is consistent and balanced.' in done.output, done.output


def test_the_flag_with_no_book_is_a_usage_error(tmp_path):
    """`gnucash-plaintext --verify-integrity $BOOK` with `$BOOK` empty checked
    nothing and exited 0, which a daily run reads as a sound book."""
    done = CliRunner().invoke(cli, ['--verify-integrity'])

    assert done.exit_code == 2, done.output
    assert ('--verify-integrity takes a book to check, or a command to run '
            'before checking the book it was given') in done.output, done.output


def test_a_mistyped_command_is_not_read_as_a_book(tmp_path):
    """`improt` is neither a command nor a file, and the reader is told both."""
    book = book_from(tmp_path, BALANCED)

    done = CliRunner().invoke(cli, ['--verify-integrity', 'improt', str(book)])

    assert done.exit_code == 2, done.output
    assert ("No such command 'improt', and no book at that path to check") \
        in done.output, done.output


def test_the_bare_command_still_prints_its_help(tmp_path):
    """The group takes a book of its own now, so it runs with no subcommand —
    and with no flag either it has nothing to do but say what it offers."""
    shown = CliRunner().invoke(cli, [])

    assert shown.exit_code == 0, shown.output
    assert 'GnuCash Plaintext' in shown.output, shown.output
    assert '--verify-integrity' in shown.output, shown.output


def test_without_the_flag_nothing_is_checked(tmp_path):
    """It is expensive — two GnuCash reports and a walk of every split."""
    book = tmp_path / 'book.gnucash'

    done = _run(CliRunner(), 'import', '--new', str(book),
                str(FIXTURES / BALANCED))

    assert done.exit_code == 0, done.output
    assert 'Integrity check' not in done.output, done.output
