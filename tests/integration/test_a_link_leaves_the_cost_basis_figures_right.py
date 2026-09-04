"""Q-040: a transaction that stops being a borrowing gives up its cost basis.

USD arriving in an asset account, against CAD going out of an asset or onto a
liability, is the shape of buying or borrowing USD, so importing one opens a
cost basis on the split that received the USD.

What that transaction turns out to be decides whether the basis stays:

- linked to pay an invoice in full, it is neither a purchase nor a borrowing
  any more — it is that invoice being paid, and the invoice's own posting split
  has had a cost basis for the same USD since it was posted. The basis the
  import opened is discarded, or the same USD has two. The link is refused
  while a disposal still draws on that basis, because the `share_price:` on
  the deposit's USD split and the invoice's posting rate need not agree.
- linked to pay a bill, USD drawn on a credit line is still borrowed: the
  payable is paid and the credit line is still owed. So it is still a
  borrowing and its basis stands, kept by writing the price onto the split.

The reproduction is the four steps in `docs/issues/Q-040-…`, measured from a
real book.
"""

import re
import time

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.kvp import get_custom_metadata
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import (
    COST_BASIS_BALANCE_KEY,
    iter_splits,
    split_guid,
)

RATES = 'tests/fixtures/fx_rates_usd_two_invoice_dates.yaml'
LOW_ON_THE_DAY = 'tests/fixtures/fx_rates_usd_low_on_the_deposit_date.yaml'
BANK = ('Assets:Current assets:Cash and deposits:Deposits in Canadian banks '
        'and institutions – Foreign currency:Foreign Payments Provider '
        'Chequing 000000000000001')
DEPOSIT_TX = '15f40458487e434abd1d9a95c46a7041'
DEPOSIT_SPLIT = '00e958a8d56547d484d7629000292dc3'
PARKED_TX = 'aa11bb22cc33dd44ee55ff6677889900'
EXPENSE_SPLIT = 'bb22cc33dd44ee55ff6677889900aa11'
CREDIT_LINE_SPLIT = 'cc33dd44ee55ff6677889900aa11bb22'


def _run(runner, *args):
    time.sleep(1.1)
    return runner.invoke(cli, list(args))


def _balances(runner, book):
    result = _run(runner, 'fx-balances', str(book))
    assert result.exit_code == 0, result.output
    return result.output


def _stored_balance(book, guid):
    """The `cost_basis_balance` KVP on one split, read straight from the book.

    Read from the split rather than from `fx-balances`, because the whole
    defect is a figure the listing cannot see.
    """
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        for split in iter_splits(repo.book):
            if split_guid(split) == guid:
                return get_custom_metadata(split).get(COST_BASIS_BALANCE_KEY)
    finally:
        repo.close()
    return None


