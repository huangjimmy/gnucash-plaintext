"""The part of a foreign-currency balance past zero has a cost basis on the other side of the book.

An asset account below zero owes the currency, and a liability account above
zero holds it. A movement that crosses zero is two movements: the part up to
zero moves the side the balance is leaving, and the part past zero moves the
other side. Q-047 gives the cases and the figures they were worked out from.

`tests/fixtures/usd_moved_out_of_an_empty_account.txt` is the book every case
starts from: C holds 1,000.00 USD bought at 1.30, and 500.00 USD moved from an
empty A to B at 1.35 leaves A owing 500.00. The layers imported on top of it
sell B's dollars, refill A, pay income into A across zero, move more out of C
than it holds, and overpay a US dollar card and spend its credit.

After each, per currency and side, the cost bases hold what the accounts hold
and owe, and `--verify-integrity` finds the book consistent.
"""

from datetime import date
from fractions import Fraction

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata
from infrastructure.gnucash.utils import get_account_full_name
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import (
    cost_basis_items_by_currency_and_side,
    foreign_currency_account_balances,
    iter_splits,
)
from tests.conftest import _run

FIXTURES = 'tests/fixtures/'
THE_BOOK = FIXTURES + 'usd_moved_out_of_an_empty_account.txt'
SOLD = FIXTURES + 'usd_moved_out_of_an_empty_account_then_sold.txt'
REFILLED = FIXTURES + 'usd_moved_out_of_an_empty_account_then_refilled.txt'
INCOME = FIXTURES + 'usd_moved_out_of_an_empty_account_then_income_into_it.txt'
INCOME_GIVING_NO_COST_BASIS = (
    FIXTURES + 'usd_moved_out_of_an_empty_account_then_income_into_it_giving_no_cost_basis.txt')
MORE_THAN_C_HOLDS = (
    FIXTURES + 'usd_moved_out_of_an_empty_account_then_more_moved_out_of_c_than_it_holds.txt')
THE_CARD = FIXTURES + 'a_usd_card_overpaid_then_its_credit_spent.txt'
INCOME_GIVING_A_GUID_THE_BOOK_DOES_NOT_HOLD = (
    FIXTURES
    + 'usd_moved_out_of_an_empty_account_then_income_into_it_giving_a_guid_the_book_does_not_hold.txt')
BOUGHT_STATING_WHAT_IT_BROUGHT_IN = (
    FIXTURES + 'usd_moved_out_of_an_empty_account_then_bought_stating_what_it_brought_in.txt')
A_FEE_WITH_NO_COST_BASIS = FIXTURES + 'usd_moved_with_a_fee_in_a_book_keeping_no_usd_cost_basis.txt'
THE_FEES_CORRECTED = (
    FIXTURES + 'usd_moved_with_a_fee_in_a_book_keeping_no_usd_cost_basis_fees_corrected.txt')
A_RECEIVABLE_STATING_WHAT_IT_BROUGHT_IN = (
    FIXTURES + 'usd_moved_out_of_an_empty_account_then_a_receivable_stating_what_it_brought_in.txt')
REFILLED_STATING_NO_CANADIAN_FIGURE = (
    FIXTURES
    + 'usd_moved_out_of_an_empty_account_then_refilled_in_a_transaction_stating_no_canadian_figure.txt')
SHARES_SOLD_BEFORE_ANY_WERE_BOUGHT = (
    FIXTURES + 'usd_moved_out_of_an_empty_account_then_shares_sold_before_any_were_bought.txt')
INCOME_GIVING_ITS_OWN_GUID = (
    FIXTURES + 'usd_moved_out_of_an_empty_account_then_income_into_it_giving_its_own_guid.txt')
SHARES_BOUGHT = FIXTURES +'usd_moved_out_of_an_empty_account_then_shares_bought.txt'
FEE_EDITED_INTO_A_SALE = (
    FIXTURES + 'usd_moved_out_of_an_empty_account_then_shares_bought_fee_edited_into_a_sale.txt')
IN_CANADIAN_DOLLARS = FIXTURES +'usd_moved_out_of_an_empty_account_then_income_in_canadian_dollars.txt'
INCOME_EDITED_INTO_A = FIXTURES + 'usd_moved_out_of_an_empty_account_then_income_edited_into_a.txt'
CARD_OVERPAID_FOR_THE_EDIT = FIXTURES + 'a_usd_card_overpaid_then_its_travel_edited_onto_it.txt'
TRAVEL_CHARGED_TO_THE_CARD = (
    FIXTURES + 'a_usd_card_overpaid_then_its_travel_edited_onto_it_travel_charged_to_the_card.txt')
