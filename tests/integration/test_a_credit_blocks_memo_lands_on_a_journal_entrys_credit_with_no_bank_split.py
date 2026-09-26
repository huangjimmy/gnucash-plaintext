"""A credit block's memo lands on a journal entry's credit that has no bank split.

C001's credit is made by a journal entry whose two splits are both on the
receivable, and INV-001 spends it with a `from_credit:` block. A file then
writes the memo "Attributed to Acme" on the entry's credit split and the memo
"Spent on INV-001" on INV-001's block.

A block whose memo is the one its file writes on the bank split is how a ledger an
earlier release wrote is recognised, and it changes nothing. This entry has no
split off the receivable, so no bank split can be what the block states, and
the block's memo is written. Measured on 5.10: the credit split reads "Spent on
INV-001" afterwards, and so does INV-001's payment block.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
ACCOUNTS = FIXTURES / 'payment_roundtrip_accounts.txt'
CREDIT = FIXTURES / 'a_customers_credit_made_by_a_journal_entry.txt'
INVOICE = FIXTURES / 'an_invoice_spending_the_journal_entrys_credit.txt'
WITH_MEMOS = FIXTURES / 'a_journal_entrys_credit_and_the_invoice_spending_it_with_memos.txt'


def _done(*args):
    result = CliRunner().invoke(cli, [str(arg) for arg in args])
    assert result.exit_code == 0, result.output
    return result


def test_the_credit_split_takes_the_blocks_memo(tmp_path):
    book = tmp_path / 'book.gnucash'
    _done('import', '--new', book, ACCOUNTS)
    _done('import', book, CREDIT, '--include-business-objects')
    _done('import', book, INVOICE, '--include-business-objects')

    _done('import', book, WITH_MEMOS, '--include-business-objects')

    out = tmp_path / 'out.txt'
    _done('export', book, out, '--include-business-objects')
    exported = out.read_text()
    assert re.search(r'guid: "b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1"\n\t\tmemo: ?"Spent on INV-001"',
                     exported), exported
    invoice = exported[exported.index('invoice "INV-001"'):]
    assert '\t\tmemo: "Spent on INV-001"\n' in invoice, invoice
