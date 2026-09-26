"""Q-040: a book an older version left wrong is repaired as one file under `--atomic`, or in two runs.

Repairing it takes two changes:

* clear the deposit's balance, which alone leaves the fee below it drawing on
  a split that is no cost basis;
* re-point the fee at the receivable's cost basis.

Re-pointing the fee first was refused until Q-051, because an edit in place
could not change what a disposal draws on. It is now read as a new
transaction would be — what it drew is put back and it draws afresh — so
re-pointing it and then clearing the balance repairs the book in two runs.
`--atomic` applies both in one, and reads the book it left before saving it.

Everything the guards protected is still asked, which the refusal tests below
hold in place — a file may not use this to leave a book that does not add up.
"""

import re

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.kvp import get_custom_metadata
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import (
    COST_BASIS_BALANCE_KEY,
    iter_splits,
    split_guid,
)
from tests.conftest import _run

RATES = 'tests/fixtures/fx_rates_usd_two_invoice_dates.yaml'
DEPOSIT_SPLIT = '00e958a8d56547d484d7629000292dc3'


def _stored_balance(book, guid):
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        for split in iter_splits(repo.book):
            if split_guid(split) == guid:
                return get_custom_metadata(split).get(COST_BASIS_BALANCE_KEY)
    finally:
        repo.close()
    return None


def _block_for(text, opening):
    return re.search(rf'{re.escape(opening)}[^\n]*\n(?:\t[^\n]*\n)*', text).group(0)


def _stranded(runner, book):
    """A deposit priced, a fee drawn on it, and then the price taken away.

    What the link used to leave. Built by importing each part as it was
    written and then doing to the book what the link did — the link itself now
    refuses this, which is the fix, so a book in this state can only be one an
    earlier version wrote.
    """
    result = runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_two_usd_invoices_posted.txt',
        '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output
    assert _run(runner, 'import', str(book),
                'tests/fixtures/fx_usd_deposit_against_due_from_director.txt'
                ).exit_code == 0
    assert _run(runner, 'import', str(book),
                'tests/fixtures/fx_fee_drawn_from_the_deposits_basis.txt'
                ).exit_code == 0

    from gnucash import Query

    from infrastructure.gnucash.utils import find_account, wrap_invoice_or_bill
    from services.gnucash_importer import _attach_split_to_lot

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        receivable = find_account(repo.book.get_root_account(),
                                  'Assets:Current assets:Accounts receivable:USD')
        query = Query()
        query.search_for('gncInvoice')
        query.set_book(repo.book)
        lot = next(wrap_invoice_or_bill(raw).GetPostedLot() for raw in query.run()
                   if wrap_invoice_or_bill(raw).GetID() == 'INV-USD-001')
        query.destroy()

        deposit = next(split for split in iter_splits(repo.book)
                       if split_guid(split) == DEPOSIT_SPLIT)
        transaction = deposit.GetParent()
        counter = next(split for split in transaction.GetSplitList()
                       if split_guid(split) != DEPOSIT_SPLIT)
        settled = deposit.GetAmount().neg()
        transaction.BeginEdit()
        counter.SetAccount(receivable)
        counter.SetAmount(settled)
        counter.SetValue(settled)
        transaction.SetCurrency(deposit.GetAccount().GetCommodity())
        transaction.CommitEdit()
        _attach_split_to_lot(counter, lot)
    finally:
        repo.save()
        repo.close()


def _the_repair(runner, book, tmp_path):
    """The end state, stated: three blocks that only make sense together.

    The deposit loses its balance, the invoice's posting split takes on
    what the fee will have drawn from it, and the fee draws on that cost basis
    instead. Each balance is what it should be when the file has landed, which
    is what a stated balance means — net of the file's own disposals — and is
    why the third block does not lower the second's figure a second time.
    """
    exported = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(exported)).exit_code == 0
    text = exported.read_text()
    ar_basis = re.search(
        r'Assets:Current assets:Accounts receivable:USD 2720\.00 USD\n'
        r'\t+guid: "([0-9a-f]{32})"', text).group(1)

    deposit = re.sub(r'\t\tcost_basis_balance: "[^"]*"\n',
                     '\t\tcost_basis_balance: ""\n',
                     _block_for(text, '2026-08-13 * "Received'))
    posting = _block_for(text, '2026-07-31 * "INV-USD-001"').replace(
        'cost_basis_balance: "2720.00"', 'cost_basis_balance: "2719.28"')
    assert '2719.28' in posting, posting
    fee = _block_for(text, '2026-08-13 * "Charges').replace(DEPOSIT_SPLIT,
                                                            ar_basis)
    repair = tmp_path / 'repair.txt'
    repair.write_text(posting + deposit + fee)
    return repair, ar_basis