A_CARD_OWING_300_PAID_500 = FIXTURES +'a_usd_card_owing_300_paid_500_from_c.txt'
A_CARD_OWING_300_PAID_500_VALUED_AT_THE_DAYS_RATE = (
    FIXTURES + 'a_usd_card_owing_300_paid_500_from_c_valued_at_the_days_rate.txt')
A_CARD_OWING_300_PAID_500_FROM_B_AND_C =FIXTURES + 'a_usd_card_owing_300_paid_500_from_b_and_c.txt'
MOVED_BESIDE_A_BORROWING = FIXTURES + 'usd_moved_from_c_to_b_beside_a_borrowing_on_card_2.txt'
REFILLED_PAST_ZERO = FIXTURES + 'usd_moved_out_of_an_empty_account_then_refilled_past_zero.txt'
A_DEPOSIT_INTO_IT = FIXTURES +'usd_moved_out_of_an_empty_account_then_a_deposit_into_it.txt'
CHARGED_AND_REFUNDED = FIXTURES + 'a_usd_card_charged_and_refunded_in_one_transaction.txt'
REFUNDED_AND_CHARGED = FIXTURES + 'a_usd_card_refunded_and_charged_in_one_transaction.txt'
BALANCE_TRANSFER = FIXTURES + 'a_usd_card_balance_transferred_to_another_card.txt'
INCOME_VALUED_AT_THE_DAYS_RATE = (
    FIXTURES + 'usd_moved_out_of_an_empty_account_then_income_into_it_valued_at_the_days_rate.txt')
INCOME_VALUED_BELOW_WHAT_IT_REPAID = (
    FIXTURES
    + 'usd_moved_out_of_an_empty_account_then_income_into_it_valued_below_what_it_repaid.txt')
BOUGHT_INTO_A_WITH_HONG_KONG_DOLLARS = (
    FIXTURES + 'usd_moved_out_of_an_empty_account_then_bought_into_it_with_hong_kong_dollars.txt')
A_DEPOSIT_DATED_BEFORE_THE_TRANSFER = (
    FIXTURES + 'usd_moved_out_of_an_empty_account_then_a_deposit_dated_before_it.txt')
BALANCE_TRANSFER_OF_MORE_THAN_OWED = (
    FIXTURES + 'a_usd_card_balance_transfer_of_more_than_the_card_owes.txt')

AS_OF = date(2034, 2, 28)


def _book(tmp_path, *layers):
    """The book, with each layer imported on top of it in turn."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    made = _run(runner, 'import', '--new', str(book), THE_BOOK)
    assert made.exit_code == 0 and 'Errors:       0' in made.output, made.output
    for layer in layers:
        done = _run(runner, 'import', str(book), layer)
        assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    return book


def _read(book):
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        rows = list(cost_basis_items_by_currency_and_side(repo.book, AS_OF))
        holdings = list(foreign_currency_account_balances(repo.book))
    finally:
        repo.close()
    return rows, holdings


def _bases(book):
    """Every cost basis with something left in it: account, side, balance, cost."""
    rows, _ = _read(book)
    return sorted((row['account'], row['side'], row['balance'], row['cost'])
                  for row in rows if row['balance'])


def _in_step(book):
    """Per side, the cost bases hold what the accounts hold and owe."""
    rows, holdings = _read(book)
    for side, sign in (('asset', 1), ('liability', -1)):
        bases = sum((row['balance'] for row in rows if row['side'] == side), Fraction(0))
        accounts = sum((sign * held['balance'] for held in holdings
                        if sign * held['balance'] > 0), Fraction(0))
        assert bases == accounts, (side, bases, accounts, rows)


def _what_each_split_brought_in(book, account):
    """Each split on the account, by amount, with what the import recorded it brought in."""
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        return sorted(
            (Fraction(split.GetAmount().num(), split.GetAmount().denom()),
             get_custom_metadata(split).get('cost_basis_brought_in'))
            for split in iter_splits(repo.book)
            if get_account_full_name(split.GetAccount()) == account)
    finally:
        repo.close()


def _consistent(book):
    checked = CliRunner().invoke(cli, ['--verify-integrity', str(book)])
    assert checked.exit_code == 0, checked.output


def _sheet(book, as_of='2034-02-01'):
    """The balance sheet's figures, by key, for the keys a line gives once."""
    page = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', as_of).output
    figures = {}
    for line in page.splitlines():
        key, _, rest = line.strip().partition(': ')
        if key in ('total_assets', 'total_liabilities_and_equity',
                   'total_realized_gains', 'unrealized_gains_fx',
                   'unrealized_gains_liabilities_fx'):
            figures[key] = rest.split()[0]
    assert figures['total_assets'] == figures['total_liabilities_and_equity'], page
    return figures


