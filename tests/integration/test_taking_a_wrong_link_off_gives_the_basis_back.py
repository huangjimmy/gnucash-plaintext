"""Taking a payment off a wrongly linked transaction opens its cost basis again.

Linking a bank transaction to pay an invoice says that transaction is the
invoice being paid rather than currency being bought, so its cost basis is
discarded. Someone who linked the wrong transaction has to be able to get back
to where they were.

`unapply-payment --to <account>` is what they run. It takes the split off the
receivable and gives it the account `--to` states, restated into that account's
currency — so with the base-currency account the money came from written there,
the transaction is `Due From CAD / Bank USD` again, a purchase of USD. The
same question the import asks of such a transaction is asked here of the
finished one, and the cost basis opens for the whole amount.

What is not recovered is the rate the transaction was originally entered at.
The link overwrote the base-currency amount that held it, so the only figure
left is the fx rate on the transaction's own day, which is what the unapply
restates the split at and what the reopened cost basis is therefore priced at. That
is pinned below, because it decides what the director is owed.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from tests.conftest import _run

RATES = 'tests/fixtures/fx_rates_usd_two_invoice_dates.yaml'
QUOTED_ON_THE_DAY = 'tests/fixtures/fx_rates_usd_quoted_on_the_deposit_date.yaml'
LOW_ON_THE_DAY = 'tests/fixtures/fx_rates_usd_low_on_the_deposit_date.yaml'
WITH_A_DATED_CAD_LINE = 'tests/fixtures/fx_rates_usd_and_a_dated_cad_line.yaml'
# For the overpaid book below, whose payment is dated 2026-02-25. This file
# quotes 2026-01-05 and 2026-02-20, so that day is answered by the 20th's rate
# carried forward and the run says so on stderr — which is not what the test
# is about, and does not change the figures it reads.
OWN_CURRENCY_RATES = 'tests/fixtures/fx_rates_usd_dated.yaml'
DEPOSIT_SPLIT = '00e958a8d56547d484d7629000292dc3'
BANK_USD = ('Assets:Current assets:Cash and deposits:Deposits in Canadian '
            'banks and institutions – Foreign currency:Foreign Payments '
            'Provider Chequing 000000000000001')
DUE_FROM = 'Assets:Current assets:Due from director'


def _with_payment(text, header, payment_lines):
    """Replace a record's `payment: none` with the payment block given."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(header))
    end = start + 1
    while end < len(lines) and (lines[end].startswith('\t')
                                or not lines[end].strip()):
        end += 1
    block = [line for line in lines[start:end]
             if line.strip() != 'payment: none']
    return '\n'.join(lines[:start] + block + payment_lines + lines[end:]) + '\n'


def _the_deposit_line(runner, book):
    listing = _run(runner, 'fx-balances', str(book)).output
    line = next((one for one in listing.splitlines()
                 if DEPOSIT_SPLIT in one), None)
    return line, listing


def _linked_to_the_wrong_invoice(runner, tmp_path, clear_the_balance=False):
    """The deposit imported, then linked to pay INV-USD-001 in full.

    `clear_the_balance` takes the deposit's `cost_basis_balance` off first,
    which is the state a deposit made in the GnuCash GUI is in: a cost basis
    reading `none recorded`, its cost readable from its own transaction and
    how much of it has been sold written down nowhere.
    """
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_two_usd_invoices_posted.txt',
        '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output
    assert _run(runner, 'import', str(book),
                'tests/fixtures/fx_usd_deposit_against_due_from_director.txt'
                ).exit_code == 0

    if clear_the_balance:
        first = tmp_path / 'first.txt'
        assert _run(runner, 'export', str(book), str(first)).exit_code == 0
        block = re.search(r'2026-08-13 \* "Received[^\n]*\n(?:\t[^\n]*\n)*',
                          first.read_text()).group(0)
        cleared = tmp_path / 'cleared.txt'
        cleared.write_text(re.sub(r'\t\tcost_basis_balance: "[^"]*"\n',
                                  '\t\tcost_basis_balance: ""\n', block))
        assert _run(runner, 'import', str(book), str(cleared),
                    '--strategy', 'update').exit_code == 0
        assert 'none recorded' in _run(runner, 'fx-balances', str(book)).output

    out = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(out),
                '--include-business-objects').exit_code == 0
    text = out.read_text()
    deposit_tx = re.search(
        r'2026-08-13 \* "Received[^\n]*\n\t+guid: "([0-9a-f]{32})"',
        text).group(1)

    linked = tmp_path / 'linked.txt'
    linked.write_text(_with_payment(text, 'invoice "INV-USD-001"', [
        '\tpayment:',
        '\t\tdate: 2026-08-13',
        '\t\tamount: 2720',
        f'\t\taccount: "{BANK_USD}"',
        f'\t\ttxn_guid: "{deposit_tx}"',
    ]))
    result = _run(runner, 'import', str(book), str(linked),
                  '--include-business-objects', '--fx-rates', RATES,
                  '--strategy', 'update')
    assert result.exit_code == 0, result.output
    return book


