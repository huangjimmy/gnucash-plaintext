"""Spending part of a credit moves the disposals with the cost basis.

Spending part of an owner's credit divides the split it comes from. The part
applied keeps the source split's guid and settles the record; the currency
still unsold moves to the remainder, a new split with a guid of its own.

A sale already measured against that credit gives the old guid, and the old
guid matches the settlement now. Nothing about the sale changed — it sold what
it sold, at the cost it sold it at, out of the same pool — so it is given the
remainder's guid, and the pool it draws on is the split that holds it.

Left where it was, the sale draws on a split that is no cost basis:
`--verify-costs` reports it, and the export writes that guid into
`cost_basis_split_guid:`, so the book's own ledger is refused on the way back
in with "matches a split that is no USD cost basis".

Both ways a credit is divided are covered. A `txn_split_guid:` block giving the
credit's guid divides it here; `auto_apply_credit: true` leaves the division to
GnuCash, which carves it differently — the applied part keeps the source's
slots and the remainder comes out empty.

Both are covered for a credit carrying no cost basis key at all, which is the shape
that gets missed: a credit overpaid from a CAD bank stores no cost, spending it
takes its balance, and an unpost hands it back with neither key and a sale
still giving its guid. Read off the keys, such a credit is one nothing moves
for — and it is the division that says where the pool went, not the keys.

Spending a credit in full is covered too, and is not refused. A credit is money
owed back to the owner rather than a particular pile of currency, so an
overpayment settling their next invoice in full is the commonest thing an
overpayment is for, and whether the company converted some of that currency in
the meantime has no bearing on it. Nothing is left for the sale to move to, so
it keeps giving the credit's guid — a cost basis the book consumed, which the import
takes and neither lowers nor refuses. A guid that was never a cost basis still is
refused.
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

    A file may give one either way — every reader of `cost_basis_split_guid:`
    takes the dashes out — so a book can hold the key in this spelling.
    """
    return '-'.join([guid[:8], guid[8:12], guid[12:16], guid[16:20],
                     guid[20:]])


def _a_credit_with_80_sold_from_it(runner, tmp_path, dashed=False):
    """The overpaid book's 100.00 USD credit, with 80.00 sold against it."""
    book = _overpaid_book(runner, tmp_path)
    listing = runner.invoke(cli, ['fx-balances', str(book)]).output
    credit_guid = next(
        line.split()[1] for line in listing.splitlines()
        if 'Accounts Receivable USD' in line and '2026-02-25' in line)
    sale = tmp_path / 'sale.txt'
    sale.write_text(
        Path('tests/fixtures/fx_sell_part_of_a_credit.txt').read_text()
        .replace('{basis}',
                 _dashed(credit_guid) if dashed else credit_guid))
    assert _run(runner, 'import', str(book), str(sale),
                '--fx-rates', RATES).exit_code == 0
    return book, credit_guid


def _spend_30_of_it_through_a_block(runner, tmp_path, book):
    """A 30.00 USD invoice giving the credit by guid — divided by this tool."""
    credit_txn, credit_split = _the_credit_split(book)
    second = tmp_path / 'second.txt'
    second.write_text(
        Path('tests/fixtures/fx_invoice_giving_a_part_sold_credit.txt')
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
    return re.search(r'"Sell 80 USD of the credit"[^\n]*\n(?:\t[^\n]*\n)*',
                     text).group(0)


def _the_sales_basis_guid(runner, tmp_path, book):
    """The guid the 80.00 USD sale gives, read back out of the export.

    None where the export writes none, which is what it does once the pool the
    sale drew on has been spent: the line would rebuild nothing.
    """
    out = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(out),
                '--include-business-objects').exit_code == 0
    given = re.search(r'cost_basis_split_guid: "([0-9a-f]{32})"',
                      _the_sale_block(out.read_text()))
    return (given.group(1) if given else None), out


def _the_sale_giving(text, guid, mark=''):
    """The same ledger with the sale giving `guid`, and optionally that split
    marked as a credit this book spent."""
    block = _the_sale_block(text)
    written = re.sub(r'\t\tcost_basis_split_guid: "[0-9a-f]{32}"\n', '', block)
    written = written.rstrip('\n') + f'\n\t\tcost_basis_split_guid: "{guid}"\n'
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


def test_the_sale_gives_the_remainder_after_a_block_divides_the_credit(tmp_path):
    runner = CliRunner()
    book, credit_guid = _a_credit_with_80_sold_from_it(runner, tmp_path)
    _spend_30_of_it_through_a_block(runner, tmp_path, book)

    given, out = _the_sales_basis_guid(runner, tmp_path, book)
    assert given != credit_guid, 'still gives the split that was spent'
    assert given == _the_remainders_guid(out.read_text(), '70.00')


