"""Money on a receivable that belongs to no customer is listed by `find-prepayments`.

GnuCash's register lets a split sit on Accounts Receivable in no lot, in a
transaction that gives no owner either: a deposit entered against the
receivable before anyone knows whose it is. Such money is no customer's
credit and pays no invoice, and it is still on the receivable. Measured on
5.10, nothing said so: `find-prepayments` answered "No pre-payment credits
found" and `find-orphan-payments` listed nothing.

So `find-prepayments` lists it in a section of its own, for the whole book
only, since it belongs to nobody a filter could select: the loose figure as
the account holds it, and how to give it an owner.

A loose split on a transaction that does give an owner is not this. An
unposted invoice's orphan read back from an export is exactly that shape
(CLAUDE.md finding 10), and `find-orphan-payments` lists it under its owner.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

DEPOSIT = 'tests/fixtures/an_unidentified_deposit_on_the_receivable.txt'
CUSTOMER = 'tests/fixtures/customer_c001_acme.txt'
AR = 'Assets:Accounts Receivable'
HEADING = ('Found 1 amount on a receivable or payable that belongs to no customer '
           'or vendor.')
NO_ORPHAN = 'No orphan bank-side payment transactions found.'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _imported(*args):
    result = _run('import', *args)
    assert result.exit_code == 0, result.output
    return result


def _a_deposit_nobody_owns(tmp_path):
    book = tmp_path / 'book.gnucash'
    _imported('--new', book, DEPOSIT)
    return book


def test_a_deposit_nobody_owns_is_listed(tmp_path):
    book = _a_deposit_nobody_owns(tmp_path)

    listed = _run('find-prepayments', book)

    assert listed.exit_code == 0, listed.output
    assert 'No pre-payment credits found.' in listed.output, listed.output
    assert HEADING in listed.output, listed.output
    assert f'CAD -50.00  on {AR}' in listed.output, listed.output
    assert '2026-03-02  "Deposit, sender unknown"' in listed.output, listed.output
    assert 'guid: d0d0d0d0-d0d0-d0d0-d0d0-d0d0d0d0d0d0' in listed.output, listed.output
    assert 'lot_owner: customer:' in listed.output, listed.output
    assert NO_ORPHAN in _run('find-orphan-payments', book).output


def test_it_is_not_listed_under_one_customer(tmp_path):
    book = _a_deposit_nobody_owns(tmp_path)

    listed = _run('find-prepayments', book, '--customer', 'C001')

    assert listed.exit_code == 0, listed.output
    assert 'belongs to no customer' not in listed.output, listed.output


def test_a_split_of_nothing_is_not_listed(tmp_path):
    """0.00 on the receivable in no lot holds no money to account for."""
    book = tmp_path / 'book.gnucash'
    _imported('--new', book, 'tests/fixtures/payment_roundtrip_accounts.txt')
    _imported(book, 'tests/fixtures/a_line_of_nothing_on_the_receivable.txt')

    listed = _run('find-prepayments', book)

    assert listed.exit_code == 0, listed.output
    assert 'belongs to no customer' not in listed.output, listed.output


def _a_settlement_taken_out_of_the_lot_an_unpost_left(tmp_path):
    """An unposted invoice's settlement, taken out of its lot in View → Lots.

    The unpost marked it. In no lot, neither the lot nor the transaction gives
    an owner any more, and the invoice the mark gives is all that does.
    """
    import ctypes

    from infrastructure.gnucash.engine import load_gnc_engine
    from infrastructure.gnucash.utils import get_account_full_name, qof_pointer
    from repositories.gnucash_repository import GnuCashRepository
    from services.foreign_currency import iter_splits
    from tests.integration.test_find_orphan_payments import ACCOUNTS, _fixture

    book = tmp_path / 'book.gnucash'
    source = tmp_path / 'in.txt'
    source.write_text(ACCOUNTS + '\n' + _fixture('q014_invoice_posted_paid'))
    _imported('--new', book, source, '--include-business-objects')
    assert _run('unpost-invoices', book, 'INV-001').exit_code == 0
    lib = load_gnc_engine()
    lib.gnc_lot_remove_split.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.gnc_lot_remove_split.restype = None
    repo = GnuCashRepository(str(book))
    repo.open()
    try:
        settlement = next(split for split in iter_splits(repo.book)
                          if get_account_full_name(split.GetAccount()) == AR
                          and split.GetLot() is not None)
        account = settlement.GetAccount()
        account.BeginEdit()
        lib.gnc_lot_remove_split(qof_pointer(settlement.GetLot()), qof_pointer(settlement))
        account.CommitEdit()
        repo.save()
    finally:
        repo.close()
    return book


def test_a_settlement_an_unpost_left_in_no_lot_is_its_invoices_customers(tmp_path):
    """`find-orphan-payments` lists it under C001, and nothing says it belongs to nobody."""
    book = _a_settlement_taken_out_of_the_lot_an_unpost_left(tmp_path)

    listed = _run('find-prepayments', book)
    orphans = _run('find-orphan-payments', book)

    assert 'belongs to no customer' not in listed.output, listed.output
    assert 'customer C001 (Acme)' in orphans.output, orphans.output
    assert 'the invoice its unpost marked it with is for' in orphans.output, orphans.output


def test_one_whose_unposted_invoice_is_deleted_belongs_to_nobody(tmp_path):
    """With the invoice gone, nothing gives an owner, so it is listed as nobody's."""
    book = _a_settlement_taken_out_of_the_lot_an_unpost_left(tmp_path)
    deleted = _run('delete-invoices', book, 'INV-001')
    assert deleted.exit_code == 0, deleted.output

    listed = _run('find-prepayments', book)
    orphans = _run('find-orphan-payments', book)

    assert HEADING in listed.output, listed.output
    assert f'on {AR}' in listed.output, listed.output
    assert NO_ORPHAN in orphans.output, orphans.output


def test_giving_it_an_owner_makes_it_that_customers_credit(tmp_path):
    book = _a_deposit_nobody_owns(tmp_path)
    _imported(book, CUSTOMER, '--include-business-objects')
    text = Path(DEPOSIT).read_text()
    split_guid = '\t\tguid: "e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0"\n'
    assert split_guid in text, text
    owned = tmp_path / 'owned.txt'
    owned.write_text(text.replace(split_guid, split_guid + '\t\tlot_owner: customer:C001\n'))

    _imported(book, owned, '--strategy', 'update')

    listed = _run('find-prepayments', book)
    assert 'customer C001 (Acme)  CAD 50.00' in listed.output, listed.output
    assert 'belongs to no customer' not in listed.output, listed.output

