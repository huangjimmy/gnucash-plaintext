"""A transaction marked as a payment, with no receivable or payable split, is no orphan.

`find-orphan-payments` lists a payment an unpost left behind: money on a
receivable or a payable whose invoice or bill is no longer posted. A ledger can
mark any transaction `txn_type: P`, and this one moves 10.00 from the bank to
an expense account. Nothing of it was ever on a receivable, so no unpost can
have left it there, and it is not listed.
"""

from click.testing import CliRunner

from cli.main import cli

LEDGER = 'tests/fixtures/txn_type_payment_plain.txt'


def test_it_is_not_listed(tmp_path):
    book = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), LEDGER])
    assert made.exit_code == 0, made.output

    result = CliRunner().invoke(cli, ['find-orphan-payments', str(book)])

    assert result.exit_code == 0, result.output
    assert 'No orphan bank-side payment transactions found' in result.output, \
        result.output