C_BOUGHT = ('Assets:USD C', 'asset', Fraction(1000), Fraction(13, 10))
A_OWES = ('Assets:USD A', 'liability', Fraction(500), Fraction(27, 20))
B_HOLDS = ('Assets:USD B', 'asset', Fraction(500), Fraction(27, 20))


class TestMovedOutOfAnEmptyAccount:
    """500.00 USD from an empty A to B is a borrowing: a cost basis on each side."""

    def test_a_owes_and_b_holds_each_at_the_transfers_rate(self, tmp_path):
        book = _book(tmp_path)

        assert _bases(book) == sorted([C_BOUGHT, A_OWES, B_HOLDS])
        _in_step(book)
        _consistent(book)

    def test_the_owed_side_is_revalued_with_the_held_side(self, tmp_path):
        """At 1.40 B's 500.00 gains 25.00 and A's 500.00 owed loses 25.00."""
        figures = _sheet(_book(tmp_path))

        assert figures['unrealized_gains_liabilities_fx'] == '-25.00'
        assert figures['unrealized_gains_fx'] == '100.00'
        assert figures['total_realized_gains'] == '0.00'


class TestMoreMovedOutOfAnAccountThanItHolds:
    """1,200.00 USD from C holding 1,000.00: 1,000.00 moved, 200.00 borrowed."""

    def test_only_the_part_past_zero_opens_a_cost_basis_on_each_side(self, tmp_path):
        book = _book(tmp_path, MORE_THAN_C_HOLDS)

        assert _bases(book) == sorted([
            C_BOUGHT, A_OWES, B_HOLDS,
            ('Assets:USD B', 'asset', Fraction(200), Fraction(7, 5)),
            ('Assets:USD C', 'liability', Fraction(200), Fraction(7, 5)),
        ])
        _in_step(book)
        _consistent(book)


class TestWhatTheBorrowingBroughtInSold:
    """B's 500.00 sold at 1.40 draws on B's cost basis and leaves C's whole."""

    def test_c_keeps_its_cost_basis(self, tmp_path):
        book = _book(tmp_path, SOLD)

        assert _bases(book) == sorted([C_BOUGHT, A_OWES])
        _in_step(book)
        _consistent(book)

    def test_the_sale_realizes_what_the_borrowed_dollars_made(self, tmp_path):
        figures = _sheet(_book(tmp_path, SOLD))

        assert figures['total_realized_gains'] == '25.00'
        assert figures['unrealized_gains_liabilities_fx'] == '-25.00'
        assert figures['unrealized_gains_fx'] == '75.00'


class TestTheEmptyAccountRefilled:
    """A refilled from C repays what A owes: each side's cost basis drawn down."""

    def test_the_owed_cost_basis_is_drawn_to_nothing(self, tmp_path):
        book = _book(tmp_path, REFILLED)

        assert _bases(book) == sorted([
            ('Assets:USD C', 'asset', Fraction(500), Fraction(13, 10)),
            B_HOLDS,
        ])
        _in_step(book)
        _consistent(book)

    def test_written_wholly_in_us_dollars_it_is_refused(self, tmp_path):
        """No Canadian split can state the 25.00 between the two cost bases."""
        done = TestIncomePaidIntoTheEmptyAccountAcrossZero._imported_onto_the_book(
            tmp_path, REFILLED_STATING_NO_CANADIAN_FIGURE)

        assert 'Errors:       1' in done.output, done.output
        assert ('this transaction pays off 500.00 USD owed, which cost 1.35 CAD/USD, '
                'with 500.00 USD held, which cost 1.3 CAD/USD') in done.output, done.output

    def test_the_repayment_realizes_both_differences(self, tmp_path):
        """50.00 on C's dollars used at 1.40, less 25.00 on A's debt repaid at 1.40."""
        figures = _sheet(_book(tmp_path, REFILLED))

        assert figures['total_realized_gains'] == '25.00'
        assert figures['unrealized_gains_liabilities_fx'] == '0.00'
        assert figures['unrealized_gains_fx'] == '75.00'