def test_re_pointing_the_fee_and_then_clearing_the_balance_repairs_it_in_two_runs(tmp_path):
    """Since Q-051 the fee's edit is read as a new transaction would be.

    What it drew is put back on the deposit's cost basis, and its 0.72 USD
    comes off the receivable's, where the money it spent is. The deposit's
    balance, 2,720.00 on a split that is no cost basis, is what
    `--verify-costs` reports until it is cleared, and clearing it finishes the
    repair.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _stranded(runner, book)

    exported = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(exported)).exit_code == 0
    text = exported.read_text()
    ar_basis = re.search(
        r'Assets:Current assets:Accounts receivable:USD 2720\.00 USD\n'
        r'\t+guid: "([0-9a-f]{32})"', text).group(1)

    repoint = tmp_path / 'repoint.txt'
    repoint.write_text(
        _block_for(text, '2026-08-13 * "Charges').replace(DEPOSIT_SPLIT, ar_basis))
    moved = _run(runner, 'import', str(book), str(repoint), '--strategy', 'update')
    assert moved.exit_code == 0, moved.output
    assert _stored_balance(book, ar_basis) == '2719.28'
    assert _stored_balance(book, DEPOSIT_SPLIT) == '2720.00'
    still_wrong = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert still_wrong.exit_code == 1, still_wrong.output
    assert DEPOSIT_SPLIT in still_wrong.output, still_wrong.output

    clear = tmp_path / 'clear.txt'
    clear.write_text(re.sub(r'\t\tcost_basis_balance: "[^"]*"\n',
                            '\t\tcost_basis_balance: ""\n',
                            _block_for(text, '2026-08-13 * "Received')))
    assert _run(runner, 'import', str(book), str(clear),
                '--strategy', 'update').exit_code == 0

    assert _stored_balance(book, DEPOSIT_SPLIT) is None
    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 0, verified.output


def test_clearing_the_balance_first_leaves_the_fee_drawing_on_no_cost_basis(tmp_path):
    """The other order, which the finished book still reports."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _stranded(runner, book)

    exported = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(exported)).exit_code == 0
    text = exported.read_text()

    # Clearing the balance on its own is allowed, and leaves the fee drawing
    # on a split that is now no cost basis. The stranded balance the other
    # check would have found is exactly what was just removed, so what reports
    # this half-repair is the disposal check rather than the balance one.
    clear = tmp_path / 'clear.txt'
    clear.write_text(re.sub(r'\t\tcost_basis_balance: "[^"]*"\n',
                            '\t\tcost_basis_balance: ""\n',
                            _block_for(text, '2026-08-13 * "Received')))
    assert _run(runner, 'import', str(book), str(clear),
                '--strategy', 'update').exit_code == 0

    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 1, verified.output
    assert DEPOSIT_SPLIT in verified.output, verified.output
    assert 'no cost basis' in verified.output, verified.output

    # And the book's own export no longer re-imports, which is the state this
    # half-repair leaves behind.
    half = tmp_path / 'half.txt'
    assert _run(runner, 'export', str(book), str(half)).exit_code == 0
    assert f'cost_basis_split_guid: "{DEPOSIT_SPLIT}"' in half.read_text()


