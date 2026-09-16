"""A 0.00 split put in a paid invoice's lot is exported as a payment from its bank.

GnuCash's View → Lots offers every split that is in no lot, and "add split to
lot" calls `gnc_lot_add_split` inside the account's edit, with no scrub
(`lv_add_split_to_lot_cb` in `dialog-lot-viewer.c`). So a 0.00 receivable
split can sit in INV-001's lot until Check & Repair destroys it. The test
builds that book with the same two calls.

The export reads where a payment's money came from by the sign opposite the
settling split, and a split of nothing has no sign. So the account comes from
the type order alone: the bank. What the export writes has to read back as
the same invoice, in a new book as in its own.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.engine import load_gnc_engine
from infrastructure.gnucash.utils import qof_pointer
from repositories.gnucash_repository import GnuCashRepository
from services.foreign_currency import iter_splits
from services.gnucash_importer import _find_invoices_by_id
from tests.integration.test_find_orphan_payments import ACCOUNTS, _fixture

NOTHING = 'tests/fixtures/a_line_of_nothing_on_the_receivable.txt'


def _invoice_block(text):
    start = text.index('invoice "INV-001"')
    return text[start:text.index('\n\n', start)]


def _export(book, out):
    result = CliRunner().invoke(cli, ['export', str(book), str(out),
                                      '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return out.read_text()


def _a_book_with_a_split_of_nothing_in_the_lot(tmp_path):
    book = tmp_path / 'book.gnucash'
    source = tmp_path / 'in.txt'
    source.write_text(ACCOUNTS + '\n' + _fixture('q014_invoice_posted_paid') + '\n'
                      + Path(NOTHING).read_text())
    made = CliRunner().invoke(cli, ['import', '--new', str(book), str(source),
                                    '--include-business-objects'])
    assert made.exit_code == 0, made.output

    lib = load_gnc_engine()
    repo = GnuCashRepository(str(book))
    repo.open()
    try:
        lot = _find_invoices_by_id(repo.book, 'INV-001')[0].GetPostedLot()
        nothing = next(split for split in iter_splits(repo.book)
                       if split.GetParent().GetDescription() == 'A line of nothing'
                       and split.GetAccount().GetName() == 'Accounts Receivable')
        account = nothing.GetAccount()
        account.BeginEdit()
        lib.gnc_lot_add_split(qof_pointer(lot), int(nothing.instance))
        account.CommitEdit()
        assert nothing.GetLot() is not None
        repo.save()
    finally:
        repo.close()
    return book


def test_the_split_of_nothing_is_a_payment_from_the_bank(tmp_path):
    book = _a_book_with_a_split_of_nothing_in_the_lot(tmp_path)

    invoice = _invoice_block(_export(book, tmp_path / 'out.txt'))

    assert ('\tpayment:\n\t\tdate: 2026-01-20\n\t\tamount: 0.00\n'
            '\t\tbank_account: "Assets:Bank"\n') in invoice, invoice


def test_the_export_reads_back_as_the_same_invoice_in_a_new_book(tmp_path):
    book = _a_book_with_a_split_of_nothing_in_the_lot(tmp_path)
    exported = _export(book, tmp_path / 'out.txt')

    fresh = tmp_path / 'fresh.gnucash'
    rebuilt = CliRunner().invoke(cli, ['import', '--new', str(fresh),
                                       str(tmp_path / 'out.txt'),
                                       '--include-business-objects'])
    assert rebuilt.exit_code == 0, rebuilt.output

    assert (_invoice_block(_export(fresh, tmp_path / 'again.txt'))
            == _invoice_block(exported))