class TestIncomePaidIntoTheEmptyAccountAcrossZero:
    """1,000.00 USD into A at −500.00, one split: 500.00 repaid, 500.00 held."""

    def test_the_owed_cost_basis_goes_and_a_held_one_opens_for_the_rest(self, tmp_path):
        book = _book(tmp_path, INCOME)

        assert _bases(book) == sorted([
            C_BOUGHT, B_HOLDS,
            ('Assets:USD A', 'asset', Fraction(500), Fraction(7, 5)),
        ])
        _in_step(book)
        _consistent(book)

    def test_repaying_the_debt_at_1_40_realizes_a_loss(self, tmp_path):
        figures = _sheet(_book(tmp_path, INCOME))

        assert figures['total_realized_gains'] == '-25.00'
        assert figures['unrealized_gains_liabilities_fx'] == '0.00'
        assert figures['unrealized_gains_fx'] == '125.00'

    def test_valued_at_the_days_rate_throughout_it_is_refused(self, tmp_path):
        """1,400.00, the register's figure, would cost the 500.00 held at 1.45."""
        done = self._imported_onto_the_book(tmp_path, INCOME_VALUED_AT_THE_DAYS_RATE)

        assert 'Errors:       1' in done.output, done.output
        assert ('this split repays 500.00 USD from cost basis '
                '0a0a0000000000000000000000000001 at 1.35 CAD/USD and brings '
                '500.00 USD in at the 1.4 CAD/USD it came at, i.e. '
                '1375.00 CAD, but is valued at 1400.00 CAD') in done.output, done.output

    def test_valued_below_what_it_repaid_it_is_refused(self, tmp_path):
        """600.00 would leave the 500.00 brought in a cost below nothing."""
        done = self._imported_onto_the_book(tmp_path, INCOME_VALUED_BELOW_WHAT_IT_REPAID)

        assert 'Errors:       1' in done.output, done.output
        assert 'i.e. 1375.00 CAD, but is valued at 600.00 CAD' in done.output, done.output

    def test_bought_with_another_currency_it_is_costed_from_its_value(self, tmp_path):
        """The transaction's CAD figures price the HKD, so the value is the file's statement."""
        book = _book(tmp_path, BOUGHT_INTO_A_WITH_HONG_KONG_DOLLARS)

        assert ('Assets:USD A', 'asset', Fraction(500), Fraction(7, 5)) in _bases(book)
        assert A_OWES not in _bases(book)

    @staticmethod
    def _imported_onto_the_book(tmp_path, layer):
        runner = CliRunner()
        book = tmp_path / 'book.gnucash'
        _run(runner, 'import', '--new', str(book), THE_BOOK)
        return _run(runner, 'import', str(book), layer)

    def test_giving_no_cost_basis_is_refused(self, tmp_path):
        runner = CliRunner()
        book = tmp_path / 'book.gnucash'
        _run(runner, 'import', '--new', str(book), THE_BOOK)
        done = _run(runner, 'import', str(book), INCOME_GIVING_NO_COST_BASIS)

        assert 'Errors:       1' in done.output, done.output
        assert ('this transaction spends 500.00 USD the book owed, which draws '
                'down a cost basis, but no split says which one') in done.output, done.output


