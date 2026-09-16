"""A customer's credit whose transaction has no bank split is still listed.

`find-prepayments` reports each credit with the bank account its money came
through, read off its transaction. A credit can be made without one: a journal
entry moving 50.00 from the plain receivable onto C001, the receivable against
itself. There is no bank account to report, and the credit is listed all the
same, under its owner.
"""

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'
CUSTOMER = 'tests/fixtures/customer_c001_acme.txt'
MOVED = 'tests/fixtures/a_credit_moved_from_the_receivable_onto_a_customer.txt'


def test_it_is_listed_under_its_owner(tmp_path):
    book = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), ACCOUNTS])
    assert made.exit_code == 0, made.output
    customer = CliRunner().invoke(cli, ['import', str(book), CUSTOMER,
                                        '--include-business-objects'])
    assert customer.exit_code == 0, customer.output
    moved = CliRunner().invoke(cli, ['import', str(book), MOVED])
    assert moved.exit_code == 0, moved.output

    listed = CliRunner().invoke(cli, ['find-prepayments', str(book)])

    assert listed.exit_code == 0, listed.output
    assert 'Found 1 open pre-payment credit.' in listed.output, listed.output
    assert 'C001' in listed.output, listed.output
    assert 'CAD 50.00' in listed.output, listed.output
