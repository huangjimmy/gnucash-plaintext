"""An `--atomic` import brings a book back to a state it exported, in one file (Q-053).

An owner books a statement line: a deposit imported against
`Assets:Due from director` is edited into the invoice it collected. Later they
find the booking wrong and import the export they kept from before it. That
file is the earlier state of the book, whole. gnucash-plaintext keeps no
history and cannot know the file is an undo; the test knows, because it holds
the earlier export.

Under `--atomic` every block of the file is applied, in the order the file
lists them, and the book is checked once, finished, before it is saved. A check
that depends on the order the blocks are applied in is not asked of a book
half way through. The book the file describes is either the book saved, or
nothing is saved.
"""

import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from tests.conftest import _run

FIXTURES = 'tests/fixtures/'
BASE = FIXTURES + 'a_usd_invoice_and_bill_for_statement_lines_on_a_holding_account.txt'
RATES = FIXTURES + 'usd_at_the_rates_the_statement_lines_records_were_posted_at.yaml'

INVOICE = 'invoice "INV-USD-1"'
DEPOSIT_HEAD = '2026-08-13 * "Received money from Example Customer Inc"'
FEE_HEAD = '2026-08-13 * "Transfer fee"'


def _book(tmp_path, *statements):
    """The base book, then each statement's lines imported onto it in turn."""
    book = tmp_path / 'book.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(book), BASE,
                '--include-business-objects', '--fx-rates', RATES)
    assert made.exit_code == 0, made.output
    for statement in statements:
        done = _run(CliRunner(), 'import', str(book), FIXTURES + statement, '--fx-rates', RATES)
        assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    return book


def _exported(book, tmp_path, name='exported.txt'):
    ledger = tmp_path / name
    done = _run(CliRunner(), 'export', str(book), str(ledger), '--include-business-objects')
    assert done.exit_code == 0, done.output
    return ledger.read_text()


def _block(text, head):
    return re.search(rf'{re.escape(head)}\n(?:\t[^\n]*\n)*', text).group(0)


def _without_comments(path):
    return ''.join(line for line in open(path).read().splitlines(keepends=True)
                   if not line.startswith('#'))