class TestWhatASplitBroughtInIsTheImportsToRead:
    def test_a_guid_the_book_does_not_hold_is_refused_for_the_guid(self, tmp_path):
        """Income across zero giving an unknown guid: nothing prices what it brought in."""
        runner = CliRunner()
        book = tmp_path / 'book.gnucash'
        _run(runner, 'import', '--new', str(book), THE_BOOK)
        done = _run(runner, 'import', str(book), INCOME_GIVING_A_GUID_THE_BOOK_DOES_NOT_HOLD)

        assert 'Errors:       1' in done.output, done.output
        assert ("cost_basis_split_guid '0a0a0000000000000000000000000099' "
                'matches no split in the book') in done.output, done.output

    def test_a_split_giving_its_own_guid_is_refused_for_the_guid(self, tmp_path):
        """What it brought in is costed from what it repays, which is itself."""
        done = TestIncomePaidIntoTheEmptyAccountAcrossZero._imported_onto_the_book(
            tmp_path, INCOME_GIVING_ITS_OWN_GUID)

        assert 'Errors:       1' in done.output, done.output
        assert ("cost_basis_split_guid '0a0a0000000000000000000000000009' matches a "
                'split that is no USD cost basis') in done.output, done.output
        assert 'recursion' not in done.output, done.output

    def test_a_file_stating_it_is_refused(self, tmp_path):
        """`cost_basis_brought_in:` is the import's own record, and no file may state it."""
        done = TestIncomePaidIntoTheEmptyAccountAcrossZero._imported_onto_the_book(
            tmp_path, BOUGHT_STATING_WHAT_IT_BROUGHT_IN)

        assert 'Errors:       1' in done.output, done.output
        assert ("the split on 'Assets:USD C': `cost_basis_brought_in:` is not a key "
                'a file may state') in done.output, done.output

    def test_a_file_stating_it_on_a_receivable_is_refused(self, tmp_path):
        """A split the import passes over would keep it, and open a cost basis of 1.00."""
        done = TestIncomePaidIntoTheEmptyAccountAcrossZero._imported_onto_the_book(
            tmp_path, A_RECEIVABLE_STATING_WHAT_IT_BROUGHT_IN)

        assert 'Errors:       1' in done.output, done.output
        assert ("the split on 'Assets:Accounts Receivable USD': "
                '`cost_basis_brought_in:` is not a key') in done.output, done.output

    def test_it_is_read_the_same_whatever_order_the_file_gives_the_splits(self, tmp_path):
        """A charge and a refund on one card, in either order: neither crosses zero."""
        read = []
        for order, ledger in enumerate((CHARGED_AND_REFUNDED, REFUNDED_AND_CHARGED)):
            place = tmp_path / str(order)
            place.mkdir()
            read.append(_what_each_split_brought_in(_book(place, ledger), 'Liabilities:USD Card'))

        assert read[0] == read[1], read
        assert read[0] == [(Fraction(-150), None), (Fraction(100), None)], read[0]

    def test_an_edit_that_stops_a_split_crossing_zero_takes_the_record_off(self, tmp_path):
        """150.00 of fees from savings holding 100.00 brought 50.00 in owed; corrected to 80.00, none."""
        runner = CliRunner()
        book = tmp_path / 'book.gnucash'
        _run(runner, 'import', '--new', str(book), A_FEE_WITH_NO_COST_BASIS)
        assert _what_each_split_brought_in(book, 'Assets:USD Savings') == [
            (Fraction(-150), '50.00'), (Fraction(100), None)]

        done = _run(runner, 'import', str(book), THE_FEES_CORRECTED, '--strategy', 'update')

        assert done.exit_code == 0, done.output
        assert _what_each_split_brought_in(book, 'Assets:USD Savings') == [
            (Fraction(-80), None), (Fraction(100), None)]


def test_a_repaid_cost_basis_deleted_in_gnucash_leaves_the_book_readable(tmp_path):
    """The transfer that opened A's owed cost basis deleted in GnuCash itself.

    Nothing in GnuCash checks what draws on a split before deleting its
    transaction, so the income that crossed zero then gives a guid matching
    nothing. What it brought in is costed from the cost basis it repaid, so
    it has no cost and is no cost basis, and `fx-balances` lists what is left.
    """
    book = _book(tmp_path, INCOME)
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        transfer = next(split.GetParent() for split in iter_splits(repo.book)
                        if split.GetParent().GetDescription()
                        == 'Move 500.00 USD from an empty A to B')
        transfer.BeginEdit()
        transfer.Destroy()
        transfer.CommitEdit()
        repo.save()
    finally:
        repo.close()

    listing = CliRunner().invoke(cli, ['fx-balances', str(book)])

    assert listing.exit_code == 0, listing.output
    assert _bases(book) == [C_BOUGHT], _bases(book)


