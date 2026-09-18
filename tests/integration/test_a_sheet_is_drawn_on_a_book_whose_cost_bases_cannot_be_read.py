"""A balance sheet is drawn on a book holding a cost basis it cannot read.

Two shapes a book can hold that this tool never writes, and both reach the
balance sheet's own reading of the cost bases:

- **a cost basis with no balance recorded.** The KVP is the record of what a
  cost basis has left, so a split carrying none has no balance rather than its
  full amount — it may have been made in the GnuCash GUI or predate the
  feature, and sales may already have been measured against it that nothing
  wrote down.
- **a cost that will not parse.** Reading it raises rather than answering
  nothing, because a stated cost is refused rather than ignored.

Neither may take the page down, and neither may be counted: a basis whose
balance or cost cannot be read counts for nothing, exactly as it does in what
`fx-balances` totals. That currency then keeps GnuCash's own revaluation, and
the sheet still balances.

Both books are made through the book rather than through a file, because no
file reaches either state: a cost that will not parse is refused as it lands,
and an import writes a balance for every cost basis it opens. These are the
books somebody else's editor leaves behind, which is what `fx-balances
--verify-costs` exists to report — and a reader reaches for a balance sheet at
exactly the moment there is something in the book worth looking at.
"""

from click.testing import CliRunner

from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata
from infrastructure.gnucash.utils import find_account
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from tests.conftest import _run
from tests.integration.text_report_pages import key_of

OVERPAID = 'tests/fixtures/fx_invoice_usd_overpaid_into_usd_bank.txt'
RATES = 'tests/fixtures/fx_rates_usd_dated.yaml'
RECEIVABLE = 'Assets:Accounts Receivable USD'
AS_OF = '2026-03-31'


def _a_book_of_two_cost_bases(runner, tmp_path):
    """100.00 USD invoiced and overpaid with 200.00, into a US dollar bank.

    Both receivable splits are cost bases at the rate the invoice was booked
    at, and the overpayment's own transaction is stated wholly in US dollars,
    so its cost is stored on the split rather than derived from the entry.
    """
    book = tmp_path / 'book.gnucash'
    result = _run(runner, 'import', '--new', str(book), OVERPAID,
                  '--include-business-objects', '--fx-rates', RATES)
    assert result.exit_code == 0, result.output
    return book


def _edit_the_stored_basis(book, change):
    """Rewrite the KVP of the receivable split that carries a stored cost.

    Inside the transaction's own edit, since a KVP written outside one on an
    object the book already holds never reaches disk.
    """
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        account = find_account(repo.book.get_root_account(), RECEIVABLE)
        split = next(s for s in account.GetSplitList()
                     if 'cost_basis_cost' in get_custom_metadata(s))
        transaction = split.GetParent()
        transaction.BeginEdit()
        set_custom_metadata(split, change(dict(get_custom_metadata(split))))
        transaction.CommitEdit()
        repo.save()
    finally:
        repo.close()


def _sheet(runner, book):
    result = _run(runner, 'balance-sheet', str(book), '--as-of', AS_OF,
                  '--fx-rates', RATES)
    assert result.exit_code == 0, result.output
    return result.output


class TestACostBasisWithNoBalanceRecorded:
    """Counted as nothing, rather than as everything it brought in."""

    def test_the_page_is_drawn_and_balances(self, tmp_path):
        runner = CliRunner()
        book = _a_book_of_two_cost_bases(runner, tmp_path)
        _edit_the_stored_basis(
            book,
            lambda kvp: {key: value for key, value in kvp.items()
                         if key != 'cost_basis_balance'})

        page = _sheet(runner, book)

        assert key_of(page, 'total_assets') == \
            key_of(page, 'total_liabilities_and_equity')

    def test_the_gain_keys_are_still_stated(self, tmp_path):
        """A currency the cost bases cannot speak for is still currency.

        It keeps GnuCash's own revaluation and is stated under `_fx` all the
        same, so the keys are there to be read rather than missing.
        """
        runner = CliRunner()
        book = _a_book_of_two_cost_bases(runner, tmp_path)
        _edit_the_stored_basis(
            book,
            lambda kvp: {key: value for key, value in kvp.items()
                         if key != 'cost_basis_balance'})

        page = _sheet(runner, book)

        assert key_of(page, 'unrealized_gains_fx').endswith(' CAD'), page
        assert key_of(page, 'total_unrealized_gains').endswith(' CAD'), page


class TestACostThatWillNotParse:
    """`cost_basis_cost: "oops"`, as a book edited elsewhere can hold.

    Reading it raises, and one such split used to take a whole command down
    with it — so the page is drawn and that basis counts for nothing.
    """

    def test_the_page_is_drawn_and_balances(self, tmp_path):
        runner = CliRunner()
        book = _a_book_of_two_cost_bases(runner, tmp_path)
        _edit_the_stored_basis(book,
                               lambda kvp: {**kvp, 'cost_basis_cost': 'oops'})

        page = _sheet(runner, book)

        assert key_of(page, 'total_assets') == \
            key_of(page, 'total_liabilities_and_equity')

    def test_the_gain_keys_are_still_stated(self, tmp_path):
        runner = CliRunner()
        book = _a_book_of_two_cost_bases(runner, tmp_path)
        _edit_the_stored_basis(book,
                               lambda kvp: {**kvp, 'cost_basis_cost': 'oops'})

        page = _sheet(runner, book)

        assert key_of(page, 'unrealized_gains_fx').endswith(' CAD'), page
        assert key_of(page, 'total_unrealized_gains').endswith(' CAD'), page
