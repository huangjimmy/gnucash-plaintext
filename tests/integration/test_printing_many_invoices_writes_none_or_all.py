"""A refused figure must not leave a directory of half the pages.

`print-invoice … -o out/` and `print-bill … -o out/` write one file per
page. A printed `payment:` block now states the amount at the unit its
account is kept to, and refuses a figure the currency cannot hold — the same
answer the export gives — so rendering can stop partway through a run.

Writing inside the loop, what it stopped partway through was the directory: the
pages before the offender were on disk, the ones after it were not, and the
refusal said nothing about which. A reader who sends that directory on has a
set of pages that looks complete.

`export` was given the same treatment for the same reason and says so at
`cli/export_cmd.py`: it renders in full before opening the target, because
opening first meant a good ledger was truncated by an export that then refused.
The combined form of these two commands already builds every page into a
list before writing; only the per-page form did not.
"""

import os

import pytest
from click.testing import CliRunner

from cli.main import cli
from tests.integration.test_export_refuses_what_it_cannot_write import (
    _move_a_receivable_split,
    _overpaid_invoice_book,
)


def _two_invoices_one_unwritable():
    """Two overpaid invoices; the second settled by a figure CAD cannot hold.

    The first stays writable on purpose — a book where every page is
    refused cannot tell a run that wrote nothing from a run that stopped at
    the first page.
    """
    import tempfile
    from pathlib import Path

    path = _overpaid_invoice_book()
    second = (Path('tests/fixtures/overpaid_invoice_on_a_finer_account.txt')
              .read_text()
              .replace('INV-FINE-OVER', 'INV-FINE-TWO')
              .replace('price: 30', 'price: 40')
              .replace('amount: 50.00', 'amount: 55.00')
              .replace('prepayment: 20.00', 'prepayment: 15.00'))
    with tempfile.NamedTemporaryFile('w', suffix='.txt',
                                     delete=False) as handle:
        handle.write(second)
        ledger = handle.name
    try:
        result = CliRunner().invoke(cli, [
            'import', path, ledger, '--include-business-objects'])
        assert result.exit_code == 0, result.output
    finally:
        os.unlink(ledger)
    return _move_a_receivable_split(path, -4000, -40005)


def _move_a_payable_split(path, cents, thousandths):
    """Move the A/P split holding `cents` to `thousandths`, through GnuCash.

    `_move_a_receivable_split`'s twin, and moved the same way and for the same
    reason: the account's unit takes the figure, the GUI writes it, and this
    tool's importer will not.
    """
    from gnucash import GncNumeric, Query, Session, Transaction

    session = Session(f'xml://{path}')
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(session.book)
        moved = 0
        for raw in query.run():
            transaction = Transaction(instance=raw)
            for split in transaction.GetSplitList():
                amount = split.GetAmount()
                if 'Payable' not in split.GetAccount().get_full_name():
                    continue
                if amount.num() * 100 != cents * amount.denom():
                    continue
                transaction.BeginEdit()
                split.SetAmount(GncNumeric(thousandths, 1000))
                split.SetValue(GncNumeric(thousandths, 1000))
                transaction.CommitEdit()
                moved += 1
        query.destroy()
        assert moved == 1, f'expected one split at {cents / 100}, moved {moved}'
        session.save()
    finally:
        session.end()
    return path


def _bills_book():
    """Two overpaid bills on a payable kept to thousandths."""
    import tempfile

    fd, path = tempfile.mkstemp(suffix='.gnucash')
    os.close(fd)
    os.unlink(path)
    result = CliRunner().invoke(cli, [
        'import', '--new', path,
        'tests/fixtures/overpaid_bills_on_a_payable_kept_finer.txt',
        '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return path


@pytest.fixture
def book_with_one_unwritable_invoice():
    path = _two_invoices_one_unwritable()
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def book_with_one_unwritable_bill():
    """The second bill's settling split moved to 40.005."""
    path = _move_a_payable_split(_bills_book(), 4000, 40005)
    yield path
    if os.path.exists(path):
        os.unlink(path)


class TestPrintingInvoicesOneFileEach:
    def test_the_run_is_refused(self, book_with_one_unwritable_invoice,
                                tmp_path):
        outdir = tmp_path / 'out'
        result = CliRunner().invoke(cli, [
            'print-invoice', book_with_one_unwritable_invoice, '*',
            '--format', 'plaintext', '-o', f'{outdir}/'])

        assert result.exit_code != 0, result.output
        assert '40.005' in result.output, result.output

    def test_it_leaves_no_pages_behind(self,
                                           book_with_one_unwritable_invoice,
                                           tmp_path):
        """Neither the good one nor the bad one — the run wrote nothing."""
        outdir = tmp_path / 'out'
        CliRunner().invoke(cli, [
            'print-invoice', book_with_one_unwritable_invoice, '*',
            '--format', 'plaintext', '-o', f'{outdir}/'])

        written = sorted(p.name for p in outdir.iterdir()) if outdir.exists() \
            else []
        assert written == [], written

    def test_a_book_it_can_write_still_writes_every_page(self, tmp_path):
        """The good path is unchanged: one file per page, all of them."""
        book = _overpaid_invoice_book()
        try:
            outdir = tmp_path / 'ok'
            result = CliRunner().invoke(cli, [
                'print-invoice', book, '*', '--format', 'plaintext',
                '-o', f'{outdir}/'])

            assert result.exit_code == 0, result.output
            assert sorted(p.name for p in outdir.iterdir()) == [
                'INV-FINE-OVER.txt']
        finally:
            if os.path.exists(book):
                os.unlink(book)


class TestPrintingBillsOneFileEach:
    """The same command on the other side of the ledger, and the same rule."""

    def test_the_run_is_refused(self, book_with_one_unwritable_bill, tmp_path):
        outdir = tmp_path / 'out'
        result = CliRunner().invoke(cli, [
            'print-bill', book_with_one_unwritable_bill, '*',
            '--format', 'plaintext', '-o', f'{outdir}/'])

        assert result.exit_code != 0, result.output
        assert '40.005' in result.output, result.output

    def test_it_leaves_no_pages_behind(self, book_with_one_unwritable_bill,
                                           tmp_path):
        outdir = tmp_path / 'out'
        CliRunner().invoke(cli, [
            'print-bill', book_with_one_unwritable_bill, '*',
            '--format', 'plaintext', '-o', f'{outdir}/'])

        written = sorted(p.name for p in outdir.iterdir()) if outdir.exists() \
            else []
        assert written == [], written

    def test_a_book_it_can_write_still_writes_every_page(self, tmp_path):
        book = _bills_book()
        try:
            outdir = tmp_path / 'ok'
            result = CliRunner().invoke(cli, [
                'print-bill', book, '*', '--format', 'plaintext',
                '-o', f'{outdir}/'])

            assert result.exit_code == 0, result.output
            assert sorted(p.name for p in outdir.iterdir()) == [
                'BILL-FINE-ONE.txt', 'BILL-FINE-TWO.txt']
        finally:
            if os.path.exists(book):
                os.unlink(book)
