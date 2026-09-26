"""A credit in a lot with no owner: listed under its transaction's owner, or warned about, and its owner attached by `lot_owner:`.

GnuCash's View → Lots makes such a lot. "New Lot" inserts a lot with no owner,
and "add split to lot" puts any loose split in it (`dialog-lot-viewer.c`).
The tests make one with the same calls. Measured on 5.10, before this:

- `find-prepayments` called the lot "a bug … Please report it", and printed
  its account as `Assets.Accounts Receivable`;
- `lot_owner: customer:C001` on the split, read with `import --strategy
  update`, exited 0 and changed nothing: the line was read by nobody;
- an unposted invoice's orphan read back from an export, put in such a lot,
  was warned about as belonging to nobody and listed as C001's credit in the
  same run.

A lot with no owner is still somebody's where its transaction says whose, and
it is listed under that owner. It is warned about only where nothing has an
owner, with how to attach one. A `lot_owner:` attaches its owner to a lot with
no owner, and one stating a lot owned by someone else is refused rather than
passed over.
"""

import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli
from tests.integration.test_find_orphan_payments import ACCOUNTS as TAB_ACCOUNTS
from tests.integration.test_find_orphan_payments import _fixture

DEPOSIT = 'tests/fixtures/an_unidentified_deposit_on_the_receivable.txt'
PAID_AHEAD = 'tests/fixtures/an_unidentified_payment_on_the_payable.txt'
V001 = 'tests/fixtures/vendor_v001_active.txt'
C001 = 'tests/fixtures/customer_c001_acme.txt'
C002 = 'tests/fixtures/customer_c002_bright.txt'
ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'
OVERPAID = 'tests/fixtures/q015_oh_inv_export_emits.txt'
AR = 'Assets:Accounts Receivable'
AP = 'Liabilities:Accounts Payable'
WARNED = 'is in a lot with no owner'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _imported(*args):
    result = _run('import', *args)
    assert result.exit_code == 0, result.output
    return result


def _into_a_new_lot(book, account):
    """The loose split on `account` put in a new lot, as View → Lots does it."""
    from infrastructure.gnucash.engine import load_gnc_engine
    from infrastructure.gnucash.utils import get_account_full_name, qof_pointer
    from repositories.gnucash_repository import GnuCashRepository
    from services.foreign_currency import iter_splits

    lib = load_gnc_engine()
    repo = GnuCashRepository(str(book))
    repo.open()
    try:
        loose = next(split for split in iter_splits(repo.book)
                     if get_account_full_name(split.GetAccount()) == account
                     and split.GetLot() is None)
        holder = loose.GetAccount()
        holder.BeginEdit()
        lot = lib.gnc_lot_new(int(repo.book.instance))
        lib.xaccAccountInsertLot(int(holder.instance), lot)
        lib.gnc_lot_add_split(lot, qof_pointer(loose))
        holder.CommitEdit()
        repo.save()
    finally:
        repo.close()


def _a_deposit_in_a_lot_with_no_owner(tmp_path):
    book = tmp_path / 'deposit.gnucash'
    _imported('--new', book, DEPOSIT)
    _into_a_new_lot(book, AR)
    return book


def _an_orphan_read_back_in_a_lot_with_no_owner(tmp_path, record, unpost, account,
                                                with_owners=True):
    book = tmp_path / 'book.gnucash'
    source = tmp_path / 'in.txt'
    source.write_text(TAB_ACCOUNTS + '\n' + _fixture(record))
    _imported('--new', book, source, '--include-business-objects')
    record_id = 'BILL-001' if 'bill' in record else 'INV-001'
    unposted = _run(unpost, book, record_id)
    assert unposted.exit_code == 0, unposted.output
    out = tmp_path / 'out.txt'
    exported = _run('export', book, out,
                    *(['--include-business-objects'] if with_owners else []))
    assert exported.exit_code == 0, exported.output
    fresh = tmp_path / 'fresh.gnucash'
    _imported('--new', fresh, out, *(['--include-business-objects'] if with_owners else []))
    _into_a_new_lot(fresh, account)
    return fresh


def test_a_deposit_in_a_lot_with_no_owner_is_warned_about(tmp_path):
    book = _a_deposit_in_a_lot_with_no_owner(tmp_path)

    listed = _run('find-prepayments', book)

    assert listed.exit_code == 0, listed.output
    assert WARNED in listed.output, listed.output
    assert f'{AR}  CAD 50.00' in listed.output, listed.output
    assert '`lot_owner: customer:<id>`' in listed.output, listed.output
    assert 'Please report it' not in listed.output, listed.output


@pytest.mark.parametrize('fixture, account, owner_file, split_guid, lot_owner, credit', [
    (DEPOSIT, AR, C001, 'e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0', 'customer:C001',
     'customer C001 (Acme)  CAD 50.00'),
    (PAID_AHEAD, AP, V001, 'e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1', 'vendor:V001',
     'vendor V001 (Supplier)  CAD 50.00'),
], ids=['customer', 'vendor'])
def test_a_lot_owner_attaches_its_owner_to_that_lot(tmp_path, fixture, account, owner_file,
                                                   split_guid, lot_owner, credit):
    book = tmp_path / 'book.gnucash'
    _imported('--new', book, fixture)
    _into_a_new_lot(book, account)
    _imported(book, owner_file, '--include-business-objects')
    text = Path(fixture).read_text()
    guid_line = f'\t\tguid: "{split_guid}"\n'
    assert guid_line in text, text
    owned = tmp_path / 'owned.txt'
    owned.write_text(text.replace(guid_line, guid_line + f'\t\tlot_owner: {lot_owner}\n'))

    _imported(book, owned, '--strategy', 'update')

    listed = _run('find-prepayments', book)
    assert credit in listed.output, listed.output
    assert WARNED not in listed.output, listed.output


