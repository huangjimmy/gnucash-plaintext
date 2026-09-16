"""A `from_credit:` block that gives no guid is refused when the invoice is read again.

A credit block gives the credit it spends with `txn_guid:` and
`txn_split_guid:`. INV-001 is posted and paid from the bank, and its export is
read back with the payment block rewritten as a credit giving neither. The
comparison cannot match a block giving no guid to the payment the book holds,
so the invoice reads as changed, and the block is refused for the guids it
does not give. The book keeps the payment it had.
"""

import re

from click.testing import CliRunner

from cli.main import cli
from tests.integration.test_find_orphan_payments import ACCOUNTS, _fixture


def _exported(book, tmp_path):
    out = tmp_path / 'out.txt'
    result = CliRunner().invoke(cli, ['export', str(book), str(out),
                                      '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return out.read_text()


def _invoice(exported):
    block = exported[exported.index('invoice "INV-001"'):]
    return block[:block.index('\n\n')] if '\n\n' in block else block


def test_it_is_refused_and_the_payment_stays(tmp_path):
    book = tmp_path / 'book.gnucash'
    source = tmp_path / 'in.txt'
    source.write_text(ACCOUNTS + '\n' + _fixture('q014_invoice_posted_paid'))
    made = CliRunner().invoke(cli, ['import', '--new', str(book), str(source),
                                    '--include-business-objects'])
    assert made.exit_code == 0, made.output
    exported = _exported(book, tmp_path)
    payment = '\t\tdate: 2026-01-15\n\t\tamount: 100.00\n\t\tbank_account: "Assets:Bank"\n'
    assert payment in exported, exported
    credit = re.sub(r'\t\ttxn_(split_)?guid: "[0-9a-f]+"\n', '', exported.replace(
        payment, '\t\tamount: 100.00\n\t\tfrom_credit: #True\n\t\tcredit_dated: 2026-01-15\n'))
    ledger = tmp_path / 'credit.txt'
    ledger.write_text(credit)

    result = CliRunner().invoke(cli, ['import', str(book), str(ledger),
                                      '--include-business-objects'])

    assert result.exit_code != 0, result.output
    assert ('a payment with `from_credit: true` must give the guid of the credit '
            'it spends, in `txn_guid:` and `txn_split_guid:`') in result.output, result.output
    assert _invoice(_exported(book, tmp_path)) == _invoice(exported)