def _with_payment(text, record, payment):
    """The record's `payment: none` replaced with the payment block `payment`."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(record))
    end = start + 1
    while end < len(lines) and (lines[end].startswith('\t') or not lines[end].strip()):
        end += 1
    block = [line for line in lines[start:end] if line.strip() != 'payment: none']
    return '\n'.join(lines[:start] + block + payment + lines[end:]) + '\n'


def _posting_split(text):
    """The guid of the receivable split INV-USD-1 was posted with."""
    return re.search(r'Accounts Receivable USD 2720\.00 USD\n'
                     r'\t+guid: "([0-9a-f]{32})"', text).group(1)


def _imported(book, tmp_path, text, *flags):
    ledger = tmp_path / 'to_import.txt'
    ledger.write_text(text)
    return _run(CliRunner(), 'import', str(book), str(ledger), '--strategy', 'update',
                '--include-business-objects', '--fx-rates', RATES, *flags)


def _accepted(done):
    message = done.output + str(done.exception)
    assert done.exit_code == 0 and 'Errors:       0' in done.output, message


#: The memo INV-USD-1's `payment:` block writes onto the deposit's bank split
#: and receivable split. The export kept from before the booking has no memo
#: line on either, and a line a file leaves out says nothing about it (README,
#: "What a key says, and what leaving it out says"), so the memo stays.
MEMO = '\t\tmemo:"Received money from Example Customer Inc"\n'


def _blocks(text):
    """The export's blocks, each a line that opens one and the lines under it, in no order.

    What the book holds is compared apart from the order the export writes it
    in, which `test_the_export_keeps_its_order` asserts on its own, so a
    failure says which of the two went wrong.
    """
    blocks, block = [], []
    for line in text.splitlines():
        if line and not line[0].isspace() and block:
            blocks.append('\n'.join(block))
            block = []
        block.append(line)
    blocks.append('\n'.join(block))
    return sorted(blocks)


def _the_same_book(after, before):
    assert _blocks(after) == _blocks(before)


def _as_before_but_the_memo(after, before, memo=MEMO):
    """The book exports as it did before the booking, but for the booking's memo on the settlement's two splits."""
    assert memo not in before
    assert after.count(memo) == 2
    _the_same_book(after.replace(memo, ''), before)


def _cost_bases(book):
    """What `fx-balances --verify-costs` lists, each row with the line under it, in no order, having found nothing wrong."""
    listed = _run(CliRunner(), 'fx-balances', str(book), '--verify-costs')
    assert listed.exit_code == 0 and 'warning' not in listed.output, listed.output
    return _blocks(listed.output)


class TestTheFeeAsATransactionOfItsOwn:
    """The deposit and its fee are two transactions, the fee drawing on the deposit's cost basis."""

    STATEMENT = 'a_usd_deposit_on_a_holding_account_and_its_fee_as_its_own_transaction.txt'
    BOOKED = 'a_usd_deposit_and_its_own_fee_transaction_booked_as_the_invoice_it_collected.txt'
    PAYMENT = [
        '\tpayment:',
        '\t\tdate: 2026-08-13',
        '\t\tamount: 2720',
        '\t\taccount: "Assets:Wise USD"',
        '\t\ttxn_guid: "0e530000000000000000000000000c01"',
        '\t\ttxn_split_guid: "0e530000000000000000000000000c03"',
        '\t\tmemo: "Received money from Example Customer Inc"',
    ]

    def _booking(self, before):
        """The export `before`, with the deposit and its fee booked as INV-USD-1's collection."""
        booked = _without_comments(FIXTURES + self.BOOKED).replace(
            '{invoice_posting}', _posting_split(before))
        deposit, fee = _block(booked, DEPOSIT_HEAD), _block(booked, FEE_HEAD)
        text = before.replace(_block(before, DEPOSIT_HEAD), deposit)
        text = text.replace(_block(text, FEE_HEAD), fee)
        return _with_payment(text, INVOICE, self.PAYMENT)

    def test_the_booking_is_accepted_in_one_file(self, tmp_path):
        book = _book(tmp_path, self.STATEMENT)
        before = _exported(book, tmp_path, 'before.txt')

        _accepted(_imported(book, tmp_path, self._booking(before), '--atomic'))

        assert 'txn_guid: "0e530000000000000000000000000c01"' in _block(
            _exported(book, tmp_path), INVOICE)
        _cost_bases(book)

    def test_the_export_kept_from_before_brings_the_book_back(self, tmp_path):
        book = _book(tmp_path, self.STATEMENT)
        before = _exported(book, tmp_path, 'before.txt')
        bases_before = _cost_bases(book)
        _accepted(_imported(book, tmp_path, self._booking(before), '--atomic'))

        done = _imported(book, tmp_path, before, '--atomic')

        _accepted(done)
        _as_before_but_the_memo(_exported(book, tmp_path), before)
        assert _cost_bases(book) == bases_before
        assert ('invoice "INV-USD-1": took off the payment of 2720.00 USD by '
                'transaction 0e530000000000000000000000000c01, onto '
                'Assets:Due from director, as this file states the invoice '
                'unpaid by it') in done.output

    def test_the_booking_imported_again_books_it_again(self, tmp_path):
        book = _book(tmp_path, self.STATEMENT)
        before = _exported(book, tmp_path, 'before.txt')
        _accepted(_imported(book, tmp_path, self._booking(before), '--atomic'))
        booked = _exported(book, tmp_path, 'booked.txt')
        bases_booked = _cost_bases(book)
        _accepted(_imported(book, tmp_path, before, '--atomic'))

        _accepted(_imported(book, tmp_path, booked, '--atomic'))

        _the_same_book(_exported(book, tmp_path), booked)
        assert _cost_bases(book) == bases_booked

    def test_a_rolled_back_undo_says_no_payment_was_taken_off(self, tmp_path):
        """The fee in the undo states a cost basis the book has not got, so the run rolls back after the payment was taken off in memory."""
        book = _book(tmp_path, self.STATEMENT)
        before = _exported(book, tmp_path, 'before.txt')
        _accepted(_imported(book, tmp_path, self._booking(before), '--atomic'))
        fee = _block(before, FEE_HEAD)
        wrong = before.replace(fee, fee.replace(
            'cost_basis_split_guid: "0e530000000000000000000000000c02"',
            'cost_basis_split_guid: "0e53000000000000000000000000ffff"'))

        done = _imported(book, tmp_path, wrong, '--atomic')

        assert done.exit_code != 0, done.output
        assert 'took off the payment' not in done.output

    def test_a_file_whose_finished_book_is_wrong_changes_nothing(self, tmp_path):
        """The fee left drawing on the deposit's cost basis, which the booking does not establish."""
        book = _book(tmp_path, self.STATEMENT)
        before = _exported(book, tmp_path, 'before.txt')
        wrong = self._booking(before).replace(
            _block(self._booking(before), FEE_HEAD), _block(before, FEE_HEAD))
        on_disk = Path(book).read_bytes()

        done = _imported(book, tmp_path, wrong, '--atomic')

        assert done.exit_code != 0, done.output
        assert Path(book).read_bytes() == on_disk


