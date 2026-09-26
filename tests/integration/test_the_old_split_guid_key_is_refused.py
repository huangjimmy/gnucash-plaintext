"""`split_guid:` on a split is refused, and the refusal states the key's new name.

A split states its guid with `guid:`. A ledger written before the key was
renamed still says `split_guid:`, and read as a custom key it would be stored
on the split while GnuCash assigned the split a guid of its own.
"""

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'
LEDGER = 'tests/fixtures/a_split_stating_the_old_split_guid_key.txt'


def test_the_transaction_is_refused_with_the_new_name(tmp_path):
    book = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), ACCOUNTS])
    assert made.exit_code == 0, made.output

    result = CliRunner().invoke(cli, ['import', str(book), LEDGER])

    assert 'split_guid: is no longer accepted on a split' in result.output, result.output
    assert 'guid:' in result.output, result.output
    exported = tmp_path / 'out.txt'
    assert CliRunner().invoke(cli, ['export', str(book), str(exported)]).exit_code == 0
    assert 'Cash sale' not in exported.read_text(), exported.read_text()
