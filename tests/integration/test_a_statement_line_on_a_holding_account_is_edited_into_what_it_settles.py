"""A statement line imported against a holding account is edited, once the owner knows what it was, into the invoice or bill it settles (Q-051).

A bank statement's US dollar lines are imported before the owner knows what
they are: each line's other side goes to `Assets:Due from director`, and the
bank's fee comes out of the same line, in the same transaction. Later the
owner exports the book, edits the transaction into what it was, and imports it
with `--strategy update`, beside the invoice's or bill's `payment:` block.

The edit is read as the transaction would be read if it were new, and is
accepted when the new version is a correct transaction and the book is correct
afterwards. A cost basis the old version established and the new one does not
is not established: a deposit that was an invoice's collection establishes
none, because the dollars' cost is the invoice's. Where another transaction
drew on a cost basis the new version would not establish, or at other figures,
the edit is refused and the transaction is left as it was.
"""

import re
from datetime import date
from fractions import Fraction
from pathlib import Path

import pytest
from click.testing import CliRunner

from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import cost_basis_items_by_currency_and_side, iter_splits, split_guid
from tests.conftest import _run

FIXTURES = 'tests/fixtures/'
BASE = FIXTURES + 'a_usd_invoice_and_bill_for_statement_lines_on_a_holding_account.txt'
RATES = FIXTURES + 'usd_at_the_rates_the_statement_lines_records_were_posted_at.yaml'
DOLLARS = 'usd_bought_into_wise_before_the_statement.txt'
DEPOSIT = 'a_usd_deposit_and_its_fee_on_a_holding_account.txt'
WITHDRAWAL = 'a_usd_withdrawal_and_its_fee_on_a_holding_account.txt'
SALE = 'usd_sold_out_of_the_statement_deposit.txt'
FEE_FIRST = 'a_usd_fee_on_a_holding_account_imported_before_the_dollars_it_spent.txt'

DEPOSIT_HEAD = '2026-08-13 * "Received money from Example Customer Inc"'
WITHDRAWAL_HEAD = '2026-08-20 * "Paid Example Supplier Inc"'
FEE_HEAD = '2026-08-20 * "Transfer fee"'

INVOICE_PAYMENT = [
    '\tpayment:',
    '\t\tdate: 2026-08-13',
    '\t\tamount: 2720',
    '\t\taccount: "Assets:Wise USD"',
    '\t\ttxn_guid: "0e510000000000000000000000000a01"',
    '\t\ttxn_split_guid: "0e510000000000000000000000000a03"',
    '\t\tmemo: "Received money from Example Customer Inc"',
]
BILL_PAYMENT = [
    '\tpayment:',
    '\t\tdate: 2026-08-20',
    '\t\tamount: 1000',
    '\t\taccount: "Assets:Wise USD"',
    '\t\ttxn_guid: "0e510000000000000000000000000b01"',
    '\t\ttxn_split_guid: "0e510000000000000000000000000b03"',
    '\t\tmemo: "Paid Example Supplier Inc"',
]

INVOICE_1 = ('Assets:Accounts Receivable USD', 'USD', 'asset', Fraction('2720.00'))
INVOICE_2 = ('Assets:Accounts Receivable USD', 'USD', 'asset', Fraction('4000.00'))
BILL = ('Liabilities:Accounts Payable USD', 'USD', 'liability', Fraction('1000.00'))
BILL_2 = ('Liabilities:Accounts Payable USD', 'USD', 'liability', Fraction('1500.00'))


def _book(tmp_path, *files):
    """The base book, then each file imported onto it in turn."""
    book = tmp_path / 'book.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(book), BASE,
                '--include-business-objects', '--fx-rates', RATES)
    assert made.exit_code == 0, made.output
    for name in files:
        done = _run(CliRunner(), 'import', str(book), FIXTURES + name, '--fx-rates', RATES)
        assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    return book


def _exported(book, tmp_path):
    ledger = tmp_path / 'exported.txt'
    done = _run(CliRunner(), 'export', str(book), str(ledger), '--include-business-objects')
    assert done.exit_code == 0, done.output
    return ledger.read_text()


def _block(text, head):
    return re.search(rf'{re.escape(head)}\n(?:\t[^\n]*\n)*', text).group(0)


def _without_comments(path):
    return ''.join(line for line in open(path).read().splitlines(keepends=True)
                   if not line.startswith('#'))


def _with_payment(text, record, payment):
    """The record's `payment: none` replaced with the payment block given."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(record))
    end = start + 1
    while end < len(lines) and (lines[end].startswith('\t') or not lines[end].strip()):
        end += 1
    block = [line for line in lines[start:end] if line.strip() != 'payment: none']
    return '\n'.join(lines[:start] + block + payment + lines[end:]) + '\n'


def _posting_split(text, amount):
    """The guid of the receivable or payable split an invoice or bill was posted with."""
    return re.search(rf'Accounts (?:Receivable|Payable) USD -?{re.escape(amount)} USD\n'
                     r'\t+guid: "([0-9a-f]{32})"', text).group(1)


def _edited(book, tmp_path, head, booked, record=None, payment=(), *flags, **fill):
    """The book exported, the transaction at `head` replaced by `booked`, imported as an edit."""
    text = _exported(book, tmp_path)
    new = _without_comments(FIXTURES + booked)
    for key, value in fill.items():
        new = new.replace('{' + key + '}', value)
    text = text.replace(_block(text, head), new)
    if record:
        text = _with_payment(text, record, list(payment))
    edit = tmp_path / 'edit.txt'
    edit.write_text(text)
    return _run(CliRunner(), 'import', str(book), str(edit), '--strategy', 'update',
                '--include-business-objects', '--fx-rates', RATES, *flags)


def _bases(book):
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        return sorted((row['account'], row['currency'], row['side'], row['balance'])
                      for row in cost_basis_items_by_currency_and_side(
                          repo.book, date(2026, 12, 31)))
    finally:
        repo.close()


def _sound(book):
    checked = _run(CliRunner(), 'fx-balances', str(book), '--verify-costs')
    assert checked.exit_code == 0 and 'warning' not in checked.output, checked.output


def _paid_by(book, tmp_path, record, guid):
    """Whether the record's `payment:` block gives the transaction `guid`."""
    return f'txn_guid: "{guid}"' in _block(_exported(book, tmp_path), record)


