"""Taking a payment off a wrongly linked transaction opens its basis again.

Linking a bank transaction to pay an invoice says that transaction is the
invoice being paid rather than currency being bought, so its cost basis is
discarded. Someone who linked the wrong transaction has to be able to get back
to where they were.

`unapply-payment --to <account>` is what they run. It takes the split off the
receivable and gives it the account `--to` states, restated into that account's
currency — so with the base-currency account the money came from written there,
the transaction is `Due From CAD / Bank USD` again, a purchase of USD. The
same question the import asks of such a transaction is asked here of the
finished one, and the basis opens for the whole amount.

What is not recovered is the rate the transaction was originally entered at.
The link overwrote the base-currency amount that held it, so the only figure
left is the fx rate on the transaction's own day, which is what the unapply
restates the split at and what the reopened basis is therefore priced at. That
is pinned below, because it decides what the director is owed.
"""

import re
import time

from click.testing import CliRunner

from cli.main import cli

RATES = 'tests/fixtures/fx_rates_usd_two_invoice_dates.yaml'
QUOTED_ON_THE_DAY = 'tests/fixtures/fx_rates_usd_quoted_on_the_deposit_date.yaml'
LOW_ON_THE_DAY = 'tests/fixtures/fx_rates_usd_low_on_the_deposit_date.yaml'
WITH_A_DATED_CAD_LINE = 'tests/fixtures/fx_rates_usd_and_a_dated_cad_line.yaml'
DEPOSIT_SPLIT = '00e958a8d56547d484d7629000292dc3'
BANK_USD = ('Assets:Current assets:Cash and deposits:Deposits in Canadian '
            'banks and institutions – Foreign currency:Foreign Payments '
            'Provider Chequing 000000000000001')
DUE_FROM = 'Assets:Current assets:Due from director'


def _run(runner, *args):
    time.sleep(1.1)
    return runner.invoke(cli, list(args))


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


def _linked_to_the_wrong_invoice(runner, tmp_path):
    """The deposit imported, then linked to pay INV-USD-001 in full."""
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_two_usd_invoices_posted.txt',
        '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output
    assert _run(runner, 'import', str(book),
                'tests/fixtures/fx_usd_deposit_against_due_from_director.txt'
                ).exit_code == 0

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
    assert 'Total USD basis balance: 3,740.00 USD' in listing, listing


def test_taking_it_off_makes_it_a_cost_basis_again(tmp_path):
    """The cost comes back on its own; the balance is the person's to state.

    Nothing here knows what the balance was, and opening one at the split's
    full amount cannot tell a figure this tool removed from one that was never
    written — a deposit made in the GnuCash GUI is a cost basis reading `none
    recorded`, and a link leaves it alone. So the listing says what to do.
    """
    runner = CliRunner()
    book = _linked_to_the_wrong_invoice(runner, tmp_path)

    unlink = _run(runner, 'unapply-payment', str(book), 'INV-USD-001',
                  '--to', DUE_FROM, '--fx-rates', RATES)
    assert unlink.exit_code == 0, unlink.output

    line, listing = _the_deposit_line(runner, book)
    assert line is not None, listing
    assert '381589/272000 CAD/USD' in line, line
    assert '2,720.00 USD' in line, line
    assert 'none recorded' in line, line
    assert 'State `cost_basis_balance:`' in listing, listing

    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 0, verified.output


def test_stating_the_balance_finishes_it(tmp_path):
    """One line, and the book is where it was before the wrong link."""
    runner = CliRunner()
    book = _linked_to_the_wrong_invoice(runner, tmp_path)
    assert _run(runner, 'unapply-payment', str(book), 'INV-USD-001',
                '--to', DUE_FROM, '--fx-rates', RATES).exit_code == 0

    out = tmp_path / 'after.txt'
    assert _run(runner, 'export', str(book), str(out)).exit_code == 0
    block = re.search(r'2026-08-13 \* "Received[^\n]*\n(?:\t[^\n]*\n)*',
                      out.read_text()).group(0)
    stated = tmp_path / 'stated.txt'
    stated.write_text(block.replace(
        f'guid: "{DEPOSIT_SPLIT}"',
        f'guid: "{DEPOSIT_SPLIT}"\n\t\tcost_basis_balance: "2720.00"'))
    assert _run(runner, 'import', str(book), str(stated),
                '--strategy', 'update', '--fx-rates', RATES).exit_code == 0

    _, listing = _the_deposit_line(runner, book)
    assert 'Total USD basis balance: 6,460.00 USD' in listing, listing


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
    director is owed and what the reopened basis is priced at.
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
    """Then both sides are USD, nothing states a cost, and there is no basis.

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
