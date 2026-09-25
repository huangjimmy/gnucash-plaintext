"""A split draws on a cost basis by its position in the file being imported, so a transaction spends currency it brings in (Q-050).

`cost_basis_split_guid: $transactions_to_import[n].splits[m].guid$`, unquoted,
stands where the guid of the split a cost basis sits on would go, and is
resolved to the guid GnuCash assigns that split. The reported case is E1: a
book with no cost basis, whose first import brings 2,720.00 USD in and takes a
0.72 USD fee out of it in the same transaction. Each case below is one of the
Q-050 scenarios, and its fixture says what the book it leaves holds.
"""

import re
from datetime import date
from fractions import Fraction

import pytest
from click.testing import CliRunner

from infrastructure.gnucash.kvp import get_custom_metadata
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import (
    COST_BASIS_SPLIT_KEY,
    cost_basis_items_by_currency_and_side,
    iter_splits,
)
from tests.conftest import _run

FIXTURES = 'tests/fixtures/'
ACCOUNTS = FIXTURES + 'accounts_for_spending_currency_its_own_import_brings_in.txt'
HELD_BEFORE = FIXTURES + 'usd_bought_before_the_import_that_brings_more_in.txt'


def _import(tmp_path, *files, extra=()):
    """A book with the accounts, each file imported onto it; the last run's result."""
    book = tmp_path / 'book.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(book), ACCOUNTS)
    assert made.exit_code == 0, made.output
    done = None
    for name in files:
        done = _run(CliRunner(), 'import', str(book), FIXTURES + name, *extra)
    return book, done


def _bases(book):
    """Each cost basis as (account, currency, side, balance)."""
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        return sorted((row['account'], row['currency'], row['side'], row['balance'])
                      for row in cost_basis_items_by_currency_and_side(
                          repo.book, date(2026, 12, 31)))
    finally:
        repo.close()


def _picks(book):
    """What each split drawing on a cost basis keeps as the guid it gives."""
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        return [str(get_custom_metadata(split)[COST_BASIS_SPLIT_KEY])
                for split in iter_splits(repo.book)
                if get_custom_metadata(split).get(COST_BASIS_SPLIT_KEY)]
    finally:
        repo.close()


def _sound(book):
    checked = _run(CliRunner(), 'fx-balances', str(book), '--verify-costs')
    assert checked.exit_code == 0 and 'warning' not in checked.output, checked.output


def _imported(done):
    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output


class TestTheSameTransaction:
    def test_the_reported_fee_draws_on_the_dollars_its_own_transaction_brings_in(self, tmp_path):
        """E1: 2,720.00 USD in, 0.72 out: 2,719.28 left, and the book is sound."""
        book, done = _import(tmp_path, 'a_usd_arrival_and_the_fee_drawn_on_it_in_one_transaction.txt')

        _imported(done)
        assert _bases(book) == [('Assets:Wise USD', 'USD', 'asset', Fraction('2719.28'))]
        _sound(book)

    def test_what_is_kept_is_the_guid_and_never_the_variable(self, tmp_path):
        book, _ = _import(tmp_path, 'a_usd_arrival_and_the_fee_drawn_on_it_in_one_transaction.txt')

        assert [re.fullmatch('[0-9a-f]{32}', pick) is not None for pick in _picks(book)] == [True]

    def test_a_fee_and_the_rest_sent_on_spend_the_arrival_to_nothing(self, tmp_path):
        """E2: the last of it valued at what is left, 3,798.99."""
        book, done = _import(tmp_path, 'a_usd_arrival_its_fee_and_the_rest_sent_on_in_one_transaction.txt')

        _imported(done)
        assert _bases(book) == [('Assets:Wise USD', 'USD', 'asset', Fraction(0))]
        _sound(book)

    def test_a_transaction_stated_in_us_dollars(self, tmp_path):
        """E3: the reported arrival as a US dollar statement writes it."""
        book, done = _import(tmp_path, 'a_usd_arrival_stated_in_usd_and_the_fee_drawn_on_it_in_one_transaction.txt')

        _imported(done)
        assert _bases(book) == [('Assets:Wise USD', 'USD', 'asset', Fraction('2719.28'))]
        _sound(book)

    def test_currency_owed_and_part_of_it_repaid(self, tmp_path):
        """E4: 2.00 USD charged to a card, 1.00 paid back: 1.00 still owed."""
        book, done = _import(tmp_path, 'usd_owed_on_a_card_and_part_of_it_repaid_in_one_transaction.txt')

        _imported(done)
        assert _bases(book) == [('Liabilities:USD Card', 'USD', 'liability', Fraction('1.00'))]
        _sound(book)

    def test_a_conversion_opening_a_cost_basis_its_own_transaction_draws_on(self, tmp_path):
        """E5: 1,720.00 USD and 899.00 EUR left."""
        book, done = _import(
            tmp_path, 'a_usd_arrival_part_converted_to_euros_and_a_euro_fee_in_one_transaction.txt')

        _imported(done)
        assert _bases(book) == [('Assets:Wise EUR', 'EUR', 'asset', Fraction('899.00')),
                                ('Assets:Wise USD', 'USD', 'asset', Fraction('1720.00'))]
        _sound(book)

    def test_under_atomic(self, tmp_path):
        """E6: as E1, committed."""
        book, done = _import(tmp_path, 'a_usd_arrival_and_the_fee_drawn_on_it_in_one_transaction.txt',
                             extra=('--atomic',))

        _imported(done)
        assert _bases(book) == [('Assets:Wise USD', 'USD', 'asset', Fraction('2719.28'))]


