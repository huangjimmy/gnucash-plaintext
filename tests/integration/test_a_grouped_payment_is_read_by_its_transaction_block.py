"""A payment written as a `Transaction` block is read by that block and nothing beside it.

`a_payment_giving_two_settling_splits.txt` pays INV-USD-001 with two splits of
one transaction, given as `PaymentSplit` lines under a `Transaction` block. A
split given there has to be one of that transaction's. And where the block
also carries `txn_split_guid:`, the key is not read, and the run says so.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from tests.integration.test_linking_a_split_not_on_the_receivable import (  # noqa: F401
    AR,
    NAMES_TWO_SPLITS,
    TWO_SPLITS,
    _each_split_of,
    book,
)

NO_SUCH_SPLIT = '0123456789abcdef0123456789abcdef'


def _paid_with(book, tmp_path, old, new):
    assert CliRunner().invoke(cli, ['import', str(book), TWO_SPLITS]).exit_code == 0
    text = Path(NAMES_TWO_SPLITS).read_text()
    assert old in text, text
    ledger = tmp_path / 'payment.txt'
    ledger.write_text(text.replace(old, new))
    return CliRunner().invoke(cli, ['import', str(book), str(ledger),
                                    '--include-business-objects'])


def test_a_payment_split_that_is_not_the_transactions_is_refused(book, tmp_path):
    result = _paid_with(
        book, tmp_path,
        'PaymentSplit "8192a3b4c5d6e7f80912233445566778"',
        f'PaymentSplit "{NO_SUCH_SPLIT}"')

    assert result.exit_code != 0, result.output
    assert (f"PaymentSplit '{NO_SUCH_SPLIT}' is not a split of tx "
            "'5e6f708192a3b4c5d6e7f80912233445'") in result.output, result.output


def test_a_split_key_beside_the_block_is_not_read_and_the_run_says_so(book, tmp_path):
    result = _paid_with(
        book, tmp_path,
        '    account: "Assets:Bank:USD"\n',
        '    account: "Assets:Bank:USD"\n'
        '    txn_split_guid: "708192a3b4c5d6e7f809122334455667"\n')

    assert result.exit_code == 0, result.output
    assert ('`txn_guid:` and `txn_split_guid:` are not read where a `Transaction` block'
            in result.output), result.output
    rows = _each_split_of(book, 'Money in, two lines')
    receivables = [row for row in rows if row['account'] == AR]
    assert all(row['in_a_lot'] for row in receivables), receivables
