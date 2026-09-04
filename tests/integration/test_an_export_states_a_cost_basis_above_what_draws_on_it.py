"""A ledger states a cost basis above the sales that draw on it.

An export writes transactions in the order the book keeps them, which is
GnuCash's own: the posted date, then `num`, then when each was entered, then
the description, then the guid. Two transactions of one day, entered in the
same second and carrying no `num`, are therefore ordered by their
descriptions — and a deposit called "Received money from Example Customer Inc"
comes after the fee called "Charges for: TRANSFER-0000001" that is drawn on
it.

Read in that order the file cannot be read back. `cost_basis_split_guid:` is
resolved as each block is applied, so a fee stating the guid of a split no
block above it has created is refused with "matches no split in the book", and
the whole import fails. That is a sound book whose own ledger does not rebuild
it, which is the state `fx-balances --verify-costs` exists to report and
reported nothing about, because every figure in it agrees.

So the export makes one exception to the book's order: a transaction holding a
split that another transaction draws on is written above it. Nothing else
moves.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import iter_splits, split_guid
from tests.conftest import _run
from tests.integration.test_a_disposal_drawing_on_a_split_that_is_no_basis import (  # noqa: E501
    a_deposit_and_a_fee_of_the_same_day,
)

DEPOSIT = 'Received money from Example Customer Inc'
FEE = 'Charges for: TRANSFER-0000001'
RATES = 'tests/fixtures/fx_rates_usd_two_invoice_dates.yaml'

# The two transactions and their USD splits, from the fixtures that state
# them.
DEPOSIT_TXN = '15f40458487e434abd1d9a95c46a7041'
FEE_TXN = '10379c8ab37547b8b7c8dbebca45d3e3'
DEPOSIT_SPLIT = '00e958a8d56547d484d7629000292dc3'
FEE_SPLIT = '51fe44af5e9a41d9be672cf6251f5fdd'


def _the_ledger_of_that_book(runner, tmp_path):
    book = a_deposit_and_a_fee_of_the_same_day(runner, tmp_path)
    out = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(out)).exit_code == 0
    return book, out


def test_the_deposit_is_stated_above_the_fee_drawn_on_it(tmp_path):
    runner = CliRunner()
    _, out = _the_ledger_of_that_book(runner, tmp_path)

    written = re.findall(r'^\d{4}-\d\d-\d\d \* "([^"]*)"', out.read_text(),
                         re.M)
    assert DEPOSIT in written and FEE in written, written
    assert written.index(DEPOSIT) < written.index(FEE), written


def test_the_books_own_ledger_rebuilds_it(tmp_path):
    """Which is what the order is for."""
    runner = CliRunner()
    _, out = _the_ledger_of_that_book(runner, tmp_path)

    fresh = tmp_path / 'fresh.gnucash'
    rebuilt = _run(runner, 'import', '--new', str(fresh), str(out))
    message = rebuilt.output + str(rebuilt.exception)
    assert rebuilt.exit_code == 0, message
    assert re.search(r'Errors:\s+0$', rebuilt.output, re.M), rebuilt.output


def test_the_rebuilt_book_measures_the_fee_against_the_deposit(tmp_path):
    """And the rebuilt book holds the same cost basis, drawn on by the fee.

    2720.00 USD bought for 3815.89 CAD, less the 0.72 USD the fee took.
    """
    runner = CliRunner()
    _, out = _the_ledger_of_that_book(runner, tmp_path)
    fresh = tmp_path / 'fresh.gnucash'
    assert _run(runner, 'import', '--new', str(fresh), str(out)).exit_code == 0

    listing = _run(runner, 'fx-balances', str(fresh))
    assert listing.exit_code == 0, listing.output
    assert '2,719.28 USD' in listing.output, listing.output

    verified = _run(runner, 'fx-balances', str(fresh), '--verify-costs')
    assert verified.exit_code == 0, verified.output
    assert 'every cost agrees' in verified.output, verified.output


def test_the_undo_copy_a_delete_writes_states_them_in_that_order(tmp_path):
    """`delete-transactions -o` writes a ledger too, and it is an undo copy.

    The order the guids are typed in is not free: a cost basis cannot be
    deleted while a sale measures against it, so the fee is named first and
    the copy came out fee first — a file whose opening block gives the guid of
    a split no block above it creates, and whose split is gone from the book
    as well. Re-importing it to undo the delete was refused outright.

    And the balance the copy states is the second half of the same fault.
    Deleting the fee gives its 0.72 USD back to the deposit's cost basis, so
    the deposit written out after that stated 2720.00 — the whole of what it
    brought in — and a re-import trusting the file left the book offering
    currency the bank does not hold. Both transactions are written out before
    either is deleted now.
    """
    runner = CliRunner()
    book = a_deposit_and_a_fee_of_the_same_day(runner, tmp_path)

    backup = tmp_path / 'undo.txt'
    deleted = _run(runner, 'delete-transactions', str(book), '--by-guid',
                   FEE_TXN, DEPOSIT_TXN, '-o', str(backup))
    assert deleted.exit_code == 0, deleted.output

    written = re.findall(r'^\d{4}-\d\d-\d\d \* "([^"]*)"', backup.read_text(),
                         re.M)
    assert written == [DEPOSIT, FEE], written

    undone = _run(runner, 'import', str(book), str(backup))
    assert undone.exit_code == 0, undone.output
    assert re.search(r'Errors:\s+0$', undone.output, re.M), undone.output

    # And the book is back: the deposit's basis, less what the fee took.
    listing = _run(runner, 'fx-balances', str(book))
    assert listing.exit_code == 0, listing.output
    assert '2,719.28 USD' in listing.output, listing.output


def test_two_transactions_asked_for_by_guid_come_out_in_that_order(tmp_path):
    """`export-transaction` states them in the order it can read back.

    The guids are given in whatever order the caller types, and typing the
    fee first is the natural way to ask for it — it is the transaction the
    reader is looking at, and the deposit is what it draws on.
    """
    runner = CliRunner()
    book = a_deposit_and_a_fee_of_the_same_day(runner, tmp_path)

    out = tmp_path / 'two.txt'
    asked = _run(runner, 'export-transaction', str(book),
                 '--guid', FEE_TXN, '--guid', DEPOSIT_TXN, '-o', str(out))
    assert asked.exit_code == 0, asked.output

    written = re.findall(r'^\d{4}-\d\d-\d\d \* "([^"]*)"', out.read_text(),
                         re.M)
    assert written == [DEPOSIT, FEE], written

    fresh = tmp_path / 'fresh.gnucash'
    rebuilt = _run(runner, 'import', '--new', str(fresh), str(out))
    assert rebuilt.exit_code == 0, rebuilt.output
    assert re.search(r'Errors:\s+0$', rebuilt.output, re.M), rebuilt.output


def _a_basis_dated_after_the_fee_that_draws_on_it(runner, tmp_path):
    """The same two, with the fee dated the day before the deposit.

    An odd book, and one a person reaches by mistyping a date. The dates are
    not what settles which block a pick can name — the import applies them in
    the order the file states them — so the book is made the same way, from
    the same two fixtures.
    """
    book = tmp_path / 'book.gnucash'
    assert runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_two_usd_invoices_posted.txt',
        '--include-business-objects',
        '--fx-rates', RATES]).exit_code == 0
    assert _run(runner, 'import', str(book),
                'tests/fixtures/fx_usd_deposit_against_due_from_director.txt'
                ).exit_code == 0

    earlier = tmp_path / 'earlier.txt'
    earlier.write_text(
        Path('tests/fixtures/fx_fee_drawn_from_the_deposits_basis.txt')
        .read_text().replace('2026-08-13 * "Charges',
                             '2026-08-12 * "Charges'))
    imported = _run(runner, 'import', str(book), str(earlier))
    assert imported.exit_code == 0, imported.output
    return book


def test_a_basis_dated_after_the_fee_is_still_stated_above_it(tmp_path):
    """Which puts the file out of date order, and it reads back."""
    runner = CliRunner()
    book = _a_basis_dated_after_the_fee_that_draws_on_it(runner, tmp_path)

    out = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(out)).exit_code == 0
    written = re.findall(r'^(\d{4}-\d\d-\d\d) \* "([^"]*)"', out.read_text(),
                         re.M)
    assert ('2026-08-13', DEPOSIT) in written, written
    assert written.index(('2026-08-13', DEPOSIT)) < \
        written.index(('2026-08-12', FEE)), written

    fresh = tmp_path / 'fresh.gnucash'
    rebuilt = _run(runner, 'import', '--new', str(fresh), str(out))
    assert rebuilt.exit_code == 0, rebuilt.output


def test_the_running_balances_are_still_the_books_own_order(tmp_path):
    """A balance is a figure as at a date, whatever order the file states.

    The fee is dated 2026-08-12 and the deposit 2026-08-13, so the USD bank
    holds -0.72 after the fee and 2719.28 after the deposit — even though the
    deposit is written above the fee. Added up in the file's order instead,
    the fee's row would read the closing 2719.28 and the deposit's row the
    2720.00 that stood before the fee ever happened.
    """
    runner = CliRunner()
    book = _a_basis_dated_after_the_fee_that_draws_on_it(runner, tmp_path)

    out = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(out), '--with-balance'
                ).exit_code == 0
    text = out.read_text()
    fee_block = re.search(r'2026-08-12 \* "Charges[^\n]*\n(?:\t[^\n]*\n)*',
                          text).group(0)
    deposit_block = re.search(r'2026-08-13 \* "Received[^\n]*\n(?:\t[^\n]*\n)*',
                              text).group(0)
    assert 'balance: "-0.72 USD"' in fee_block, fee_block
    assert 'balance: "2719.28 USD"' in deposit_block, deposit_block


def _a_book_whose_two_transactions_draw_on_each_other(runner, tmp_path):
    """The same book, with the deposit made to draw on the fee as well.

    Nothing this tool does writes that: a pick is taken from a file, and a
    file naming this pair would be refused for the same reason its export
    cannot be read back. It is written into the book directly, which is how
    a book carrying it would arrive.
    """
    book = a_deposit_and_a_fee_of_the_same_day(runner, tmp_path)
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        for split in iter_splits(repo.book):
            if split_guid(split) != DEPOSIT_SPLIT:
                continue
            transaction = split.GetParent()
            transaction.BeginEdit()
            metadata = get_custom_metadata(split)
            metadata['cost_basis_split_guid'] = FEE_SPLIT
            set_custom_metadata(split, metadata)
            transaction.CommitEdit()
    finally:
        repo.save()
        repo.close()

    # Read back, because a slot written outside `BeginEdit`/`CommitEdit` is
    # kept for the rest of the session and lost on save — CLAUDE.md finding
    # 11 — and a test that did not check would pass on a book with no cycle
    # in it at all.
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        stored = {split_guid(split):
                  get_custom_metadata(split).get('cost_basis_split_guid')
                  for split in iter_splits(repo.book)}
    finally:
        repo.close()
    assert stored.get(DEPOSIT_SPLIT) == FEE_SPLIT, stored
    assert stored.get(FEE_SPLIT) == DEPOSIT_SPLIT, stored
    return book


def test_neither_is_dropped_when_the_two_draw_on_each_other(tmp_path):
    """There is no order that reads back, and the book's own is written.

    Every transaction the book holds is in the file — which order the two are
    in is not asserted, because the book's own order decides it and these two
    were entered a moment apart. What the file cannot do is rebuild the book:
    whichever of the two is written first states a guid the other has not
    created yet, and that is a property of the book rather than of the order
    chosen for it.
    """
    runner = CliRunner()
    book = _a_book_whose_two_transactions_draw_on_each_other(runner, tmp_path)

    out = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(out)).exit_code == 0
    written = re.findall(r'^\d{4}-\d\d-\d\d \* "([^"]*)"', out.read_text(),
                         re.M)
    assert sorted(written) == sorted(
        ['INV-USD-001', FEE, DEPOSIT, 'INV-USD-002']), written

    fresh = tmp_path / 'fresh.gnucash'
    refused = _run(runner, 'import', '--new', str(fresh), str(out))
    message = refused.output + str(refused.exception)
    assert refused.exit_code != 0, message
    assert 'matches no split in the book' in message, message