def _with_payment(text, header, payment_lines):
    """Replace a record's `payment: none` with the payment block given."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(header))
    end = start + 1
    while end < len(lines) and (lines[end].startswith('\t') or not lines[end].strip()):
        end += 1
    block = [line for line in lines[start:end] if line.strip() != 'payment: none']
    return '\n'.join(lines[:start] + block + payment_lines + lines[end:]) + '\n'


def _exported(runner, book, path, *extra):
    result = _run(runner, 'export', str(book), str(path), *extra)
    assert result.exit_code == 0, result.output
    return path.read_text()


# ---------------------------------------------------------------- invoice side

def _invoices_and_a_parked_deposit(runner, book, with_fee):
    """Steps 1-3: two invoices posted, the deposit in, optionally the fee."""
    result = runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_two_usd_invoices_posted.txt',
        '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output
    result = _run(runner, 'import', str(book),
                  'tests/fixtures/fx_usd_deposit_against_due_from_director.txt')
    assert result.exit_code == 0, result.output
    if with_fee:
        result = _run(runner, 'import', str(book),
                      'tests/fixtures/fx_fee_drawn_from_the_deposits_basis.txt')
        assert result.exit_code == 0, result.output


def _linked_to_the_invoice(runner, book, tmp_path):
    before = _exported(runner, book, tmp_path / 'before.txt',
                       '--include-business-objects')
    linked = tmp_path / 'linked.txt'
    linked.write_text(_with_payment(before, 'invoice "INV-USD-001"', [
        '\tpayment:',
        '\t\tdate: 2026-08-13',
        '\t\tamount: 2720',
        f'\t\taccount: "{BANK}"',
        f'\t\ttxn_guid: "{DEPOSIT_TX}"',
        '\t\tmemo: "Received money from Example Customer Inc"',
    ]))
    return _run(runner, 'import', str(book), str(linked),
                '--include-business-objects', '--fx-rates', RATES,
                '--strategy', 'update')


def test_a_part_payment_link_hands_the_currency_to_the_receivable(tmp_path):
    """A part payment discards the deposit's basis like any other payment.

    The deposit is 2,720.00 USD and the invoice it is linked to is 5,000.00,
    so 2,280.00 is still owed afterwards — and the receivable has priced the
    whole 5,000.00 since the day it was posted. Keeping the deposit's basis
    beside it counts the same money twice, and the two are not both held back
    for long: pay the rest and the invoice's lot closes, the receivable's
    basis becomes sellable, and the book offers 7,720.00 USD where it holds
    5,000.00. That is the fault this issue is named for, arrived at from the
    other side.

    What it costs is that the currency in the bank is the receivable's from
    the link on: a sale of it waits until the invoice is collected, or says
    `cost_basis_force: true`, which is what that flag is for. The listing
    keeps showing the receivable's basis throughout, so nothing goes quiet.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _invoices_and_a_parked_deposit(runner, book, with_fee=False)
    assert _run(runner, 'import', str(book),
                'tests/fixtures/fx_a_larger_usd_invoice_posted.txt',
                '--include-business-objects', '--fx-rates', RATES
                ).exit_code == 0

    before = _exported(runner, book, tmp_path / 'before.txt',
                       '--include-business-objects')
    linked = tmp_path / 'linked.txt'
    linked.write_text(_with_payment(before, 'invoice "INV-USD-BIG"', [
        '\tpayment:',
        '\t\tdate: 2026-08-13',
        '\t\tamount: 2720',
        f'\t\taccount: "{BANK}"',
        f'\t\ttxn_guid: "{DEPOSIT_TX}"',
    ]))
    result = _run(runner, 'import', str(book), str(linked),
                  '--include-business-objects', '--fx-rates', RATES,
                  '--strategy', 'update')
    assert result.exit_code == 0, result.output

    listing = _balances(runner, book)
    assert DEPOSIT_SPLIT not in listing, (
        'the receivable prices this money now, and the deposit is still '
        f'listed beside it:\n{listing}')
    # The invoice's own basis is what carries it: the three posted invoices —
    # 2,720.00, 5,000.00 and 1,020.00 — and nothing else. Kept, the deposit
    # would add its 2,720.00 on top and the book would offer 11,460.00.
    assert '5,000.00 USD' in listing, listing
    assert 'Total USD basis balance: 8,740.00 USD' in listing, listing

    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 0, verified.output


def test_the_link_takes_the_balance_off_the_deposit(tmp_path):
    """With nothing drawn on it, the whole basis is discarded.

    The transaction is paying the invoice, not borrowing, so the receivable is
    the one basis for that 2,720.00 USD from then on — the state a `payment:`
    block reaches when it pays a USD invoice in full from a USD bank.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _invoices_and_a_parked_deposit(runner, book, with_fee=False)
    assert _stored_balance(book, DEPOSIT_SPLIT) == '2720.00'

    result = _linked_to_the_invoice(runner, book, tmp_path)
    assert result.exit_code == 0, result.output

    assert _stored_balance(book, DEPOSIT_SPLIT) is None, (
        'the deposit stopped being a borrowing but kept its basis balance:\n'
        f'{_balances(runner, book)}')
    listing = _balances(runner, book)
    assert 'Total USD basis balance: 3,740.00 USD' in listing, listing


def test_the_link_is_refused_while_a_disposal_draws_on_the_deposit(tmp_path):
    """The 0.72 fee was valued at the deposit's rate, not the invoice's.

    Re-pointing it at the receivable would silently re-price it, and
    `_require_stated_cost` would reject that same fee on the next re-import. So
    the link is refused and says which disposals stand in the way.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _invoices_and_a_parked_deposit(runner, book, with_fee=True)
    assert _stored_balance(book, DEPOSIT_SPLIT) == '2719.28'

    result = _linked_to_the_invoice(runner, book, tmp_path)
    message = result.output + str(result.exception)
    assert result.exit_code != 0, message
    assert 'Charges for: TRANSFER-0000001' in message, message
    assert '0.72' in message, message
    # And nothing moved.
    assert _stored_balance(book, DEPOSIT_SPLIT) == '2719.28', message