def test_the_link_discards_it_first(tmp_path):
    """Which is what there is to get back."""
    runner = CliRunner()
    book = _linked_to_the_wrong_invoice(runner, tmp_path)
    line, listing = _the_deposit_line(runner, book)
    assert line is None, listing
    assert 'Total USD cost basis balance: 3,740.00 USD' in listing, listing


def test_taking_it_off_makes_it_a_cost_basis_again(tmp_path):
    """Priced, and holding all of the currency the purchase brought in.

    None of that 2,720.00 USD has been sold: a settlement is no cost basis, so
    while it settled the invoice nothing could draw on it, and the transaction
    is a purchase again the moment the base-currency split goes back on it.
    That is the same shape the importer opens a cost basis for, at the same figure.
    """
    runner = CliRunner()
    book = _linked_to_the_wrong_invoice(runner, tmp_path)

    unlink = _run(runner, 'unapply-payment', str(book), 'INV-USD-001',
                  '--to', DUE_FROM, '--fx-rates', RATES)
    assert unlink.exit_code == 0, unlink.output

    line, listing = _the_deposit_line(runner, book)
    assert line is not None, listing
    assert '381589/272000 CAD/USD' in line, line
    assert line.count('2,720.00 USD') == 2, line
    assert 'none recorded' not in listing, listing
    assert 'Total USD cost basis balance: 6,460.00 USD' in listing, listing

    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 0, verified.output


def test_a_basis_that_had_no_balance_comes_back_holding_all_of_it(tmp_path):
    """The limit of the rule, written down because it costs something.

    A cost basis reading `none recorded` — one the GnuCash GUI made, or one
    older than this — says how much of its currency is unsold nowhere. An edit
    leaves such a split alone for that reason: opening it at its full amount
    would offer currency that may be long since spent.

    Linking it to an invoice and taking that off is the one route past that.
    The link makes the split a settlement, which is no cost basis, so by the
    time the payment comes off there is nothing to tell a balance this tool
    removed from one that was never written — both read as no balance at all.
    The split comes back holding the whole 2,720.00 USD.

    It is the same answer every other writer gives for that transaction: the
    importer opens a purchase's cost basis at its full amount, so a book
    rebuilt from this one's ledger reads 2,720.00 too. Recording what the link
    took would tell the two apart, and it is not recorded, because nothing in
    a file may state it and an export cannot carry it.
    """
    runner = CliRunner()
    book = _linked_to_the_wrong_invoice(runner, tmp_path,
                                        clear_the_balance=True)

    assert _run(runner, 'unapply-payment', str(book), 'INV-USD-001',
                '--to', DUE_FROM, '--fx-rates', RATES).exit_code == 0

    line, listing = _the_deposit_line(runner, book)
    assert line is not None, listing
    assert line.count('2,720.00 USD') == 2, line
    assert 'none recorded' not in listing, listing