def test_restating_the_balance_the_book_holds_beside_the_repair(tmp_path):
    """2,720.00 on the receivable, as the book already holds it: the fee draws its 0.72 from it.

    A figure an update restates as the book holds it states nothing new, so
    it is not read as a balance the file states net of its own disposals
    (Q-051) — an export restates every balance, and an owner editing one
    transaction of it would otherwise have the rest of the export tell the
    edit's draws to leave those balances alone. The repair's fee is read as a
    new transaction would be, draws 0.72 USD from the receivable, and the
    book is level.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _stranded(runner, book)

    exported = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(exported)).exit_code == 0
    text = exported.read_text()
    ar_basis = re.search(
        r'Assets:Current assets:Accounts receivable:USD 2720\.00 USD\n'
        r'\t+guid: "([0-9a-f]{32})"', text).group(1)
    deposit = re.sub(r'\t\tcost_basis_balance: "[^"]*"\n',
                     '\t\tcost_basis_balance: ""\n',
                     _block_for(text, '2026-08-13 * "Received'))
    posting = _block_for(text, '2026-07-31 * "INV-USD-001"')
    assert 'cost_basis_balance: "2720.00"' in posting, posting
    fee = _block_for(text, '2026-08-13 * "Charges').replace(DEPOSIT_SPLIT,
                                                            ar_basis)
    gross = tmp_path / 'gross.txt'
    gross.write_text(posting + deposit + fee)

    result = _run(runner, 'import', str(book), str(gross),
                  '--strategy', 'update', '--atomic')
    assert result.exit_code == 0, result.output
    assert 'Changes saved' in result.output, result.output

    assert _stored_balance(book, ar_basis) == '2719.28'
    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 0, verified.output
    assert 'Nothing is refused' not in verified.output, verified.output


def test_the_repair_commits_under_atomic(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _stranded(runner, book)
    repair, ar_basis = _the_repair(runner, book, tmp_path)

    result = _run(runner, 'import', str(book), str(repair),
                  '--strategy', 'update', '--atomic')
    assert result.exit_code == 0, result.output
    assert 'Changes saved' in result.output, result.output

    assert _stored_balance(book, DEPOSIT_SPLIT) is None
    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 0, verified.output
    assert 'every cost agrees' in verified.output, verified.output
    assert 'accounts hold' not in verified.output, verified.output

    exported = _run(runner, 'export', str(book), str(tmp_path / 'final.txt'))
    assert exported.exit_code == 0, exported.output
    text = (tmp_path / 'final.txt').read_text()
    assert ar_basis in text, text
    assert f'cost_basis_split_guid: "{DEPOSIT_SPLIT}"' not in text, text


def test_half_the_repair_commits_and_is_still_reported(tmp_path):
    """The half that moves the fee lands; the balance it leaves is still wrong.

    Re-pointing the fee without clearing the deposit's balance leaves the
    deposit offering 2,719.28 USD that no account holds. That shows up in the
    per-currency totals, which `--verify-costs` prints as a warning and says
    on the page it refuses nothing over — so it is not what an `--atomic` run
    throws a file away for, and this file commits.

    A book with a divided credit cannot level those totals at all, the arrived
    side counting what a remainder holds while the sale that drew on the pool
    is still the size it was, so a rollback on them would refuse ordinary work.
    What the gate does refuse is pinned by
    `test_a_repriced_basis_is_caught_under_its_sales.py::
    test_an_atomic_reprice_is_rolled_back`, where every block applies and the
    finished book is what refuses the file.

    The stranded balance is not lost sight of: it was there before this file
    and `--verify-costs` goes on reporting it afterwards.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _stranded(runner, book)

    exported = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(exported)).exit_code == 0
    text = exported.read_text()
    ar_basis = re.search(
        r'Assets:Current assets:Accounts receivable:USD 2720\.00 USD\n'
        r'\t+guid: "([0-9a-f]{32})"', text).group(1)
    half = tmp_path / 'half.txt'
    half.write_text(
        _block_for(text, '2026-08-13 * "Charges').replace(DEPOSIT_SPLIT, ar_basis))

    result = _run(runner, 'import', str(book), str(half),
                  '--strategy', 'update', '--atomic')
    assert result.exit_code == 0, result.output
    assert 'Changes saved' in result.output, result.output
    assert 'Rolled back' not in result.output, result.output

    still_wrong = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert still_wrong.exit_code == 1, still_wrong.output
    assert DEPOSIT_SPLIT in still_wrong.output, still_wrong.output
