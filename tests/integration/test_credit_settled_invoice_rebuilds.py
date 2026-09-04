"""An invoice settled from an owner's credit survives being rebuilt.

Exporting a book and importing it into a fresh one is how this tool moves a
book, and an invoice settled out of credit used to come back unpaid: the
export said `payment: none` with `auto_apply_credit: true` above it, so the
rebuild asked GnuCash to apply the credit again. Re-applying it on a book
where it is already applied left every invoice of that owner with a `postlot`
pointing at a lot the file does not contain, which GnuCash drops on load —
`invoice_postlot_handler: assertion 'lot' failed` — so the invoices came back
with no lot at all and `IsPaid = False`, including ones settled by an ordinary
bank payment.

The export now records what settled the invoice instead of the request that
settled it, and the rebuild attaches that same split to that same lot.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from tests.conftest import a_ledger_without_the_day_it_was_written

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'
FIXTURES = Path('tests/fixtures')


def _import(runner, book, fixture, tmp_path, new=False):
    path = tmp_path / fixture
    path.write_text((FIXTURES / fixture).read_text())
    args = ['import'] + (['--new'] if new else []) + [str(book), str(path),
                                                      '--include-business-objects']
    result = runner.invoke(cli, args)
    assert result.exit_code == 0, result.output
    return result


def _export(runner, book, tmp_path, name):
    out = tmp_path / name
    result = runner.invoke(cli, ['export', str(book), str(out),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return out


def _settled(book):
    """{invoice id: (lot balance as a string, IsPaid)} for every invoice."""
    from gnucash import Query

    from infrastructure.gnucash.utils import wrap_invoice_or_bill

    repo = GnuCashRepository(str(book), )
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('gncInvoice')
        query.set_book(repo.book)
        found = {}
        for raw in query.run():
            invoice = wrap_invoice_or_bill(raw)
            lot = invoice.GetPostedLot()
            found[invoice.GetID()] = (
                None if lot is None else str(lot.get_balance()),
                invoice.IsPaid())
        query.destroy()
        return found
    finally:
        repo.close()


def _credit_book(runner, tmp_path, kind='invoice'):
    """A book where one invoice was settled out of the owner's credit."""
    book = tmp_path / f'{kind}.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(book), ACCOUNTS]).exit_code == 0
    if kind == 'invoice':
        _import(runner, book, 'q015_aac_primer_invoice.txt', tmp_path)
        _import(runner, book, 'q015_aac_inv002_partial_credit.txt', tmp_path)
    else:
        _import(runner, book, 'q015_aac_primer_bill.txt', tmp_path)
        _import(runner, book, 'q015_aac_bill002_partial_credit.txt', tmp_path)
    return book


def test_invoice_settled_from_credit_comes_back_settled(tmp_path):
    runner = CliRunner()
    book = _credit_book(runner, tmp_path, 'invoice')
    before = _settled(book)
    assert before == {'INV-001': ('0/100', True), 'INV-002': ('0/100', True)}, before

    exported = _export(runner, book, tmp_path, 'out.txt')
    rebuilt = tmp_path / 'rebuilt.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(rebuilt), str(exported),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output

    assert _settled(rebuilt) == before, (
        f'rebuild lost which payments settled it.\nbefore: {before}\n'
        f'after:  {_settled(rebuilt)}')

    # And the rebuilt book exports to the same file it was built from, so a
    # third generation says the same thing as the first.
    again = _export(runner, rebuilt, tmp_path, 'out2.txt')
    # Without the day each was written on: an account and a commodity have no
    # date of their own, so the export stamps the day it runs, and two
    # exports either side of midnight differ over that alone.
    assert a_ledger_without_the_day_it_was_written(again.read_text()) == \
        a_ledger_without_the_day_it_was_written(exported.read_text())