def test_an_overpaid_records_deposit_is_not_opened_whole(tmp_path):
    """A cost basis opens at everything its split brought in, and that figure
    is only this record's where nothing else accounts for part of it.

    A 100.00 USD invoice paid with 200.00 USD from a USD bank: the other
    100.00 is the customer's credit, and a cost basis already. Every split is
    USD, so nothing in the transaction says what the USD cost and the bank
    split is no cost basis at all.

    Giving the settlement a CAD account prices that transaction — and with it
    the bank's whole 200.00, the customer's half included. Measured before the
    check: `fx-balances` totalled 300.00 USD against the 200.00 the bank
    holds, every figure passing `--verify-costs`, because 200.00 is exactly
    what that split brought in.
    """
    runner = CliRunner()
    book = tmp_path / 'over.gnucash'
    assert runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_invoice_usd_overpaid_into_usd_bank.txt',
        '--include-business-objects',
        '--fx-rates', OWN_CURRENCY_RATES]).exit_code == 0

    unapplied = _run(runner, 'unapply-payment', str(book), 'INV-USD-OVER',
                     '--to', 'Assets:Bank', '--fx-rates', OWN_CURRENCY_RATES)
    assert unapplied.exit_code == 0, unapplied.output

    listing = _run(runner, 'fx-balances', str(book)).output
    assert 'Total USD cost basis balance: 100.00 USD' in listing, listing
    bank = next(line for line in listing.splitlines()
                if 'Assets:Bank:USD' in line)
    assert 'none recorded' in bank, bank

    # `--verify-costs` does report this book, and about the credit rather than
    # about the bank: the restatement gives the transaction a base-currency
    # figure, which makes the bank split the one that brings that USD in, and
    # the credit's stored balance is left over. Measured with the opening
    # disabled outright, the report is identical — it follows from restating
    # the settlement, not from anything opened here.
    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 1, verified.output
    assert 'it is no cost basis' in verified.output, verified.output
    assert 'Assets:Bank:USD' not in verified.output.split(
        'do not hold:')[-1], verified.output


def test_a_deposit_whose_credit_another_invoice_spent_is_not_opened_whole(
        tmp_path):
    """The same 200.00 USD deposit, after its credit settled a second invoice.

    Spending the credit takes its balance off and puts the split in the second
    invoice's lot, so nothing in the transaction is a cost basis any more and
    the check on that alone lets the unapply through. What stops it is the
    other question — whether some other split of the transaction is already
    somebody's money — and that one has to be asked without the exception
    `_settles_another_record` carries for a split spent from credit, which
    this one is.

    Measured with that exception in place: `fx-balances` totalled 400.00 USD
    against the 200.00 the bank holds.
    """
    runner = CliRunner()
    book = tmp_path / 'spent.gnucash'
    assert runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_invoice_usd_overpaid_into_usd_bank.txt',
        '--include-business-objects',
        '--fx-rates', OWN_CURRENCY_RATES]).exit_code == 0
    spent = _run(runner, 'import', str(book),
                 'tests/fixtures/fx_invoice_auto_applying_the_whole_credit.txt',
                 '--include-business-objects', '--fx-rates', OWN_CURRENCY_RATES)
    assert spent.exit_code == 0, spent.output

    unapplied = _run(runner, 'unapply-payment', str(book), 'INV-USD-OVER',
                     '--to', 'Assets:Bank', '--fx-rates', OWN_CURRENCY_RATES)
    assert unapplied.exit_code == 0, unapplied.output

    listing = _run(runner, 'fx-balances', str(book)).output
    assert 'Total USD cost basis balance: 200.00 USD' in listing, listing
    bank = next(line for line in listing.splitlines()
                if 'Assets:Bank:USD' in line)
    assert 'none recorded' in bank, bank


def _one_deposit_settling_both_invoices(runner, tmp_path, link_both=True):
    """3,740.00 USD in, settling INV-USD-001 (2,720) and INV-USD-002 (1,020).

    A receivable split per invoice, each given by its own `payment:` block.
    With `link_both=False` only the first is linked, which leaves the second
    invoice's share on the receivable and in no lot — nobody's, and not
    written down as anybody's. Returns the book.
    """
    book = tmp_path / 'shared.gnucash'
    assert runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_two_usd_invoices_posted.txt',
        '--include-business-objects', '--fx-rates', RATES]).exit_code == 0
    assert _run(runner, 'import', str(book),
                'tests/fixtures/fx_one_usd_deposit_settling_two_invoices.txt'
                ).exit_code == 0

    out = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(out),
                '--include-business-objects').exit_code == 0
    text = out.read_text()
    records = [('INV-USD-001', '2720', '5a1e77cc11d34cf0b2b0c0d5aa9e3313')]
    if link_both:
        records.append(('INV-USD-002', '1020',
                        '5a1e77cc11d34cf0b2b0c0d5aa9e3314'))
    for record, amount, split in records:
        linked = tmp_path / f'{record}.txt'
        linked.write_text(_with_payment(text, f'invoice "{record}"', [
            '\tpayment:',
            '\t\tdate: 2026-08-13',
            f'\t\tamount: {amount}',
            f'\t\taccount: "{BANK_USD}"',
            '\t\ttxn_guid: "5a1e77cc11d34cf0b2b0c0d5aa9e3311"',
            f'\t\ttxn_split_guid: "{split}"',
        ]))
        applied = _run(runner, 'import', str(book), str(linked),
                       '--include-business-objects', '--fx-rates', RATES,
                       '--strategy', 'update')
        assert applied.exit_code == 0, applied.output
        again = _run(runner, 'export', str(book), str(out),
                     '--include-business-objects')
        assert again.exit_code == 0, again.output
        text = out.read_text()
    return book


