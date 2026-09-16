"""A payment giving a guid that matches nothing is refused where the deposit it describes has no readable owner.

Beta's INV-B is settled by one 100.00 deposit. Acme's INV-A then gives a
`txn_guid:` that matches no transaction in this book, with that deposit's date,
amount, account and memo — a mistyped guid, or a page written against another
book.

Whose money the deposit is decides what happens. Beta's receipt cannot settle
Acme's invoice, so where the book reads Beta as its owner the match is a
coincidence and INV-A is paid by a payment of its own. Where the book cannot
say — a customer whose id is empty, which GnuCash's dialogs allow, on either
invoice — the block is read as describing the deposit, and the import is
refused rather than entering the same money twice.

Measured on 5.10 and 3.8: with both ids in place the run reports INV-A
`updated` and both invoices paid; with either id emptied it is refused, INV-A
stays outstanding, and the refusal quotes the deposit and INV-B.
"""

import pytest
from click.testing import CliRunner

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.gnucash_importer import _find_invoices_by_id

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'
BOOK = 'tests/fixtures/a_deposit_settling_inv_b_for_another_customer.txt'
GIVING_A_GUID_THAT_MATCHES_NOTHING = (
    'tests/fixtures/a_payment_giving_a_guid_that_matches_no_transaction.txt')


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _done(*args):
    result = _run(*args)
    assert result.exit_code == 0, result.output
    return result


def _a_book_with_the_deposit(tmp_path):
    book = tmp_path / 'book.gnucash'
    _done('import', '--new', book, ACCOUNTS)
    _done('import', book, BOOK, '--include-business-objects')
    return book


def _empty_the_id_of(book, owner_id):
    """Leave that customer with no id, as a person does by clearing the field."""
    repo = GnuCashRepository(str(book))
    repo.open(SessionMode.NORMAL)
    try:
        customer = repo.book.CustomerLookupByID(owner_id)
        customer.BeginEdit()
        customer.SetID('')
        customer.CommitEdit()
        repo.save()
    finally:
        repo.close()


def _is_paid(book, record_id):
    repo = GnuCashRepository(str(book))
    repo.open(SessionMode.READ_ONLY)
    try:
        record = _find_invoices_by_id(repo.book, record_id)[0]
        return record.IsPaid()
    finally:
        repo.close()


def test_the_block_is_a_payment_of_its_own_where_both_owners_read(tmp_path):
    book = _a_book_with_the_deposit(tmp_path)

    result = _done('import', book, GIVING_A_GUID_THAT_MATCHES_NOTHING,
                   '--include-business-objects')

    assert 'invoice "INV-A": updated' in result.output, result.output
    assert _is_paid(book, 'INV-A'), 'INV-A should be paid by a payment of its own'


@pytest.mark.parametrize('emptied', ['C002', 'C001'])
def test_the_import_is_refused_where_an_owner_has_no_id(tmp_path, emptied):
    """C002 owns the invoice the deposit settles; C001 owns the one being paid."""
    book = _a_book_with_the_deposit(tmp_path)
    _empty_the_id_of(book, emptied)

    result = _run('import', book, GIVING_A_GUID_THAT_MATCHES_NOTHING,
                  '--include-business-objects')

    assert result.exit_code != 0, result.output
    assert 'Recording it would enter the same money twice' in result.output, result.output
    assert 'already settling invoice "INV-B"' in result.output, result.output
    assert not _is_paid(book, 'INV-A'), 'INV-A should be left outstanding'
