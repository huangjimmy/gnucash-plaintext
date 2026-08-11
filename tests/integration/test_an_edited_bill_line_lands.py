"""Editing a line of a bill in the ledger and importing again must land.

The mirror of the invoice case, and the same question: a field left out of the
comparison that answers "does the book already say this?" is a field a person
can change in the ledger, import, and see reported `unchanged`.

Two of them were left out. The bill comparison skipped `taxable:` and
`tax_included:`, on the reasoning that GnuCash could not persist a bill
entry's tax flags — which was true of a vendor bill handled as a customer
invoice, and is not true of one handled as a bill (CLAUDE.md §8). Both are
written on import and both are read back, so untaxing a bill line in the
ledger reported `unchanged` and left it taxed.
"""

from fractions import Fraction
from pathlib import Path

import pytest
from click.testing import CliRunner
from gnucash import Query
from gnucash import gnucash_business as gb

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository, SessionMode

FIXTURES = Path('tests/fixtures')
BEFORE = str(FIXTURES / 'bill_lines_before_an_edit.txt')
AFTER = str(FIXTURES / 'bill_lines_after_an_edit.txt')


def _line_of(book, bill_id):
    """The one entry of one bill, as the book holds it."""
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('gncInvoice')
        query.set_book(repo.book)
        for raw in query.run():
            bill = gb.Bill(instance=raw)
            if bill.GetID() != bill_id:
                continue
            entry = list(bill.GetEntries())[0]
            table = entry.GetBillTaxTable() if entry.GetBillTaxable() else None
            found = {
                'date': entry.GetDate().strftime('%Y-%m-%d'),
                'description': entry.GetDescription(),
                'account': entry.GetBillAccount().get_full_name(),
                'quantity': str(entry.GetQuantity()),
                'price': str(entry.GetBillPrice()),
                'taxable': bool(entry.GetBillTaxable()),
                'tax_included': bool(entry.GetBillTaxIncluded()),
                'tax_table': table.GetName() if table is not None else None,
            }
            query.destroy()
            return found
        query.destroy()
        raise AssertionError(f'no bill {bill_id}')
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
    @pytest.mark.parametrize('bill_id,field,value', [
        ('BILL-DATE', 'date', '2026-01-08'),
        ('BILL-DESC', 'description', 'A different line'),
        ('BILL-ACCOUNT', 'account', 'Expenses.Travel'),
        ('BILL-TAXABLE', 'taxable', False),
        ('BILL-INCLUDED', 'tax_included', True),
        ('BILL-TABLE', 'tax_table', 'PST'),
    ])
    def test_the_edit_is_in_the_book(self, edited, bill_id, field, value):
        assert _line_of(edited, bill_id)[field] == value, \
            _line_of(edited, bill_id)

    def test_the_quantity_is_the_edited_one(self, edited):
        quantity = _line_of(edited, 'BILL-QUANTITY')['quantity']
        assert Fraction(quantity) == 3, quantity

    def test_the_price_is_the_edited_one(self, edited):
        price = _line_of(edited, 'BILL-PRICE')['price']
        assert Fraction(price) == 125, price


class TestWhatIsNotEdited:
    def test_the_untouched_fields_stay(self, edited):
        line = _line_of(edited, 'BILL-PRICE')

        assert line['description'] == 'A line', line
        assert line['account'] == 'Expenses.Supplies', line

    def test_the_edited_file_settles_too(self, edited):
        """Importing the edited file again must find nothing left to do.

        The `before` file is all `taxable: true`, so re-importing it never
        meets a line that is untaxed *and* names a tax table — which is the
        combination a comparison can disagree with the writer about. On a
        posted document that disagreement is not a wrong number: it unposts,
        destroys the posting, orphans the payments and rebuilds, every run.
        """
        again = CliRunner().invoke(cli, [
            'import', str(edited), AFTER, '--include-business-objects'])
        assert again.exit_code == 0, again.output

        updated = [line for line in again.output.splitlines()
                   if line.startswith('bill ') and 'updated' in line]
        assert not updated, again.output

    def test_importing_the_same_file_twice_changes_nothing(self, book):
        again = CliRunner().invoke(cli, [
            'import', str(book), BEFORE, '--include-business-objects'])

        assert again.exit_code == 0, again.output
        assert 'unchanged' in again.output, again.output
