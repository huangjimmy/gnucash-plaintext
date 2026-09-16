"""An invoice's or bill's blocks out of their order are refused.

Inside an `invoice` or `bill` the blocks come in one order: its `entry:`
blocks, then `posted:`, then its `payment:` blocks. That is the order the
export and a printed page write, and the order README gives.

Read in any other order, the import did what the order said. Measured on 5.10:
an invoice whose `posted:` block came before its `entry:` block imported
`created` with `Errors: 0`, and its posting transaction put 0.00 CAD on the
receivable with no income split. The invoice was posted before its line
existed. Written with the entry first, the same invoice posts 100.00.
"""

import re

import pytest
from click.testing import CliRunner

from cli.main import cli
from tests.integration.test_find_orphan_payments import ACCOUNTS, _fixture

ORDER = 'then `posted:`, then'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _blocks(record):
    """The fixture's head and its `entry:`, `posted:` and `payment:` blocks."""
    text = _fixture(record)
    entry, posted, payment = (text.index(f'\t{name}:\n') for name in ('entry', 'posted', 'payment'))
    return text[:entry], {'entry': text[entry:posted], 'posted': text[posted:payment],
                          'payment': text[payment:]}


@pytest.mark.parametrize('record, ident', [
    ('q014_invoice_posted_paid', 'invoice "INV-001"'),
    ('q014_bill_posted_paid', 'bill "BILL-001"'),
], ids=['invoice', 'bill'])
@pytest.mark.parametrize('order', ['posted, entry, payment', 'entry, payment, posted',
                                   'payment, posted, entry'])
def test_it_is_refused_and_nothing_is_booked(tmp_path, record, ident, order):
    head, blocks = _blocks(record)
    book = tmp_path / 'book.gnucash'
    accounts = tmp_path / 'accounts.txt'
    accounts.write_text(ACCOUNTS)
    opened = _run('import', '--new', book, accounts)
    assert opened.exit_code == 0, opened.output
    source = tmp_path / 'ledger.txt'
    source.write_text(head + ''.join(blocks[name] for name in order.split(', ')))

    made = _run('import', book, source, '--include-business-objects')

    assert made.exit_code != 0, made.output
    assert ORDER in made.output, made.output
    out = tmp_path / 'out.txt'
    exported = _run('export', book, out, '--include-business-objects')
    assert exported.exit_code == 0, exported.output
    assert ident not in out.read_text(), out.read_text()
    assert not re.search(r'txn_type: [IB]\n', out.read_text()), out.read_text()


def test_the_lines_among_themselves_keep_the_order_written(tmp_path):
    """Two `entry:` blocks one after the other are not out of order."""
    head, blocks = _blocks('q014_invoice_posted_paid')
    second = blocks['entry'].replace('"Service"', '"Travel"')
    book = tmp_path / 'book.gnucash'
    source = tmp_path / 'ledger.txt'
    source.write_text(ACCOUNTS + '\n' + head + blocks['entry'] + second + blocks['posted']
                      + blocks['payment'].replace('amount: 100', 'amount: 200'))

    made = _run('import', '--new', book, source, '--include-business-objects')

    assert made.exit_code == 0, made.output
    out = tmp_path / 'out.txt'
    assert _run('export', book, out, '--include-business-objects').exit_code == 0
    text = out.read_text()
    assert text.index('"Service"') < text.index('"Travel"'), text
