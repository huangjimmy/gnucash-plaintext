"""Spending currency the book keeps no usable cost basis for is not refused.

A disposal that says which cost basis it came out of is the rule, and one that
says nothing is refused — but the refusal asks a question first: does the book
keep a cost basis on that side that could have been drawn on at all? Where it
does not, there is nothing to state and nothing to choose, and sending a reader
to a listing they could not have used is worse than not asking.

Two ways a book gets there, and both are in
`tests/fixtures/a_currency_whose_cost_bases_cannot_be_drawn_on.txt`:

* **a cost basis spent to the last cent.** It stays on the book as a row
  reading 0.00, and a row with no units left offers nothing;
* **currency that arrived with no cost.** These dollars were borrowed in a
  transaction stated wholly in US dollars, which gives neither side a Canadian
  figure, so no cost basis was opened for them.

A third is currency whose stored cost cannot be read — a figure a hand edit or
an older release can leave behind. It counts for nothing here, as it does
everywhere else that adds these up; `fx-balances --verify-costs` is what reports
it.
"""

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata
from infrastructure.gnucash.utils import find_account
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from tests.conftest import _run
from tests.integration.text_report_pages import book_from

SPENDING = 'tests/fixtures/a_disposal_of_dollars_no_cost_basis_can_speak_for.txt'
LEDGER = 'a_currency_whose_cost_bases_cannot_be_drawn_on.txt'


def _spend_the_dollars(book):
    return _run(CliRunner(), 'import', str(book), SPENDING)


def test_the_book_keeps_one_cost_basis_and_it_holds_nothing(tmp_path):
    listing = CliRunner().invoke(
        cli, ['fx-balances', str(book_from(tmp_path, LEDGER))]).output

    assert 'Total USD cost basis balance: 0.00 USD' in listing, listing
    assert 'Total USD held in accounts: 500.00 USD' in listing, listing


def test_spending_them_is_not_refused(tmp_path):
    done = _spend_the_dollars(book_from(tmp_path, LEDGER))

    assert done.exit_code == 0, done.output
    assert 'Errors:       0' in done.output, done.output
    assert 'Transactions: 1' in done.output, done.output


def test_nor_is_it_refused_where_a_stored_cost_cannot_be_read(tmp_path):
    """A cost basis with dollars left whose cost will not parse counts for nothing.

    Rather than taking the run down. No file can write one — `import` refuses a
    `cost_basis_cost:` it cannot read — so the book is put in that state the
    way a book already in it got there: written straight onto the split, with a
    balance left on it, since a cost basis holding nothing is turned away
    before its cost is read.
    """
    book = book_from(tmp_path, LEDGER)
    _leave_an_unreadable_cost_on(book)

    done = _spend_the_dollars(book)

    assert done.exit_code == 0, done.output
    assert 'Errors:       0' in done.output, done.output


def _leave_an_unreadable_cost_on(book):
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        account = find_account(repo.book.get_root_account(), 'Assets:USD Held')
        split = next(s for s in account.GetSplitList() if s.GetAmount().num() > 0)
        transaction = split.GetParent()
        transaction.BeginEdit()
        metadata = dict(get_custom_metadata(split))
        metadata['cost_basis_cost'] = 'oops'
        metadata['cost_basis_balance'] = '100.00'
        set_custom_metadata(split, metadata)
        transaction.CommitEdit()
        repo.save()
    finally:
        repo.close()