def _accepted(done):
    message = done.output + str(done.exception)
    assert done.exit_code == 0 and 'Errors:       0' in done.output, message


def _refused(done):
    message = done.output + str(done.exception)
    assert done.exit_code != 0, message
    return message


class TestADepositBookedAsTheInvoiceItCollected:
    """E1: the holding-account amount becomes the receivable, the fee draws on the invoice."""

    def _booked(self, tmp_path, *flags):
        book = _book(tmp_path, DEPOSIT)
        posting = _posting_split(_exported(book, tmp_path), '2720.00')
        done = _edited(book, tmp_path, DEPOSIT_HEAD,
                       'a_usd_deposit_booked_as_the_invoice_it_collected.txt',
                       'invoice "INV-USD-1"', INVOICE_PAYMENT, *flags,
                       invoice_posting=posting)
        return book, done

    def test_it_is_accepted_and_the_invoice_is_paid(self, tmp_path):
        book, done = self._booked(tmp_path)

        _accepted(done)
        assert _paid_by(book, tmp_path, 'invoice "INV-USD-1"',
                        '0e510000000000000000000000000a01')

    def test_the_deposit_establishes_no_cost_basis_and_the_fee_draws_on_the_invoices(self, tmp_path):
        book, done = self._booked(tmp_path)

        _accepted(done)
        assert _bases(book) == sorted([
            ('Assets:Accounts Receivable USD', 'USD', 'asset', Fraction('2719.28')),
            INVOICE_2, BILL, BILL_2])
        _sound(book)

    def test_under_atomic(self, tmp_path):
        """E14: the same book, committed as one."""
        book, done = self._booked(tmp_path, '--atomic')

        _accepted(done)
        assert _bases(book) == sorted([
            ('Assets:Accounts Receivable USD', 'USD', 'asset', Fraction('2719.28')),
            INVOICE_2, BILL, BILL_2])
        _sound(book)

    def test_without_the_business_objects_the_fee_is_refused(self, tmp_path):
        """E17: the `payment:` block is not applied, so nothing collects the invoice.

        The receivable split settles INV-USD-1 only once the block applies it,
        and a run without `--include-business-objects` applies no block. Read
        as collected on the block's word, the edit left a fee drawn on an
        invoice nobody had paid and a deposit establishing no cost basis.
        """
        book = _book(tmp_path, DEPOSIT)
        before = _bases(book)
        text = _exported(book, tmp_path)
        booked = _without_comments(
            FIXTURES + 'a_usd_deposit_booked_as_the_invoice_it_collected.txt').replace(
            '{invoice_posting}', _posting_split(text, '2720.00'))
        text = _with_payment(text.replace(_block(text, DEPOSIT_HEAD), booked),
                             'invoice "INV-USD-1"', INVOICE_PAYMENT)
        edit = tmp_path / 'edit.txt'
        edit.write_text(text)

        message = _refused(_run(CliRunner(), 'import', str(book), str(edit),
                                '--strategy', 'update', '--fx-rates', RATES))

        assert 'the invoice it belongs to has not been collected' in message, message
        assert _bases(book) == before

    def test_booked_back_onto_the_holding_account_is_refused_and_the_invoice_stays_paid(self, tmp_path):
        """The receivable split settles INV-USD-1, so it is not moved off its lot's account.

        The refusal comes before anything is written. A refused edit is put
        back after its commit, and the put-back sets no lot, so it matters
        that no edit reaching the commit has moved or removed a split in a
        lot: the commit would have taken it out of the lot.
        """
        book, done = self._booked(tmp_path)
        _accepted(done)
        text = _exported(book, tmp_path)
        edit = tmp_path / 'edit.txt'
        edit.write_text(text.replace(_block(text, DEPOSIT_HEAD),
                                     _without_comments(FIXTURES + DEPOSIT)))

        message = _refused(_run(CliRunner(), 'import', str(book), str(edit), '--strategy',
                                'update', '--fx-rates', RATES))

        assert ('the split 0e510000000000000000000000000a03 is in lot' in message
                and 'take it out of the lot first' in message), message
        assert _paid_by(book, tmp_path, 'invoice "INV-USD-1"',
                        '0e510000000000000000000000000a01')
        _sound(book)

    def test_the_export_rebuilds_the_book(self, tmp_path):
        """E16."""
        book, done = self._booked(tmp_path)
        _accepted(done)
        ledger = tmp_path / 'ledger.txt'
        assert _run(CliRunner(), 'export', str(book), str(ledger),
                    '--include-business-objects').exit_code == 0

        rebuilt = tmp_path / 'rebuilt.gnucash'
        made = _run(CliRunner(), 'import', '--new', str(rebuilt), str(ledger),
                    '--include-business-objects', '--fx-rates', RATES)

        _accepted(made)
        assert _bases(rebuilt) == _bases(book)
        # The deposit's block too: a balance left on it, which `_bases` does
        # not list once the deposit establishes no cost basis, is written here.
        assert (_block(_exported(rebuilt, tmp_path), DEPOSIT_HEAD)
                == _block(_exported(book, tmp_path), DEPOSIT_HEAD))
        _sound(rebuilt)


def test_a_deposit_booked_as_part_payment_of_a_larger_invoice(tmp_path):
    """E2: INV-USD-2 is still owed 1,280.00, and the fee draws on what was collected of it."""
    book = _book(tmp_path, DEPOSIT)
    posting = _posting_split(_exported(book, tmp_path), '4000.00')
    payment = [line if 'amount' not in line else '\t\tamount: 2720' for line in INVOICE_PAYMENT]

    done = _edited(book, tmp_path, DEPOSIT_HEAD,
                   'a_usd_deposit_booked_as_the_invoice_it_collected.txt',
                   'invoice "INV-USD-2"', payment, invoice_posting=posting)

    _accepted(done)
    assert _paid_by(book, tmp_path, 'invoice "INV-USD-2"', '0e510000000000000000000000000a01')
    assert _bases(book) == sorted([
        INVOICE_1, ('Assets:Accounts Receivable USD', 'USD', 'asset', Fraction('3999.28')),
        BILL, BILL_2])
    _sound(book)