def test_a_deposit_imported_after_a_later_transfer_out_is_reported(tmp_path):
    """What the transfer brought in was read when it was imported, and is not read again.

    A deposit into A dated before the transfer out of it, imported after, means
    by date the transfer borrowed nothing. Its recorded 500.00 owed on A and
    500.00 held on B stay, the deposit opens 500.00 held of its own, and
    `--verify-integrity` reports both sides. Q-047 records it as known.
    """
    book = _book(tmp_path, A_DEPOSIT_DATED_BEFORE_THE_TRANSFER)
    checked = CliRunner().invoke(cli, ['--verify-integrity', str(book)])

    assert checked.exit_code == 1, checked.output
    assert ('the USD cost bases on the asset side hold 2,000.00, and the book '
            'holds 1,500.00') in checked.output, checked.output
    assert ('the USD cost bases on the liability side hold 500.00, and the book '
            'owes 0.00') in checked.output, checked.output


def test_shares_sold_before_any_were_bought_open_no_cost_basis(tmp_path):
    """A share account below zero is not read as owing shares: this is currency's rule."""
    book = _book(tmp_path, SHARES_SOLD_BEFORE_ANY_WERE_BOUGHT)

    assert _bases(book) == sorted([C_BOUGHT, A_OWES, B_HOLDS])
    assert _what_each_split_brought_in(book, 'Assets:AMZN') == [(Fraction(-10), None)]


class TestABookImportedBeforeABalancePastZeroHadASide:
    """An account an earlier import left below zero has no owed cost basis.

    The transfer out of an empty A is put back as an earlier import left it:
    nothing recorded on its splits and no cost basis opened for either.
    """

    @staticmethod
    def _as_an_earlier_import_left_it(tmp_path):
        book = _book(tmp_path)
        repo = GnuCashRepository(str(book))
        repo.open(mode=SessionMode.NORMAL)
        try:
            transfer = next(split.GetParent() for split in iter_splits(repo.book)
                            if split.GetParent().GetDescription()
                            == 'Move 500.00 USD from an empty A to B')
            transfer.BeginEdit()
            for split in transfer.GetSplitList():
                set_custom_metadata(split, {
                    key: value for key, value in get_custom_metadata(split).items()
                    if key not in ('cost_basis_brought_in', 'cost_basis_balance')})
            transfer.CommitEdit()
            repo.save()
        finally:
            repo.close()
        assert _bases(book) == [C_BOUGHT], _bases(book)
        return book

    def test_a_deposit_into_the_account_brings_in_only_what_is_past_zero(self, tmp_path):
        """1,000.00 into A at −500.00 opens 500.00 held; the 500.00 repaid had no cost basis."""
        book = self._as_an_earlier_import_left_it(tmp_path)
        done = _run(CliRunner(), 'import', str(book), A_DEPOSIT_INTO_IT)

        assert 'Errors:       0' in done.output, done.output
        assert _bases(book) == sorted([
            C_BOUGHT, ('Assets:USD A', 'asset', Fraction(500), Fraction(7, 5))])

    def test_brought_forward_through_its_export_the_deposit_gives_the_owed_cost_basis(
            self, tmp_path):
        """Rebuilt, the transfer opens A's owed cost basis, and the deposit repaying it must give it."""
        book = self._as_an_earlier_import_left_it(tmp_path)
        runner = CliRunner()
        _run(runner, 'import', str(book), A_DEPOSIT_INTO_IT)
        exported = tmp_path / 'exported.txt'
        assert _run(runner, 'export', str(book), str(exported)).exit_code == 0

        fresh = tmp_path / 'fresh.gnucash'
        rebuilt = _run(runner, 'import', '--new', str(fresh), str(exported))

        assert 'Errors:       1' in rebuilt.output, rebuilt.output
        assert ('this transaction spends 500.00 USD the book owed, which draws down '
                'a cost basis, but no split says which one') in rebuilt.output, rebuilt.output
        assert A_OWES in _bases(fresh), _bases(fresh)


def test_a_book_keeping_no_cost_basis_moves_its_money_with_a_fee_as_it_likes(tmp_path):
    """A transfer with a fee in one transaction touches no cost basis, and is imported."""
    book = tmp_path / 'book.gnucash'
    done = _run(CliRunner(), 'import', '--new', str(book), A_FEE_WITH_NO_COST_BASIS)

    assert done.exit_code == 0, done.output
    assert 'Errors:       0' in done.output, done.output