class TestAnotherTransaction:
    def test_a_transaction_above(self, tmp_path):
        """E8: the same book as E1."""
        book, done = _import(tmp_path, 'a_usd_arrival_and_the_fee_drawn_on_it_in_the_next_transaction.txt')

        _imported(done)
        assert _bases(book) == [('Assets:Wise USD', 'USD', 'asset', Fraction('2719.28'))]
        _sound(book)

    def test_a_transaction_the_import_refused_gives_no_guid(self, tmp_path):
        """E18: the arrival's transaction is refused, and the fee giving its position is too."""
        book, done = _import(
            tmp_path, 'a_fee_giving_the_position_of_a_transaction_the_import_refused.txt')

        assert done.exit_code != 0, done.output
        assert 'Errors:       2' in done.output, done.output
        assert ('split 1 gives $transactions_to_import[0].splits[0].guid$, and '
                'transaction 0 of the file was not imported, so no split of it has a '
                'guid to give') in done.output, done.output
        assert _bases(book) == []

    def test_a_transaction_refused_after_its_own_position_resolved_gives_no_guid(self, tmp_path):
        """E18: a transaction refused part way through resolving its positions keeps no guids."""
        book, done = _import(
            tmp_path,
            'a_fee_giving_the_position_of_a_transaction_refused_after_its_positions_resolved.txt')

        assert done.exit_code != 0, done.output
        assert 'Errors:       3' in done.output, done.output
        assert ('split 1 gives $transactions_to_import[1].splits[0].guid$, and '
                'transaction 1 of the file was not imported') in done.output, done.output
        assert 'matches no split in the book' not in done.output, done.output
        assert _bases(book) == []

    def test_a_transaction_passed_over_whose_line_gives_no_guid(self, tmp_path):
        """E19: the arrival is already in the book, and the file does not say which split it is.

        The book holds the arrival from an earlier import. The file writes it
        again with no `guid:`, so the import passes over it as a duplicate,
        and the fee below giving its position is refused: nothing in the file
        says which split of the book that line is.
        """
        book, first = _import(tmp_path, 'a_usd_arrival_whose_fee_an_edit_adds_the_arrival_alone.txt')
        _imported(first)

        done = _run(CliRunner(), 'import', str(book),
                    FIXTURES + 'a_usd_arrival_and_the_fee_drawn_on_it_in_the_next_transaction.txt')

        assert done.exit_code != 0, done.output
        assert 'Skipped:      1' in done.output, done.output
        assert ('split 1 gives $transactions_to_import[0].splits[0].guid$, and that '
                'transaction was already in the book and its split 0 gives no '
                '`guid:`') in done.output, done.output
        assert _bases(book) == [('Assets:Wise USD', 'USD', 'asset', Fraction('2720.00'))]

    @pytest.mark.parametrize('name', [
        'a_usd_arrival_passed_over_by_its_guid_giving_a_split_guid_the_book_does_not_hold.txt',
        'a_usd_arrival_passed_over_as_a_duplicate_giving_a_split_guid_the_book_does_not_hold.txt',
    ], ids=['by-its-guid', 'as-a-duplicate'])
    def test_a_transaction_passed_over_whose_line_gives_a_guid_it_does_not_hold(self, tmp_path, name):
        """E19: a `guid:` that is no split of the transaction the book holds says no more than none."""
        book, first = _import(tmp_path, 'a_usd_arrival_whose_fee_an_edit_adds_the_arrival_alone.txt')
        _imported(first)

        done = _run(CliRunner(), 'import', str(book), FIXTURES + name)

        assert done.exit_code != 0, done.output
        assert 'Skipped:      1' in done.output, done.output
        assert ('split 1 gives $transactions_to_import[0].splits[0].guid$, and that '
                'transaction was already in the book and its split 0 gives no '
                '`guid:` of a split the book holds for it') in done.output, done.output
        assert 'matches no split in the book' not in done.output, done.output
        assert _bases(book) == [('Assets:Wise USD', 'USD', 'asset', Fraction('2720.00'))]

    def test_a_transaction_below_refuses_the_whole_file(self, tmp_path):
        """E7: refused before any of it is applied; the arrival does not land on its own."""
        book, done = _import(tmp_path, 'a_fee_giving_the_position_of_an_arrival_below_it.txt')

        assert done.exit_code != 0, done.output
        assert ('points at transaction 1, below it, which has not been imported '
                'when this one is') in done.output, done.output
        assert _bases(book) == []