def test_a_balance_a_refused_edit_states_is_not_read_as_stated(tmp_path):
    """The deposit's edit states 2,000.00 and is refused, and the sale later in the file draws as ever.

    The refused edit is put back with the balance the book held. Left marked
    as stated by the file, that balance took no draw: the sale restated from
    500.00 to 400.00 gave nothing back and drew nothing, and the cost basis
    stayed at 2,219.28.
    """
    book = _book(tmp_path, DEPOSIT, SALE)
    assert ('Assets:Wise USD', 'USD', 'asset', Fraction('2219.28')) in _bases(book)
    text = _exported(book, tmp_path)
    refused_deposit = (_without_comments(FIXTURES + DEPOSIT)
                       .replace('cost_basis_split_guid: $transactions_to_import[0].splits[0].guid$',
                                'cost_basis_split_guid: ""')
                       .replace('\t\tvalue: "3815.89"\n',
                                '\t\tvalue: "3815.89"\n\t\tcost_basis_balance: "2000.00"\n'))
    smaller_sale = (_without_comments(FIXTURES + SALE)
                    .replace('-500.00 USD', '-400.00 USD')
                    .replace('value: "-701.45"', 'value: "-561.16"')
                    .replace('Chequing 700.00 CAD', 'Chequing 560.00 CAD'))
    text = (text.replace(_block(text, DEPOSIT_HEAD), refused_deposit)
            .replace(_block(text, '2026-08-14 * "Sold 500 USD"'), smaller_sale))
    edit = tmp_path / 'edit.txt'
    edit.write_text(text)

    done = _run(CliRunner(), 'import', str(book), str(edit), '--strategy', 'update',
                '--include-business-objects', '--fx-rates', RATES)

    assert done.exit_code != 0 and 'Errors:       1' in done.output, done.output
    assert ('Assets:Wise USD', 'USD', 'asset', Fraction('2319.28')) in _bases(book)
    _sound(book)


def test_a_balance_restated_below_a_sale_that_changed_it_is_not_read_as_stated(tmp_path):
    """The sale's block comes first and draws 400.00 where it drew 500.00; the deposit's, below, restates the balance as exported.

    2,219.28 is what the book held when the run started, so the deposit's
    block restates it and states nothing. Compared with the balance the sale
    had just left, 2,319.28, it read as a figure the file changed: noted as
    stated and written, it put back the 100.00 the sale no longer draws. The
    deposit's description changes too, so its block is edited rather than
    found up to date.
    """
    book = _book(tmp_path, DEPOSIT, SALE)
    text = _exported(book, tmp_path)
    deposit = _block(text, DEPOSIT_HEAD)
    sale = _block(text, '2026-08-14 * "Sold 500 USD"')
    assert 'cost_basis_balance: "2219.28"' in deposit, deposit
    smaller_sale = (sale.replace('-500.00 USD', '-400.00 USD')
                    .replace('value: "-701.45"', 'value: "-561.16"')
                    .replace('Chequing 700.00 CAD', 'Chequing 560.00 CAD'))
    smaller_sale = re.sub(r'\tIncome:FX gain [^\n]*\n(?:\t\t[^\n]*\n)*', '\tIncome:FX gain $residual$ CAD\n',
                          smaller_sale)
    renamed = deposit.replace('"Received money from Example Customer Inc"',
                              '"Received money from Example Customer Inc, checked"', 1)
    edit = tmp_path / 'edit.txt'
    edit.write_text(text.replace(sale, '').replace(deposit, smaller_sale + renamed))

    done = _run(CliRunner(), 'import', str(book), str(edit), '--strategy', 'update',
                '--include-business-objects', '--fx-rates', RATES)

    _accepted(done)
    assert ('Assets:Wise USD', 'USD', 'asset', Fraction('2319.28')) in _bases(book)
    _sound(book)


def test_an_edit_refused_before_its_commit_leaves_what_draws_on_a_cost_basis_known(tmp_path):
    """The sale's block, first in the file, re-points it and does not balance; the deposit's block, below, moves the deposit a day earlier.

    The sale's refused block wrote its new pick before the rollback put the
    old one back. Kept from that write, the book's index of what draws on
    each cost basis had the sale drawing on the dollars bought, and nothing
    on the deposit, so the deposit's new date was accepted under the sale
    still drawing on it. The dollars bought, first in the file, get a new
    description, and editing them is what builds the index before the sale's
    block writes.
    """
    book = _book(tmp_path, DOLLARS, DEPOSIT, SALE)
    text = _exported(book, tmp_path).replace('* "Dollars bought"', '* "Dollars bought, checked"')
    deposit = _block(text, DEPOSIT_HEAD)
    sale = _block(text, '2026-08-14 * "Sold 500 USD"')
    re_pointed = (sale.replace('0e510000000000000000000000000a02', '0e510000000000000000000000000d02')
                  .replace('value: "-701.45"', 'value: "-675.00"'))
    earlier = deposit.replace('2026-08-13 *', '2026-08-12 *', 1)
    edit = tmp_path / 'edit.txt'
    edit.write_text(text.replace(sale, '').replace(deposit, re_pointed + earlier))

    refused = _run(CliRunner(), 'import', str(book), str(edit), '--strategy', 'update',
                   '--fx-rates', RATES)

    assert refused.exit_code != 0 and 'Errors:       2' in refused.output, refused.output
    assert ('touches a cost basis another transaction draws on' in refused.output
            and 'Sold 500 USD' in refused.output), refused.output
    assert DEPOSIT_HEAD in _exported(book, tmp_path)


