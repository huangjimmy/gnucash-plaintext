"""What each GnuCash text field this format carries holds after a save: never set, set to `None`, or set to `""`.

`$None$` and `#None` on a field GnuCash keeps itself cannot remove it, and
GnuCash's setters may ignore `None`. So for each text field this builds three
objects: one whose field is never set, one set to "x" and then to `None`, one
set to "x" and then to `""`. Each edit is committed, the book is saved and
closed, and every field is read back from the reopened book. A getter or
setter a build does not have is printed as such.

Run: ./scripts/test.sh <tag> tests/research/what_a_gnucash_field_reads_before_it_is_set_probe.py -s
"""

from click.testing import CliRunner

from tests.conftest import _run

CASES = ('never set', 'x', 'x then None', 'x then ""')

TRANSACTION = ('Notes', 'DocLink', 'Association', 'Num', 'Description')
SPLIT = ('Memo', 'Action')
ACCOUNT = ('Code', 'Description', 'Notes', 'Color')
OWNER = ('Notes',)
ADDRESS = ('Name', 'Addr1', 'Addr2', 'Addr3', 'Addr4', 'Phone', 'Fax', 'Email')
RECORD = ('Notes', 'BillingID')
ENTRY = ('Description', 'Action', 'Notes')


def _apply(obj, field, case):
    """Set `field` on `obj` as `case` says; what went wrong, or ''."""
    setter = getattr(obj, f'Set{field}', None)
    if setter is None:
        return 'no setter on this build'
    try:
        if case != 'never set':
            setter('x')
        if case == 'x then None':
            setter(None)
        elif case == 'x then ""':
            setter('')
    except Exception as error:
        return f'Set{field} raised {type(error).__name__}: {error}'
    return ''


def _read(obj, field):
    getter = getattr(obj, f'Get{field}', None)
    if getter is None:
        return 'no getter on this build'
    try:
        return repr(getter())
    except Exception as error:
        return f'Get{field} raised {type(error).__name__}'


def test_what_each_text_field_holds_after_a_save(tmp_path):
    from gnucash import Account, Query, Split, Transaction
    from gnucash.gnucash_business import Bill, Customer, Entry, Invoice, Vendor

    from infrastructure.gnucash.utils import get_account_full_name
    from repositories.gnucash_repository import GnuCashRepository, SessionMode

    book_path = tmp_path / 'book.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(book_path),
                'tests/fixtures/a_bank_draft_1_with_no_key.txt')
    assert made.exit_code == 0, made.output

    # What each case went through before the save: the guid or id it can be
    # found by again, and what its setter said.
    built = []

    repo = GnuCashRepository(str(book_path))
    repo.open(mode=SessionMode.NORMAL)
    try:
        book = repo.book
        root = book.get_root_account()
        cad = book.get_table().lookup('CURRENCY', 'CAD')
        bank_a = next(a for a in root.get_descendants()
                      if get_account_full_name(a) == 'Asset:BankA')
        bank_b = next(a for a in root.get_descendants()
                      if get_account_full_name(a) == 'Asset:BankB')

        for kind, fields in (('Transaction', TRANSACTION), ('Split', SPLIT)):
            for field in fields:
                for case in CASES:
                    transaction = Transaction(book)
                    transaction.BeginEdit()
                    transaction.SetCurrency(cad)
                    first = Split(book)
                    first.SetParent(transaction)
                    first.SetAccount(bank_a)
                    second = Split(book)
                    second.SetParent(transaction)
                    second.SetAccount(bank_b)
                    target = transaction if kind == 'Transaction' else first
                    said = _apply(target, field, case)
                    transaction.CommitEdit()
                    built.append((kind, field, case, transaction.GetGUID().to_string(), said))

        number = 0
        for field in ACCOUNT:
            for case in CASES:
                number += 1
                account = Account(book)
                account.BeginEdit()
                account.SetName(f'Probe {number}')
                account.SetType(bank_a.GetType())
                account.SetCommodity(cad)
                root.append_child(account)
                said = _apply(account, field, case)
                account.CommitEdit()
                built.append(('Account', field, case, f'Probe {number}', said))

        for kind, cls in (('Customer', Customer), ('Vendor', Vendor)):
            for where, fields in ((kind, OWNER), (f'{kind} address', ADDRESS)):
                for field in fields:
                    for case in CASES:
                        number += 1
                        owner = cls(book, f'{kind[0]}-{number}', cad, f'{kind} {number}')
                        owner.BeginEdit()
                        target = owner if where == kind else owner.GetAddr()
                        said = _apply(target, field, case)
                        owner.CommitEdit()
                        built.append((where, field, case, f'{kind[0]}-{number}', said))

        customer = Customer(book, 'C-RECORDS', cad, 'records customer')
        vendor = Vendor(book, 'V-RECORDS', cad, 'records vendor')
        for kind, cls, owner in (('Invoice', Invoice, customer), ('Bill', Bill, vendor)):
            for where, fields in ((kind, RECORD), (f'{kind} line', ENTRY)):
                for field in fields:
                    for case in CASES:
                        number += 1
                        record = cls(book, f'{kind[0]}{number}', cad, owner)
                        record.BeginEdit()
                        entry = Entry(book)
                        entry.BeginEdit()
                        record.AddEntry(entry)
                        target = record if where == kind else entry
                        said = _apply(target, field, case)
                        entry.CommitEdit()
                        record.CommitEdit()
                        built.append((where, field, case, f'{kind[0]}{number}', said))
        repo.save()
    finally:
        repo.close()

    repo = GnuCashRepository(str(book_path))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        book = repo.book
        query = Query()
        query.search_for('Trans')
        query.set_book(book)
        transactions = {}
        for raw in query.run():
            transaction = Transaction(instance=raw)
            transactions[transaction.GetGUID().to_string()] = transaction
        query.destroy()
        accounts = {a.GetName(): a for a in book.get_root_account().get_descendants()}

        for where, field, case, found_by, said in built:
            if where == 'Transaction':
                target = transactions[found_by]
            elif where == 'Split':
                target = next(s for s in transactions[found_by].GetSplitList()
                              if s.GetAccount().GetName() == 'BankA')
            elif where == 'Account':
                target = accounts[found_by]
            elif where in ('Customer', 'Customer address'):
                owner = book.CustomerLookupByID(found_by)
                target = owner if where == 'Customer' else owner.GetAddr()
            elif where in ('Vendor', 'Vendor address'):
                owner = book.VendorLookupByID(found_by)
                target = owner if where == 'Vendor' else owner.GetAddr()
            elif where in ('Invoice', 'Invoice line'):
                record = book.InvoiceLookupByID(found_by)
                target = record if where == 'Invoice' else record.GetEntries()[0]
            else:
                record = book.BillLookupByID(found_by)
                target = record if where == 'Bill' else record.GetEntries()[0]
            print(f'FIELD {where}.{field} [{case}]: {said or _read(target, field)}')
    finally:
        repo.close()
