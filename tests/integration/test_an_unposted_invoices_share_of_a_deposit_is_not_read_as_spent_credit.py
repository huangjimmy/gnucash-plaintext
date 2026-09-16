"""An unposted invoice's share of a deposit is not read as spent credit on the others.

One 300.00 deposit settles INV-A, INV-B and INV-C, a receivable split for each,
and nothing on any of them records a credit being applied. `unpost-invoices
INV-C` leaves INV-C's split in the lot the unpost abandoned.

INV-A's block is read back asking for the customer's credit as well, so what
its lot holds is read for credit already spent. With nothing recorded, a
payment reads as spent credit where its transaction also has a split in another
record's lot and one in a lot no record owns. INV-A's deposit has both: INV-B's
split, and INV-C's. INV-C's lot holds no credit, though: a bank paid it, and
the unpost marked it. So INV-A's payment is still its payment, and the invoice
is not rebuilt.
"""

import re

from click.testing import CliRunner

from cli.main import cli
from tests.integration.test_find_orphan_payments import ACCOUNTS, _fixture


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _done(*args):
    result = _run(*args)
    assert result.exit_code == 0, result.output
    return result


def _posting_of_inv_a(book, out):
    _done('export', book, out, '--include-business-objects')
    block = next(part for part in out.read_text().split('\n\n')
                 if part.startswith('invoice "INV-A"'))
    return re.search(r'posted_txn_guid: "([0-9a-f]+)"', block).group(1)


def test_inv_a_keeps_its_payment_and_its_posting(tmp_path):
    book = tmp_path / 'book.gnucash'
    ledger = ACCOUNTS + '\n' + _fixture('one_deposit_settling_inv_a_inv_b_and_inv_c')
    source = tmp_path / 'in.txt'
    source.write_text(ledger)
    _done('import', '--new', book, source, '--include-business-objects')
    _done('unpost-invoices', book, 'INV-C')
    posting = _posting_of_inv_a(book, tmp_path / 'before.txt')
    without_c = tmp_path / 'without_c.txt'
    without_c.write_text(ledger[:ledger.index('invoice "INV-C"')].replace(
        'invoice "INV-A"\n\tcustomer_id: "C001"\n',
        'invoice "INV-A"\n\tcustomer_id: "C001"\n\tauto_apply_credit: true\n'))

    result = _done('import', book, without_c, '--include-business-objects')

    assert 'orphan' not in result.output.lower(), result.output
    assert 'invoice "INV-B": unchanged' in result.output, result.output
    assert _posting_of_inv_a(book, tmp_path / 'after.txt') == posting