def test_a_payment_block_stating_another_amount_than_the_split_it_gives_is_refused(tmp_path):
    """INV-USD-2's block gives the 2,720.00 receivable split and states `amount: 1000`.

    A block giving `txn_split_guid:` attaches the whole split to its invoice,
    so the invoice is paid 2,720.00 whatever `amount:` the block states.
    Accepted, the book recorded a figure the file did not state and said
    nothing. The export writes the split's own amount, so a block that
    differs was written by hand, and the file is the thing to correct.
    """
    book = _book(tmp_path, DEPOSIT)
    before = _bases(book)
    posting = _posting_split(_exported(book, tmp_path), '4000.00')
    payment = [line if 'amount' not in line else '\t\tamount: 1000' for line in INVOICE_PAYMENT]

    message = _refused(_edited(book, tmp_path, DEPOSIT_HEAD,
                               'a_usd_deposit_booked_as_the_invoice_it_collected.txt',
                               'invoice "INV-USD-2"', payment, invoice_posting=posting))

    assert ('states amount: 1000, and the split given in txn_split_guid '
            '0e510000000000000000000000000a03 carries 2720.00') in message, message
    assert 'payment: none' in _block(_exported(book, tmp_path), 'invoice "INV-USD-2"')
    assert _bases(book) == before


def test_a_payment_block_giving_a_split_with_an_amount_that_will_not_parse_is_refused_in_words(tmp_path):
    """`amount: 27x0` beside the receivable split INV-USD-1's block gives.

    Refused before the amount is weighed against the split, giving the
    invoice and the figure, so the weighing only ever reads a number.
    """
    book = _book(tmp_path, DEPOSIT)
    before = _bases(book)
    posting = _posting_split(_exported(book, tmp_path), '2720.00')
    payment = [line if 'amount' not in line else '\t\tamount: 27x0' for line in INVOICE_PAYMENT]

    message = _refused(_edited(book, tmp_path, DEPOSIT_HEAD,
                               'a_usd_deposit_booked_as_the_invoice_it_collected.txt',
                               'invoice "INV-USD-1"', payment, invoice_posting=posting))

    assert 'invoice "INV-USD-1": payment amount must be a number, got \'27x0\'' in message, message
    assert _bases(book) == before


def test_an_invoice_stating_the_pick_key_as_its_own_is_imported(tmp_path):
    """INV-USD-1 carries `cost_basis_split_guid:` among its own custom keys, as a person could write it.

    The change log that keeps the index of picks asked every object written
    with that key for its guid, and an invoice has no `GetGUID` (CLAUDE.md
    finding 13): the import raised `AttributeError`, where the key had always
    been stored. Only a split's pick is a pick.
    """
    book = tmp_path / 'book.gnucash'
    text = Path(BASE).read_text().replace(
        'invoice "INV-USD-1"\n\tcustomer_id: "C-USD"\n',
        'invoice "INV-USD-1"\n\tcustomer_id: "C-USD"\n'
        '\tcost_basis_split_guid: "0e510000000000000000000000000a02"\n')
    ledger = tmp_path / 'ledger.txt'
    ledger.write_text(text)

    done = _run(CliRunner(), 'import', '--new', str(book), str(ledger),
                '--include-business-objects', '--fx-rates', RATES)

    assert done.exit_code == 0, done.output + str(done.exception)
    assert ('cost_basis_split_guid: "0e510000000000000000000000000a02"'
            in _block(_exported(book, tmp_path), 'invoice "INV-USD-1"'))


def test_a_prepayment_beside_the_split_does_not_divide_it(tmp_path):
    """`prepayment: 720` beside the 2,720.00 split INV-USD-2's block gives, to leave 2,000.00 collected.

    On `txn_split_guid:`, `prepayment:` is weighed against the transaction's
    other receivable splits, the ones the block does not apply; it does not
    divide the split the block gives. This transaction has none, so the block
    is refused and the run saves nothing. The split a block gives is attached
    whole on every route that is accepted, which is why it is counted whole
    as collected while the transaction is read.
    """
    book = _book(tmp_path, DEPOSIT)
    before = _bases(book)
    posting = _posting_split(_exported(book, tmp_path), '4000.00')

    message = _refused(_edited(book, tmp_path, DEPOSIT_HEAD,
                               'a_usd_deposit_booked_as_the_invoice_it_collected.txt',
                               'invoice "INV-USD-2"', INVOICE_PAYMENT + ['\t\tprepayment: 720'],
                               invoice_posting=posting))

    assert ('declared `prepayment: 720` does not match the residual AR/AP splits'
            in message), message
    assert _bases(book) == before


def test_a_second_edit_counts_the_part_payment_once(tmp_path):
    """E2 edited again: the collection in the invoice's lot is counted once, against every draw beside it.

    The receivable split is in INV-USD-2's lot, and the exported `payment:`
    block applies it again. Counted from the lot and from the block, the
    2,720.00 collected read as 5,440.00. And each split was checked alone,
    so two sales of 1,400.00 on the invoice's cost basis beside the fee each
    passed against 2,720.00, though together they draw 2,800.72.
    """
    book = _book(tmp_path, DOLLARS, 'more_usd_bought_into_wise_before_the_statement.txt', DEPOSIT)
    posting = _posting_split(_exported(book, tmp_path), '4000.00')
    payment = [line if 'amount' not in line else '\t\tamount: 2720' for line in INVOICE_PAYMENT]
    _accepted(_edited(book, tmp_path, DEPOSIT_HEAD,
                      'a_usd_deposit_booked_as_the_invoice_it_collected.txt',
                      'invoice "INV-USD-2"', payment, invoice_posting=posting))
    before = _bases(book)

    message = _refused(_edited(
        book, tmp_path, DEPOSIT_HEAD,
        'a_usd_deposit_booked_as_the_invoice_it_collected_beside_a_sale_drawing_more.txt',
        invoice_posting=posting))

    assert 'the invoice it belongs to has not been collected' in message, message
    assert _bases(book) == before


