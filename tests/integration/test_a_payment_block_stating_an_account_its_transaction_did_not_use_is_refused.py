"""A payment block stating its transaction and an account that transaction did not use is refused.

INV-001 is imported paid and exported, and its block is read back into the
same book with `bank_account:` changed to `Assets:Savings`. The block still
states the payment's transaction by `txn_guid:`, and that transaction moved the
money through `Assets:Bank`. The file and the book disagree about where the
money went.

Measured on 5.10 before this: the import unposted the invoice, destroyed its
posting transaction, posted it again under a new one and reported `updated`
with exit 0. The export still wrote `Assets:Bank`, so the edit was dropped,
and every later read of the same file did all of that again.

The same for a bill.
"""

import pytest
from click.testing import CliRunner

from cli.main import cli
from tests.integration.test_find_orphan_payments import ACCOUNTS, _fixture

SAVINGS = '''2026-01-01 open Assets:Savings
\ttype: Bank
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
'''


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _exported(book, out):
    assert _run('export', book, out, '--include-business-objects').exit_code == 0
    return out.read_text()


@pytest.mark.parametrize('fixture, record', [
    ('q014_invoice_posted_paid', 'invoice "INV-001"'),
    ('q014_bill_posted_paid', 'bill "BILL-001"'),
], ids=['invoice', 'bill'])
def test_it_is_refused_and_the_posting_is_kept(tmp_path, fixture, record):
    book = tmp_path / 'book.gnucash'
    source = tmp_path / 'in.txt'
    source.write_text(ACCOUNTS + SAVINGS + '\n' + _fixture(fixture))
    made = _run('import', '--new', book, source, '--include-business-objects')
    assert made.exit_code == 0, made.output
    before = _exported(book, tmp_path / 'before.txt')
    block = next(part for part in before.split('\n\n') if part.startswith(record))
    assert 'bank_account: "Assets:Bank"' in block, block
    edited = tmp_path / 'edited.txt'
    edited.write_text(block.replace('bank_account: "Assets:Bank"',
                                    'bank_account: "Assets:Savings"') + '\n')

    result = _run('import', book, edited, '--include-business-objects')

    assert result.exit_code != 0, result.output
    assert 'Assets:Savings' in result.output, result.output
    txn_guid = next(line.split(':', 1)[1].strip().strip('"')
                    for line in block.splitlines()
                    if line.strip().startswith('txn_guid:'))
    assert txn_guid in result.output, result.output
    after = _exported(book, tmp_path / 'after.txt')
    posting = next(line for line in block.splitlines() if 'posted_txn_guid:' in line)
    assert posting in after, after
