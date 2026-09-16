"""A `lot_owner:` whose ID and guid are two different customers is refused.

`lot_owner: customer:ID:guid` gives the owner by both, and the guid decides.
Where the ID is C001's and the guid is C002's, the line says two things about
whose credit the split is, so the import refuses the transaction rather than
choose.
"""

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'
CUSTOMERS = 'tests/fixtures/two_customers_with_their_guids.txt'
CREDIT = 'tests/fixtures/a_credit_whose_lot_owner_gives_one_customers_id_and_anothers_guid.txt'


def test_the_transaction_is_refused(tmp_path):
    book = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), ACCOUNTS])
    assert made.exit_code == 0, made.output
    customers = CliRunner().invoke(cli, ['import', str(book), CUSTOMERS,
                                         '--include-business-objects'])
    assert customers.exit_code == 0, customers.output

    result = CliRunner().invoke(cli, ['import', str(book), CREDIT])

    assert ("lot_owner customer id 'C001' and guid "
            "'c2c2c2c2c2c2c2c2c2c2c2c2c2c2c2c2' resolve to different customers"
            in result.output), result.output
    out = tmp_path / 'out.txt'
    assert CliRunner().invoke(cli, ['export', str(book), str(out)]).exit_code == 0
    assert 'given to two customers' not in out.read_text(), out.read_text()