class TestAWithdrawalBookedAsTheBillItPaid:
    """E4: the holding-account amount becomes the payable; the dollars and the fee draw as before."""

    def test_it_is_accepted_and_the_bill_is_paid(self, tmp_path):
        book = _book(tmp_path, DOLLARS, WITHDRAWAL)

        done = _edited(book, tmp_path, WITHDRAWAL_HEAD,
                       'a_usd_withdrawal_booked_as_the_bill_it_paid.txt',
                       'bill "BILL-USD-1"', BILL_PAYMENT)

        _accepted(done)
        assert _paid_by(book, tmp_path, 'bill "BILL-USD-1"', '0e510000000000000000000000000b01')
        assert ('Assets:Wise USD', 'USD', 'asset', Fraction('999.28')) in _bases(book)
        _sound(book)

    def test_as_part_payment_of_a_larger_bill(self, tmp_path):
        """E5: BILL-USD-2 is still owed 500.00."""
        book = _book(tmp_path, DOLLARS, WITHDRAWAL)

        done = _edited(book, tmp_path, WITHDRAWAL_HEAD,
                       'a_usd_withdrawal_booked_as_the_bill_it_paid.txt',
                       'bill "BILL-USD-2"', BILL_PAYMENT)

        _accepted(done)
        assert _paid_by(book, tmp_path, 'bill "BILL-USD-2"', '0e510000000000000000000000000b01')
        assert 'payment: none' in _block(_exported(book, tmp_path), 'bill "BILL-USD-1"')
        assert ('Assets:Wise USD', 'USD', 'asset', Fraction('999.28')) in _bases(book)
        _sound(book)

    def test_the_export_rebuilds_the_book(self, tmp_path):
        """E16, the bill's side."""
        book = _book(tmp_path, DOLLARS, WITHDRAWAL)
        _accepted(_edited(book, tmp_path, WITHDRAWAL_HEAD,
                          'a_usd_withdrawal_booked_as_the_bill_it_paid.txt',
                          'bill "BILL-USD-1"', BILL_PAYMENT))
        ledger = tmp_path / 'ledger.txt'
        assert _run(CliRunner(), 'export', str(book), str(ledger),
                    '--include-business-objects').exit_code == 0

        rebuilt = tmp_path / 'rebuilt.gnucash'
        made = _run(CliRunner(), 'import', '--new', str(rebuilt), str(ledger),
                    '--include-business-objects', '--fx-rates', RATES)

        _accepted(made)
        assert _bases(rebuilt) == _bases(book)
        assert (_block(_exported(rebuilt, tmp_path), WITHDRAWAL_HEAD)
                == _block(_exported(book, tmp_path), WITHDRAWAL_HEAD))
        _sound(rebuilt)


class TestATransferBesideItsFee:
    """E7: dollars moved between the owner's accounts, and a fee in the same transaction giving its cost basis.

    The savings account's dollars are an opening balance against equity, as
    in a book started part-way through its life. The fee gives the cost basis
    it spends, so it is what left, and the rest moved.
    """

    OPENING = 'usd_held_in_savings_as_an_opening_balance.txt'
    SAVINGS = ('Assets:USD Savings', 'USD', 'asset', Fraction('2999.28'))

    def test_an_opening_balance_against_equity_opens_a_cost_basis(self, tmp_path):
        book = _book(tmp_path, self.OPENING)

        assert ('Assets:USD Savings', 'USD', 'asset', Fraction('3000.00')) in _bases(book)

    def test_imported_as_a_new_transaction(self, tmp_path):
        book = _book(tmp_path, self.OPENING,
                     'a_usd_transfer_from_savings_and_its_fee_in_one_transaction.txt')

        assert _bases(book) == sorted([INVOICE_1, INVOICE_2, BILL, BILL_2, self.SAVINGS])
        _sound(book)

    def test_a_deposit_booked_as_the_transfer_it_was(self, tmp_path):
        book = _book(tmp_path, self.OPENING, DEPOSIT)

        done = _edited(book, tmp_path, DEPOSIT_HEAD,
                       'a_usd_deposit_booked_as_a_transfer_from_savings.txt')

        _accepted(done)
        assert _bases(book) == sorted([INVOICE_1, INVOICE_2, BILL, BILL_2, self.SAVINGS])
        _sound(book)


