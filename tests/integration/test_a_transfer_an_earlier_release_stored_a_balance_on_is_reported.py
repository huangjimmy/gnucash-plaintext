"""A transfer's receiving split on which an earlier release stored a cost basis balance.

US dollars moved from one US dollar account to another arrive nowhere: the book
held them before and holds them after, so the receiving split is no cost basis.
An earlier release read a transfer stated in Canadian dollars as an arrival at
the rate it states, and stored a `cost_basis_balance` on its receiving split. A
book written then still carries that figure; `fx-balances` no longer lists it.

`fx-balances --verify-costs` reports it, as it reports any balance left on a
split that is no cost basis, and says why this one is none and what a spend out
of that account states instead: the guid of the cost basis the dollars came from.
README says how to repair such a book.

The book is put in that state the way the earlier release left it: the balance
written straight onto the split, since no file can state one there.
`tests/fixtures/a_transfer_between_us_dollar_accounts_stated_in_canadian_dollars.txt`.
"""

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata
from infrastructure.gnucash.utils import find_account
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import COST_BASIS_BALANCE_KEY
from tests.integration.text_report_pages import book_from

LEDGER = 'a_transfer_between_us_dollar_accounts_stated_in_canadian_dollars.txt'


def _store_a_balance_on_the_transfer(book):
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        savings = find_account(repo.book.get_root_account(), 'Assets:USD Savings')
        split = savings.GetSplitList()[0]
        transaction = split.GetParent()
        transaction.BeginEdit()
        metadata = dict(get_custom_metadata(split))
        metadata[COST_BASIS_BALANCE_KEY] = '400.00'
        set_custom_metadata(split, metadata)
        transaction.CommitEdit()
        repo.save()
    finally:
        repo.close()


def test_verify_costs_reports_the_balance_and_says_why_it_is_no_cost_basis(tmp_path):
    book = book_from(tmp_path, LEDGER)
    _store_a_balance_on_the_transfer(book)

    checked = CliRunner().invoke(cli, ['fx-balances', str(book), '--verify-costs'])

    assert checked.exit_code == 1, checked.output
    assert 'Move 400.00 USD to savings' in checked.output, checked.output
    assert ("this split stores cost_basis_balance: '400.00', but it is no cost "
            "basis: it moves USD between accounts on one side of the book, and "
            "no more arrived on that side than left it, so there is nothing to "
            "open a cost basis for. A disposal out of this account states the guid "
            "of the cost basis the USD came from") \
        in ' '.join(checked.output.split()), checked.output


def test_the_listing_offers_only_the_dollars_bought(tmp_path):
    """1,000.00 USD, held across the two accounts: the transfer adds none."""
    book = book_from(tmp_path, LEDGER)
    _store_a_balance_on_the_transfer(book)

    listing = CliRunner().invoke(cli, ['fx-balances', str(book)]).output

    assert 'Total USD cost basis balance: 1,000.00 USD' in listing, listing
    assert 'Total USD held in accounts: 1,000.00 USD' in listing, listing