def test_the_sale_gives_the_remainder_after_the_engine_divides_it(tmp_path):
    runner = CliRunner()
    book, credit_guid = _a_credit_with_80_sold_from_it(runner, tmp_path)
    _spend_40_of_it_through_the_engine(runner, tmp_path, book)

    given, out = _the_sales_basis_guid(runner, tmp_path, book)
    assert given != credit_guid, 'still gives the split that was spent'
    assert given == _the_remainders_guid(out.read_text(), '60.00')


def test_verify_costs_reports_nothing_after_a_block_divides_the_credit(tmp_path):
    runner = CliRunner()
    book, _ = _a_credit_with_80_sold_from_it(runner, tmp_path)
    _spend_30_of_it_through_a_block(runner, tmp_path, book)

    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 0, verified.output
    assert 'every cost agrees' in verified.output, verified.output


def test_verify_costs_reports_nothing_after_the_engine_divides_it(tmp_path):
    runner = CliRunner()
    book, _ = _a_credit_with_80_sold_from_it(runner, tmp_path)
    _spend_40_of_it_through_the_engine(runner, tmp_path, book)

    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 0, verified.output
    assert 'every cost agrees' in verified.output, verified.output


def test_the_export_of_a_divided_credits_book_re_imports(tmp_path):
    """Which is what the guid being right is for."""
    runner = CliRunner()
    book, _ = _a_credit_with_80_sold_from_it(runner, tmp_path)
    _spend_30_of_it_through_a_block(runner, tmp_path, book)

    _, out = _the_sales_basis_guid(runner, tmp_path, book)
    fresh = tmp_path / 'fresh.gnucash'
    again = _run(runner, 'import', '--new', str(fresh), str(out),
                 '--include-business-objects', '--fx-rates', RATES)
    assert again.exit_code == 0, again.output
    assert re.search(r'Errors:\s+0$', again.output, re.M), again.output


def _spend_all_of_it_through_a_block(runner, tmp_path, book):
    """A 100.00 USD invoice giving the whole credit by guid."""
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
    book, _ = _a_credit_with_80_sold_from_it(runner, tmp_path)
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
    book, _ = _a_credit_with_80_sold_from_it(runner, tmp_path)
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
    book, _ = _a_credit_with_80_sold_from_it(runner, tmp_path)
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
    book, _ = _a_credit_with_80_sold_from_it(runner, tmp_path)
    spent = _spend_all_of_it_through_the_engine(runner, tmp_path, book)
    assert spent.exit_code == 0, spent.output

    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 0, verified.output
    assert 'every cost agrees' in verified.output, verified.output


def test_the_export_leaves_the_guid_out_once_the_pool_is_spent(tmp_path):
    """There is no remainder to move the sale to, so the line rebuilds nothing.

    Spending the credit in full ended the pool, and the split that was the
    credit is the record's settlement afterwards — no cost basis. The book
    keeps the guid, which is what it knows about where that currency came
    from; the file does not, because a rebuilt book has nothing to measure
    against it and the import says so. The same rule the export already
    follows for a `cost_basis_cost` on a split that is no cost basis.
    """
    runner = CliRunner()
    book, _ = _a_credit_with_80_sold_from_it(runner, tmp_path)
    assert _spend_all_of_it_through_a_block(
        runner, tmp_path, book).exit_code == 0

    given, out = _the_sales_basis_guid(runner, tmp_path, book)
    assert given is None, _the_sale_block(out.read_text())

    fresh = tmp_path / 'fresh.gnucash'
    again = _run(runner, 'import', '--new', str(fresh), str(out),
                 '--include-business-objects', '--fx-rates', RATES)
    assert again.exit_code == 0, again.output
    assert re.search(r'Errors:\s+0$', again.output, re.M), again.output


def test_a_dashed_guid_is_read_the_same_way(tmp_path):
    """The spelling a file may use, which the readers all take the dashes out of.

    `cost_basis_guid_of` and `find_split_by_guid` both normalise, so a sale
    stating `8ec2f1a0-…` picks its cost basis and draws it down like any other, and
    the key is stored on the split as the file spelled it. The export's own
    question — is this guid a pool the book consumed — has to normalise too,
    or it looks up nothing, answers no, and writes out a guid the import then
    refuses.
    """
    runner = CliRunner()
    book, _ = _a_credit_with_80_sold_from_it(runner, tmp_path, dashed=True)
    assert _spend_all_of_it_through_a_block(
        runner, tmp_path, book).exit_code == 0

    out = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(out),
                '--include-business-objects').exit_code == 0
    sale = _the_sale_block(out.read_text())
    assert 'cost_basis_split_guid' not in sale, sale