class TestTheSameCostBasis:
    """E6 and E10: booked as income, the deposit establishes the cost basis it did."""

    def test_booked_as_income(self, tmp_path):
        book = _book(tmp_path, DEPOSIT)
        before = _bases(book)

        done = _edited(book, tmp_path, DEPOSIT_HEAD, 'a_usd_deposit_booked_as_income.txt')

        _accepted(done)
        assert _bases(book) == before

    @staticmethod
    def _stated(book, tmp_path, figure):
        """The deposit's balance stated by a file of its own, as a book records currency sold outside it."""
        stated = _exported(book, tmp_path).replace('cost_basis_balance: "2719.28"',
                                                    f'cost_basis_balance: "{figure}"')
        ledger = tmp_path / 'stated.txt'
        ledger.write_text(stated)
        _accepted(_run(CliRunner(), 'import', str(book), str(ledger), '--strategy', 'update',
                       '--include-business-objects', '--fx-rates', RATES))

    def test_booked_as_income_under_atomic(self, tmp_path):
        """Only the Canadian dollar side moves, so no cost basis fact changes, and under `--atomic` the edit is made in place.

        Read as new only where a cost basis fact changes: under the flag, a
        split that only moves is left to the finished book, as every edit
        was before.
        """
        book = _book(tmp_path, DEPOSIT)
        before = _bases(book)

        done = _edited(book, tmp_path, DEPOSIT_HEAD, 'a_usd_deposit_booked_as_income.txt',
                       None, (), '--atomic')

        _accepted(done)
        assert _bases(book) == before
        _sound(book)

    def test_booked_as_income_keeps_the_balance_a_file_stated(self, tmp_path):
        """2,000.00 USD stated: 719.28 was sold outside the book, and stays sold.

        Reopened at what the deposit brought in less its fee, the edit offered
        the 719.28 again.
        """
        book = _book(tmp_path, DEPOSIT)
        self._stated(book, tmp_path, '2000.00')
        before = _bases(book)
        assert ('Assets:Wise USD', 'USD', 'asset', Fraction('2000.00')) in before

        done = _edited(book, tmp_path, DEPOSIT_HEAD, 'a_usd_deposit_booked_as_income.txt')

        _accepted(done)
        assert _bases(book) == before

    def test_a_deposit_into_two_accounts_booked_as_income(self, tmp_path):
        """Each arriving split establishes the cost basis it did, at the same figures."""
        book = _book(tmp_path, 'a_usd_deposit_into_two_accounts_on_a_holding_account.txt')
        before = _bases(book)
        assert ('Assets:USD Savings', 'USD', 'asset', Fraction('50.00')) in before

        done = _edited(book, tmp_path, '2026-08-15 * "Received money in two accounts"',
                       'a_usd_deposit_into_two_accounts_booked_as_income.txt')

        _accepted(done)
        assert _bases(book) == before

    def test_booked_as_income_on_a_balance_that_will_not_parse_is_refused(self, tmp_path):
        """A balance that will not parse is neither cleared nor reopened.

        Left where it is, the fee drawing on it meets no balance it can read
        and is refused as the create path refuses it. The old version is put
        back, so `--verify-costs` still reports the figure.
        """
        book = _book(tmp_path, DEPOSIT)
        repo = GnuCashRepository(str(book))
        repo.open(mode=SessionMode.NORMAL)
        try:
            split = next(each for each in iter_splits(repo.book)
                         if split_guid(each) == '0e510000000000000000000000000a02')
            transaction = split.GetParent()
            transaction.BeginEdit()
            set_custom_metadata(split, {**get_custom_metadata(split),
                                        'cost_basis_balance': 'oops'})
            transaction.CommitEdit()
            repo.save()
        finally:
            repo.close()

        message = _refused(_edited(book, tmp_path, DEPOSIT_HEAD,
                                   'a_usd_deposit_booked_as_income.txt'))

        assert ('cost basis 0e510000000000000000000000000a02 has no balance recorded'
                in message), message
        assert 'Due from director' in _block(_exported(book, tmp_path), DEPOSIT_HEAD)
        checked = _run(CliRunner(), 'fx-balances', str(book), '--verify-costs')
        assert "'oops'" in checked.output, checked.output

    def test_booked_as_income_holds_no_balance_where_a_file_cleared_it(self, tmp_path):
        """Cleared, the deposit's cost basis is read as holding nothing, and still is after the edit."""
        book = _book(tmp_path, DEPOSIT)
        self._stated(book, tmp_path, '')
        before = _bases(book)
        assert not [row for row in before if row[0] == 'Assets:Wise USD']

        done = _edited(book, tmp_path, DEPOSIT_HEAD, 'a_usd_deposit_booked_as_income.txt')

        _accepted(done)
        assert _bases(book) == before

    def test_a_fee_drawing_more_than_the_stated_balance_leaves_is_refused(self, tmp_path):
        """0.00 USD stated, every dollar sold outside the book: a fee of 1.00 where 0.72 was draws 0.28 nobody holds."""
        book = _book(tmp_path, DEPOSIT)
        self._stated(book, tmp_path, '0.00')
        before = _bases(book)
        text = _exported(book, tmp_path)
        booked = (_without_comments(FIXTURES + 'a_usd_deposit_booked_as_income.txt')
                  .replace('Expenses:Bank charges 1.01 CAD', 'Expenses:Bank charges 1.40 CAD')
                  .replace('Assets:Wise USD -0.72 USD', 'Assets:Wise USD -1.00 USD')
                  .replace('value: "-1.01"', 'value: "-1.40"'))
        edit = tmp_path / 'edit.txt'
        edit.write_text(text.replace(_block(text, DEPOSIT_HEAD), booked))

        message = _refused(_run(CliRunner(), 'import', str(book), str(edit), '--strategy',
                                'update', '--include-business-objects', '--fx-rates', RATES))

        assert ('would hold 2719.00 USD as this edit opens it. The book held 2719.28 less '
                'than its figures give') in message, message
        assert 'would draw 0.28 more than it holds' in message, message
        assert _bases(book) == before

    def test_booked_as_income_with_a_balance_its_own_block_states(self, tmp_path):
        """The block states 2,000.00, net of its own fee, and that is the balance."""
        book = _book(tmp_path, DEPOSIT)
        text = _exported(book, tmp_path)
        booked = _without_comments(FIXTURES + 'a_usd_deposit_booked_as_income.txt').replace(
            '\t\tvalue: "3815.89"\n',
            '\t\tvalue: "3815.89"\n\t\tcost_basis_balance: "2000.00"\n')
        edit = tmp_path / 'edit.txt'
        edit.write_text(text.replace(_block(text, DEPOSIT_HEAD), booked))

        done = _run(CliRunner(), 'import', str(book), str(edit), '--strategy', 'update',
                    '--include-business-objects', '--fx-rates', RATES)

        _accepted(done)
        assert ('Assets:Wise USD', 'USD', 'asset', Fraction('2000.00')) in _bases(book)

    def test_booked_as_income_after_a_sale_drew_on_it(self, tmp_path):
        book = _book(tmp_path, DEPOSIT, SALE)
        before = _bases(book)

        done = _edited(book, tmp_path, DEPOSIT_HEAD, 'a_usd_deposit_booked_as_income.txt')

        _accepted(done)
        assert _bases(book) == before


def test_the_fee_booked_as_part_of_the_exchange_spread(tmp_path):
    """E8: the deposit establishes a cost basis for what it now brings in."""
    book = _book(tmp_path, DEPOSIT)

    done = _edited(book, tmp_path, DEPOSIT_HEAD,
                   'a_usd_deposit_booked_with_its_fee_in_the_exchange_spread.txt')

    _accepted(done)
    assert ('Assets:Wise USD', 'USD', 'asset', Fraction('2719.28')) in _bases(book)
    _sound(book)


def test_booked_as_the_invoice_after_a_sale_drew_on_the_deposit_is_refused(tmp_path):
    """E9: the sale would draw on a cost basis the new version does not establish."""
    book = _book(tmp_path, DEPOSIT, SALE)
    before = _bases(book)
    posting = _posting_split(_exported(book, tmp_path), '2720.00')

    message = _refused(_edited(book, tmp_path, DEPOSIT_HEAD,
                               'a_usd_deposit_booked_as_the_invoice_it_collected.txt',
                               'invoice "INV-USD-1"', INVOICE_PAYMENT,
                               invoice_posting=posting))

    assert "'Sold 500 USD'" in message, message
    assert _bases(book) == before
    assert not _paid_by(book, tmp_path, 'invoice "INV-USD-1"', '0e510000000000000000000000000a01')


