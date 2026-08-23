"""`lot_guid:` says which of an owner's credits a split belongs to.

`lot_owner:` says whose credit a split is, and an owner may hold more than
one. Which lot a split joined was therefore decided by the import and not by
the file: the oldest open lot the split would reduce. So a refund written
against the deposit taken in February came off the one taken in January, and
nothing in the file could say otherwise.

A lot has an identity of its own — measured in
`tests/research/a_lot_can_be_named_probe.py`: `GNC_ID_LOT` is `"Lot"`, the
collection answers by guid, and a guid can be forced on a lot the import
creates. So the export writes it and a file may name it.
"""

import pytest
from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.utils import get_account_full_name
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.gnucash_importer import _lot_guid_str

LEDGER = """2026-01-01 commodity CAD
\tmnemonic: "CAD"
\tfullname: "Canadian Dollar"
\tnamespace: "CURRENCY"
\tfraction: 100
2026-01-01 open Assets
\ttype: Asset
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Bank
\ttype: Bank
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Accounts Receivable
\ttype: Accounts Receivable
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Expenses
\ttype: Expense
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Expenses:Refunds
\ttype: Expense
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Income
\ttype: Income
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Income:Sales
\ttype: Income
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Liabilities
\ttype: Liability
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Liabilities:Accounts Payable
\ttype: Accounts Payable
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"

customer "C-LOT"
\tname: "Lot Ltd"
\tcurrency: CAD

customer "D-LOT"
\tname: "Other Ltd"
\tcurrency: CAD

vendor "V-LOT"
\tname: "Supplier Ltd"
\tcurrency: CAD

2026-01-04 * "Paid a supplier ahead"
\tAssets:Bank -20.00 CAD
\tLiabilities:Accounts Payable 20.00 CAD
\t\tlot_owner: "vendor:V-LOT"

2026-01-03 * "Another customer's deposit"
\tAssets:Bank 70.00 CAD
\tAssets:Accounts Receivable -70.00 CAD
\t\tlot_owner: "customer:D-LOT"

2026-01-05 * "January deposit"
\tAssets:Bank 50.00 CAD
\tAssets:Accounts Receivable -50.00 CAD
\t\tlot_owner: "customer:C-LOT"

2026-02-05 * "February deposit"
\tAssets:Bank 80.00 CAD
\tAssets:Accounts Receivable -80.00 CAD
\t\tlot_owner: "customer:C-LOT"
"""

#: A refund of 40.00, which either deposit could pay for. Written against the
#: February one — `{lot_guid}` is filled in by the test.
REFUND = """
2026-03-05 * "Refund to C-LOT"
\tAssets:Bank -40.00 CAD
\tAssets:Accounts Receivable 40.00 CAD
\t\tlot_owner: "customer:C-LOT"
\t\tlot_guid: "{lot_guid}"
"""


def _book(tmp_path, name='book.gnucash'):
    ledger = tmp_path / 'in.txt'
    ledger.write_text(LEDGER, encoding='utf-8')
    book = tmp_path / name
    made = CliRunner().invoke(cli, ['import', '--new', str(book), str(ledger),
                                    '--include-business-objects'])
    assert made.exit_code == 0, made.output
    return book