class TestCostBasesTheBookHolds:
    def test_a_fee_paid_from_dollars_held_leaves_the_arrival_whole(self, tmp_path):
        """E11."""
        book, done = _import(tmp_path, HELD_BEFORE.replace(FIXTURES, ''),
                             'a_usd_arrival_with_its_fee_paid_from_dollars_held.txt')

        _imported(done)
        assert _bases(book) == [('Assets:Wise USD', 'USD', 'asset', Fraction('499.28')),
                                ('Assets:Wise USD', 'USD', 'asset', Fraction('2720.00'))]
        _sound(book)

    def test_one_fee_from_each_draws_on_the_one_it_gives(self, tmp_path):
        """E12: a guid and a position in one transaction."""
        book, done = _import(tmp_path, HELD_BEFORE.replace(FIXTURES, ''),
                             'a_usd_arrival_with_one_fee_from_dollars_held_and_one_from_the_arrival.txt')

        _imported(done)
        assert _bases(book) == [('Assets:Wise USD', 'USD', 'asset', Fraction('499.28')),
                                ('Assets:Wise USD', 'USD', 'asset', Fraction('2719.28'))]
        _sound(book)

    def test_one_fee_giving_a_cost_basis_does_not_let_another_give_none(self, tmp_path):
        """E21: E12 with the second fee giving nothing is refused as E10 is."""
        book, done = _import(tmp_path, HELD_BEFORE.replace(FIXTURES, ''),
                             'a_usd_arrival_with_one_fee_from_dollars_held_and_one_giving_no_cost_basis.txt')

        assert done.exit_code != 0, done.output
        assert ('this transaction spends 0.72 USD the book held, which draws down a '
                'cost basis, but no split says which one') in done.output, done.output
        assert 'Split 2 of this transaction, out of Assets:Wise USD' in done.output, done.output
        assert _bases(book) == [('Assets:Wise USD', 'USD', 'asset', Fraction('500.00'))]