def test_a_deposit_shared_with_another_invoice_is_not_opened_whole(tmp_path):
    """Unapplying one of two invoices does not open the whole deposit.

    3,740.00 USD settles both invoices from one transaction. Taking the first
    payment off gives that settlement a CAD account, which prices the
    transaction — and the bank split holds the second invoice's 1,020.00 as
    well as the first's 2,720.00, so opening it would offer money that is
    still settling something.
    """
    runner = CliRunner()
    book = _one_deposit_settling_both_invoices(runner, tmp_path)

    unapplied = _run(runner, 'unapply-payment', str(book), 'INV-USD-001',
                     '--to', DUE_FROM, '--fx-rates', RATES)
    assert unapplied.exit_code == 0, unapplied.output

    listing = _run(runner, 'fx-balances', str(book)).output
    bank = [line for line in listing.splitlines()
            if 'Foreign Payments Provider Chequing' in line]
    assert bank, listing
    assert all('none recorded' in line for line in bank), listing
    assert not re.search(r'3,740\.00 USD[^\n]+3,740\.00 USD', listing), listing


def test_a_share_not_linked_to_its_invoice_yet_holds_the_deposit_back(
        tmp_path):
    """The same deposit with only the first invoice linked.

    The second invoice's 1,020.00 share is on the receivable and in no lot at
    all: no record owns it, no unpost orphaned it, and it is no cost basis. It
    is still that invoice's money, and the deposit cannot be opened as though
    all 3,740.00 were the first invoice's.

    Measured with the guard asking about lots and orphans instead of about the
    account: `fx-balances` totalled 7,480.00 USD against the 3,740.00 the bank
    holds.
    """
    runner = CliRunner()
    book = _one_deposit_settling_both_invoices(runner, tmp_path,
                                               link_both=False)

    unapplied = _run(runner, 'unapply-payment', str(book), 'INV-USD-001',
                     '--to', DUE_FROM, '--fx-rates', RATES)
    assert unapplied.exit_code == 0, unapplied.output

    listing = _run(runner, 'fx-balances', str(book)).output
    assert 'Total USD cost basis balance: 3,740.00 USD' in listing, listing
    bank = next(line for line in listing.splitlines()
                if 'Foreign Payments Provider Chequing' in line)
    assert 'none recorded' in bank, bank