class TestAnOwedFeeBookedAsASpend:
    """E7a and E7b: read again, the fee spends dollars held, and gives the cost basis they came out of."""

    def test_the_fee_establishes_a_cost_basis_on_the_owed_side_as_imported(self, tmp_path):
        book = _book(tmp_path, FEE_FIRST, DOLLARS)

        assert ('Assets:Wise USD', 'USD', 'liability', Fraction('1.00')) in _bases(book)

    def test_booked_giving_the_dollars_held(self, tmp_path):
        book = _book(tmp_path, FEE_FIRST, DOLLARS)

        done = _edited(book, tmp_path, FEE_HEAD,
                       'a_usd_fee_booked_as_the_bank_charge_drawing_on_the_dollars_held.txt')

        _accepted(done)
        wise = [row for row in _bases(book) if row[0] == 'Assets:Wise USD']
        assert wise == [('Assets:Wise USD', 'USD', 'asset', Fraction('1999.00'))]
        _sound(book)

    def test_booked_giving_no_cost_basis_is_refused(self, tmp_path):
        book = _book(tmp_path, FEE_FIRST, DOLLARS)
        before = _bases(book)

        message = _refused(_edited(book, tmp_path, FEE_HEAD,
                                   'a_usd_fee_booked_as_the_bank_charge_giving_no_cost_basis.txt'))

        assert ('this transaction spends 1.00 USD the book held, which draws down a '
                'cost basis, but no split says which one') in message, message
        assert _bases(book) == before


@pytest.mark.parametrize('booked, refusal', [
    pytest.param('a_usd_deposit_booked_as_the_invoice_it_collected_with_the_fee_giving_no_cost_basis.txt',
                 "cost_basis_split_guid '0e510000000000000000000000000a02' matches a split "
                 'that is no USD cost basis', id='the-pick-left-out-is-kept'),
    pytest.param('a_usd_deposit_booked_as_the_invoice_it_collected_with_the_fees_cost_basis_cleared.txt',
                 'this transaction spends 0.72 USD the book held, which draws down a cost '
                 'basis, but no split says which one', id='the-pick-cleared'),
])
def test_a_new_version_that_is_not_a_correct_transaction_is_refused(tmp_path, booked, refusal):
    """E13: refused with a new import's reasons, and the transaction is as it was.

    A block leaving `cost_basis_split_guid:` out keeps the pick the split
    has, so the fee goes on drawing on the deposit, which the new version
    does not establish as a cost basis. Cleared with `""`, the fee spends the
    dollars the transaction collects giving no cost basis.
    """
    book = _book(tmp_path, DEPOSIT)
    before = _bases(book)
    deposit = _block(_exported(book, tmp_path), DEPOSIT_HEAD)

    message = _refused(_edited(book, tmp_path, DEPOSIT_HEAD, booked,
                               'invoice "INV-USD-1"', INVOICE_PAYMENT))

    assert refusal in message, message
    assert _bases(book) == before
    assert _block(_exported(book, tmp_path), DEPOSIT_HEAD) == deposit
    assert not _paid_by(book, tmp_path, 'invoice "INV-USD-1"', '0e510000000000000000000000000a01')


def test_a_refused_edit_leaves_the_type_the_transaction_had(tmp_path):
    """The refused version states `txn_type: P`, and the saved book keeps the type the deposit had.

    Without `--include-business-objects` no `payment:` block is read, and the
    file corrects a bank charge's description as well, so the run saves. The
    type is set before the commit and the refusal comes after it; put back
    without it, the deposit was saved as a payment on GnuCash 3.4 to 4.8,
    which store the type.
    """
    book = _book(tmp_path, DEPOSIT, 'a_cad_bank_charge_on_the_holding_account.txt')
    text = _exported(book, tmp_path)
    deposit = _block(text, DEPOSIT_HEAD)
    booked = _without_comments(
        FIXTURES + 'a_usd_deposit_booked_as_the_invoice_it_collected_with_the_fees_cost_basis_cleared.txt')
    edit = tmp_path / 'edit.txt'
    edit.write_text(text.replace(deposit, booked)
                    .replace('* "Bank charge"', '* "Bank charge for September"'))

    refused = _run(CliRunner(), 'import', str(book), str(edit), '--strategy', 'update',
                   '--fx-rates', RATES)

    assert refused.exit_code != 0 and 'Changes saved' in refused.output, refused.output
    assert _block(_exported(book, tmp_path), DEPOSIT_HEAD) == deposit


def test_a_refused_edit_leaves_the_time_the_transaction_was_posted_at(tmp_path):
    """Posted at local midnight, as GnuCash 3.4 to 4.8's register writes a date, and still so after a refused edit.

    Put back through the setter that moves a date to GnuCash's neutral time,
    the refused edit left the transaction at 10:59 UTC. The export writes the
    date alone, so the time is read from the book. The file corrects a bank
    charge's description as well, and gives no `payment:` block, so the run
    saves.
    """
    from datetime import datetime

    def posted(book):
        repo = GnuCashRepository(str(book))
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            return next(each for each in iter_splits(repo.book)
                        if split_guid(each) == '0e510000000000000000000000000a02'
                        ).GetParent().GetDate()
        finally:
            repo.close()

    book = _book(tmp_path, DEPOSIT, 'a_cad_bank_charge_on_the_holding_account.txt')
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        transaction = next(each for each in iter_splits(repo.book)
                           if split_guid(each) == '0e510000000000000000000000000a02').GetParent()
        transaction.BeginEdit()
        transaction.SetDatePostedSecs(datetime(2026, 8, 13))
        transaction.CommitEdit()
        repo.save()
    finally:
        repo.close()
    assert posted(book) == datetime(2026, 8, 13)
    text = _exported(book, tmp_path)
    booked = _without_comments(
        FIXTURES + 'a_usd_deposit_booked_as_the_invoice_it_collected_with_the_fees_cost_basis_cleared.txt')
    edit = tmp_path / 'edit.txt'
    edit.write_text(text.replace(_block(text, DEPOSIT_HEAD), booked)
                    .replace('* "Bank charge"', '* "Bank charge for September"'))

    refused = _run(CliRunner(), 'import', str(book), str(edit), '--strategy', 'update',
                   '--fx-rates', RATES)

    assert refused.exit_code != 0 and 'Changes saved' in refused.output, refused.output
    assert posted(book) == datetime(2026, 8, 13)