def test_a_block_applied_again_is_no_duplicate_of_one_the_run_created(tmp_path):
    """Two fees of one day on the same accounts, the second applied in a later pass: both are imported, as without `--atomic`."""
    book = _book(tmp_path, 'usd_bought_into_wise_before_the_statement.txt')

    done = _run(CliRunner(), 'import', str(book),
                FIXTURES + 'two_fees_of_one_day_the_second_drawing_on_dollars_bought_below_it.txt',
                '--fx-rates', RATES, '--atomic')

    _accepted(done)
    assert 'Transactions: 3' in done.output
    exported = _exported(book, tmp_path)
    assert 'Assets:Wise USD -0.72 USD' in exported and 'Assets:Wise USD -1.44 USD' in exported


def test_a_block_whose_guid_nothing_can_parse_is_refused_and_listed(tmp_path):
    """Refused as any import refuses it, with the run's summary, when the refused blocks are applied again."""
    book = _book(tmp_path, 'usd_bought_into_wise_before_the_statement.txt')
    on_disk = book.read_bytes()

    done = _run(CliRunner(), 'import', str(book),
                FIXTURES + 'a_transaction_whose_guid_nothing_can_parse.txt',
                '--fx-rates', RATES, '--atomic')

    assert done.exit_code == 1, done.output
    assert 'Errors:       1' in done.output
    assert '✗ Rolled back' in done.output
    assert book.read_bytes() == on_disk


@pytest.mark.parametrize('case', ['TestTheFeeAsATransactionOfItsOwn',
                                  'TestTheFeeInTheDepositsOwnTransaction'])
def test_the_export_keeps_its_order(tmp_path, case):
    """The undo leaves every transaction where the export wrote it, the order of one day's included.

    The export writes a day's transactions in GnuCash's own order, which reads
    the time each was posted at. INV-USD-1's posting block is edited by the
    undo, restating its cost basis balance, and on GnuCash 3.8, which posts an
    invoice at midnight, the edit moved the posting to 10:59 UTC on the same
    day: it came out after INV-USD-2's. An edit stating the same day leaves the
    time as it was.
    """
    case = globals()[case]()
    book = _book(tmp_path, case.STATEMENT)
    before = _exported(book, tmp_path, 'before.txt')
    _accepted(_imported(book, tmp_path, case._booking(before), '--atomic'))

    _accepted(_imported(book, tmp_path, before, '--atomic'))

    assert _exported(book, tmp_path).replace(MEMO, '') == before