def test_reclassifying_the_other_split_is_allowed(tmp_path):
    """Due From -> Income cannot move the basis, so it must not be refused.

    The USD split keeps its account, its amount and its rate, so its cost is
    the same figure before and after. Refusing it blocks an ordinary
    correction: booking a USD deposit to revenue when there is no invoice.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _invoices_and_a_parked_deposit(runner, book, with_fee=False)

    # The way a person makes this correction: export the book, change the
    # account on the line, import it back. Writing the block by hand instead
    # would state a rate of its own, and the book holds the rate its value and
    # amount work out to — 381589/272000, not the 1.4029 that was typed.
    exported = _exported(runner, book, tmp_path / 'before.txt')
    income = 'Income:Non-farming revenue:Total sales of goods and services'
    reclassified = tmp_path / 'reclassified.txt'
    reclassified.write_text(
        exported.replace('\tAssets:Current assets:Due from director -3815.89 CAD',
                         f'\t{income} -3815.89 CAD'))
    assert income in reclassified.read_text(), reclassified.read_text()
    result = _run(runner, 'import', str(book), str(reclassified),
                  '--strategy', 'update')
    assert result.exit_code == 0, result.output

    listing = _balances(runner, book)
    row = next(line for line in listing.splitlines() if DEPOSIT_SPLIT in line)
    assert '2,720.00 USD   2,720.00 USD' in row, listing


# ------------------------------------------------------------------- bill side

def test_a_bill_link_keeps_the_live_credit_line_basis(tmp_path):
    """USD drawn on a credit line is still borrowed once the bill is paid.

    The payment moves what is owed from the supplier to the credit line: the
    payable is paid and the credit line is not, so the transaction is still a
    borrowing and its basis stands. It stands by keeping the price, written
    onto the split, since the transaction itself can no longer supply one once
    its expense split has moved to the payable.

    The paid payable keeps its own balance, as a paid invoice's receivable
    does. Consuming it was tried and is wrong: what a basis brought in and what
    it still holds are the two sides `currency_totals_that_disagree` compares,
    so lowering a balance with no disposal to account for it puts the book's
    own currency totals out by that amount.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_usd_bill_with_a_cad_expense.txt',
        '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output
    result = _run(runner, 'import', str(book),
                  'tests/fixtures/fx_supplier_paid_on_a_usd_credit_line.txt')
    assert result.exit_code == 0, result.output

    before = _exported(runner, book, tmp_path / 'before.txt',
                       '--include-business-objects')
    linked = tmp_path / 'linked.txt'
    linked.write_text(_with_payment(before, 'bill "BILL-USD-001"', [
        '\tpayment:',
        '\t\tdate: 2026-08-13',
        '\t\tamount: 2720',
        '\t\taccount: "Liabilities:USD Credit Line"',
        f'\t\ttxn_guid: "{PARKED_TX}"',
        f'\t\ttxn_split_guid: "{EXPENSE_SPLIT}"',
    ]))
    result = _run(runner, 'import', str(book), str(linked),
                  '--include-business-objects', '--fx-rates', RATES,
                  '--strategy', 'update')
    assert result.exit_code == 0, result.output

    listing = _balances(runner, book)
    credit_line = next((line for line in listing.splitlines()
                        if CREDIT_LINE_SPLIT in line), None)
    assert credit_line is not None, (
        'the credit line is still owed 2,720.00 USD, but its basis is gone '
        f'from the listing:\n{listing}')
    assert '381589/272000 CAD/USD' in credit_line, credit_line
    assert '2,720.00 USD   2,720.00 USD' in credit_line, credit_line