def _exported(book, tmp_path, name='out.txt'):
    out = tmp_path / name
    result = CliRunner().invoke(cli, ['export', str(book), '--output',
                                      str(out), '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return out.read_text(encoding='utf-8')


def _lot_guids_by_value(text):
    """`{split value: lot guid}` for every split naming a lot.

    A split block writes its value on the account line above its keys, so the
    value is carried down from there.
    """
    found, value = {}, None
    for line in text.splitlines():
        stripped = line.strip()
        if line.startswith('\t') and not line.startswith('\t\t'):
            value = stripped.split(' ')[-2] if ' CAD' in stripped else None
        elif stripped.startswith('lot_guid: "') and value:
            found[value] = stripped[len('lot_guid: "'):-1]
    return found


def _a_posted_invoices_lot(book, tmp_path):
    """Post an invoice into the book and return its lot's guid."""
    invoice = tmp_path / 'invoice.txt'
    invoice.write_text("""
invoice "INV-LOT-001"
\tcustomer_id: "C-LOT"
\tcurrency: CAD
\tdate_opened: 2026-02-01
\tentry:
\t\tdate: 2026-02-01
\t\tdescription: "A line"
\t\taccount: "Income:Sales"
\t\tquantity: 1
\t\tprice: 25
\t\ttaxable: #False
\t\ttax_included: #False
\tposted:
\t\tdate: 2026-02-01
\t\tdue: 2026-03-03
\t\tar_account: "Assets:Accounts Receivable"
\t\tmemo: "INV-LOT-001"
\t\taccumulate: #True
\tpayment: none
""", encoding='utf-8')
    result = CliRunner().invoke(cli, ['import', str(book), str(invoice),
                                      '--include-business-objects'])
    assert result.exit_code == 0, result.output

    from gnucash import Query

    from infrastructure.gnucash.utils import wrap_invoice_or_bill

    repo = GnuCashRepository(str(book))
    repo.open(SessionMode.READ_ONLY)
    try:
        q = Query()
        q.search_for('gncInvoice')
        q.set_book(repo.book)
        for raw in q.run():
            record = wrap_invoice_or_bill(raw)
            if record.GetID() == 'INV-LOT-001':
                answer = _lot_guid_str(record.GetPostedLot())
                q.destroy()
                return answer
        q.destroy()
        raise AssertionError('no such invoice')
    finally:
        repo.close()


def _the_customers_guid(text):
    """C-LOT's own guid — an account writes `guid:` at one tab as well."""
    inside = False
    for line in text.splitlines():
        if line.startswith('customer "C-LOT"'):
            inside = True
        elif inside and line.strip().startswith('guid: "'):
            return line.strip()[len('guid: "'):-1]
    raise AssertionError('no customer guid')


def _lot_balances(book):
    """`{lot guid: balance}` for every lot on the receivable.

    Through ctypes, because a lot out of `Account.GetLotList()` carries none
    of the lot methods on most builds — and through `qof_pointer`, because
    what that list holds is a wrapped `GncLot` on some of them.
    """
    from fractions import Fraction

    from infrastructure.gnucash.engine import load_gnc_engine
    from infrastructure.gnucash.utils import (
        money_text,
        numeric_to_fraction,
        qof_pointer,
    )

    lib = load_gnc_engine()
    repo = GnuCashRepository(str(book))
    repo.open(SessionMode.READ_ONLY)
    try:
        found = {}
        for account in repo.book.get_root_account().get_descendants():
            if get_account_full_name(account) != 'Assets:Accounts Receivable':
                continue
            for lot in account.GetLotList():
                balance = lib.gnc_lot_get_balance(qof_pointer(lot))
                # Through `money_text`, not `float`: a balance is a
                # rational and the project's money never goes through
                # binary floating point.
                found[_lot_guid_str(lot)] = money_text(
                    numeric_to_fraction(balance) if balance.denom
                    else Fraction(0), 100)
        return found
    finally:
        repo.close()


class TestTheLotASplitSitsIn:
    def test_is_written_on_the_split(self, tmp_path):
        book = _book(tmp_path)

        named = _lot_guids_by_value(_exported(book, tmp_path))

        # The two customers' three credits, and the vendor's on the payable.
        assert set(named) == {'-50.00', '-70.00', '-80.00', '20.00'}, named
        assert len(set(named.values())) == 4, named
        assert all(len(guid) == 32 for guid in named.values()), named

    def test_is_the_same_lot_in_a_book_rebuilt_from_the_export(self, tmp_path):
        """Two exports of the same credits describe the same two lots.

        Rebuilt into a fresh book the lots used to be whatever GnuCash minted,
        so the file that came out of the copy named different credits from the
        file that made it — and a refund written against one of them, in a
        ledger kept beside the book, meant nothing after a restore.
        """
        book = _book(tmp_path)
        first = _lot_guids_by_value(_exported(book, tmp_path))

        restored = tmp_path / 'restored.gnucash'
        made = CliRunner().invoke(cli, [
            'import', '--new', str(restored), str(tmp_path / 'out.txt'),
            '--include-business-objects'])
        assert made.exit_code == 0, made.output

        assert _lot_guids_by_value(_exported(restored, tmp_path, 'again.txt')) \
            == first


class TestASettlement:
    def test_takes_the_credit_its_block_names(self, tmp_path):
        """Not the oldest one the amount happens to fit.

        Both deposits could pay a 40.00 refund. Written against February's,
        it used to come off January's, and the two lots the export then
        described did not match the ledger that had just been imported.
        """
        book = _book(tmp_path)
        exported = _exported(book, tmp_path)
        named = _lot_guids_by_value(exported)
        february = named['-80.00']

        edited = tmp_path / 'refund.txt'
        edited.write_text(exported + REFUND.format(lot_guid=february),
                          encoding='utf-8')
        result = CliRunner().invoke(cli, ['import', str(book), str(edited),
                                          '--include-business-objects'])
        assert result.exit_code == 0, result.output

        balances = _lot_balances(book)
        assert balances[february] == '-40.00', balances
        assert balances[named['-50.00']] == '-50.00', balances

    def test_still_takes_the_oldest_where_the_block_names_none(self, tmp_path):
        """A hand-written file names no lot, and goes on working as it did."""
        book = _book(tmp_path)
        exported = _exported(book, tmp_path)
        named = _lot_guids_by_value(exported)

        edited = tmp_path / 'refund.txt'
        edited.write_text(
            exported + REFUND.format(lot_guid='').replace(
                '\t\tlot_guid: ""\n', ''), encoding='utf-8')
        result = CliRunner().invoke(cli, ['import', str(book), str(edited),
                                          '--include-business-objects'])
        assert result.exit_code == 0, result.output

        balances = _lot_balances(book)
        assert balances[named['-50.00']] == '-10.00', balances
        assert balances[named['-80.00']] == '-80.00', balances


class TestALotGuidNamingALotOfAnotherKind:
    def test_a_posted_invoices_lot_is_refused(self, tmp_path):
        """That lot is an invoice's, and settling it is the invoice's own
        business — a bare split moving into it would pay an invoice off
        with nothing in the file saying which invoice or how much."""
        book = _book(tmp_path)
        exported = _exported(book, tmp_path)
        posted = _a_posted_invoices_lot(book, tmp_path)

        edited = tmp_path / 'refund.txt'
        edited.write_text(exported + REFUND.format(lot_guid=posted),
                          encoding='utf-8')
        result = CliRunner().invoke(cli, ['import', str(book), str(edited),
                                          '--include-business-objects'])

        assert result.exit_code != 0, result.output
        message = str(result.output) + str(result.exception)
        assert posted in message, message
        assert "posted invoice's or bill's lot" in message, message

    def test_a_lot_on_another_account_is_refused(self, tmp_path):
        """A payable's lot named from a receivable's split.

        A receivable is not the payable beside it, and a settlement landing
        in a lot on another account is money moving where no account says
        it did.
        """
        book = _book(tmp_path)
        exported = _exported(book, tmp_path)
        payable = _lot_guids_by_value(exported)['20.00']

        edited = tmp_path / 'refund.txt'
        edited.write_text(exported + REFUND.format(lot_guid=payable),
                          encoding='utf-8')
        result = CliRunner().invoke(cli, ['import', str(book), str(edited),
                                          '--include-business-objects'])

        assert result.exit_code != 0, result.output
        message = str(result.output) + str(result.exception)
        assert payable in message, message
        assert 'not on' in message, message

    def test_a_credit_already_spent_is_refused(self, tmp_path):
        """A closed lot is a credit that has been used up.

        The one a real ledger meets: the deposit was spent months ago and a
        file still names its lot. Joined anyway, the settlement would sit
        in a lot that balances to nothing and the owner would appear to
        have money again.
        """
        book = _book(tmp_path)
        exported = _exported(book, tmp_path)
        named = _lot_guids_by_value(exported)

        spent = tmp_path / 'spent.txt'
        spent.write_text(exported + REFUND.format(
            lot_guid=named['-50.00']).replace('40.00', '50.00'),
            encoding='utf-8')
        assert CliRunner().invoke(cli, [
            'import', str(book), str(spent),
            '--include-business-objects']).exit_code == 0

        again = tmp_path / 'again.txt'
        again.write_text(_exported(book, tmp_path, 'now.txt')
                         + REFUND.format(lot_guid=named['-50.00']),
                         encoding='utf-8')
        result = CliRunner().invoke(cli, ['import', str(book), str(again),
                                          '--include-business-objects'])

        assert result.exit_code != 0, result.output
        message = str(result.output) + str(result.exception)
        assert 'already' in message and 'spent' in message, message


class TestGivingASplitInALotAnotherAccount:
    def test_is_refused(self, tmp_path):
        """Recategorising moves the split its block names — but not one
        sitting in a lot.

        Moved, the receivable's lot would hold a split that now lives on an
        expense account, and the check that a `lot_owner:` split is on an
        account of the right kind would have been stepped past. What such a
        split is doing is standing as an owner's credit, and moving it is
        that credit's business.
        """
        book = _book(tmp_path)
        exported = _exported(book, tmp_path)

        edited = tmp_path / 'moved.txt'
        edited.write_text(
            exported.replace('\tAssets:Accounts Receivable -50.00 CAD',
                             '\tExpenses:Refunds -50.00 CAD'),
            encoding='utf-8')
        result = CliRunner().invoke(cli, [
            'import', str(book), str(edited), '--include-business-objects',
            '--strategy', 'update'])

        assert result.exit_code != 0, result.output
        message = str(result.output) + str(result.exception)
        assert 'is in lot' in message, message
        assert 'another account' in message, message


class TestALotGuidWithNoLotOwner:
    def test_is_refused(self, tmp_path):
        """`lot_guid:` says *which* credit; `lot_owner:` says there is one.

        Alone, the line is read by nothing: it is not a slot, not acted on,
        and every later run says `unchanged` — a file asking for something
        and a book that never heard the question.
        """
        book = _book(tmp_path)
        exported = _exported(book, tmp_path)
        named = _lot_guids_by_value(exported)

        edited = tmp_path / 'orphaned.txt'
        edited.write_text(
            exported.replace(
                f'\t\tlot_owner: customer:C-LOT:{_the_customers_guid(exported)}'
                f'\n\t\tlot_guid: "{named["-50.00"]}"',
                f'\t\tlot_guid: "{named["-50.00"]}"'),
            encoding='utf-8')
        assert 'lot_guid' in edited.read_text(encoding='utf-8')
        result = CliRunner().invoke(cli, [
            'import', str(book), str(edited), '--include-business-objects',
            '--strategy', 'update'])

        assert result.exit_code != 0, result.output
        message = str(result.output) + str(result.exception)
        assert 'lot_owner' in message, message


class TestALotGuidWhoseOwnerNamesNoCustomerOrVendor:
    @pytest.mark.parametrize('owner', ['job:J1', 'customer:'])
    def test_is_refused(self, tmp_path, owner):
        """`lot_owner:` is acted on for a customer or a vendor, and for
        nothing else — so beside any other spelling the `lot_guid:` line
        would put the split in no lot, be stored nowhere, and read
        `unchanged` on every later run. The line with no `lot_owner:` at
        all is refused for that reason; this is the other way to write the
        same file.
        """
        book = _book(tmp_path)
        exported = _exported(book, tmp_path)
        named = _lot_guids_by_value(exported)

        edited = tmp_path / 'unusable.txt'
        edited.write_text(
            exported.replace(
                f'lot_owner: customer:C-LOT:{_the_customers_guid(exported)}',
                f'lot_owner: {owner}'),
            encoding='utf-8')
        text = edited.read_text(encoding='utf-8')
        assert f'lot_owner: {owner}' in text, text
        assert named['-50.00'] in text, text

        result = CliRunner().invoke(cli, [
            'import', str(book), str(edited), '--include-business-objects',
            '--strategy', 'update'])

        assert result.exit_code != 0, result.output
        message = str(result.output) + str(result.exception)
        assert 'lot_guid' in message, message
        assert 'customer or vendor' in message, message


class TestASplitAlreadyInALot:
    def test_cannot_be_moved_to_another_by_editing_its_lot_guid(self,
                                                                tmp_path):
        """Which lot a split is in is not something a re-import changes.

        A split that already sits in one is left alone — an exported credit
        carries `lot_owner:` and is in its owner's lot, and re-importing it
        over itself must not open a second. So a `lot_guid:` edited to name
        a different credit would do nothing at all, and the run would report
        the transaction updated: the file saying one thing and the book
        another, which is the silence this line exists to end. Moving money
        between credits is what an invoice's `payment:` block does, naming
        the split with `txn_split_guid:`.
        """
        book = _book(tmp_path)
        exported = _exported(book, tmp_path)
        named = _lot_guids_by_value(exported)

        edited = tmp_path / 'moved.txt'
        edited.write_text(
            exported.replace(f'lot_guid: "{named["-50.00"]}"',
                             f'lot_guid: "{named["-80.00"]}"'),
            encoding='utf-8')
        result = CliRunner().invoke(cli, [
            'import', str(book), str(edited), '--include-business-objects',
            '--strategy', 'update'])

        assert result.exit_code != 0, result.output
        message = str(result.output) + str(result.exception)
        assert named['-50.00'] in message, message
        assert named['-80.00'] in message, message


class TestALotGuidTheBookDoesNotHaveOnThatOwner:
    @pytest.mark.parametrize('named, said', [
        ('ab12ab12ab12ab12ab12ab12ab12ab12', 'names no lot in this book'),
        ('the customer', 'is an existing customer in this book, not a lot'),
        ('another owner', "names another owner's credit"),
    ])
    def test_is_refused(self, tmp_path, named, said):
        """A settlement may only take a credit that is there and is theirs.

        A guid the book has no lot for cannot be created here — a clearing
        split with nothing to reduce would be a credit invented out of a
        typo. Nor may it name a lot belonging to somebody else, or an object
        that is not a lot at all: the customer's own guid is the shape a
        confused file takes, since `lot_owner:` carries one two lines above.
        """
        book = _book(tmp_path)
        exported = _exported(book, tmp_path)
        if named == 'the customer':
            named = _the_customers_guid(exported)
        elif named == 'another owner':
            named = _lot_guids_by_value(exported)['-70.00']

        edited = tmp_path / 'refund.txt'
        edited.write_text(exported + REFUND.format(lot_guid=named),
                          encoding='utf-8')
        result = CliRunner().invoke(cli, ['import', str(book), str(edited),
                                          '--include-business-objects'])

        assert result.exit_code != 0, result.output
        message = str(result.output) + str(result.exception)
        assert named in message, message
        assert said in message, message
