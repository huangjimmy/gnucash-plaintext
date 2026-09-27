"""Spending a customer's credit leaves a sale of the dollars the bank holds where it is.

`fx_invoice_usd_overpaid_into_usd_bank.txt`: INV-USD-OVER bills 100.00 USD
and is paid 200.00 USD into Assets:Bank:USD at 1.37. The customer's 100.00
credit is a liability cost basis on the receivable, and the bank's split an
asset cost basis of the 100.00 USD past the invoice (Q-054).
`fx_sell_80_usd_the_overpayment_brought_into_the_bank.txt` sells 80.00 USD
of the bank's, stating the bank's cost basis: dollars held, sold against a
cost basis of dollars held.

The credit is then spent, in part or in full, by a `txn_split_guid:` block
stating the credit's guid, which this tool divides, or by
`auto_apply_credit: true`, which GnuCash divides. Spending the credit settles
another invoice out of what the customer is owed; no dollar leaves the bank,
so the sale goes on stating the bank's cost basis, the export writes that
guid, and a book rebuilt from the export imports without error.

The same holds for a credit overpaid from a Canadian dollar bank, whose
customer's dollars never reached a US dollar account. A sale of 50.00 USD out
of the empty US dollar bank takes it below zero and opens a liability cost
basis of its own, stating none; spending, unposting and spending the credit
again leave that sale's cost basis alone.

A guid that was never a cost basis is still refused.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from tests.conftest import _run
from tests.integration.test_a_credit_handed_back_by_an_unpost_is_checked import (
    _a_cad_paid_credit,
    _the_overpaying_transaction,
)
from tests.integration.test_applied_credit_carries_its_basis import (
    RATES,
    SECOND_INVOICE,
    _overpaid_book,
    _the_credit_split,
)


def _dashed(guid):
    """A guid in the 8-4-4-4-12 spelling GnuCash prints it in.

    A file may write one either way — every reader of `cost_basis_split_guid:`
    takes the dashes out — so a book can hold the key in this spelling.
    """
    return '-'.join([guid[:8], guid[8:12], guid[12:16], guid[16:20],
                     guid[20:]])


def _the_banks_cost_basis(runner, book):
    listing = runner.invoke(cli, ['fx-balances', str(book)]).output
    return next(line.split()[1] for line in listing.splitlines()
                if 'Assets:Bank:USD' in line and '2026-02-25' in line)


def _the_credits_cost_basis(runner, book):
    listing = runner.invoke(cli, ['fx-balances', str(book)]).output
    return next(line.split()[1] for line in listing.splitlines()
                if 'Accounts Receivable USD' in line and '2026-02-25' in line)


def _80_sold_from_the_bank_beside_a_credit(runner, tmp_path, dashed=False):
    """The overpaid book, with 80.00 USD sold against the bank's cost basis.

    Returns the book and the guid of the bank's cost basis.
    """
    book = _overpaid_book(runner, tmp_path)
    bank = _the_banks_cost_basis(runner, book)
    sale = tmp_path / 'sale.txt'
    sale.write_text(
        Path('tests/fixtures/fx_sell_80_usd_the_overpayment_brought_into_the_bank.txt')
        .read_text().replace('{basis}', _dashed(bank) if dashed else bank))
    sold = _run(runner, 'import', str(book), str(sale), '--fx-rates', RATES)
    assert sold.exit_code == 0 and re.search(r'Errors:\s+0$', sold.output, re.M), sold.output
    return book, bank


def _spend_30_of_it_through_a_block(runner, tmp_path, book):
    """A 30.00 USD invoice stating the credit by guid — divided by this tool."""
    credit_txn, credit_split = _the_credit_split(book)
    second = tmp_path / 'second.txt'
    second.write_text(
        Path('tests/fixtures/fx_invoice_stating_a_part_sold_credit.txt')
        .read_text().replace('TXN_GUID', credit_txn)
        .replace('SPLIT_GUID', credit_split))
    assert _run(runner, 'import', str(book), str(second),
                '--include-business-objects', '--fx-rates', RATES
                ).exit_code == 0


def _spend_40_of_it_through_the_engine(runner, tmp_path, book):
    """A 40.00 USD invoice asking for any credit — divided by GnuCash."""
    second = tmp_path / 'second.txt'
    second.write_text(SECOND_INVOICE)
    assert _run(runner, 'import', str(book), str(second),
                '--include-business-objects', '--fx-rates', RATES
                ).exit_code == 0


def _the_sale_block(text):
    return re.search(r'"Sell 80 USD the overpayment brought in"[^\n]*\n(?:\t[^\n]*\n)*',
                     text).group(0)


def _the_sales_basis_guid(runner, tmp_path, book):
    """The guid the 80.00 USD sale states, read back out of the export, or None."""
    out = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(out),
                '--include-business-objects').exit_code == 0
    stated = re.search(r'cost_basis_split_guid: "([0-9a-f]{32})"',
                       _the_sale_block(out.read_text()))
    return (stated.group(1) if stated else None), out


def _the_sale_stating(text, guid, mark=''):
    """The same ledger with the sale stating `guid`, and optionally that split
    marked as a credit this book spent."""
    block = _the_sale_block(text)
    written = re.sub(r'\t\tcost_basis_split_guid: "[0-9a-f]{32}"\n',
                     f'\t\tcost_basis_split_guid: "{guid}"\n', block)
    text = text.replace(block, written)
    if mark:
        settlement = re.search(
            rf'guid: "{guid}"\n(?:\t\t[^\n]*\n)*', text).group(0)
        text = text.replace(
            settlement,
            settlement.rstrip('\n') + f'\n\t\t{mark}\n')
    return text


def _the_remainders_guid(text, size):
    """The guid of the credit split that is `size` USD and still holds a
    balance — what the division left the customer."""
    block = re.search(
        rf'Assets:Accounts Receivable USD -{size} USD\n(?:\t\t[^\n]*\n)*',
        text).group(0)
    assert 'cost_basis_balance:' in block, block
    return re.search(r'guid: "([0-9a-f]{32})"', block).group(1)


def _consistent(runner, book):
    """`fx-balances --verify-costs` and `--verify-integrity` both pass."""
    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 0 and 'warning' not in verified.output, verified.output
    integrity = _run(runner, '--verify-integrity', str(book))
    assert integrity.exit_code == 0, integrity.output
    return verified.output


def test_the_sale_stays_on_the_bank_after_a_block_divides_the_credit(tmp_path):
    runner = CliRunner()
    book, bank = _80_sold_from_the_bank_beside_a_credit(runner, tmp_path)
    _spend_30_of_it_through_a_block(runner, tmp_path, book)

    stated, out = _the_sales_basis_guid(runner, tmp_path, book)
    assert stated == bank, _the_sale_block(out.read_text())
    assert _the_remainders_guid(out.read_text(), '70.00')
    _consistent(runner, book)


def test_the_sale_stays_on_the_bank_after_the_engine_divides_it(tmp_path):
    runner = CliRunner()
    book, bank = _80_sold_from_the_bank_beside_a_credit(runner, tmp_path)
    _spend_40_of_it_through_the_engine(runner, tmp_path, book)

    stated, out = _the_sales_basis_guid(runner, tmp_path, book)
    assert stated == bank, _the_sale_block(out.read_text())
    assert _the_remainders_guid(out.read_text(), '60.00')
    _consistent(runner, book)


def test_verify_costs_reports_nothing_after_a_block_divides_the_credit(tmp_path):
    runner = CliRunner()
    book, _ = _80_sold_from_the_bank_beside_a_credit(runner, tmp_path)
    _spend_30_of_it_through_a_block(runner, tmp_path, book)

    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 0, verified.output
    assert 'every cost agrees' in verified.output, verified.output


def test_verify_costs_reports_nothing_after_the_engine_divides_it(tmp_path):
    runner = CliRunner()
    book, _ = _80_sold_from_the_bank_beside_a_credit(runner, tmp_path)
    _spend_40_of_it_through_the_engine(runner, tmp_path, book)

    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 0, verified.output
    assert 'every cost agrees' in verified.output, verified.output


def test_the_export_of_a_divided_credits_book_re_imports(tmp_path):
    """Which is what the guid being right is for."""
    runner = CliRunner()
    book, _ = _80_sold_from_the_bank_beside_a_credit(runner, tmp_path)
    _spend_30_of_it_through_a_block(runner, tmp_path, book)

    _, out = _the_sales_basis_guid(runner, tmp_path, book)
    fresh = tmp_path / 'fresh.gnucash'
    again = _run(runner, 'import', '--new', str(fresh), str(out),
                 '--include-business-objects', '--fx-rates', RATES)
    assert again.exit_code == 0, again.output
    assert re.search(r'Errors:\s+0$', again.output, re.M), again.output


def _spend_all_of_it_through_a_block(runner, tmp_path, book):
    """A 100.00 USD invoice stating the whole credit by guid."""
    credit_txn, credit_split = _the_credit_split(book)
    whole = tmp_path / 'whole.txt'
    whole.write_text(
        Path('tests/fixtures/fx_invoice_spending_a_part_sold_credit_in_full.txt')
        .read_text().replace('TXN_GUID', credit_txn)
        .replace('SPLIT_GUID', credit_split))
    return _run(runner, 'import', str(book), str(whole),
                '--include-business-objects', '--fx-rates', RATES)


def _spend_all_of_it_through_the_engine(runner, tmp_path, book):
    """A 100.00 USD invoice asking for any credit — GnuCash spends it all."""
    whole = tmp_path / 'whole.txt'
    whole.write_text(
        Path('tests/fixtures/fx_invoice_auto_applying_the_whole_credit.txt')
        .read_text())
    return _run(runner, 'import', str(book), str(whole),
                '--include-business-objects', '--fx-rates', RATES)


def test_a_part_sold_credit_may_be_spent_in_full_by_a_block(tmp_path):
    """Ordinary bookkeeping, and not refused.

    A credit is money owed back to the customer, not a particular pile of
    currency, so their overpayment settling their next invoice in full is the
    commonest thing an overpayment is for. That the company converted 80.00 USD
    to CAD in the meantime has no bearing on it.
    """
    runner = CliRunner()
    book, _ = _80_sold_from_the_bank_beside_a_credit(runner, tmp_path)
    spent = _spend_all_of_it_through_a_block(runner, tmp_path, book)
    assert spent.exit_code == 0, spent.output

    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 0, verified.output
    assert 'every cost agrees' in verified.output, verified.output


def test_spending_it_in_full_commits_under_atomic(tmp_path):
    """The same file under the flag, where the book is read before it is saved.

    `--atomic` asks the questions of a book in the session that has just
    applied the file, and nothing has been written to disk. What the answer
    turns on is `is_a_spent_credit`, which asks whether the split sits in a
    lot a record owns — and a lot's tie to its invoice through
    `gncInvoiceGetInvoiceFromLot` is not visible until the session is written,
    which is why `_carry_basis_across_applied_credit` works by size instead.
    Read pessimistically, the sale that drew on this credit would look like a
    sale against a split that is no cost basis, and an ordinary file would be
    rolled back over a book that is sound.

    Measured here rather than reasoned about: it commits.
    """
    runner = CliRunner()
    book, _ = _80_sold_from_the_bank_beside_a_credit(runner, tmp_path)
    credit_txn, credit_split = _the_credit_split(book)
    whole = tmp_path / 'whole.txt'
    whole.write_text(
        Path('tests/fixtures/fx_invoice_spending_a_part_sold_credit_in_full.txt')
        .read_text().replace('TXN_GUID', credit_txn)
        .replace('SPLIT_GUID', credit_split))

    spent = _run(runner, 'import', str(book), str(whole), '--atomic',
                 '--include-business-objects', '--fx-rates', RATES)
    assert spent.exit_code == 0, spent.output
    assert 'Changes saved' in spent.output, spent.output
    assert 'Rolled back' not in spent.output, spent.output


def test_the_engine_spending_it_in_full_commits_under_atomic_too(tmp_path):
    """The same question of the path where GnuCash moves the split.

    The block path above puts the credit in the record's lot itself; here
    `AutoApplyPayments` does, and `_carry_basis_across_applied_credit`'s
    docstring records the opposite reading of the same call in the same
    session — that a lot's tie to its invoice is not visible through
    `gncInvoiceGetInvoiceFromLot` until the session is written, which is why
    that function works by size instead. If that reading held here, the sale
    that drew on this credit would look like a sale against a split that is no
    cost basis and an ordinary file would be rolled back.
    """
    runner = CliRunner()
    book, _ = _80_sold_from_the_bank_beside_a_credit(runner, tmp_path)
    whole = tmp_path / 'whole.txt'
    whole.write_text(
        Path('tests/fixtures/fx_invoice_auto_applying_the_whole_credit.txt')
        .read_text())

    spent = _run(runner, 'import', str(book), str(whole), '--atomic',
                 '--include-business-objects', '--fx-rates', RATES)
    assert spent.exit_code == 0, spent.output
    assert 'Changes saved' in spent.output, spent.output
    assert 'Rolled back' not in spent.output, spent.output


def test_a_part_sold_credit_may_be_spent_in_full_by_the_engine(tmp_path):
    runner = CliRunner()
    book, _ = _80_sold_from_the_bank_beside_a_credit(runner, tmp_path)
    spent = _spend_all_of_it_through_the_engine(runner, tmp_path, book)
    assert spent.exit_code == 0, spent.output

    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 0, verified.output
    assert 'every cost agrees' in verified.output, verified.output


def test_the_export_keeps_the_bank_s_guid_once_the_credit_is_spent(tmp_path):
    """The credit spent in full, and the sale still states the bank's cost basis.

    The ledger the book exports rebuilds a book without error.
    """
    runner = CliRunner()
    book, bank = _80_sold_from_the_bank_beside_a_credit(runner, tmp_path)
    assert _spend_all_of_it_through_a_block(
        runner, tmp_path, book).exit_code == 0

    stated, out = _the_sales_basis_guid(runner, tmp_path, book)
    assert stated == bank, _the_sale_block(out.read_text())

    fresh = tmp_path / 'fresh.gnucash'
    again = _run(runner, 'import', '--new', str(fresh), str(out),
                 '--include-business-objects', '--fx-rates', RATES)
    assert again.exit_code == 0, again.output
    assert re.search(r'Errors:\s+0$', again.output, re.M), again.output


def test_a_dashed_guid_is_read_the_same_way(tmp_path):
    """The spelling a file may use, which the readers all take the dashes out of.

    `cost_basis_guid_of` and `find_split_by_guid` both normalise, so a sale
    stating `8ec2f1a0-…` picks its cost basis and draws it down like any other,
    and the export of the book, the credit spent in full, rebuilds a book in
    which the bank's cost basis has the same 20.00 USD left.
    """
    runner = CliRunner()
    book, bank = _80_sold_from_the_bank_beside_a_credit(runner, tmp_path, dashed=True)
    assert _spend_all_of_it_through_a_block(
        runner, tmp_path, book).exit_code == 0

    out = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(out),
                '--include-business-objects').exit_code == 0
    fresh = tmp_path / 'fresh.gnucash'
    again = _run(runner, 'import', '--new', str(fresh), str(out),
                 '--include-business-objects', '--fx-rates', RATES)
    assert again.exit_code == 0 and re.search(r'Errors:\s+0$', again.output, re.M), again.output
    listed = _consistent(runner, fresh)
    assert re.search(rf'{bank}\s+Assets:Bank:USD\s+1\.37 CAD/USD\s+100\.00 USD\s+'
                     r'20\.00 USD\s+asset', listed), listed


def test_a_disposal_of_another_currency_on_it_is_still_reported(tmp_path):
    """Being a pool the book consumed excuses one question and not the rest.

    A sale that drew on a credit before it was spent still states its guid,
    and that is history rather than a fault — which is what `is_a_spent_credit`
    exempts it from. It does not make the split a pool of whatever currency
    somebody points at it: a CAD split drawing on a USD credit sold no US
    dollars out of it, spent or live.

    The state is written into the book rather than imported, because the
    import refuses this outright — `_validate_pick` asks the currency question
    of every file. What reaches it is an `--atomic` re-point, where the pick
    is allowed to differ and nothing draws a cost basis down, so this is the
    question the finished book has to ask.
    """
    runner = CliRunner()
    book, _ = _80_sold_from_the_bank_beside_a_credit(runner, tmp_path)
    assert _spend_all_of_it_through_a_block(
        runner, tmp_path, book).exit_code == 0

    _, out = _the_sales_basis_guid(runner, tmp_path, book)
    text = out.read_text()
    # The credit that was spent, not the settlement of the first invoice:
    # both are −100.00 USD on the receivable, and the mark is what separates
    # them.
    spent_block = next(
        block for block in
        text.split('Assets:Accounts Receivable USD -100.00 USD')[1:]
        if 'applied_from_credit' in block.split('\n\tAssets')[0])
    spent = re.search(r'guid: "([0-9a-f]{32})"', spent_block).group(1)

    from infrastructure.gnucash.kvp import set_custom_metadata
    from repositories.gnucash_repository import GnuCashRepository, SessionMode
    from services.foreign_currency import (
        COST_BASIS_SPLIT_KEY,
        cost_basis_guid_of,
        iter_splits,
        split_commodity,
        split_guid,
    )

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    marked = None
    try:
        for split in iter_splits(repo.book):
            if split_commodity(split) != 'CAD' or cost_basis_guid_of(split):
                continue
            transaction = split.GetParent()
            transaction.BeginEdit()
            set_custom_metadata(split, {COST_BASIS_SPLIT_KEY: spent})
            transaction.CommitEdit()
            marked = split_guid(split)
            break
    finally:
        repo.save()
        repo.close()
    assert marked is not None, 'expected a CAD split to point at the credit'

    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 1, verified.output
    assert marked in verified.output, verified.output
    assert 'which holds USD' in verified.output, verified.output


def test_verify_costs_says_nothing_about_the_book_that_keeps_it(tmp_path):
    """The book still holds the guid, and holding it is not a fault."""
    runner = CliRunner()
    book, _ = _80_sold_from_the_bank_beside_a_credit(runner, tmp_path)
    assert _spend_all_of_it_through_a_block(
        runner, tmp_path, book).exit_code == 0

    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 0, verified.output


def test_a_guid_that_was_never_a_basis_is_still_refused(tmp_path):
    """Taking a consumed cost basis does not take any split that is no cost basis.

    The settlement of the first invoice is on the same account, in the same
    transaction, and lowers its USD the same way — and it was never anybody's
    credit, so it is refused as before.
    """
    runner = CliRunner()
    book, _ = _80_sold_from_the_bank_beside_a_credit(runner, tmp_path)
    assert _spend_all_of_it_through_a_block(
        runner, tmp_path, book).exit_code == 0

    _, out = _the_sales_basis_guid(runner, tmp_path, book)
    text = out.read_text()
    settlement = re.search(
        r'Assets:Accounts Receivable USD -100\.00 USD\n(?:\t\t[^\n]*\n)*',
        text).group(0)
    other = re.search(r'guid: "([0-9a-f]{32})"', settlement).group(1)

    fresh = tmp_path / 'fresh.gnucash'
    forged = tmp_path / 'forged.txt'
    forged.write_text(_the_sale_stating(text, other))
    again = _run(runner, 'import', '--new', str(fresh), str(forged),
                 '--include-business-objects', '--fx-rates', RATES)
    assert again.exit_code != 0, again.output
    assert 'is no USD cost basis' in again.output, again.output


def test_a_file_cannot_buy_its_way_past_the_refusal_with_the_credit_mark(tmp_path):
    """`applied_from_credit` reaches a book from a file, and buys nothing here.

    The export emits that key and fixtures state it, so unlike
    `orphaned_by_unpost` it is not something only a book can know. If it
    excused a sale's guid from the refusal, a file could write it onto any
    split at all and have a sale skip the drawdown, the over-sell refusal,
    `_require_basis_collected` and `_require_stated_cost` together. Nothing in
    the import reads it for that, so the same file is refused with or without
    it.
    """
    runner = CliRunner()
    book, _ = _80_sold_from_the_bank_beside_a_credit(runner, tmp_path)
    assert _spend_all_of_it_through_a_block(
        runner, tmp_path, book).exit_code == 0

    _, out = _the_sales_basis_guid(runner, tmp_path, book)
    text = out.read_text()
    settlement = re.search(
        r'Assets:Accounts Receivable USD -100\.00 USD\n(?:\t\t[^\n]*\n)*',
        text).group(0)
    other = re.search(r'guid: "([0-9a-f]{32})"', settlement).group(1)

    forged = tmp_path / 'forged.txt'
    forged.write_text(_the_sale_stating(
        text, other, mark='applied_from_credit: "true"'))
    fresh = tmp_path / 'fresh.gnucash'
    again = _run(runner, 'import', '--new', str(fresh), str(forged),
                 '--include-business-objects', '--fx-rates', RATES)
    assert again.exit_code != 0, again.output
    assert 'is no USD cost basis' in again.output, again.output


def test_the_book_counts_each_cost_basis_once_the_credit_is_divided(tmp_path):
    """30.00 of the credit spent on INV-USD-NAMES-CREDIT.

    The bank holds 120.00 USD: INV-USD-OVER's 100.00 collected, and 20.00 of
    the 100.00 the overpayment brought in. The customer is owed 70.00.
    INV-USD-NAMES-CREDIT's cost basis is spent by the credit that paid it.
    """
    runner = CliRunner()
    book, bank = _80_sold_from_the_bank_beside_a_credit(runner, tmp_path)
    _spend_30_of_it_through_a_block(runner, tmp_path, book)

    listed = _consistent(runner, book)
    assert re.search(rf'{bank}\s+Assets:Bank:USD\s+1\.37 CAD/USD\s+100\.00 USD\s+'
                     r'20\.00 USD\s+asset', listed), listed
    assert re.search(r'Assets:Accounts Receivable USD\s+1\.37 CAD/USD\s+70\.00 USD\s+'
                     r'70\.00 USD\s+liability', listed), listed
    assert re.search(r'Assets:Accounts Receivable USD\s+1\.37 CAD/USD\s+30\.00 USD\s+'
                     r'0\.00 USD\s+asset', listed), listed
    assert 'Total USD cost basis balance: 120.00 USD held, 70.00 USD owed' in listed, listed


def _a_keyless_credit_the_engine_can_divide(runner, tmp_path):
    """The USD book with 80.00 sold from the bank, and neither key on the credit.

    A credit reaches this state on its own — overpaid from a CAD bank, so its
    cost is read from its transaction and stored nowhere, then spent on an
    invoice, which takes its balance, then handed back by an unpost. Applying
    *that* credit through `auto_apply_credit:` is what cannot be measured:
    GnuCash 3.8, 4.4 and 4.13 rewrite a CAD-quoted credit's value at par and
    add a balancing split, so the book under test would be a different book on
    three of the ten supported builds.

    So the same state is built on the USD book, where the engine's application
    is the same everywhere, by removing the two keys in a file — which is
    what `cost_basis_balance: $None$` is for and what the listing tells a
    reader to write.

    Returns the book and the guid of the bank's cost basis.
    """
    book, bank = _80_sold_from_the_bank_beside_a_credit(runner, tmp_path)
    credit = _the_credits_cost_basis(runner, book)

    out = tmp_path / 'before.txt'
    assert _run(runner, 'export', str(book), str(out)).exit_code == 0
    block = re.search(r'2026-02-25 \* [^\n]*\n(?:\t[^\n]*\n)*',
                      out.read_text()).group(0)
    assert 'cost_basis_balance:' in block, block
    # The credit split's own lines, so the other splits in the transaction
    # keep whatever they carry.
    chunk = re.search(rf'guid: "{credit}"\n(?:\t\t[^\n]*\n)*', block).group(0)
    cleared = block.replace(chunk, re.sub(
        r'cost_basis_(balance|cost): "[^"]*"', r'cost_basis_\1: $None$', chunk))
    stripped = tmp_path / 'stripped.txt'
    stripped.write_text(cleared)
    result = _run(runner, 'import', str(book), str(stripped),
                  '--strategy', 'update', '--fx-rates', RATES)
    assert result.exit_code == 0, result.output

    # The premise, asserted rather than assumed: a test of what happens to a
    # credit carrying neither key is worth nothing if the keys are still on it.
    check = tmp_path / 'stripped-check.txt'
    assert _run(runner, 'export', str(book), str(check)).exit_code == 0
    written = re.search(rf'guid: "{credit}"\n(?:\t\t[^\n]*\n)*',
                        check.read_text()).group(0)
    assert 'cost_basis_balance' not in written, written
    assert 'cost_basis_cost' not in written, written
    return book, bank


def test_the_engine_dividing_a_keyless_credit_leaves_the_sale_on_the_bank(tmp_path):
    """`auto_apply_credit:` divides a credit carrying no key, and the sale of the
    bank's dollars still states the bank's cost basis."""
    runner = CliRunner()
    book, bank = _a_keyless_credit_the_engine_can_divide(runner, tmp_path)
    _spend_40_of_it_through_the_engine(runner, tmp_path, book)

    stated, out = _the_sales_basis_guid(runner, tmp_path, book)
    assert stated == bank, _the_sale_block(out.read_text())


def _a_keyless_credit_beside_a_sale_of_its_own(runner, tmp_path):
    """A credit carrying neither cost basis key, beside 50.00 USD sold out of an empty bank.

    A credit overpaid from a CAD bank is priced by its own transaction, so it
    stores no cost of its own; spending it whole on an invoice takes its
    balance; and unposting that invoice hands it back carrying neither key.

    The customer's dollars never reached a US dollar account, so the 50.00 USD
    sold takes Assets:Bank:USD from 0.00 to -50.00 and opens a liability cost
    basis of its own.
    """
    book, credit = _a_cad_paid_credit(runner, tmp_path)

    sale = tmp_path / 'sale.txt'
    sale.write_text(
        Path('tests/fixtures/fx_sell_50_usd_out_of_an_empty_usd_bank.txt').read_text())
    sold = _run(runner, 'import', str(book), str(sale), '--fx-rates', RATES)
    assert sold.exit_code == 0 and re.search(r'Errors:\s+0$', sold.output, re.M), sold.output

    spend = tmp_path / 'spend.txt'
    spend.write_text(
        Path('tests/fixtures/fx_invoice_spending_a_cad_paid_credit_whole.txt')
        .read_text()
        .replace('TXN_GUID', _the_overpaying_transaction(book))
        .replace('SPLIT_GUID', credit))
    assert _run(runner, 'import', str(book), str(spend),
                '--include-business-objects', '--fx-rates', RATES
                ).exit_code == 0
    assert _run(runner, 'unpost-invoices', str(book),
                'INV-FX-SPENDS-CREDIT').exit_code == 0
    return book, credit


def _spend_30_of_the_loosened_credit(runner, tmp_path, book, credit):
    """A 30.00 USD invoice stating that credit by guid, leaving 70.00."""
    part = tmp_path / 'part.txt'
    part.write_text(
        Path('tests/fixtures/fx_invoice_spending_part_of_a_cad_paid_credit.txt')
        .read_text()
        .replace('TXN_GUID', _the_overpaying_transaction(book))
        .replace('SPLIT_GUID', credit))
    result = _run(runner, 'import', str(book), str(part),
                  '--include-business-objects', '--fx-rates', RATES)
    assert result.exit_code == 0, result.output


def _the_sale_of_50(text):
    return re.search(r'"Sell 50 USD the bank does not hold"[^\n]*\n(?:\t[^\n]*\n)*',
                     text).group(0)


def test_spending_the_credit_leaves_the_sale_s_own_cost_basis_alone(tmp_path):
    """The credit spent, handed back and 30.00 of it spent again, and the sale
    still states no cost basis and keeps its own 50.00 USD liability cost basis."""
    runner = CliRunner()
    book, credit = _a_keyless_credit_beside_a_sale_of_its_own(runner, tmp_path)
    _spend_30_of_the_loosened_credit(runner, tmp_path, book, credit)

    out = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(out),
                '--include-business-objects').exit_code == 0
    sale = _the_sale_of_50(out.read_text())
    assert 'cost_basis_split_guid' not in sale, sale
    assert 'cost_basis_balance: "50.00"' in sale, sale


def test_the_rebuilt_book_keeps_the_sale_s_own_cost_basis(tmp_path):
    """The export of that book rebuilds one holding the same 50.00 USD liability cost basis."""
    runner = CliRunner()
    book, credit = _a_keyless_credit_beside_a_sale_of_its_own(runner, tmp_path)
    _spend_30_of_the_loosened_credit(runner, tmp_path, book, credit)

    out = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(out),
                '--include-business-objects').exit_code == 0
    fresh = tmp_path / 'fresh.gnucash'
    again = _run(runner, 'import', '--new', str(fresh), str(out),
                 '--include-business-objects', '--fx-rates', RATES)
    assert again.exit_code == 0, again.output
    assert re.search(r'Errors:\s+0$', again.output, re.M), again.output

    listing = _run(runner, 'fx-balances', str(fresh)).output
    assert re.search(r'2026-03-05\s+[0-9a-f]{32}\s+Assets:Bank:USD\s+1\.37 CAD/USD\s+'
                     r'50\.00 USD\s+50\.00 USD\s+liability', listing), listing