def test_a_disposal_of_another_currency_on_it_is_still_reported(tmp_path):
    """Being a pool the book consumed excuses one question and not the rest.

    A sale that drew on a credit before it was spent keeps giving its guid,
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
    book, _ = _a_credit_with_80_sold_from_it(runner, tmp_path)
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
    book, _ = _a_credit_with_80_sold_from_it(runner, tmp_path)
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
    book, _ = _a_credit_with_80_sold_from_it(runner, tmp_path)
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
    forged.write_text(_the_sale_giving(text, other))
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
    book, _ = _a_credit_with_80_sold_from_it(runner, tmp_path)
    assert _spend_all_of_it_through_a_block(
        runner, tmp_path, book).exit_code == 0

    _, out = _the_sales_basis_guid(runner, tmp_path, book)
    text = out.read_text()
    settlement = re.search(
        r'Assets:Accounts Receivable USD -100\.00 USD\n(?:\t\t[^\n]*\n)*',
        text).group(0)
    other = re.search(r'guid: "([0-9a-f]{32})"', settlement).group(1)

    forged = tmp_path / 'forged.txt'
    forged.write_text(_the_sale_giving(
        text, other, mark='applied_from_credit: "true"'))
    fresh = tmp_path / 'fresh.gnucash'
    again = _run(runner, 'import', '--new', str(fresh), str(forged),
                 '--include-business-objects', '--fx-rates', RATES)
    assert again.exit_code != 0, again.output
    assert 'is no USD cost basis' in again.output, again.output


def test_the_sale_is_counted_against_the_remainder(tmp_path):
    """The listing's own arithmetic, which the stale guid took the sale out of.

    A disposal drawing on a split that is no cost basis is counted against no
    basis, so the ledger read as though the 80.00 had never been sold.
    """
    runner = CliRunner()
    book, _ = _a_credit_with_80_sold_from_it(runner, tmp_path)
    _spend_30_of_it_through_a_block(runner, tmp_path, book)

    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert '80.00 USD was sold against a cost basis' in verified.output, \
        verified.output


def _a_keyless_credit_the_engine_can_divide(runner, tmp_path):
    """The same shape on the book GnuCash may divide: neither key, 80.00 sold.

    A credit reaches this state on its own — overpaid from a CAD bank, so its
    cost is read from its transaction and stored nowhere, then spent on an
    invoice, which takes its balance, then handed back by an unpost. Applying
    *that* credit through `auto_apply_credit:` is what cannot be measured:
    GnuCash 3.8, 4.4 and 4.13 rewrite a CAD-quoted credit's value at par and
    add a balancing split, so the book under test would be a different book on
    three of the ten supported builds.

    So the same state is built on the USD book, where the engine's application
    is the same everywhere, by taking the two keys off in a file — which is
    what `cost_basis_balance: ""` is for and what the listing tells a reader
    to write. The split is then a credit with a sale against it and nothing
    saying what its currency cost, which is the state under test.
    """
    book, credit = _a_credit_with_80_sold_from_it(runner, tmp_path)

    out = tmp_path / 'before.txt'
    assert _run(runner, 'export', str(book), str(out)).exit_code == 0
    block = re.search(r'2026-02-25 \* [^\n]*\n(?:\t[^\n]*\n)*',
                      out.read_text()).group(0)
    assert 'cost_basis_balance:' in block, block
    # The credit split's own lines, so the other splits in the transaction
    # keep whatever they carry.
    chunk = re.search(rf'guid: "{credit}"\n(?:\t\t[^\n]*\n)*', block).group(0)
    cleared = block.replace(chunk, re.sub(
        r'cost_basis_(balance|cost): "[^"]*"', r'cost_basis_\1: ""', chunk))
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
    return book, credit


def test_the_engine_moves_a_keyless_credits_sale_too(tmp_path):
    """`auto_apply_credit:` divides it, and the sale follows the pool.

    The walk that follows an engine-carved credit collected the splits that
    carry a cost basis key, so a credit carrying none was never looked at: the
    engine halved it, the sale went on giving the applied part, and that part
    settles the invoice — no cost basis, and marked as a credit the book
    consumed, which is what stops `--verify-costs` reporting it and what makes
    the export drop the guid. The book's own ledger then rebuilt a remainder
    with nothing measured against it.
    """
    runner = CliRunner()
    book, _ = _a_keyless_credit_the_engine_can_divide(runner, tmp_path)
    _spend_40_of_it_through_the_engine(runner, tmp_path, book)

    out = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(out)).exit_code == 0
    text = out.read_text()
    remainder = re.search(
        r'Assets:Accounts Receivable USD -60\.00 USD\n(?:\t\t[^\n]*\n)*',
        text).group(0)
    remainder_guid = re.search(r'guid: "([0-9a-f]{32})"', remainder).group(1)

    given = re.search(r'cost_basis_split_guid: "([0-9a-f]{32})"',
                      _the_sale_block(text))
    assert given, _the_sale_block(text)
    assert given.group(1) == remainder_guid, _the_sale_block(text)


def _a_keyless_credit_a_sale_draws_on(runner, tmp_path):
    """A credit carrying neither cost basis key, with 50.00 USD sold against it.

    A credit overpaid from a CAD bank is priced by its own transaction, so it
    stores no cost of its own; spending it whole on an invoice takes its
    balance; and unposting that invoice hands it back carrying neither key.
    The sale made while it still had a balance goes on giving its guid.

    Nothing is carried across a division of that credit, there being no keys
    to carry, and the sale has to follow the pool all the same.
    """
    book, credit = _a_cad_paid_credit(runner, tmp_path)

    sale = tmp_path / 'sale.txt'
    sale.write_text(
        Path('tests/fixtures/fx_sell_50_usd_against_a_cad_paid_credit.txt')
        .read_text().replace('{basis}', credit))
    assert _run(runner, 'import', str(book), str(sale),
                '--fx-rates', RATES).exit_code == 0

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
    """A 30.00 USD invoice giving that credit by guid, leaving 70.00."""
    part = tmp_path / 'part.txt'
    part.write_text(
        Path('tests/fixtures/fx_invoice_spending_part_of_a_cad_paid_credit.txt')
        .read_text()
        .replace('TXN_GUID', _the_overpaying_transaction(book))
        .replace('SPLIT_GUID', credit))
    result = _run(runner, 'import', str(book), str(part),
                  '--include-business-objects', '--fx-rates', RATES)
    assert result.exit_code == 0, result.output


def test_the_sale_follows_a_credit_that_carries_no_basis_key(tmp_path):
    """The keys are not what says where the pool went; the division is.

    Read off the keys, a credit carrying none of them is a credit nothing
    moves for, and the sale goes on giving the split that is the invoice's
    settlement now. Measured: the export then writes the sale no
    `cost_basis_split_guid:` at all — the guid gives a pool the book consumed,
    which is dropped rather than written out — so the ledger says nothing
    about where the 50.00 USD it sold came from, and a book rebuilt from it
    has a sale drawing on nothing.
    """
    runner = CliRunner()
    book, credit = _a_keyless_credit_a_sale_draws_on(runner, tmp_path)
    _spend_30_of_the_loosened_credit(runner, tmp_path, book, credit)

    out = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(out),
                '--include-business-objects').exit_code == 0
    text = out.read_text()
    remainder = re.search(
        r'Assets:Accounts Receivable USD -70\.00 USD\n(?:\t\t[^\n]*\n)*',
        text).group(0)
    remainder_guid = re.search(r'guid: "([0-9a-f]{32})"', remainder).group(1)

    sale = re.search(r'"Sell 50 USD of the credit"[^\n]*\n(?:\t[^\n]*\n)*',
                     text).group(0)
    given = re.search(r'cost_basis_split_guid: "([0-9a-f]{32})"', sale)
    assert given, sale
    assert given.group(1) == remainder_guid, sale


def test_the_rebuilt_book_measures_the_sale_against_the_remainder(tmp_path):
    """The guid is what carries that, and the file carries the guid.

    The remainder is a cost basis with no balance recorded in the book this ledger
    comes from — spending the credit took the balance, and the unpost handed
    the split back without one — and no line states that, there being no way
    to write "not known" in a file. So the rebuilt book opens a balance for
    the 70.00 the split brought in, and the 50.00 sale draws it down to 20.00.
    Measured against nothing, which is where the sale points without the
    guid, the same rebuild offers the whole 70.00.
    """
    runner = CliRunner()
    book, credit = _a_keyless_credit_a_sale_draws_on(runner, tmp_path)
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
    remainder = [line for line in listing.splitlines() if '70.00 USD' in line]
    assert remainder, listing
    assert '20.00 USD' in remainder[0], remainder[0]