def test_a_claim_part_sold_before_a_bill_spent_it_is_not_opened_whole(
        tmp_path):
    """A cost basis whose balance was taken off because it was *spent*.

    100.00 USD prepaid to a supplier out of a CAD bank, 80.00 of it sold, and
    a bill then settles out of the claim: spending it strips the balance,
    which records that the currency went — not that none of it had been sold
    first. The 20.00 that was left is written down nowhere after that.

    Unapplying the bill puts the claim on a USD bank, priced by the CAD split
    beside it, and the transaction holds nothing else: no second settlement,
    no other claim, no orphan. So the figure to open it at would be the whole
    100.00, and 80.00 of that is gone.

    The customer side cannot reach this: a credit is money owed back and sits
    negative on the receivable, so moving it brings no currency in. The claim
    on a vendor is a debit, and does.

    Measured before the check: `fx-balances` read 200.00 USD against a book
    holding 20.00 of sellable USD, and `--verify-costs` reported nothing,
    because 100.00 is exactly what that split brought in.
    """
    runner = CliRunner()
    book = tmp_path / 'vendor.gnucash'
    assert runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_vendor_claim_prepaid_in_cad.txt',
        '--include-business-objects',
        '--fx-rates', OWN_CURRENCY_RATES]).exit_code == 0

    claim = next(line.split()[1] for line in
                 _run(runner, 'fx-balances', str(book)).output.splitlines()
                 if 'Accounts Payable USD' in line)
    sale = tmp_path / 'sale.txt'
    sale.write_text(
        Path('tests/fixtures/fx_sell_80_of_a_claim_bought_at_1_37.txt')
        .read_text().replace('{basis}', claim))
    assert _run(runner, 'import', str(book), str(sale),
                '--fx-rates', OWN_CURRENCY_RATES).exit_code == 0

    out = tmp_path / 'tx.txt'
    assert _run(runner, 'export', str(book), str(out)).exit_code == 0
    prepayment = re.search(r'2026-02-01 \* "Prepaid[^\n]*\n\t+guid: '
                           r'"([0-9a-f]{32})"', out.read_text()).group(1)
    bill = tmp_path / 'bill.txt'
    bill.write_text(Path('tests/fixtures/fx_bill_spending_the_vendor_claim.txt')
                    .read_text().replace('TXN_GUID', prepayment)
                    .replace('SPLIT_GUID', claim))
    spent = _run(runner, 'import', str(book), str(bill),
                 '--include-business-objects', '--fx-rates', OWN_CURRENCY_RATES)
    assert spent.exit_code == 0, spent.output

    unapplied = _run(runner, 'unapply-payment', str(book), 'BILL-SPENDS-IT',
                     '--bill', '--to', 'Assets:Bank:USD',
                     '--fx-rates', OWN_CURRENCY_RATES)
    assert unapplied.exit_code == 0, unapplied.output

    listing = _run(runner, 'fx-balances', str(book)).output
    claim_row = next(line for line in listing.splitlines()
                     if 'Assets:Bank:USD' in line)
    assert 'none recorded' in claim_row, listing
    assert 'Total USD cost basis balance: 100.00 USD' in listing, listing


def test_the_book_and_a_book_rebuilt_from_its_ledger_agree(tmp_path):
    """Which is what said the old answer was wrong.

    The ledger states the deposit as what it is, a purchase of 2,720.00 USD
    against CAD, and states no balance for it — there is no balance to state,
    the split carries none. Imported, that transaction opens a cost basis for the
    whole 2,720.00, because that is what the importer does with a purchase. So
    the book that wrote the ledger has to say the same, and it said `none
    recorded` over a sentence reading "this tool never wrote one for them".
    """
    runner = CliRunner()
    book = _linked_to_the_wrong_invoice(runner, tmp_path)
    assert _run(runner, 'unapply-payment', str(book), 'INV-USD-001',
                '--to', DUE_FROM, '--fx-rates', RATES).exit_code == 0

    out = tmp_path / 'after.txt'
    assert _run(runner, 'export', str(book), str(out),
                '--include-business-objects').exit_code == 0
    fresh = tmp_path / 'fresh.gnucash'
    rebuilt = _run(runner, 'import', '--new', str(fresh), str(out),
                   '--include-business-objects', '--fx-rates', RATES)
    assert rebuilt.exit_code == 0, rebuilt.output

    here, _ = _the_deposit_line(runner, book)
    there, listing = _the_deposit_line(runner, fresh)
    assert there is not None, listing
    assert here.split()[2:] == there.split()[2:], (here, there)


def test_the_ledger_states_the_balance_and_re_importing_it_changes_nothing(
        tmp_path):
    """The figure is on the split, so the export writes it and an update of
    that same block leaves it where it is."""
    runner = CliRunner()
    book = _linked_to_the_wrong_invoice(runner, tmp_path)
    assert _run(runner, 'unapply-payment', str(book), 'INV-USD-001',
                '--to', DUE_FROM, '--fx-rates', RATES).exit_code == 0

    out = tmp_path / 'after.txt'
    assert _run(runner, 'export', str(book), str(out)).exit_code == 0
    block = re.search(r'2026-08-13 \* "Received[^\n]*\n(?:\t[^\n]*\n)*',
                      out.read_text()).group(0)
    assert 'cost_basis_balance: "2720.00"' in block, block

    again = tmp_path / 'again.txt'
    again.write_text(block)
    assert _run(runner, 'import', str(book), str(again),
                '--strategy', 'update', '--fx-rates', RATES).exit_code == 0

    _, listing = _the_deposit_line(runner, book)
    assert 'Total USD cost basis balance: 6,460.00 USD' in listing, listing