class TestAFeeGivingNoCostBasis:
    def _refused(self, tmp_path):
        book, done = _import(tmp_path, 'a_usd_arrival_and_a_fee_giving_no_cost_basis_in_one_transaction.txt')
        assert done.exit_code != 0, done.output
        return book, done.output

    def test_it_is_refused(self, tmp_path):
        """E10: the fee spends dollars, and every spend gives its cost basis."""
        book, output = self._refused(tmp_path)

        assert ('this transaction spends 0.72 USD the book held, which draws down a cost '
                'basis, but no split says which one') in output, output
        assert 'Split 1 of this transaction, out of Assets:Wise USD, can be written' in output, output
        assert _bases(book) == []

    def test_the_refusal_gives_the_arrival_net_of_the_fee(self, tmp_path):
        _, output = self._refused(tmp_path)

        assert ('as part of the exchange spread, not a fee' in output
                and '`Assets:Wise USD 2719.28 USD` with its `value: "3800.00"`' in output), output

    def test_the_refusal_lists_no_cost_basis_of_a_receivable(self, tmp_path):
        """An open invoice's cost basis is drawn down by settling it, so a fee is not offered it."""
        rates = ('--fx-rates', 'tests/fixtures/usd_at_the_invoice_rate_then_lower_at_the_year_end.yaml')
        book, first = _import(
            tmp_path, 'an_open_usd_invoice_before_the_import_that_brings_dollars_in.txt',
            extra=(*rates, '--include-business-objects'))
        _imported(first)
        assert _bases(book) == [
            ('Assets:Accounts Receivable USD', 'USD', 'asset', Fraction('500.00'))]

        done = _run(CliRunner(), 'import', str(book),
                    FIXTURES + 'a_usd_arrival_and_a_fee_giving_no_cost_basis_in_one_transaction.txt',
                    *rates)

        assert done.exit_code != 0, done.output
        assert 'Split 1 of this transaction, out of Assets:Wise USD' in done.output, done.output
        assert 'Accounts Receivable' not in done.output, done.output
        assert _bases(book) == [
            ('Assets:Accounts Receivable USD', 'USD', 'asset', Fraction('500.00'))]

    def test_a_repayment_is_offered_no_net_charge(self, tmp_path):
        """On the owed side a spend repays, with money that left the book, so only its cost basis is asked for."""
        book, done = _import(
            tmp_path, 'usd_owed_on_a_card_and_part_of_it_repaid_giving_no_cost_basis.txt')

        assert done.exit_code != 0, done.output
        assert ('this transaction spends 1.00 USD the book owed, which draws down a '
                'cost basis') in done.output, done.output
        assert 'exchange spread' not in done.output, done.output
        assert ('`cost_basis_split_guid: $transactions_to_import[0].splits[1].guid$` — '
                'the 2.00 USD this transaction brings into Liabilities:USD Card'
                in done.output), done.output
        assert _bases(book) == []

    def test_fees_from_two_accounts_beside_an_arrival_are_refused_as_a_transfer(self, tmp_path):
        """E22: one US dollar account rising while another falls is refused first, as a transfer."""
        book, done = _import(tmp_path, 'a_usd_arrival_and_fees_from_two_accounts_giving_no_cost_basis.txt')

        assert done.exit_code != 0, done.output
        assert 'exchange spread' not in done.output, done.output
        assert ('this transaction moves 5.00 USD between accounts on the held side, '
                'and 2714.28 USD arrives on that side as well') in done.output, done.output
        assert _bases(book) == [('Assets:USD Savings', 'USD', 'asset', Fraction('100.00'))]

    @pytest.mark.parametrize('name', [
        'a_usd_arrival_written_net_of_its_fee.txt',
        'a_usd_arrival_stated_in_usd_written_net_of_its_fee.txt',
    ], ids=['stated-in-cad', 'stated-in-usd'])
    def test_the_arrival_written_as_the_refusal_says_imports(self, tmp_path, name):
        """The first way, followed: 2,719.28 USD arrives with its cost basis, and no fee is kept."""
        book, done = _import(tmp_path, name)

        _imported(done)
        assert _bases(book) == [('Assets:Wise USD', 'USD', 'asset', Fraction('2719.28'))]
        _sound(book)

    def test_stated_in_us_dollars_the_splits_beside_the_arrival_are_valued_at_what_is_kept(
            self, tmp_path):
        """The arrival's value is its amount there, so the splits beside it change instead."""
        book, done = _import(
            tmp_path, 'a_usd_arrival_stated_in_usd_and_a_fee_giving_no_cost_basis_in_one_transaction.txt')

        assert done.exit_code != 0, done.output
        assert ('`Assets:Wise USD 2719.28 USD` with its `value: "2719.28"`, and the '
                'splits beside it valued 2719.28 USD between them in place of 2720.00'
                in done.output), done.output
        assert _bases(book) == []

    def test_the_refusal_gives_the_position_of_the_arrival(self, tmp_path):
        _, output = self._refused(tmp_path)

        assert ('`cost_basis_split_guid: $transactions_to_import[0].splits[0].guid$` — '
                'the 2720.00 USD this transaction brings into Assets:Wise USD') in output, output

    def test_the_refusal_lists_the_cost_bases_the_book_holds(self, tmp_path):
        book, done = _import(tmp_path, HELD_BEFORE.replace(FIXTURES, ''),
                             'a_usd_arrival_and_a_fee_giving_no_cost_basis_in_one_transaction.txt')

        assert done.exit_code != 0, done.output
        assert ('`cost_basis_split_guid: "0e5e00000000000000000000000000b1"` — 500.00 USD '
                'left on Assets:Wise USD') in done.output, done.output


