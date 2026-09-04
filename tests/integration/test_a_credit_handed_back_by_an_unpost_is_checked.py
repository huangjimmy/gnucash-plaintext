"""Unposting the record a credit settled makes it a live cost basis again.

Spending a credit marks the split `applied_from_credit: true`, and that mark
survives an unpost — CLAUDE.md finding 10. Unposting the record it settled
hands the split back as an owner's credit, loose and spendable, and where its
cost is readable it is a cost basis once more.

So the mark alone does not say a pool was consumed. What says it is the split
not being a cost basis now; the mark only separates a pool that was used up
from a guid that was never a cost basis at all. Asked the other way round — the mark
first — a sale against a live credit skipped the drawdown, the over-sell
refusal, the "has it been collected" test and the "is it valued at what the
basis cost" test alike, and its realized gain was whatever the file said.

The overpayment here is paid from a **CAD** bank, and that is the point. A
credit paid in USD into a USD bank carries its cost in a stored key, which is
stripped when the credit is spent, so the split cannot price anything
afterwards however it is loosened. Under a CAD transaction the cost is read
from the transaction itself, which the spending never touched.
"""

import re
from pathlib import Path

from click.testing import CliRunner
from gnucash import Query, Transaction

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from tests.conftest import _run
from tests.integration.test_applied_credit_carries_its_basis import (
    _overpaid_book,
)

RATES = 'tests/fixtures/fx_rates_usd_dated.yaml'
OWN_CURRENCY_RATES = 'tests/fixtures/fx_rates_usd_dated.yaml'

SALE = 'tests/fixtures/fx_sell_from_a_credit_handed_back.txt'


def _the_overpaying_transaction(book):
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        found = None
        for raw in query.run():
            transaction = Transaction(instance=raw)
            if transaction.GetDescription().startswith('FX Customer'):
                found = transaction.GetGUID().to_string()
        query.destroy()
    finally:
        repo.close()
    assert found is not None
    return found


def _a_cad_paid_credit(runner, tmp_path):
    """100.00 USD of credit, overpaid into a USD receivable from a CAD bank.

    What it cost is readable from that CAD transaction, so the credit is a
    cost basis with no stored cost of its own.

    Returns the book and the guid of the credit split.
    """
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_usd_invoice_paid_from_a_cad_bank.txt',
        '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output

    assert _run(runner, 'import', str(book),
                'tests/fixtures/fx_cad_bank_overpaying_a_usd_receivable.txt',
                '--fx-rates', RATES).exit_code == 0

    attach = tmp_path / 'attach.txt'
    attach.write_text(
        Path('tests/fixtures/fx_usd_invoice_overpaid_from_the_cad_bank.txt')
        .read_text().replace('TXN_GUID', _the_overpaying_transaction(book)))
    assert _run(runner, 'import', str(book), str(attach),
                '--include-business-objects', '--fx-rates', RATES
                ).exit_code == 0

    listing = _run(runner, 'fx-balances', str(book)).output
    credit = next(line.split()[1] for line in listing.splitlines()
                  if 'Accounts Receivable USD' in line
                  and '2026-02-25' in line
                  and 'none recorded' not in line)
    return book, credit


def _a_credit_handed_back(runner, tmp_path):
    """That credit, spent whole on an invoice and loosened by an unpost.

    The whole credit, so it is spent rather than divided: a division leaves a
    remainder holding the balance, which is a sound cost basis and not the split
    this is about.

    Returns the book and the guids `fx-balances` lists on the receivable.
    """
    book, credit = _a_cad_paid_credit(runner, tmp_path)

    # The credit is given by guid, so this tool spends it. Left to
    # `auto_apply_credit`, GnuCash 3.8, 4.4 and 4.13 rewrite the credit split's
    # value at par and add a balancing split — CLAUDE.md finding 19 — and the
    # book under test would then be a different book on those builds.
    spend = tmp_path / 'spend.txt'
    spend.write_text(
        Path('tests/fixtures/fx_invoice_spending_a_cad_paid_credit_whole.txt')
        .read_text()
        .replace('TXN_GUID', _the_overpaying_transaction(book))
        .replace('SPLIT_GUID', credit))
    spent = _run(runner, 'import', str(book), str(spend),
                 '--include-business-objects', '--fx-rates', RATES)
    assert spent.exit_code == 0, spent.output

    unposted = _run(runner, 'unpost-invoices', str(book),
                    'INV-FX-SPENDS-CREDIT')
    assert unposted.exit_code == 0, unposted.output

    listing = _run(runner, 'fx-balances', str(book)).output
    loosened = [line.split()[1] for line in listing.splitlines()
                if 'Accounts Receivable USD' in line
                and 'none recorded' in line]
    return book, loosened, listing


def test_the_loosened_credit_is_a_cost_basis_again(tmp_path):
    """Which is what makes the order of the two tests matter."""
    runner = CliRunner()
    _, loosened, listing = _a_credit_handed_back(runner, tmp_path)
    assert loosened, listing


