"""A payment block stating an account an earlier block of the same invoice emptied is refused.

INV-150's first payment block moves a deposit's 100.00 suspense split onto the
receivable. Its second block states the deposit's 50.00 clearing split and says
the money is in `Assets:Suspense`. The check made when the file is read passes,
because the deposit still has a split there. When the second block is applied it
has none, and a parked split's worth is read from the split on the account the
block states. Measured on 5.10: the import is refused with that account and the
deposit's guid, and nothing is imported.
"""

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'
TWO_BLOCKS = 'tests/fixtures/inv_150_stating_an_account_its_first_payment_emptied.txt'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def test_the_second_block_is_refused_and_nothing_is_imported(tmp_path):
    book = tmp_path / 'book.gnucash'
    assert _run('import', '--new', book, ACCOUNTS).exit_code == 0

    result = _run('import', book, TWO_BLOCKS, '--include-business-objects')

    assert result.exit_code != 0, result.output
    assert ("this block says the money is in 'Assets:Suspense', and tx "
            "'a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9' has no split on that account. "
            "What a parked split is worth is read from the one that received "
            "the money") in result.output, result.output
    exported = _run('export', book, tmp_path / 'out.txt')
    assert 'Exported 0 transaction(s)' in exported.output, exported.output