def test_the_bills_link_writes_a_cost_the_export_keeps(tmp_path):
    """The written cost has to reach the file, or it is written and thrown away.

    The link keeps this basis by storing `cost_basis_cost` on the split, and
    the split is not a cost basis at the moment that is written — being no
    longer priced by its transaction is the whole reason it needs storing. The
    export drops a stored cost from any split that is no basis
    (`_stored_cost_is_ignorable`), so the key survives only because writing it
    makes the split a basis again.

    Nothing else says so. Were that to stop holding, the run would report a
    repaired book while exporting a ledger with the balance and no cost — the
    reported Q-040 book exactly, on the bill side, and the rate unrecoverable
    because nothing in the transaction states it any more.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_usd_bill_with_a_cad_expense.txt',
        '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output
    assert _run(runner, 'import', str(book),
                'tests/fixtures/fx_supplier_paid_on_a_usd_credit_line.txt'
                ).exit_code == 0

    before = _exported(runner, book, tmp_path / 'before.txt',
                       '--include-business-objects')
    linked = tmp_path / 'linked.txt'
    linked.write_text(_with_payment(before, 'bill "BILL-USD-001"', [
        '\tpayment:',
        '\t\tdate: 2026-08-13',
        '\t\tamount: 2720',
        '\t\taccount: "Liabilities:USD Credit Line"',
        f'\t\ttxn_guid: "{PARKED_TX}"',
        f'\t\ttxn_split_guid: "{EXPENSE_SPLIT}"',
    ]))
    assert _run(runner, 'import', str(book), str(linked),
                '--include-business-objects', '--fx-rates', RATES,
                '--strategy', 'update').exit_code == 0

    after = _exported(runner, book, tmp_path / 'after.txt',
                      '--include-business-objects')
    block = re.search(
        rf'guid: "{CREDIT_LINE_SPLIT}"\n(?:\t\t[^\n]*\n)*', after).group(0)
    assert 'cost_basis_cost:' in block, block
    assert 'cost_basis_balance:' in block, block

    # And the ledger carrying it rebuilds the book it came from.
    fresh = tmp_path / 'fresh.gnucash'
    again = _run(runner, 'import', '--new', str(fresh),
                 str(tmp_path / 'after.txt'), '--include-business-objects',
                 '--fx-rates', RATES)
    assert again.exit_code == 0, again.output
    assert re.search(r'Errors:\s+0$', again.output, re.M), again.output


def _a_bill_linked_to_the_credit_line_payment(runner, book, tmp_path):
    """The bill side of the story, up to the link: a supplier paid on a USD
    credit line before the bill was posted, and the bill then linked to it."""
    result = runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_usd_bill_with_a_cad_expense.txt',
        '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output
    assert _run(runner, 'import', str(book),
                'tests/fixtures/fx_supplier_paid_on_a_usd_credit_line.txt'
                ).exit_code == 0

    before = _exported(runner, book, tmp_path / 'before.txt',
                       '--include-business-objects')
    linked = tmp_path / 'linked.txt'
    linked.write_text(_with_payment(before, 'bill "BILL-USD-001"', [
        '\tpayment:',
        '\t\tdate: 2026-08-13',
        '\t\tamount: 2720',
        '\t\taccount: "Liabilities:USD Credit Line"',
        f'\t\ttxn_guid: "{PARKED_TX}"',
        f'\t\ttxn_split_guid: "{EXPENSE_SPLIT}"',
    ]))
    assert _run(runner, 'import', str(book), str(linked),
                '--include-business-objects', '--fx-rates', RATES,
                '--strategy', 'update').exit_code == 0


def test_a_bill_link_keeps_a_basis_that_has_no_recorded_balance(tmp_path):
    """A basis with no balance is still a basis, and still owes its price.

    A deposit or a draw entered in the GnuCash GUI, or made before this tool
    wrote balances, is a cost basis reading `none recorded`: the currency is
    there and the transaction says what it cost, and only how much of it is
    still unsold is unknown. Linking a bill to such a payment takes the
    transaction's CAD split away, so nothing prices the split any more.

    Read off the balances alone — which is what "the ones with something to
    lose" meant — that split was never looked at, so no cost was written and
    it stopped being a cost basis. `fx-balances` then dropped the row
    altogether: 2,720.00 USD the book holds and owes, with nothing said about
    it anywhere, and no stranded balance and no disposal for `--verify-costs`
    to report. That is the fault this issue opens with, on the branch that is
    supposed to keep its basis.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_usd_bill_with_a_cad_expense.txt',
        '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output
    assert _run(runner, 'import', str(book),
                'tests/fixtures/fx_supplier_paid_on_a_usd_credit_line.txt'
                ).exit_code == 0

    # The balance off, and nothing else: what the GUI would have left.
    before = _exported(runner, book, tmp_path / 'before.txt',
                       '--include-business-objects')
    block = re.search(r'2026-08-13 \* "Director paid[^\n]*\n(?:\t[^\n]*\n)*',
                      before).group(0)
    cleared = tmp_path / 'cleared.txt'
    cleared.write_text(re.sub(r'\t\tcost_basis_balance: "[^"]*"\n', '', block)
                       .replace(f'guid: "{CREDIT_LINE_SPLIT}"',
                                f'guid: "{CREDIT_LINE_SPLIT}"\n'
                                f'\t\tcost_basis_balance: ""'))
    assert _run(runner, 'import', str(book), str(cleared),
                '--strategy', 'update', '--fx-rates', RATES).exit_code == 0
    assert _stored_balance(book, CREDIT_LINE_SPLIT) is None
    assert 'none recorded' in _balances(runner, book)

    linked = tmp_path / 'linked.txt'
    linked.write_text(_with_payment(
        _exported(runner, book, tmp_path / 'again.txt',
                  '--include-business-objects'),
        'bill "BILL-USD-001"', [
            '\tpayment:',
            '\t\tdate: 2026-08-13',
            '\t\tamount: 2720',
            '\t\taccount: "Liabilities:USD Credit Line"',
            f'\t\ttxn_guid: "{PARKED_TX}"',
            f'\t\ttxn_split_guid: "{EXPENSE_SPLIT}"',
        ]))
    assert _run(runner, 'import', str(book), str(linked),
                '--include-business-objects', '--fx-rates', RATES,
                '--strategy', 'update').exit_code == 0

    listing = _balances(runner, book)
    row = next((line for line in listing.splitlines()
                if CREDIT_LINE_SPLIT in line), None)
    assert row is not None, (
        'the credit line is still owed 2,720.00 USD, and its basis is gone '
        f'from the listing:\n{listing}')
    assert '381589/272000 CAD/USD' in row, row
    assert 'none recorded' in row, row