def test_bill_settled_from_credit_comes_back_settled(tmp_path):
    runner = CliRunner()
    book = _credit_book(runner, tmp_path, 'bill')
    before = _settled(book)
    assert before == {'BILL-001': ('0/100', True), 'BILL-002': ('0/100', True)}, before

    exported = _export(runner, book, tmp_path, 'out.txt')
    rebuilt = tmp_path / 'rebuilt.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(rebuilt), str(exported),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output

    assert _settled(rebuilt) == before, (
        f'rebuild lost which payments settled it.\nbefore: {before}\n'
        f'after:  {_settled(rebuilt)}')
    again = _export(runner, rebuilt, tmp_path, 'out2.txt')
    # Without the day each was written on: an account and a commodity have no
    # date of their own, so the export stamps the day it runs, and two
    # exports either side of midnight differ over that alone.
    assert a_ledger_without_the_day_it_was_written(again.read_text()) == \
        a_ledger_without_the_day_it_was_written(exported.read_text())


def test_a_invoice_settled_by_a_divided_credit_comes_back_settled(tmp_path):
    """The split shape a division makes has to rebuild like any other.

    Dividing a credit leaves the transaction carrying three splits — the bank
    side, the part that settled the invoice, and the credit parked for what
    was left — and a rebuild is where this whole area has failed silently
    before: every invoice of an owner coming back unpaid, with nothing in
    the file to say so.
    """
    from gnucash import Query, Transaction

    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(book), ACCOUNTS]).exit_code == 0
    _import(runner, book, 'q015_aac_primer_invoice.txt', tmp_path)

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        txn_guid = split_guid = None
        for raw in query.run():
            transaction = Transaction(instance=raw)
            for split in transaction.GetSplitList():
                if str(split.GetAmount()) != '-5000/100':
                    continue
                txn_guid = transaction.GetGUID().to_string()
                split_guid = split.GetGUID().to_string()
        query.destroy()
    finally:
        repo.close()
    assert split_guid is not None

    text = ((FIXTURES / 'credit_payment_bigger_than_the_invoice.txt').read_text()
            .replace('TXN_GUID', txn_guid).replace('SPLIT_GUID', split_guid))
    path = tmp_path / 'divides.txt'
    path.write_text(text)
    assert runner.invoke(cli, ['import', str(book), str(path),
                               '--include-business-objects']).exit_code == 0

    before = _settled(book)
    assert before['INV-CREDIT-OVERPAID'] == ('0/100', True), before

    exported = _export(runner, book, tmp_path, 'out.txt')
    rebuilt = tmp_path / 'rebuilt.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(rebuilt), str(exported),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output
    assert _settled(rebuilt) == before, (
        f'rebuild lost the settlement.\nbefore: {before}\n'
        f'after:  {_settled(rebuilt)}')

    # And the customer's 20.00 is still theirs in the rebuilt book.
    prepayments = runner.invoke(cli, ['find-prepayments', str(rebuilt)])
    assert prepayments.exit_code == 0, prepayments.output
    assert 'CAD 20.00' in prepayments.output, prepayments.output

    # The rebuilt book says the same file back — the split a division mints
    # carries two keys no other shape has, and they go out through the same
    # generic KVP path as everything else.
    again = _export(runner, rebuilt, tmp_path, 'out2.txt')
    # Without the day each was written on: an account and a commodity have no
    # date of their own, so the export stamps the day it runs, and two
    # exports either side of midnight differ over that alone.
    assert a_ledger_without_the_day_it_was_written(again.read_text()) == \
        a_ledger_without_the_day_it_was_written(exported.read_text())


def test_the_credit_left_over_stays_the_owners(tmp_path):
    """Rebuilding spends no more of the credit than the file says was spent."""
    runner = CliRunner()
    book = _credit_book(runner, tmp_path, 'invoice')
    exported = _export(runner, book, tmp_path, 'out.txt')
    rebuilt = tmp_path / 'rebuilt.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(rebuilt), str(exported),
                               '--include-business-objects']).exit_code == 0

    prepayments = runner.invoke(cli, ['find-prepayments', str(rebuilt)])
    assert prepayments.exit_code == 0, prepayments.output
    # 150.00 paid against a 100.00 invoice left 50.00, of which 30.00 settled
    # INV-002.
    assert '20.00' in prepayments.output, prepayments.output
