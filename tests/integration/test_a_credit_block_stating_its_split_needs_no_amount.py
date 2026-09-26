"""A `from_credit:` block that states its credit's split needs no `amount:`.

`amount:` on such a block says what the split holds, and is checked against
it. Left out, the split says it: INV-B for 50.00 is paid from the 50.00 credit
an overpayment left C001 all the same, and the export writes the amount back.
"""

from pathlib import Path

from tests.integration.test_taking_a_payment_off_onto_its_receivable_leaves_the_owners_credit import (
    ACCOUNTS,
    AR,
    OVERPAID,
    SPENDING,
    _imported,
    _run,
    _the_credit,
)

STATED = '\t\tamount: 50.00\n'


def test_the_invoice_is_paid_from_the_credit_its_block_states(tmp_path):
    book = tmp_path / 'book.gnucash'
    _imported('--new', book, ACCOUNTS)
    _imported(book, OVERPAID, '--include-business-objects')
    txn, split = _the_credit(book, AR)
    text = Path(SPENDING).read_text()
    assert STATED in text, text
    spending = tmp_path / 'spending.txt'
    spending.write_text(text.replace(STATED, '')
                        .replace('TXN_GUID', txn).replace('SPLIT_GUID', split))

    _imported(book, spending, '--include-business-objects')

    out = tmp_path / 'out.txt'
    exported = _run('export', book, out, '--include-business-objects')
    assert exported.exit_code == 0, exported.output
    written = out.read_text()
    invoice = written[written.index('invoice "INV-B"'):]
    invoice = invoice[:invoice.find('\n\n')] if '\n\n' in invoice else invoice
    assert 'from_credit: #True' in invoice, invoice
    assert 'amount: 50.00' in invoice, invoice