class TestASplitInALotTheFileDoesNotTakeOff:
    """A split settling a record is taken off it only where the file states the record unpaid by its transaction.

    Otherwise the edit moving the split to another account is refused, as it is
    without `--atomic`: moving a split in a lot is the record's business.
    """

    STATEMENT = TestTheFeeAsATransactionOfItsOwn.STATEMENT

    def _booked(self, tmp_path):
        """The book with the deposit booked as INV-USD-1's collection, and its export."""
        book = _book(tmp_path, self.STATEMENT)
        before = _exported(book, tmp_path, 'before.txt')
        _accepted(_imported(book, tmp_path,
                            TestTheFeeAsATransactionOfItsOwn()._booking(before), '--atomic'))
        return book, before, _exported(book, tmp_path, 'booked.txt')

    def _refused_to_move(self, book, tmp_path, text):
        on_disk = Path(book).read_bytes()
        done = _imported(book, tmp_path, text, '--atomic')
        assert done.exit_code != 0, done.output
        assert 'take it out of the lot first' in done.output, done.output
        assert Path(book).read_bytes() == on_disk

    def test_where_the_file_does_not_state_the_invoice(self, tmp_path):
        book, before, booked = self._booked(tmp_path)
        text = booked.replace(_block(booked, DEPOSIT_HEAD), _block(before, DEPOSIT_HEAD))
        text = text.replace(_block(text, INVOICE), '')

        self._refused_to_move(book, tmp_path, text)

    def test_where_the_file_still_pays_the_invoice_with_it(self, tmp_path):
        book, before, booked = self._booked(tmp_path)
        text = booked.replace(_block(booked, DEPOSIT_HEAD), _block(before, DEPOSIT_HEAD))

        self._refused_to_move(book, tmp_path, text)

    def test_where_it_is_the_invoices_own_posting(self, tmp_path):
        book = _book(tmp_path, self.STATEMENT)
        before = _exported(book, tmp_path)
        posting = _block(before, '2026-07-31 * "INV-USD-2" "Invoice INV-USD-2"')

        self._refused_to_move(book, tmp_path, before.replace(posting, posting.replace(
            'Assets:Accounts Receivable USD 4000.00 USD', 'Assets:USD Savings 4000.00 USD')))

    def test_where_it_stands_as_the_customers_credit(self, tmp_path):
        book = _book(tmp_path, 'a_usd_advance_parked_as_the_customers_credit.txt')
        before = _exported(book, tmp_path)
        advance = _block(before, '2026-08-14 * "Advance from Example Customer Inc"')

        self._refused_to_move(book, tmp_path, before.replace(advance, advance.replace(
            'Assets:Accounts Receivable USD -100.00 USD', 'Assets:USD Savings -100.00 USD')))


class TestAWithdrawalBookedAsTheBillItPaid:
    """A withdrawal and its fee, on the suspense account, booked as BILL-USD-1's payment (Q-051 E4)."""

    STATEMENTS = ('usd_bought_into_wise_before_the_statement.txt',
                  'a_usd_withdrawal_and_its_fee_on_a_holding_account.txt')
    HEAD = '2026-08-20 * "Paid Example Supplier Inc"'
    BILL = 'bill "BILL-USD-1"'
    MEMO = '\t\tmemo:"Paid Example Supplier Inc"\n'
    PAYMENT = [
        '\tpayment:',
        '\t\tdate: 2026-08-20',
        '\t\tamount: 1000',
        '\t\taccount: "Assets:Wise USD"',
        '\t\ttxn_guid: "0e510000000000000000000000000b01"',
        '\t\ttxn_split_guid: "0e510000000000000000000000000b03"',
        '\t\tmemo: "Paid Example Supplier Inc"',
    ]

    def _booking(self, before):
        booked = _without_comments(FIXTURES + 'a_usd_withdrawal_booked_as_the_bill_it_paid.txt')
        text = before.replace(_block(before, self.HEAD), booked)
        return _with_payment(text, self.BILL, self.PAYMENT)

    def test_the_export_kept_from_before_brings_the_book_back(self, tmp_path):
        book = _book(tmp_path, *self.STATEMENTS)
        before = _exported(book, tmp_path, 'before.txt')
        bases_before = _cost_bases(book)
        _accepted(_imported(book, tmp_path, self._booking(before), '--atomic'))

        _accepted(_imported(book, tmp_path, before, '--atomic'))

        _as_before_but_the_memo(_exported(book, tmp_path), before, self.MEMO)
        assert _cost_bases(book) == bases_before

    def test_the_booking_imported_again_books_it_again(self, tmp_path):
        book = _book(tmp_path, *self.STATEMENTS)
        before = _exported(book, tmp_path, 'before.txt')
        _accepted(_imported(book, tmp_path, self._booking(before), '--atomic'))
        booked = _exported(book, tmp_path, 'booked.txt')
        bases_booked = _cost_bases(book)
        _accepted(_imported(book, tmp_path, before, '--atomic'))

        _accepted(_imported(book, tmp_path, booked, '--atomic'))

        _the_same_book(_exported(book, tmp_path), booked)
        assert _cost_bases(book) == bases_booked