def test_unapplying_the_bills_link_leaves_no_cost_the_ledger_contradicts(tmp_path):
    """The stored cost comes off when the transaction prices the split again.

    The link stores `cost_basis_cost` on the credit-line split because its
    transaction can no longer supply one — the CAD expense split has become
    the payable's settlement. Taking the payment off puts a CAD split back, so
    the transaction prices that currency itself, and the two answers are then
    both there to disagree: the unapply restates the CAD side from
    `--fx-rates` at the transaction's own date, which is 1.20 here against the
    1.4029 the link stored.

    Left on, `--verify-costs` reported the book unsound after an ordinary
    undo — "cost_basis_cost says 381589/272000 … but the transaction says
    1.2" — with nothing telling its reader that `cost_basis_cost: ""` is the
    fix. The transaction outranks a stored copy wherever both exist, so the
    copy is what goes.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _a_bill_linked_to_the_credit_line_payment(runner, book, tmp_path)

    undone = _run(runner, 'unapply-payment', str(book), 'BILL-USD-001',
                  '--bill', '--to', 'Expenses:Supplies',
                  '--fx-rates', LOW_ON_THE_DAY)
    assert undone.exit_code == 0, undone.output

    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 0, verified.output
    assert 'cost_basis_cost' not in verified.output, verified.output

    # And the split is still a basis — priced by its own transaction now.
    listing = _balances(runner, book)
    row = next((line for line in listing.splitlines()
                if CREDIT_LINE_SPLIT in line), None)
    assert row is not None, listing
    assert '1.2 CAD/USD' in row, row


def test_no_split_keeps_a_balance_it_cannot_account_for(tmp_path):
    """Whatever the link decides, it may not leave a figure nothing reads.

    A `cost_basis_balance` on a split that is no basis is invisible to
    `fx-balances` and to `--verify-costs`, and the export writes it back out —
    so the book's own ledger no longer rebuilds it. Stated over the listing
    rather than over either outcome, so it holds whichever way the link
    answers: a split with a balance on it has to be one the listing shows.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _invoices_and_a_parked_deposit(runner, book, with_fee=False)
    assert _linked_to_the_invoice(runner, book, tmp_path).exit_code == 0

    stored = _stored_balance(book, DEPOSIT_SPLIT)
    listed = re.search(rf'^.*{DEPOSIT_SPLIT}.*$', _balances(runner, book), re.M)
    assert (stored is None) or (listed is not None), (
        f'split {DEPOSIT_SPLIT} has cost_basis_balance {stored!r} on it and is '
        f'listed by nothing')
