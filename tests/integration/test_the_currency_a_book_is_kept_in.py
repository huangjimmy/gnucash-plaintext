"""Which currency a book is kept in, and so which currency its reports are in.

Q-042: GnuCash stores no currency for a book, so gnucash-plaintext finds it. The
first of these that states one:

1. a currency passed on the command;
2. the `company` block's `base_currency:`, kept in the book;
3. the currency every top-level account held in a currency shares.

Where none states one, the book's currency is refused. Nothing is taken to be
CAD.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.book_currency import BookCurrencyUnknownError, book_currency
from tests.conftest import _run

FIXTURES = Path('tests/fixtures')


def _book(tmp_path, fixture):
    book = tmp_path / 'book.gnucash'
    result = _run(CliRunner(), 'import', '--new', str(book), str(FIXTURES / fixture),
                  '--include-business-objects')
    assert result.exit_code == 0, result.output
    return book


def _currency_of(book, stated=None):
    repo = GnuCashRepository(str(book))
    repo.open(SessionMode.READ_ONLY)
    try:
        return book_currency(repo.book, stated)
    finally:
        repo.close()


class TestTheAccountsGnuCashMakesForItself:
    """`Imbalance-<CUR>`, `Orphan-<CUR>` and `Trading` decide nothing.

    GnuCash's scrub completes a transaction whose splits do not add up by
    parking the difference in `Imbalance-<CUR>`, and puts a split whose account
    has gone in `Orphan-<CUR>` — as children of the root, one of each per
    currency it met. A book kept in CAD that once met a USD transaction
    GnuCash had to complete therefore holds a top-level account in US dollars
    that no ledger opened, and counting it made the book's top-level
    currencies two and its answer none.
    """

    FIXTURE = 'a_cad_book_beside_the_accounts_gnucash_makes.txt'

    def test_a_cad_book_beside_them_is_still_kept_in_cad(self, tmp_path):
        book = _book(tmp_path, self.FIXTURE)

        assert _currency_of(book) == 'CAD'

    def test_the_balance_sheet_prints_rather_than_refusing(self, tmp_path):
        book = _book(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-01-31')

        assert result.exit_code == 0, result.output
        assert 'currency.mnemonic: "CAD"' in result.output, result.output
        assert '1000.00 CAD' in result.output, result.output


class TestWhereTheCurrencyComesFrom:
    def test_top_level_accounts_that_all_hold_hkd(self, tmp_path):
        book = _book(tmp_path, 'a_book_kept_in_hkd.txt')

        assert _currency_of(book) == 'HKD'

    def test_the_company_blocks_base_currency_before_the_top_level_accounts(self, tmp_path):
        book = _book(tmp_path, 'a_cad_book_whose_company_states_hkd_as_its_base_currency.txt')

        assert _currency_of(book) == 'HKD'

    def test_a_currency_passed_on_the_command_before_both(self, tmp_path):
        book = _book(tmp_path, 'a_cad_book_whose_company_states_hkd_as_its_base_currency.txt')

        assert _currency_of(book, stated='USD') == 'USD'

    def test_a_top_level_account_holding_shares_is_held_in_no_currency(self, tmp_path):
        book = _book(tmp_path, 'an_hkd_book_with_a_top_level_account_holding_shares.txt')

        assert _currency_of(book) == 'HKD'


class TestWhenNothingStatesTheCurrency:
    def test_top_level_accounts_in_two_currencies_are_refused(self, tmp_path):
        book = _book(tmp_path, 'a_book_whose_top_level_accounts_are_in_two_currencies.txt')

        with pytest.raises(BookCurrencyUnknownError) as refusal:
            _currency_of(book)

        message = str(refusal.value)
        assert 'CAD' in message and 'USD' in message, message
        assert '--currency' in message and 'base_currency' in message, message

    def test_a_book_with_no_accounts_is_refused(self, tmp_path):
        book = _book(tmp_path, 'a_company_with_no_accounts.txt')

        with pytest.raises(BookCurrencyUnknownError) as refusal:
            _currency_of(book)

        assert '--currency' in str(refusal.value) and 'base_currency' in str(refusal.value)

    def test_a_base_currency_gnucash_does_not_know_is_refused(self, tmp_path):
        book = _book(tmp_path, 'a_company_stating_a_base_currency_gnucash_does_not_know.txt')

        with pytest.raises(BookCurrencyUnknownError) as refusal:
            _currency_of(book)

        assert 'XYZ' in str(refusal.value) and 'base_currency' in str(refusal.value)

    def test_a_currency_passed_on_the_command_that_gnucash_does_not_know_is_refused(self, tmp_path):
        book = _book(tmp_path, 'a_book_kept_in_hkd.txt')

        with pytest.raises(BookCurrencyUnknownError) as refusal:
            _currency_of(book, stated='ABC')

        assert 'ABC' in str(refusal.value) and '--currency' in str(refusal.value)