@pytest.mark.parametrize('record, unpost, account, owner', [
    ('q014_invoice_posted_paid', 'unpost-invoices', AR, 'customer C001'),
    ('q014_bill_posted_paid', 'unpost-bills', AP, 'vendor V001'),
], ids=['invoice', 'bill'])
def test_an_orphan_read_back_into_such_a_lot_is_its_owners_credit(tmp_path, record, unpost,
                                                                  account, owner):
    book = _an_orphan_read_back_in_a_lot_with_no_owner(tmp_path, record, unpost, account)

    listed = _run('find-prepayments', book)

    assert listed.exit_code == 0, listed.output
    assert 'Found 1 open pre-payment credit.' in listed.output, listed.output
    assert f'• {owner} ' in listed.output, listed.output
    assert WARNED not in listed.output, listed.output


@pytest.mark.parametrize('record, unpost, account', [
    ('q014_invoice_posted_paid', 'unpost-invoices', AR),
    ('q014_bill_posted_paid', 'unpost-bills', AP),
], ids=['customer', 'vendor'])
def test_one_whose_owner_the_book_lacks_is_warned_about_and_not_listed(tmp_path, record,
                                                                       unpost, account):
    book = _an_orphan_read_back_in_a_lot_with_no_owner(
        tmp_path, record, unpost, account, with_owners=False)

    listed = _run('find-prepayments', book)

    assert 'No pre-payment credits found.' in listed.output, listed.output
    assert WARNED in listed.output, listed.output


PAID_TO_C001 = 'tests/fixtures/a_payment_to_c001_on_the_receivable.txt'


def _the_lot_guid_of(book, guid):
    """The guid of the lot the split with `guid` is in."""
    from repositories.gnucash_repository import GnuCashRepository, SessionMode
    from services.foreign_currency import iter_splits, split_guid
    from services.gnucash_importer import _lot_guid_str

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        return _lot_guid_str(next(split for split in iter_splits(repo.book)
                                  if split_guid(split) == guid).GetLot())
    finally:
        repo.close()


def test_a_split_stating_a_lot_with_no_owner_is_refused(tmp_path):
    """`lot_guid:` joins a split to an owner's credit, and a lot with no owner is nobody's."""
    book = _a_deposit_in_a_lot_with_no_owner(tmp_path)
    _imported(book, C001, '--include-business-objects')
    lot = _the_lot_guid_of(book, 'e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0')
    paid = tmp_path / 'paid.txt'
    paid.write_text(Path(PAID_TO_C001).read_text().replace('LOT_GUID', lot))

    result = _run('import', book, paid)

    assert 'is a lot belonging to nobody' in result.output, result.output
    assert WARNED in _run('find-prepayments', book).output


def test_a_split_stating_no_lot_passes_a_lot_with_no_owner_by(tmp_path):
    """Looking for C001's credit to pay back, the import does not take a lot nobody owns.

    The 50.00 in that lot is nobody's, so C001 has no credit, and money paid
    back to C001 out of the bank is refused for having none to settle.
    """
    book = _a_deposit_in_a_lot_with_no_owner(tmp_path)
    _imported(book, C001, '--include-business-objects')
    text = Path(PAID_TO_C001).read_text()
    line = '\t\tlot_guid: "LOT_GUID"\n'
    assert line in text, text
    paid = tmp_path / 'paid.txt'
    paid.write_text(text.replace(line, ''))

    result = _run('import', book, paid)

    assert result.exit_code != 0, result.output
    assert "customer 'C001' has no open credit" in result.output, result.output
    listed = _run('find-prepayments', book)
    assert WARNED in listed.output, listed.output
    assert f'{AR}  CAD 50.00' in listed.output, listed.output


def test_a_credit_read_back_under_another_customer_is_refused(tmp_path):
    book = tmp_path / 'book.gnucash'
    _imported('--new', book, ACCOUNTS)
    _imported(book, OVERPAID, '--include-business-objects')
    _imported(book, C002, '--include-business-objects')
    out = tmp_path / 'out.txt'
    assert _run('export', book, out).exit_code == 0
    text = out.read_text()
    assert re.search(r'lot_owner: customer:C001:[0-9a-f]+', text), text
    moved = tmp_path / 'moved.txt'
    moved.write_text(re.sub(r'lot_owner: customer:C001:[0-9a-f]+',
                            'lot_owner: customer:C002', text))

    result = _run('import', book, moved, '--strategy', 'update')

    assert 'states `lot_owner: customer:C002`' in result.output, result.output
    listed = _run('find-prepayments', book)
    assert 'customer C001 (Acme)  CAD 50.00' in listed.output, listed.output


def test_a_settlement_read_back_under_another_customer_is_refused(tmp_path):
    """The split settling C001's invoice, stating `lot_owner: customer:C002`, was read by nothing."""
    book = tmp_path / 'book.gnucash'
    _imported('--new', book, ACCOUNTS)
    _imported(book, OVERPAID, '--include-business-objects')
    _imported(book, C002, '--include-business-objects')
    out = tmp_path / 'out.txt'
    assert _run('export', book, out).exit_code == 0
    text = out.read_text()
    settlement = f'\t{AR} -100.00 CAD\n'
    assert settlement in text, text
    moved = tmp_path / 'moved.txt'
    moved.write_text(text.replace(settlement, settlement + '\t\tlot_owner: customer:C002\n'))

    result = _run('import', book, moved, '--strategy', 'update')

    assert result.exit_code != 0, result.output
    assert 'states `lot_owner: customer:C002`' in result.output, result.output
    assert 'unapply-payment' in result.output, result.output
