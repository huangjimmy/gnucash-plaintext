"""An invoice paid by two splits of one deposit is posted again with both, after an unpost.

INV-TWO is paid 60.00 and 40.00 out of one 100.00 deposit, by two payment
blocks: one gives the 60.00 by `txn_split_guid:`, the other gives only the
deposit's `txn_guid:`. `unpost-invoices INV-TWO` leaves both splits marked as
its orphans. The same file with the line's description changed then posts it
again. The first block puts the 60.00 back by guid. The second finds the 40.00
still marked as INV-TWO's and the 60.00 already back in the invoice's lot, and
takes the 40.00. Measured on 4.13: both splits settle the invoice again, and
nothing is left orphaned.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'
PAID_IN_TWO = Path('tests/fixtures/inv_two_paid_by_two_splits_of_one_deposit.txt')


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _done(*args):
    result = _run(*args)
    assert result.exit_code == 0, result.output
    return result


def test_both_splits_settle_the_invoice_again(tmp_path):
    book = tmp_path / 'book.gnucash'
    _done('import', '--new', book, ACCOUNTS)
    _done('import', book, PAID_IN_TWO, '--include-business-objects')
    _done('unpost-invoices', book, 'INV-TWO')
    text = PAID_IN_TWO.read_text()
    assert '\t\tdescription: "Service"\n' in text, text
    revised = tmp_path / 'revised.txt'
    revised.write_text(text.replace('\t\tdescription: "Service"\n',
                                    '\t\tdescription: "Service, revised"\n'))

    result = _done('import', book, revised, '--include-business-objects')

    assert 'invoice "INV-TWO": updated' in result.output, result.output
    out = tmp_path / 'out.txt'
    _done('export', book, out, '--include-business-objects')
    exported = out.read_text()
    assert ('\t\tTransaction "c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1"\n'
            '\t\t\tPaymentSplit "d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2"\n'
            '\t\t\tPaymentSplit "e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3"\n') in exported, exported
    orphans = _done('find-orphan-payments', book)
    assert 'No orphan bank-side payment transactions found.' in orphans.output, orphans.output
