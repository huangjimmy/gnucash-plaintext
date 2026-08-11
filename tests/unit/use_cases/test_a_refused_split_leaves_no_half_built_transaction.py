"""A transaction that cannot be finished is destroyed, not left open.

`ImportTransactionsUseCase.execute` builds each transaction between a
`BeginEdit` and a `CommitEdit`, and the split loop in between can refuse: a
missing account, or a figure the currency cannot hold. The missing account
already destroyed the transaction on its way out; the refused figure did not,
and left an edit open on a transaction with some of its splits attached —
which nothing afterwards finishes or removes, so the book carries a
half-written entry that the caller was told had failed.

Both refusals are collected per transaction, so a bad one does not cost the
good ones in the same batch. That is what the destroy has to keep true: the
good transactions are committed into the same book.
"""

import os
import tempfile

import pytest

from repositories.gnucash_repository import GnuCashRepository
from use_cases.import_transactions import ImportTransactionsUseCase


@pytest.fixture
def book_path():
    """A CAD book with a bank and an expense account."""
    import gnucash
    from gnucash import Account, Session

    fd, path = tempfile.mkstemp(suffix='.gnucash')
    os.close(fd)
    os.unlink(path)
    try:
        from gnucash import SessionOpenMode
        session = Session(f'xml://{path}', SessionOpenMode.SESSION_NEW_STORE)
    except ImportError:
        session = Session(f'xml://{path}', is_new=True)

    book = session.book
    root = book.get_root_account()
    cad = book.get_table().lookup('CURRENCY', 'CAD')

    def child(parent, name, kind):
        account = Account(book)
        account.SetName(name)
        account.SetType(kind)
        account.SetCommodity(cad)
        parent.append_child(account)
        return account

    assets = child(root, 'Assets', gnucash.ACCT_TYPE_ASSET)
    child(assets, 'Bank', gnucash.ACCT_TYPE_BANK)
    expenses = child(root, 'Expenses', gnucash.ACCT_TYPE_EXPENSE)
    child(expenses, 'Dining', gnucash.ACCT_TYPE_EXPENSE)

    session.save()
    session.end()
    yield path
    if os.path.exists(path):
        os.unlink(path)


def _entry(description, amount):
    return {
        'date': '2026-02-01',
        'description': description,
        'currency': 'CAD',
        'splits': [
            {'account': 'Expenses:Dining', 'amount': amount},
            {'account': 'Assets:Bank', 'amount': f'-{amount}'},
        ],
    }


def _descriptions(book):
    from gnucash import Query, Transaction

    query = Query()
    query.search_for('Trans')
    query.set_book(book)
    found = sorted(Transaction(instance=raw).GetDescription()
                   for raw in query.run())
    query.destroy()
    return found


class TestAFigureTheCurrencyCannotHold:
    def test_it_is_reported_as_an_error(self, book_path):
        with GnuCashRepository(book_path) as repo:
            result = ImportTransactionsUseCase(repo).execute(
                [_entry('A tenth of a cent', '18.191')], validate=False)

        assert result.error_count == 1, result.errors
        assert '18.191' in result.errors[0]['error'], result.errors

    def test_no_half_built_transaction_is_left_in_the_book(self, book_path):
        """The splits already attached before the refusal, and the open edit."""
        with GnuCashRepository(book_path) as repo:
            ImportTransactionsUseCase(repo).execute(
                [_entry('A tenth of a cent', '18.191')], validate=False)

            assert _descriptions(repo.book) == []

    def test_the_good_ones_in_the_same_batch_still_land(self, book_path):
        """Which is why the failure is collected rather than raised."""
        with GnuCashRepository(book_path) as repo:
            result = ImportTransactionsUseCase(repo).execute(
                [_entry('A tenth of a cent', '18.191'),
                 _entry('An ordinary lunch', '18.19')], validate=False)

            assert result.error_count == 1, result.errors
            assert _descriptions(repo.book) == ['An ordinary lunch']


class TestAnAccountThatIsNotThere:
    """The sibling refusal, which already destroyed and must keep doing so."""

    def test_nothing_is_left_behind_either(self, book_path):
        entry = _entry('To nowhere', '10.00')
        entry['splits'][0]['account'] = 'Expenses:Nowhere'

        with GnuCashRepository(book_path) as repo:
            result = ImportTransactionsUseCase(repo).execute(
                [entry], validate=False)

            assert result.error_count == 1, result.errors
            assert 'Expenses:Nowhere' in result.errors[0]['error']
            assert _descriptions(repo.book) == []


class TestTheRepositorysOwnBuilder:
    """`create_transaction` builds between the same two edits, and had the
    same mark-without-carrying-out on its missing-account path."""

    def test_a_missing_account_leaves_nothing_behind(self, book_path):
        from gnucash import GncNumeric

        with GnuCashRepository(book_path) as repo:
            with pytest.raises(ValueError, match='Expenses:Nowhere'):
                repo.create_transaction(
                    description='To nowhere',
                    date_tuple=(1, 2, 2026),
                    splits_data=[
                        {'account_path': 'Assets:Bank',
                         'value': GncNumeric(1000, 100)},
                        {'account_path': 'Expenses:Nowhere',
                         'value': GncNumeric(-1000, 100)},
                    ],
                    currency_code='CAD')

            assert _descriptions(repo.book) == []

    def test_a_good_one_still_lands(self, book_path):
        from gnucash import GncNumeric

        with GnuCashRepository(book_path) as repo:
            repo.create_transaction(
                description='An ordinary lunch',
                date_tuple=(1, 2, 2026),
                splits_data=[
                    {'account_path': 'Expenses:Dining',
                     'value': GncNumeric(1819, 100)},
                    {'account_path': 'Assets:Bank',
                     'value': GncNumeric(-1819, 100)},
                ],
                currency_code='CAD')

            assert _descriptions(repo.book) == ['An ordinary lunch']
