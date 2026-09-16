"""A credit block read back with an account or a date is refused, as it is when applied.

A `from_credit:` block spends a credit the book already holds, so it gives no
account and no date of its own, and README says a block stating either is
refused. That refusal was asked only where the credit was applied, and an
unchanged record never gets there. Measured on 5.10: INV-002, settled out of
C001's credit and read back from its own export with `bank_account:`,
`account:` or `date:` added to the credit block, reported `unchanged` with
exit 0, and the added line was read by nobody.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'
FIXTURES = Path('tests/fixtures')


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _done(*args):
    result = _run(*args)
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize('primer, spending, record', [
    ('q015_aac_primer_invoice.txt', 'q015_aac_inv002_partial_credit.txt', 'invoice "INV-002"'),
    ('q015_aac_primer_bill.txt', 'q015_aac_bill002_partial_credit.txt', 'bill "BILL-002"'),
], ids=['invoice', 'bill'])
@pytest.mark.parametrize('line, refusal', [
    ('\t\tbank_account: "Assets:Bank"', 'Drop `bank_account:`'),
    ('\t\taccount: "Assets:Bank"', 'Drop `account:`'),
    ('\t\tdate: 2026-02-01', '`credit_dated:`'),
], ids=['bank_account', 'account', 'date'])
def test_it_is_refused_and_nothing_changes(tmp_path, primer, spending, record,
                                           line, refusal):
    book = tmp_path / 'book.gnucash'
    _done('import', '--new', book, ACCOUNTS)
    _done('import', book, FIXTURES / primer, '--include-business-objects')
    _done('import', book, FIXTURES / spending, '--include-business-objects')
    before = tmp_path / 'before.txt'
    assert _run('export', book, before, '--include-business-objects').exit_code == 0
    ledger = before.read_text()
    block = next(part for part in ledger.split('\n\n') if part.startswith(record))
    credit = next(row for row in block.splitlines() if 'from_credit: #True' in row)
    edited = tmp_path / 'edited.txt'
    edited.write_text(ledger.replace(block, block.replace(credit, credit + '\n' + line)))

    result = _run('import', book, edited, '--include-business-objects')

    assert result.exit_code != 0, result.output
    assert refusal in result.output, result.output
    after = tmp_path / 'after.txt'
    assert _run('export', book, after, '--include-business-objects').exit_code == 0
    assert after.read_text() == ledger