class TestACardOverpaidThenItsCreditSpent:
    """A card at +200.00 holds 200.00; charging it back to 0.00 spends that."""

    def test_the_credit_is_a_held_cost_basis_spent_to_nothing(self, tmp_path):
        book = _book(tmp_path, THE_CARD)

        assert _bases(book) == sorted([
            ('Assets:USD C', 'asset', Fraction(800), Fraction(13, 10)),
            A_OWES, B_HOLDS,
        ])
        _in_step(book)
        _consistent(book)

    def test_spending_the_credit_realizes_what_the_dollars_made(self, tmp_path):
        figures = _sheet(_book(tmp_path, THE_CARD))

        assert figures['total_realized_gains'] == '20.00'
        assert figures['unrealized_gains_liabilities_fx'] == '-25.00'
        assert figures['unrealized_gains_fx'] == '80.00'


class TestACardBalanceTransferredToAnotherCard:
    """A balance transfer moves what is owed from one liability to another."""

    CARD_OWES = ('Liabilities:USD Card', 'liability', Fraction(300), Fraction(27, 20))

    def test_the_whole_balance_moves_within_the_owed_side(self, tmp_path):
        """No guid, nothing drawn down, nothing opened: the owed side owes what it owed."""
        book = _book(tmp_path, BALANCE_TRANSFER)

        assert _bases(book) == sorted([C_BOUGHT, A_OWES, B_HOLDS, self.CARD_OWES])
        _in_step(book)
        _consistent(book)

    def test_more_than_the_card_owes_is_a_borrowing_for_the_rest(self, tmp_path):
        """500.00 off a card owing 300.00: 300.00 moves, 200.00 owed and 200.00 held."""
        book = _book(tmp_path, BALANCE_TRANSFER_OF_MORE_THAN_OWED)

        assert _bases(book) == sorted([
            C_BOUGHT, A_OWES, B_HOLDS, self.CARD_OWES,
            ('Liabilities:USD Card', 'asset', Fraction(200), Fraction(7, 5)),
            ('Liabilities:USD Card 2', 'liability', Fraction(200), Fraction(7, 5)),
        ])
        _in_step(book)
        _consistent(book)


class TestPayingOffMoreThanIsOwed:
    """The mirror of a borrowing: what is repaid draws down, and the rest only moves."""

    def test_a_card_owing_300_paid_500_draws_c_down_by_300(self, tmp_path):
        """300.00 repaid from C and the card's cost bases, 200.00 moved onto the card's credit."""
        book = _book(tmp_path, A_CARD_OWING_300_PAID_500)

        assert _bases(book) == sorted([
            A_OWES, B_HOLDS, ('Assets:USD C', 'asset', Fraction(700), Fraction(13, 10))])
        _in_step(book)
        _consistent(book)
        assert _sheet(book)['total_realized_gains'] == '15.00'

    def test_the_cards_split_valued_at_the_days_rate_is_refused(self, tmp_path):
        """300.00 repaid at 1.35 and 200.00 moved from C at 1.30 is 665.00, not 700.00."""
        done = TestIncomePaidIntoTheEmptyAccountAcrossZero._imported_onto_the_book(
            tmp_path, A_CARD_OWING_300_PAID_500_VALUED_AT_THE_DAYS_RATE)

        assert 'Errors:       1' in done.output, done.output
        assert ('this split repays 300.00 USD from cost basis '
                '0a0a0000000000000000000000000008 at 1.35 CAD/USD and brings '
                '200.00 USD in at the 1.3 CAD/USD') in done.output, done.output
        assert 'i.e. 665.00 CAD, but is valued at 700.00 CAD' in done.output, done.output

    def test_paid_from_two_cost_bases_it_is_refused(self, tmp_path):
        """Nothing says which of the two the 200.00 that only moved came out of."""
        done = TestIncomePaidIntoTheEmptyAccountAcrossZero._imported_onto_the_book(
            tmp_path, A_CARD_OWING_300_PAID_500_FROM_B_AND_C)

        assert 'Errors:       1' in done.output, done.output
        assert ('this transaction pays off 300.00 USD owed and moves 200.00 USD '
                'within the held side, and 2 splits give a cost basis on the held '
                'side') in done.output, done.output

    def test_a_transfer_beside_a_borrowing_on_another_account_is_refused(self, tmp_path):
        """No account crosses zero: it is a transfer sharing a transaction with an arrival."""
        done = TestIncomePaidIntoTheEmptyAccountAcrossZero._imported_onto_the_book(
            tmp_path, MOVED_BESIDE_A_BORROWING)

        assert 'Errors:       1' in done.output, done.output
        assert ('this transaction moves 1000.00 USD between accounts on the held '
                'side, and 200.00 USD arrives on that side as well') in done.output, done.output

    def test_an_overdrawn_account_refilled_past_zero_draws_c_down_by_what_it_owed(
            self, tmp_path):
        """1,000.00 into A at −500.00 from C: 500.00 repaid, 500.00 moved."""
        book = _book(tmp_path, REFILLED_PAST_ZERO)

        assert _bases(book) == sorted([
            B_HOLDS, ('Assets:USD C', 'asset', Fraction(500), Fraction(13, 10))])
        _in_step(book)
        _consistent(book)
        assert _sheet(book)['total_realized_gains'] == '25.00'