def _a_usd_paid_credit_spent_whole(runner, tmp_path):
    """The other shape: a credit paid in the record's own currency, spent.

    Nothing in that payment's transaction says what the USD cost — it is USD
    into a USD bank — so the cost is a stored key and nothing else. Spending
    the credit must not take it, or the split cannot be priced again when the
    record is unposted, and the sale that drew on it is stranded with nothing
    on the sale a person could correct.

    Handed back before the record is unposted, so a ledger can be written
    while the credit is still spent.
    """
    book = _overpaid_book(runner, tmp_path)
    listing = _run(runner, 'fx-balances', str(book)).output
    credit = next(line.split()[1] for line in listing.splitlines()
                  if 'Accounts Receivable USD' in line and '2026-02-25' in line)

    sale = tmp_path / 'sale.txt'
    sale.write_text(
        Path('tests/fixtures/fx_sell_part_of_a_credit.txt').read_text()
        .replace('{basis}', credit))
    assert _run(runner, 'import', str(book), str(sale),
                '--fx-rates', OWN_CURRENCY_RATES).exit_code == 0

    whole = tmp_path / 'whole.txt'
    whole.write_text(
        Path('tests/fixtures/fx_invoice_auto_applying_the_whole_credit.txt')
        .read_text())
    assert _run(runner, 'import', str(book), str(whole),
                '--include-business-objects',
                '--fx-rates', OWN_CURRENCY_RATES).exit_code == 0
    return book


def _a_usd_paid_credit_handed_back(runner, tmp_path):
    """That credit, with the invoice it settled unposted afterwards."""
    book = _a_usd_paid_credit_spent_whole(runner, tmp_path)
    unposted = _run(runner, 'unpost-invoices', str(book), 'INV-USD-AUTO')
    assert unposted.exit_code == 0, unposted.output
    return book


def _the_credits_row(listing):
    """The line `fx-balances` prints for the 2026-02-25 credit, or ''."""
    for line in listing.splitlines():
        if 'Accounts Receivable USD' in line and line.startswith('2026-02-25'):
            return line
    return ''


def test_a_credit_priced_only_by_a_stored_cost_survives_being_spent(tmp_path):
    """Unposted afterwards, it is a cost basis again rather than nothing."""
    runner = CliRunner()
    book = _a_usd_paid_credit_handed_back(runner, tmp_path)

    listing = _run(runner, 'fx-balances', str(book)).output
    assert '2026-02-25' in listing, listing
    assert '1.4 CAD/USD' in _the_credits_row(listing), listing


def test_a_book_rebuilt_while_the_credit_is_spent_prices_it_the_same(tmp_path):
    """A ledger written while it is spent carries the cost that prices it.

    The cost is stored on the split, and the split is no cost basis while it
    settles the invoice — so the export's own test for a figure nothing reads
    would drop it, and only this order shows that. Written after the unpost
    the cost is on a live cost basis and is kept whatever that test says.

    Rebuild from a ledger written while the credit was spent, unpost the
    invoice there, and the split has to come back priced at 1.4 the way it
    does in the book the ledger came from. Dropped, it comes back a cost basis
    with no cost at all, the currency is unsellable, and the two books answer
    differently about the same money.
    """
    runner = CliRunner()
    book = _a_usd_paid_credit_spent_whole(runner, tmp_path)

    out = tmp_path / 'while-spent.txt'
    assert _run(runner, 'export', str(book), str(out),
                '--include-business-objects').exit_code == 0
    fresh = tmp_path / 'fresh.gnucash'
    rebuilt = _run(runner, 'import', '--new', str(fresh), str(out),
                   '--include-business-objects',
                   '--fx-rates', OWN_CURRENCY_RATES)
    assert rebuilt.exit_code == 0, rebuilt.output

    unposted = _run(runner, 'unpost-invoices', str(fresh), 'INV-USD-AUTO')
    assert unposted.exit_code == 0, unposted.output

    listing = _run(runner, 'fx-balances', str(fresh)).output
    row = _the_credits_row(listing)
    assert row, listing
    assert '1.4 CAD/USD' in row, row


def test_the_sale_that_drew_on_it_is_not_reported(tmp_path):
    """And the book's own ledger still rebuilds it.

    Stripped of its cost, that split was neither a cost basis nor a spent
    credit: `--verify-costs` reported the sale, the export wrote the guid, and
    the import refused it.
    """
    runner = CliRunner()
    book = _a_usd_paid_credit_handed_back(runner, tmp_path)

    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 0, verified.output

    out = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(out),
                '--include-business-objects').exit_code == 0
    fresh = tmp_path / 'fresh.gnucash'
    again = _run(runner, 'import', '--new', str(fresh), str(out),
                 '--include-business-objects',
                 '--fx-rates', OWN_CURRENCY_RATES)
    assert again.exit_code == 0, again.output
    assert re.search(r'Errors:\s+0$', again.output, re.M), again.output


def test_a_sale_against_it_is_still_refused(tmp_path):
    """It has no balance recorded, so nothing says how much is left to sell.

    Which is what the ordering fix is for: asked the other way round, the mark
    alone let the sale past the drawdown, the over-sell refusal,
    `_require_basis_collected` and `_require_stated_cost` alike, and its
    realized gain was whatever the file said.
    """
    runner = CliRunner()
    book, loosened, listing = _a_credit_handed_back(runner, tmp_path)
    assert loosened, listing
    sale = tmp_path / 'sale.txt'
    sale.write_text(Path(SALE).read_text().replace('{basis}', loosened[0]))

    result = _run(runner, 'import', str(book), str(sale), '--fx-rates', RATES)
    message = result.output + str(result.exception)
    assert result.exit_code != 0, message
    assert 'no balance recorded' in message, message