class TestAnEditInPlace:
    def test_a_fee_added_by_an_edit_draws_on_the_arrival(self, tmp_path):
        """E9: the position resolves to the arrival's `guid:`, and the edit is read as new (Q-051)."""
        book, first = _import(tmp_path, 'a_usd_arrival_whose_fee_an_edit_adds_the_arrival_alone.txt')
        _imported(first)

        done = _run(CliRunner(), 'import', str(book),
                    FIXTURES + 'a_usd_arrival_whose_fee_an_edit_adds.txt', '--strategy', 'update')

        _imported(done)
        assert _bases(book) == [('Assets:Wise USD', 'USD', 'asset', Fraction('2719.28'))]
        assert _picks(book) == ['0e5e0000000000000000000000000008']
        _sound(book)

    def test_a_position_at_a_line_giving_no_guid_refuses_the_whole_file(self, tmp_path):
        """E20: found before any transaction is edited, so the first keeps its description."""
        book, first = _import(tmp_path, 'two_usd_arrivals_an_edit_goes_over.txt')
        _imported(first)

        done = _run(CliRunner(), 'import', str(book),
                    FIXTURES + 'an_edit_giving_the_position_of_a_line_that_gives_no_guid.txt',
                    '--strategy', 'update')

        message = done.output + str(done.exception)
        assert done.exit_code != 0, message
        assert ('split 1 gives $transactions_to_import[1].splits[0].guid$, and that '
                'transaction was already in the book and its split 0 gives no '
                '`guid:`') in message, message
        ledger = tmp_path / 'ledger.txt'
        assert _run(CliRunner(), 'export', str(book), str(ledger)).exit_code == 0
        assert 'described again' not in ledger.read_text()


@pytest.mark.parametrize('name, refusal', [
    pytest.param('a_fee_giving_its_own_position.txt',
                 'points at the split that gives it', id='E13-itself'),
    pytest.param('a_fee_giving_a_position_past_the_end.txt',
                 'points past the end: transaction 0 has 4 split(s)', id='E14-past-the-end'),
    pytest.param('a_fee_giving_the_position_of_a_canadian_dollar_split.txt',
                 'is a CAD split but this split sells USD', id='E15-no-cost-basis'),
    pytest.param('a_fee_giving_a_position_in_quotes.txt',
                 "cost_basis_split_guid '$transactions_to_import[0].splits[0].guid$' "
                 'matches no split in the book', id='E16-in-quotes'),
    pytest.param('a_fee_giving_a_position_past_the_last_transaction.txt',
                 'points past the end: the file has 1 transaction(s)',
                 id='E14-past-the-last-transaction'),
    pytest.param('a_fee_giving_a_misspelt_position.txt',
                 '`cost_basis_split_guid: $transaction_to_import[0].splits[0].guid$` '
                 'is no variable this format knows', id='E17-misspelt'),
])
def test_a_position_that_cannot_be_resolved_is_refused(tmp_path, name, refusal):
    book, done = _import(tmp_path, name)

    assert done.exit_code != 0, done.output
    assert refusal in done.output, done.output
    assert _bases(book) == []


@pytest.mark.parametrize('name, written_as', [
    pytest.param('a_payment_giving_a_position_in_place_of_a_split_guid.txt',
                 '`txn_split_guid: $transactions_to_import[0].splits[0].guid$`',
                 id='in-a-payment-block'),
    pytest.param('a_transaction_giving_a_position_as_its_own_key.txt',
                 '`cost_basis_split_guid: $transactions_to_import[0].splits[0].guid$`',
                 id='on-a-transaction'),
])
def test_a_position_where_none_is_read_refuses_the_whole_file(tmp_path, name, written_as):
    """E23: nothing of the file is applied, and the refusal says where a position is read."""
    book, done = _import(tmp_path, name, extra=('--include-business-objects',))

    assert done.exit_code != 0, done.output
    assert (f'{written_as} is a variable, and a position is read only as '
            '`cost_basis_split_guid:` on a split of a transaction') in done.output, done.output
    ledger = tmp_path / 'ledger.txt'
    assert _run(CliRunner(), 'export', str(book), str(ledger)).exit_code == 0
    assert 'Received money' not in ledger.read_text()


def test_the_export_writes_the_guid_and_rebuilds_the_book(tmp_path):
    book, done = _import(tmp_path, 'a_usd_arrival_and_the_fee_drawn_on_it_in_one_transaction.txt')
    _imported(done)
    ledger = tmp_path / 'ledger.txt'
    exported = _run(CliRunner(), 'export', str(book), str(ledger))
    assert exported.exit_code == 0, exported.output
    assert '$transactions_to_import' not in ledger.read_text()

    rebuilt = tmp_path / 'rebuilt.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(rebuilt), str(ledger))

    _imported(made)
    assert _bases(rebuilt) == _bases(book)
