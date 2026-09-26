"""A `lot_owner:` that states no customer or vendor is refused, not read as nothing.

`lot_owner:` says a split is an owner's credit, and puts it in a lot of
theirs. The owner is written as `customer:ID` or `vendor:ID`. Written as an ID
with no kind, or as an employee, it states neither, so no lot could be found or
made, and the split would be imported loose while the file says it is somebody's
credit.
"""

import pytest
from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'


@pytest.mark.parametrize('fixture, description', [
    ('tests/fixtures/a_credit_whose_lot_owner_states_no_kind.txt',
     'Prepayment with an owner of no kind'),
    ('tests/fixtures/a_credit_whose_lot_owner_is_an_employee.txt',
     'Prepayment owned by an employee'),
], ids=['no-kind', 'employee'])
def test_the_transaction_is_refused(tmp_path, fixture, description):
    book = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), ACCOUNTS])
    assert made.exit_code == 0, made.output

    result = CliRunner().invoke(cli, ['import', str(book), fixture])

    assert '`customer:ID` or `vendor:ID`' in result.output, result.output
    out = tmp_path / 'out.txt'
    assert CliRunner().invoke(cli, ['export', str(book), str(out)]).exit_code == 0
    assert description not in out.read_text(), out.read_text()


def test_restating_a_transaction_with_one_is_refused_too(tmp_path):
    """Over a transaction the book already holds, with `--strategy update`."""
    book = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), ACCOUNTS])
    assert made.exit_code == 0, made.output
    booked = CliRunner().invoke(cli, [
        'import', str(book), 'tests/fixtures/a_receipt_booked_to_the_receivable_with_its_guid.txt'])
    assert booked.exit_code == 0, booked.output

    result = CliRunner().invoke(cli, [
        'import', str(book), 'tests/fixtures/the_same_receipt_with_a_lot_owner_of_no_kind.txt',
        '--strategy', 'update'])

    assert '`customer:ID` or `vendor:ID`' in result.output, result.output
    out = tmp_path / 'out.txt'
    assert CliRunner().invoke(cli, ['export', str(book), str(out)]).exit_code == 0
    assert 'lot_owner' not in out.read_text(), out.read_text()