def test_the_reopened_basis_is_priced_at_the_rate_the_split_was_restated_at(
        tmp_path):
    """The fx rate on the transaction's day, not the one it was entered at.

    The deposit was entered at 1.4029 and the link destroyed the CAD amount
    holding that, so the unapply restates the split from the rates file and the
    basis is priced at whatever that says. Stated here with a rate deliberately
    unlike the original, so the figure cannot come from anywhere else.
    """
    runner = CliRunner()
    book = _linked_to_the_wrong_invoice(runner, tmp_path)

    assert _run(runner, 'unapply-payment', str(book), 'INV-USD-001',
                '--to', DUE_FROM, '--fx-rates', LOW_ON_THE_DAY
                ).exit_code == 0

    line, listing = _the_deposit_line(runner, book)
    assert line is not None, listing
    assert '1.2 CAD/USD' in line, line
    assert '2,720.00 USD' in line, line

    out = tmp_path / 'after.txt'
    assert _run(runner, 'export', str(book), str(out)).exit_code == 0
    assert f'{DUE_FROM} -3264.00 CAD' in out.read_text(), out.read_text()


def test_a_rate_carried_forward_from_an_earlier_day_is_said_out_loud(tmp_path):
    """Not a refusal — a rates file states the days it states — but said.

    The deposit is dated 2026-08-13 and the rates file quotes 2026-07-31 and
    2026-08-31. Rates are carried forward rather than extrapolated, so the
    restatement uses a figure thirteen days old, and that decides both what the
    director is owed and what the reopened cost basis is priced at.
    """
    runner = CliRunner()
    book = _linked_to_the_wrong_invoice(runner, tmp_path)

    unlink = _run(runner, 'unapply-payment', str(book), 'INV-USD-001',
                  '--to', DUE_FROM, '--fx-rates', RATES)
    assert unlink.exit_code == 0, unlink.output
    assert 'quoted for 2026-07-31' in unlink.output, unlink.output
    assert 'not for 2026-08-13' in unlink.output, unlink.output


def test_a_rate_quoted_for_the_day_itself_says_nothing(tmp_path):
    runner = CliRunner()
    book = _linked_to_the_wrong_invoice(runner, tmp_path)

    unlink = _run(runner, 'unapply-payment', str(book), 'INV-USD-001',
                  '--to', DUE_FROM, '--fx-rates', QUOTED_ON_THE_DAY)
    assert unlink.exit_code == 0, unlink.output
    assert 'carried forward' not in unlink.output, unlink.output


def test_a_dated_cad_line_in_the_rates_file_says_nothing_either(tmp_path):
    """A rate for the book's own currency is 1, and no quote is consulted.

    The restatement asks for a CAD rate like any other, and `rate_fraction`
    answers 1 before it looks at the file — so a `CAD:` block, which the
    format allows and a person keeping one file per month writes dated like
    the rest, is read by nothing. Asked which day that answer came from, this
    said 2026-07-31 and the run warned that the split had been restated at a
    rate thirteen days old, when it had been restated at 1.
    """
    runner = CliRunner()
    book = _linked_to_the_wrong_invoice(runner, tmp_path)

    unlink = _run(runner, 'unapply-payment', str(book), 'INV-USD-001',
                  '--to', DUE_FROM, '--fx-rates', WITH_A_DATED_CAD_LINE)
    assert unlink.exit_code == 0, unlink.output
    assert 'the CAD rate used' not in unlink.output, unlink.output
    # And the USD one, which was consulted, is still said.
    assert 'the USD rate used' in unlink.output, unlink.output


def test_no_basis_opens_where_to_states_a_usd_account(tmp_path):
    """Then both sides are USD, nothing states a cost, and there is no cost basis.

    The question is asked of the transaction the unapply leaves, not assumed
    from the fact that a payment came off.
    """
    runner = CliRunner()
    book = _linked_to_the_wrong_invoice(runner, tmp_path)

    unlink = _run(runner, 'unapply-payment', str(book), 'INV-USD-001',
                  '--to', BANK_USD, '--fx-rates', RATES)
    assert unlink.exit_code == 0, unlink.output

    line, listing = _the_deposit_line(runner, book)
    assert line is None, listing
    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 0, verified.output
