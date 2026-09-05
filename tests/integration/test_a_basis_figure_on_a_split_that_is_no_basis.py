"""Q-040: `--verify-costs` reports a cost-basis figure nothing can read.

A `cost_basis_balance` or a `cost_basis_cost` on a split that is not a cost
basis is the fault hardest to notice. `fx-balances` walks the cost bases, so
it never shows the figure; `--verify-costs` walked the same cost bases, so it
reported the book as sound; and the export writes the key back out, so the
ledger no longer rebuilds its own book.

The reported book had 2,719.28 USD sitting that way. This is the check that
says so.
"""


from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import (
    COST_BASIS_BALANCE_KEY,
    iter_splits,
    split_guid,
)
from tests.conftest import _run

RATES = 'tests/fixtures/fx_rates_usd_two_invoice_dates.yaml'
DEPOSIT_SPLIT = '00e958a8d56547d484d7629000292dc3'


def _a_book_with_a_parked_deposit(runner, book):
    result = runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_two_usd_invoices_posted.txt',
        '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output
    result = _run(runner, 'import', str(book),
                  'tests/fixtures/fx_usd_deposit_against_due_from_director.txt')
    assert result.exit_code == 0, result.output


def _strand_the_balance(book_path, guid):
    """Leave the balance on the deposit split and take its price away.

    The state the reported book was in: every split in one foreign currency,
    the transaction stated in that currency too, so there is no base-currency
    figure to say what the USD cost — while the balance the cost basis had goes on
    being stored. Built on a real book by moving the counter split onto the
    deposit's own account and restating the transaction in its currency, which
    is what the link did; nothing is mocked, and GnuCash loads the result.
    """
    repo = GnuCashRepository(str(book_path))
    repo.open(mode=SessionMode.NORMAL)
    try:
        for split in iter_splits(repo.book):
            if split_guid(split) != guid:
                continue
            account = split.GetAccount()
            transaction = split.GetParent()
            transaction.BeginEdit()
            for other in transaction.GetSplitList():
                if split_guid(other) == guid:
                    continue
                other.SetAccount(account)
            transaction.SetCurrency(account.GetCommodity())
            transaction.CommitEdit()
    finally:
        repo.save()
        repo.close()


def test_a_stranded_balance_is_reported(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _a_book_with_a_parked_deposit(runner, book)

    listing = _run(runner, 'fx-balances', str(book))
    assert DEPOSIT_SPLIT in listing.output, listing.output

    _strand_the_balance(book, DEPOSIT_SPLIT)

    listing = _run(runner, 'fx-balances', str(book))
    assert listing.exit_code == 0, listing.output
    assert DEPOSIT_SPLIT not in listing.output, (
        'the split has stopped being a cost basis, so the listing rightly drops '
        f'it:\n{listing.output}')

    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    message = verified.output
    assert verified.exit_code == 1, message
    assert DEPOSIT_SPLIT in message, message
    assert COST_BASIS_BALANCE_KEY in message, message
    assert '2720.00' in message or '2,720.00' in message, message


def test_a_sound_book_is_still_reported_sound(tmp_path):
    """The check must not fire on a book with nothing wrong with it."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _a_book_with_a_parked_deposit(runner, book)

    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 0, verified.output
    assert 'every cost agrees' in verified.output, verified.output


def test_a_split_that_never_had_a_figure_is_not_reported(tmp_path):
    """Only a split with a cost-basis key on it is asked about.

    Most splits in any book are not cost bases, and saying so of each would
    bury the one that matters.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _a_book_with_a_parked_deposit(runner, book)

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        plain = [split_guid(split) for split in iter_splits(repo.book)
                 if not get_custom_metadata(split).get(COST_BASIS_BALANCE_KEY)]
    finally:
        repo.close()
    assert plain, 'the book should hold splits with no cost basis figure on them'

    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    for guid in plain:
        assert guid not in verified.output, verified.output


def test_a_balance_on_a_split_that_never_could_be_a_basis_is_reported(tmp_path):
    """A balance written onto a CAD split, which no cost basis can live on.

    The import refuses that line — a split in the book's own currency holds no
    foreign currency for a cost basis to be about — but a book can be handed one by
    the GUI or an older tool, and it read as sound. The export emits it, so
    this book's own ledger no longer re-imports.

    A stored *cost* in the same place is not reported, and must not be: the
    export drops it (`_stored_cost_is_ignorable`), so it neither travels nor
    round-trips, and `test_verify_costs.py` pins that a spend with an
    unreadable one on it leaves the exit code at 0.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _a_book_with_a_parked_deposit(runner, book)

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    target = None
    try:
        for split in iter_splits(repo.book):
            account = split.GetAccount()
            commodity = account.GetCommodity() if account is not None else None
            if commodity is None or commodity.get_mnemonic() != 'CAD':
                continue
            transaction = split.GetParent()
            transaction.BeginEdit()
            set_custom_metadata(split, {COST_BASIS_BALANCE_KEY: '135.00'})
            transaction.CommitEdit()
            target = split_guid(split)
            break
    finally:
        repo.save()
        repo.close()
    assert target is not None

    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 1, verified.output
    assert target in verified.output, verified.output
    assert COST_BASIS_BALANCE_KEY in verified.output, verified.output
    assert 'CAD split' in verified.output, verified.output


A_SPENDING_SPLIT = 'tests/fixtures/fx_a_balance_stated_on_a_spending_split.txt'


class TestABalanceAFileStatesOnASplitThatSpends:
    """The shape a file can actually write, and what each command does with it.

    A balance on a CAD split is refused as the file lands, because a split in
    the book's own currency holds no foreign currency for a cost basis to be about.
    On a split that holds foreign currency and spends it, every question the
    import asks of the figure is satisfied — a number, positive, within the
    cent, no more than the split carries — and what makes it unreadable is the
    direction the split moves the currency, which is not among them.

    It is accepted deliberately, and the round trip is why: a book already
    holding such a figure exports it, and its own ledger has to keep
    re-importing or the one route out of a damaged book is closed. So the file
    lands, `--verify-costs` reports the split and says the one line that
    clears it, and `--atomic` — which answers for what a file leaves behind —
    rolls the same file back.
    """

    def test_the_file_lands(self, tmp_path):
        runner = CliRunner()
        book = tmp_path / 'book.gnucash'
        _a_book_with_a_parked_deposit(runner, book)

        result = _run(runner, 'import', str(book), A_SPENDING_SPLIT,
                      '--fx-rates', RATES)
        assert result.exit_code == 0, result.output

    def test_and_verify_costs_reports_it(self, tmp_path):
        runner = CliRunner()
        book = tmp_path / 'book.gnucash'
        _a_book_with_a_parked_deposit(runner, book)
        assert _run(runner, 'import', str(book), A_SPENDING_SPLIT,
                    '--fx-rates', RATES).exit_code == 0

        verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
        assert verified.exit_code == 1, verified.output
        assert COST_BASIS_BALANCE_KEY in verified.output, verified.output
        assert 'rather than raising it' in verified.output, verified.output

    def test_and_atomic_rolls_it_back(self, tmp_path):
        """The mode that answers for the book a file leaves behind."""
        runner = CliRunner()
        book = tmp_path / 'book.gnucash'
        _a_book_with_a_parked_deposit(runner, book)

        result = _run(runner, 'import', str(book), A_SPENDING_SPLIT,
                      '--atomic', '--fx-rates', RATES)
        assert result.exit_code != 0, result.output
        assert 'Rolled back' in result.output, result.output
        assert 'Changes saved' not in result.output, result.output

        verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
        assert verified.exit_code == 0, verified.output