class TestABookKeptInHongKongDollars:
    """A deposit on the suspense account of a book kept in HKD, booked as the invoice it collected, and undone."""

    HEAD = '2026-03-12 * "Received from Harbour Trading"'
    INVOICE = 'invoice "INV-HK-1"'
    MEMO = '\t\tmemo:"Received from Harbour Trading"\n'
    PAYMENT = [
        '\tpayment:',
        '\t\tdate: 2026-03-12',
        '\t\tamount: 7800',
        '\t\taccount: "Assets:HKD Bank"',
        '\t\ttxn_guid: "0e530000000000000000000000000f01"',
        '\t\ttxn_split_guid: "0e530000000000000000000000000f03"',
        '\t\tmemo: "Received from Harbour Trading"',
    ]

    def _book(self, tmp_path):
        book = tmp_path / 'book.gnucash'
        made = _run(CliRunner(), 'import', '--new', str(book),
                    FIXTURES + 'an_hkd_book_with_an_invoice_and_its_deposit_on_a_suspense_account.txt',
                    '--include-business-objects')
        assert made.exit_code == 0 and 'Errors:       0' in made.output, made.output
        return book

    def _booking(self, before):
        deposit = _block(before, self.HEAD)
        text = before.replace(deposit, deposit.replace(
            'Assets:Suspense -7800.00 HKD', 'Assets:Accounts Receivable -7800.00 HKD'))
        return _with_payment(text, self.INVOICE, self.PAYMENT)

    def test_the_booking_is_undone_and_done_again(self, tmp_path):
        book = self._book(tmp_path)
        before = _exported(book, tmp_path, 'before.txt')
        _accepted(_imported(book, tmp_path, self._booking(before), '--atomic'))
        booked = _exported(book, tmp_path, 'booked.txt')
        assert 'txn_guid: "0e530000000000000000000000000f01"' in _block(booked, self.INVOICE)

        _accepted(_imported(book, tmp_path, before, '--atomic'))
        _as_before_but_the_memo(_exported(book, tmp_path), before, self.MEMO)

        _accepted(_imported(book, tmp_path, booked, '--atomic'))
        _the_same_book(_exported(book, tmp_path), booked)


class TestTheFeeInTheDepositsOwnTransaction:
    """The fee is a split of the deposit's transaction (Q-051 E1)."""

    STATEMENT = 'a_usd_deposit_and_its_fee_on_a_holding_account.txt'
    BOOKED = 'a_usd_deposit_booked_as_the_invoice_it_collected.txt'
    PAYMENT = [
        '\tpayment:',
        '\t\tdate: 2026-08-13',
        '\t\tamount: 2720',
        '\t\taccount: "Assets:Wise USD"',
        '\t\ttxn_guid: "0e510000000000000000000000000a01"',
        '\t\ttxn_split_guid: "0e510000000000000000000000000a03"',
        '\t\tmemo: "Received money from Example Customer Inc"',
    ]

    def _booking(self, before):
        booked = _without_comments(FIXTURES + self.BOOKED).replace(
            '{invoice_posting}', _posting_split(before))
        text = before.replace(_block(before, DEPOSIT_HEAD), booked)
        return _with_payment(text, INVOICE, self.PAYMENT)

    def test_the_export_kept_from_before_brings_the_book_back(self, tmp_path):
        book = _book(tmp_path, self.STATEMENT)
        before = _exported(book, tmp_path, 'before.txt')
        bases_before = _cost_bases(book)
        _accepted(_imported(book, tmp_path, self._booking(before), '--atomic'))

        _accepted(_imported(book, tmp_path, before, '--atomic'))

        _as_before_but_the_memo(_exported(book, tmp_path), before)
        assert _cost_bases(book) == bases_before

    def test_the_booking_imported_again_books_it_again(self, tmp_path):
        book = _book(tmp_path, self.STATEMENT)
        before = _exported(book, tmp_path, 'before.txt')
        _accepted(_imported(book, tmp_path, self._booking(before), '--atomic'))
        booked = _exported(book, tmp_path, 'booked.txt')
        bases_booked = _cost_bases(book)
        _accepted(_imported(book, tmp_path, before, '--atomic'))

        _accepted(_imported(book, tmp_path, booked, '--atomic'))

        _the_same_book(_exported(book, tmp_path), booked)
        assert _cost_bases(book) == bases_booked
