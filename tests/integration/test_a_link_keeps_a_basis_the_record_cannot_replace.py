"""Discarding a link's cost basis rests on the record having one of its own.

Linking a deposit to pay an invoice discards the deposit's cost basis because
the invoice's receivable has priced that currency since the day it was posted:
one lot of money, one cost basis. That reasoning fails where the record prices
nothing.

A foreign invoice booked to an income account kept in that same currency posts
foreign against foreign. Nothing in the posting transaction says what the
currency cost, and `_attach_posting_rate` stores no rate for it either, so its
receivable split is no cost basis at all. Discarding the deposit's cost basis there
takes away the only cost the book had for that money — measured, `fx-balances`
went from one cost basis of 2,720.00 USD to "No foreign-currency cost bases found",
with `--verify-costs` reporting nothing wrong and the currency still sitting in
the bank, unsellable.

So the price is kept instead, written onto the split the way the bill side
keeps it.
"""

import re

from click.testing import CliRunner

from cli.main import cli
from tests.conftest import _run

RATES = 'tests/fixtures/fx_rates_usd_two_invoice_dates.yaml'
SOURCE = 'tests/fixtures/fx_usd_invoice_booked_to_a_usd_income_account.txt'


def _with_payment(text, header, payment_lines):
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(header))
    end = start + 1
    while end < len(lines) and (lines[end].startswith('\t')
                                or not lines[end].strip()):
        end += 1
    block = [line for line in lines[start:end]
             if line.strip() != 'payment: none']
    return '\n'.join(lines[:start] + block + payment_lines + lines[end:]) + '\n'


def _the_deposit_paid_the_invoice(runner, tmp_path):
    book = tmp_path / 'book.gnucash'
    made = runner.invoke(cli, ['import', '--new', str(book), SOURCE,
                               '--include-business-objects',
                               '--fx-rates', RATES])
    assert made.exit_code == 0, made.output

    out = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(out),
                '--include-business-objects').exit_code == 0
    text = out.read_text()
    deposit_tx = re.search(
        r'2026-08-13 \* "Received[^\n]*\n\t+guid: "([0-9a-f]{32})"',
        text).group(1)

    linked = tmp_path / 'linked.txt'
    linked.write_text(_with_payment(text, 'invoice "INV-USD-OWN-CURRENCY"', [
        '\tpayment:',
        '\t\tdate: 2026-08-13',
        '\t\tamount: 2720',
        '\t\taccount: "Assets:Bank:USD"',
        f'\t\ttxn_guid: "{deposit_tx}"',
    ]))
    result = _run(runner, 'import', str(book), str(linked),
                  '--include-business-objects', '--fx-rates', RATES,
                  '--strategy', 'update')
    assert result.exit_code == 0, result.output
    return book


def test_the_records_posting_split_is_no_cost_basis(tmp_path):
    """Which is what makes this shape different, and it is the book's own doing."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    made = runner.invoke(cli, ['import', '--new', str(book), SOURCE,
                               '--include-business-objects',
                               '--fx-rates', RATES])
    assert made.exit_code == 0, made.output

    listing = _run(runner, 'fx-balances', str(book)).output
    assert 'Accounts Receivable' not in listing, listing
    assert 'Assets:Bank:USD' in listing, listing


def test_the_deposits_basis_is_kept(tmp_path):
    runner = CliRunner()
    book = _the_deposit_paid_the_invoice(runner, tmp_path)

    listing = _run(runner, 'fx-balances', str(book)).output
    assert 'No foreign-currency cost bases found' not in listing, listing
    assert '381589/272000 CAD/USD' in listing, listing
    # Acquired and still unsold, side by side on the row. Matched with the
    # spacing left open, so the assertion is about the two figures rather than
    # about how wide the listing's last column happens to be.
    assert re.search(r'2,720\.00 USD[^\n]+2,720\.00 USD', listing), listing


def test_the_book_still_agrees_with_itself(tmp_path):
    runner = CliRunner()
    book = _the_deposit_paid_the_invoice(runner, tmp_path)

    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 0, verified.output
    assert 'every cost agrees' in verified.output, verified.output


def test_the_export_of_that_book_re_imports(tmp_path):
    """The kept price has to reach the file, or the rebuild loses it.

    Nothing in the transaction states it any more — the link took the CAD
    split onto the receivable — so it travels as the stored
    `cost_basis_cost:`, which the export keeps because writing it makes the
    split a cost basis again.
    """
    runner = CliRunner()
    book = _the_deposit_paid_the_invoice(runner, tmp_path)

    out = tmp_path / 'after.txt'
    assert _run(runner, 'export', str(book), str(out),
                '--include-business-objects').exit_code == 0
    assert 'cost_basis_cost:' in out.read_text(), out.read_text()

    fresh = tmp_path / 'fresh.gnucash'
    again = _run(runner, 'import', '--new', str(fresh), str(out),
                 '--include-business-objects', '--fx-rates', RATES)
    assert again.exit_code == 0, again.output
    assert re.search(r'Errors:\s+0$', again.output, re.M), again.output
