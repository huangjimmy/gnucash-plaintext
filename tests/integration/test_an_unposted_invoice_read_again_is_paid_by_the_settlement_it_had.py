"""An unposted invoice read again is paid by the settlement it had.

Changing a posted invoice is refused, and the refusal gives the route:
`unpost-invoices <book> INV-001`, then import the file again. The unpost
leaves the payment's receivable split in the lot the invoice had, marked as
that invoice's, and GnuCash's View → Lots can then take it out of the lot.

The file was written by hand, so its `payment:` block gives no `txn_guid:`.
It still describes the money the book holds: the same day, the same figure,
the same account, and a split the unpost marked as this invoice's. Reading it
puts that settlement back rather than entering a second payment for money
that moved once.
"""

import pytest
from click.testing import CliRunner

from cli.main import cli
from tests.integration.test_find_orphan_payments import (
    ACCOUNTS,
    _fixture,
    _make_orphan_invoice,
)
from tests.integration.test_money_on_the_receivable_nobody_owns_is_listed import (
    _a_settlement_taken_out_of_the_lot_an_unpost_left,
)


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _in_its_lot(tmp_path):
    return _make_orphan_invoice(CliRunner(), tmp_path, 'q014_invoice_posted_paid',
                                'INV-001', 'unpost-invoices')


@pytest.mark.parametrize('unposted', [_in_its_lot,
                                      _a_settlement_taken_out_of_the_lot_an_unpost_left],
                         ids=['in-its-lot', 'in-no-lot'])
def test_it_is_paid_by_the_payment_it_had(tmp_path, unposted):
    book = unposted(tmp_path)
    ledger = tmp_path / 'edited.txt'
    source = _fixture('q014_invoice_posted_paid')
    assert 'due: 2026-01-31' in source
    ledger.write_text(ACCOUNTS + '\n' + source.replace('due: 2026-01-31',
                                                       'due: 2026-03-31'))

    result = _run('import', book, ledger, '--include-business-objects')

    assert result.exit_code == 0, result.output
    out = tmp_path / 'out.txt'
    assert _run('export', book, out, '--include-business-objects').exit_code == 0
    text = out.read_text()
    invoice = text[text.index('invoice "INV-001"'):]
    invoice = invoice[:invoice.find('\n\n')] if '\n\n' in invoice else invoice
    assert 'due: 2026-03-31' in invoice, invoice
    assert 'payment: none' not in invoice, invoice
    # One receipt of the 100.00: the payment it had, not a second one.
    assert text.count('\tAssets:Bank 100.00 CAD\n') == 1, text
    assert 'No orphan bank-side payment transactions found.' in _run(
        'find-orphan-payments', book).output


def test_a_corrected_memo_and_number_land_on_the_payment_it_had(tmp_path):
    """No unpost first: a changed payment block rebuilds the invoice itself.

    The rebuild unposts it, which leaves the payment marked as this invoice's,
    and the block then finds that payment by its day and figure. The corrected
    memo and the added number go on it, and the file read again matches.
    """
    book = tmp_path / 'book.gnucash'
    source = ACCOUNTS + '\n' + _fixture('q014_invoice_posted_paid')
    first = tmp_path / 'first.txt'
    first.write_text(source)
    assert _run('import', '--new', book, first,
                '--include-business-objects').exit_code == 0
    assert '\t\tmemo: "Payment INV-001"\n' in source
    ledger = tmp_path / 'edited.txt'
    ledger.write_text(source.replace(
        '\t\tmemo: "Payment INV-001"\n',
        '\t\tmemo: "Settled by cheque"\n\t\tnum: "CHQ-7"\n'))

    result = _run('import', book, ledger, '--include-business-objects')

    assert result.exit_code == 0, result.output
    # The payment is back, so none is orphaned to warn of.
    assert 'is now orphaned' not in result.output, result.output
    out = tmp_path / 'out.txt'
    assert _run('export', book, out, '--include-business-objects').exit_code == 0
    text = out.read_text()
    assert text.count('\tAssets:Bank 100.00 CAD\n') == 1, text
    invoice = text[text.index('invoice "INV-001"'):]
    invoice = invoice[:invoice.find('\n\n')] if '\n\n' in invoice else invoice
    assert 'memo: "Settled by cheque"' in invoice, invoice
    assert 'num: "CHQ-7"' in invoice, invoice
    again = _run('import', book, ledger, '--include-business-objects')
    assert again.exit_code == 0, again.output
    assert 'invoice "INV-001": unchanged' in again.output, again.output


def test_an_unposted_bill_read_again_is_paid_by_the_payment_it_had(tmp_path):
    book = _make_orphan_invoice(CliRunner(), tmp_path, 'q014_bill_posted_paid',
                                'BILL-001', 'unpost-bills')
    ledger = tmp_path / 'edited.txt'
    source = _fixture('q014_bill_posted_paid')
    assert 'due: 2026-01-31' in source
    ledger.write_text(ACCOUNTS + '\n' + source.replace('due: 2026-01-31',
                                                       'due: 2026-03-31'))

    result = _run('import', book, ledger, '--include-business-objects')

    assert result.exit_code == 0, result.output
    out = tmp_path / 'out.txt'
    assert _run('export', book, out, '--include-business-objects').exit_code == 0
    text = out.read_text()
    bill = text[text.index('bill "BILL-001"'):]
    bill = bill[:bill.find('\n\n')] if '\n\n' in bill else bill
    assert 'due: 2026-03-31' in bill, bill
    assert 'payment: none' not in bill, bill
    # One payment of the 50.00 sent: the payment it had, not a second one.
    assert text.count('\tAssets:Bank -50.00 CAD\n') == 1, text
    assert 'No orphan bank-side payment transactions found.' in _run(
        'find-orphan-payments', book).output
