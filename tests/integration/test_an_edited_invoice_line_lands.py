"""Editing a line of an invoice in the ledger and importing again must land.

Re-importing asks of every invoice "does the book already say this?", and
answers field by field. A field left out of that comparison is one a person
can change in the ledger, import, and see reported `unchanged` — the invoice
keeps the old figure, the invoice is not rebuilt, and nothing says so. On a
priced line that is a wrong invoice.

So every field of an invoice line is edited here, one per invoice, and each
has to come back changed.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner
from gnucash import Query
from gnucash import gnucash_business as gb

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository, SessionMode

FIXTURES = Path('tests/fixtures')
BEFORE = str(FIXTURES / 'invoice_lines_before_an_edit.txt')
AFTER = str(FIXTURES / 'invoice_lines_after_an_edit.txt')


def _line_of(book, invoice_id):
    """The one entry of one invoice, as the book holds it."""
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('gncInvoice')
        query.set_book(repo.book)
        for raw in query.run():
            invoice = gb.Invoice(instance=raw)
            if invoice.GetID() != invoice_id:
                continue
            entry = list(invoice.GetEntries())[0]
            table = entry.GetInvTaxTable() if entry.GetInvTaxable() else None
            found = {
                'date': entry.GetDate().strftime('%Y-%m-%d'),
                'description': entry.GetDescription(),
                'action': entry.GetAction(),
                'account': entry.GetInvAccount().get_full_name(),
                'quantity': str(entry.GetQuantity()),
                'price': str(entry.GetInvPrice()),
                'taxable': bool(entry.GetInvTaxable()),
                'tax_included': bool(entry.GetInvTaxIncluded()),
                'tax_table': table.GetName() if table is not None else None,
            }
            query.destroy()
            return found
        query.destroy()
        raise AssertionError(f'no invoice {invoice_id}')
    finally:
        repo.close()


@pytest.fixture
def book(tmp_path):
    path = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(cli, [
        'import', '--new', str(path), BEFORE, '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return path


@pytest.fixture
def edited(book):
    result = CliRunner().invoke(cli, [
        'import', str(book), AFTER, '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return book


class TestEachFieldOfALine:
    @pytest.mark.parametrize('invoice_id,field,value', [
        ('INV-DATE', 'date', '2026-01-08'),
        ('INV-DESC', 'description', 'A different line'),
        ('INV-ACTION', 'action', 'Days'),
        ('INV-ACCOUNT', 'account', 'Income.Other'),
        ('INV-TAXABLE', 'taxable', False),
        ('INV-INCLUDED', 'tax_included', True),
        ('INV-TABLE', 'tax_table', 'PST'),
    ])
    def test_the_edit_is_in_the_book(self, edited, invoice_id, field, value):
        assert _line_of(edited, invoice_id)[field] == value, \
            _line_of(edited, invoice_id)

    def test_the_quantity_is_the_edited_one(self, edited):
        """As a number: GnuCash is free to hold 3 as 3/1 or 300/100."""
        from fractions import Fraction
        quantity = _line_of(edited, 'INV-QUANTITY')['quantity']
        assert Fraction(quantity) == 3, quantity

    def test_the_price_is_the_edited_one(self, edited):
        from fractions import Fraction
        price = _line_of(edited, 'INV-PRICE')['price']
        assert Fraction(price) == 125, price


class TestWhatIsNotEdited:
    def test_the_untouched_fields_stay(self, edited):
        """One field changed is one field changed, not a rewrite."""
        line = _line_of(edited, 'INV-PRICE')

        assert line['description'] == 'A line', line
        assert line['account'] == 'Income.Sales', line

    def test_the_edited_file_settles_too(self, edited):
        """The invoice side of the same question."""
        again = CliRunner().invoke(cli, [
            'import', str(edited), AFTER, '--include-business-objects'])
        assert again.exit_code == 0, again.output

        updated = [line for line in again.output.splitlines()
                   if line.startswith('invoice ') and 'updated' in line]
        assert not updated, again.output

    def test_importing_the_same_file_twice_changes_nothing(self, book):
        again = CliRunner().invoke(cli, [
            'import', str(book), BEFORE, '--include-business-objects'])

        assert again.exit_code == 0, again.output
        assert 'unchanged' in again.output, again.output
