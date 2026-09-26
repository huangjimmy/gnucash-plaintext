"""An empty `amount:` on a payment block that states no transaction is refused before anything is compared.

A payment block stating its transaction need not state an amount, so there an
empty one states nothing. A block stating none records the payment from what it
states, and the amount is what it records. Measured on 5.10: INV-001's exported
payment block, read back with its guids taken off and `amount: ""`, compared
as changed, the invoice was unposted to be rebuilt — "1 bank-side payment
transaction is now orphaned" — and only then refused, "the payment amount on
this invoice must be a number, got ''". Nothing was saved, and the run said a
payment was orphaned that was not.
"""

import re

from click.testing import CliRunner

from cli.main import cli
from tests.integration.test_find_orphan_payments import ACCOUNTS, _fixture


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _invoice(text):
    block = text[text.index('invoice "INV-001"'):]
    return block[:block.find('\n\n')] if '\n\n' in block else block


def test_it_is_refused_and_nothing_is_unposted(tmp_path):
    book = tmp_path / 'book.gnucash'
    source = tmp_path / 'in.txt'
    source.write_text(ACCOUNTS + '\n' + _fixture('q014_invoice_posted_paid'))
    assert _run('import', '--new', book, source, '--include-business-objects').exit_code == 0
    out = tmp_path / 'out.txt'
    assert _run('export', book, out, '--include-business-objects').exit_code == 0
    text = out.read_text()
    block = re.search(r'\tpayment:\n(?:\t\t[^\n]*\n)*', text).group(0)
    bare = ''.join(line + '\n' for line in block.splitlines()
                   if not line.strip().startswith(('txn_guid:', 'txn_split_guid:')))
    bare = re.sub(r'\t\tamount: [^\n]*\n', '\t\tamount: ""\n', bare)
    assert bare != block, block
    edited = tmp_path / 'edited.txt'
    edited.write_text(text.replace(block, bare))

    result = _run('import', book, edited, '--include-business-objects')

    assert result.exit_code != 0, result.output
    assert "payment amount must be a number, got ''" in result.output, result.output
    assert 'orphaned' not in result.output, result.output
    after = tmp_path / 'after.txt'
    assert _run('export', book, after, '--include-business-objects').exit_code == 0
    assert _invoice(after.read_text()) == _invoice(text)