def test_a_give_back_failing_part_way_is_taken_again(tmp_path):
    """The sale's second cost basis holds a `cost_basis_brought_in` that will not parse.

    Written through the bindings, as nothing this tool writes can be. The
    sale is read as new, what it drew is given back, and giving back to the
    second cost basis fails after the first has had its 5.00 back. The
    refused edit is put back, and the first gives the 5.00 up again.
    """
    book = _book(tmp_path, DOLLARS, DEPOSIT, 'usd_sold_from_the_deposit_and_the_dollars_bought.txt',
                 'a_cad_bank_charge_on_the_holding_account.txt')
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        split = next(each for each in iter_splits(repo.book)
                     if split_guid(each) == '0e510000000000000000000000000d02')
        transaction = split.GetParent()
        transaction.BeginEdit()
        set_custom_metadata(split, {**get_custom_metadata(split),
                                    'cost_basis_brought_in': 'oops'})
        transaction.CommitEdit()
        repo.save()
    finally:
        repo.close()
    before = _bases(book)
    assert ('Assets:Wise USD', 'USD', 'asset', Fraction('2714.28')) in before
    text = _exported(book, tmp_path)
    head = '2026-08-20 * "Sold 10 USD from two cost bases"'
    sale = _block(text, head)
    edit = tmp_path / 'edit.txt'
    edit.write_text(text.replace(sale, sale.replace('Assets:Chequing 14.00 CAD',
                                                    'Assets:Due from director 14.00 CAD'))
                    .replace('* "Bank charge"', '* "Bank charge for September"'))

    refused = _run(CliRunner(), 'import', str(book), str(edit), '--strategy', 'update',
                   '--fx-rates', RATES)

    assert refused.exit_code != 0 and 'Changes saved' in refused.output, refused.output
    assert "Invalid literal for Fraction: 'oops'" in refused.output, refused.output
    assert _bases(book) == before


def test_a_refused_edit_leaves_the_splits_it_removed_reconciled(tmp_path):
    """The fee's two splits, reconciled in GnuCash, are removed by an edit that is refused after its commit.

    The edit folds the fee into the exchange spread while a sale draws on
    the deposit, so it is refused, and the fee's splits are made again under
    their own guids. Made again unreconciled, the saved book had lost the
    reconciliation GnuCash's register recorded on them. The file corrects a
    bank charge's description as well, so the run saves.
    """
    from datetime import datetime

    fee = ('0e510000000000000000000000000a04', '0e510000000000000000000000000a05')

    def reconciled(book):
        repo = GnuCashRepository(str(book))
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            return sorted((split_guid(each), each.GetReconcile(), each.GetDateReconciled())
                          for each in iter_splits(repo.book) if split_guid(each) in fee)
        finally:
            repo.close()

    book = _book(tmp_path, DEPOSIT, SALE, 'a_cad_bank_charge_on_the_holding_account.txt')
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        splits = [each for each in iter_splits(repo.book) if split_guid(each) in fee]
        transaction = splits[0].GetParent()
        transaction.BeginEdit()
        for split in splits:
            split.SetReconcile('y')
            split.SetDateReconciledSecs(datetime(2026, 8, 31))
        transaction.CommitEdit()
        repo.save()
    finally:
        repo.close()
    before = reconciled(book)
    assert [state for _guid, state, _when in before] == ['y', 'y']
    text = _exported(book, tmp_path)
    edit = tmp_path / 'edit.txt'
    edit.write_text(text.replace(_block(text, DEPOSIT_HEAD), _without_comments(
        FIXTURES + 'a_usd_deposit_booked_with_its_fee_in_the_exchange_spread.txt'))
        .replace('* "Bank charge"', '* "Bank charge for September"'))

    refused = _run(CliRunner(), 'import', str(book), str(edit), '--strategy', 'update',
                   '--fx-rates', RATES)

    assert refused.exit_code != 0 and 'Changes saved' in refused.output, refused.output
    assert 'touches a cost basis another transaction draws on' in refused.output, refused.output
    assert reconciled(book) == before


def test_the_fee_giving_an_invoice_the_transaction_does_not_collect_is_refused(tmp_path):
    """E13b: the fee draws on INV-USD-2 while the deposit collects INV-USD-1.

    Nothing of INV-USD-2 has been collected, by its lot or by this
    transaction, so its dollars are owed rather than held, and the fee has
    none of them to spend.
    """
    book = _book(tmp_path, DEPOSIT)
    before = _bases(book)
    other_invoice = _posting_split(_exported(book, tmp_path), '4000.00')

    message = _refused(_edited(book, tmp_path, DEPOSIT_HEAD,
                               'a_usd_deposit_booked_as_the_invoice_it_collected.txt',
                               'invoice "INV-USD-1"', INVOICE_PAYMENT,
                               invoice_posting=other_invoice))

    assert 'the invoice it belongs to has not been collected' in message, message
    assert _bases(book) == before


def test_a_payment_block_giving_a_transaction_the_import_refused_records_no_payment(tmp_path):
    """E15: the transaction is refused, and the invoice's block with it."""
    book = _book(tmp_path)
    text = _exported(book, tmp_path) + '\n' + _without_comments(
        FIXTURES
        + 'a_usd_deposit_booked_as_the_invoice_it_collected_with_the_fee_giving_no_cost_basis.txt')
    ledger = tmp_path / 'ledger.txt'
    ledger.write_text(_with_payment(text, 'invoice "INV-USD-1"', INVOICE_PAYMENT))

    message = _refused(_run(CliRunner(), 'import', str(book), str(ledger),
                            '--include-business-objects', '--fx-rates', RATES))

    # Its own sentences first, and the transaction's reason last, whole: the
    # reason ends in a list here, and a sentence pasted after it ran into
    # the list's lead-in.
    assert ('0e510000000000000000000000000a01 is a transaction this file states, and it '
            'was not imported. No payment is recorded from this block') in message, message
    assert 'Why it was not imported: this transaction spends 0.72 USD' in message, message
    assert 'payment: none' in _block(_exported(book, tmp_path), 'invoice "INV-USD-1"')
    assert [row for row in _bases(book) if row[0] == 'Assets:Wise USD'] == []