class TestAnEditInPlace:
    """An edit runs none of a disposal's checks, so one that adds a disposal is refused."""

    @staticmethod
    def _edited(tmp_path, *layers_then_edit):
        *layers, edit = layers_then_edit
        book = _book(tmp_path, IN_CANADIAN_DOLLARS, *layers)
        return _run(CliRunner(), 'import', str(book), edit, '--strategy', 'update')

    def test_income_edited_into_an_account_owing_is_refused(self, tmp_path):
        """1,000.00 into A at −500.00 repays 500.00 owed, which a cost basis stands for."""
        done = self._edited(tmp_path, INCOME_EDITED_INTO_A)

        assert done.exit_code != 0, done.output
        assert ('this edit spends 500.00 USD the book owed, which a cost basis '
                'stands for') in done.output, done.output

    def test_a_fee_edited_into_a_sale_of_shares_is_refused(self, tmp_path):
        """A share's side is its account's type, and a sale of 5 of 10 spends 5 held."""
        book = _book(tmp_path, SHARES_BOUGHT)
        done = _run(CliRunner(), 'import', str(book), FEE_EDITED_INTO_A_SALE,
                    '--strategy', 'update')

        assert done.exit_code != 0, done.output
        assert 'this edit spends 5.0000 AMZN the book held' in done.output, done.output

    def test_travel_edited_onto_a_card_holding_a_credit_is_refused(self, tmp_path):
        """200.00 charged to a card holding 200.00 spends what it held."""
        done = self._edited(tmp_path, CARD_OVERPAID_FOR_THE_EDIT, TRAVEL_CHARGED_TO_THE_CARD)

        assert done.exit_code != 0, done.output
        assert ('this edit spends 200.00 USD the book held, which a cost basis '
                'stands for') in done.output, done.output


class TestTheExportRebuildsTheSameCostBases:
    """Each book's export imports into a new book holding the same cost bases."""

    def _rebuilt(self, tmp_path, *layers):
        book = _book(tmp_path, *layers)
        runner = CliRunner()
        exported = tmp_path / 'exported.txt'
        assert _run(runner, 'export', str(book), str(exported)).exit_code == 0
        fresh = tmp_path / 'fresh.gnucash'
        rebuilt = _run(runner, 'import', '--new', str(fresh), str(exported))
        assert rebuilt.exit_code == 0 and 'Errors:       0' in rebuilt.output, rebuilt.output
        return book, fresh

    def test_the_transfer_keeps_its_currency_and_its_amounts(self, tmp_path):
        """A transaction in CAD whose splits are all USD states its currency.

        Written without it, the import read the transfer as a US dollar
        transaction and each split's 675.00 CAD value as its amount, so the
        rebuilt book moved 675.00 USD where the book had moved 500.00.
        """
        book, fresh = self._rebuilt(tmp_path)
        exported = (tmp_path / 'exported.txt').read_text()
        transfer = exported[exported.index('"Move 500.00 USD from an empty A to B"'):]
        transfer = transfer[:transfer.index('\n2034')] if '\n2034' in transfer else transfer

        assert '\tcurrency.mnemonic: "CAD"' in transfer, transfer
        assert _bases(fresh) == _bases(book)

    def test_after_income_across_zero(self, tmp_path):
        book, fresh = self._rebuilt(tmp_path, INCOME)

        assert _bases(fresh) == _bases(book)

    def test_after_the_refill(self, tmp_path):
        book, fresh = self._rebuilt(tmp_path, REFILLED)

        assert _bases(fresh) == _bases(book)

    def test_after_the_card_credit_is_spent(self, tmp_path):
        book, fresh = self._rebuilt(tmp_path, THE_CARD)

        assert _bases(fresh) == _bases(book)
