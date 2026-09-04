"""Q-040: getting a book that was linked by an earlier version back in order.

A link used to move the split that priced a USD deposit and leave the
deposit's basis balance written on it: unlisted, unreadable, and still given by
any disposal that had drawn on it. Books in that state exist, and this is how
they come out of it.

Two shapes, and which one a book is in decides the work:

* nothing drew on the stranded basis — one file clears it;
* something did — the disposal has to be deleted first, because re-pointing it
  in place is refused and would re-price it besides.

`--verify-costs` is what says which shape a book is in, and prints the split's
guid.
"""

import re
import time
from pathlib import Path

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
BANK = ('Assets:Current assets:Cash and deposits:Deposits in Canadian banks '
        'and institutions – Foreign currency:Foreign Payments Provider '
        'Chequing 000000000000001')
DEPOSIT_SPLIT = '00e958a8d56547d484d7629000292dc3'
FEE_TX = '10379c8ab37547b8b7c8dbebca45d3e3'


def _run(runner, *args):
    time.sleep(1.1)
    return runner.invoke(cli, list(args))


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


def _linked_by_the_old_version(runner, book, with_fee):
    """A book in the state the old link left: a borrowing that stopped being one.

    Built by importing the deposit as it was written, drawing the fee against
    it where the shape calls for one, and then taking the transaction's
    base-currency figure away — which is what replacing the counter split did.
    Nothing is mocked; the book is one GnuCash loads.
    """
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

    _link_the_old_way(book)


def _link_the_old_way(book_path):
    """Do to the book exactly what the old link did, and no more.

    The counter split is moved onto the receivable and into the invoice's lot
    — so the invoice reads as paid, which it must, or the recovery below
    would be refused for selling against an invoice nobody has paid — and the
    transaction is left stated in the deposit's own currency, which is what
    takes the price off it. The balance stays where it was.

    Done here rather than by running the link, because the link no longer does
    it: with a disposal drawing on the deposit's basis it is refused outright,
    which is the whole point of the fix. A book in this state can only be one
    an earlier version wrote.
    """
    from gnucash import Query

    from infrastructure.gnucash.utils import (
        find_account,
        get_account_full_name,
        wrap_invoice_or_bill,
    )
    from services.gnucash_importer import _attach_split_to_lot

    repo = GnuCashRepository(str(book_path))
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
        # Restated, as the link restates it: a split on an account of another
        # currency holds a figure that is not the settlement, so
        # moving it alone would book 3,815.89 against the receivable as USD.
        settled = deposit.GetAmount().neg()
        transaction.BeginEdit()
        counter.SetAccount(receivable)
        counter.SetAmount(settled)
        counter.SetValue(settled)
        transaction.SetCurrency(deposit.GetAccount().GetCommodity())
        transaction.CommitEdit()
        _attach_split_to_lot(counter, lot)
        assert get_account_full_name(counter.GetAccount()).endswith('USD')
    finally:
        repo.save()
        repo.close()


def _block_for(text, opening):
    return re.search(rf'{re.escape(opening)}[^\n]*\n(?:\t[^\n]*\n)*', text).group(0)


def test_verify_costs_says_which_split_to_correct(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _linked_by_the_old_version(runner, book, with_fee=False)

    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 1, verified.output
    assert DEPOSIT_SPLIT in verified.output, verified.output
    assert 'no cost basis' in verified.output, verified.output


def test_a_stranded_balance_nothing_drew_on_is_cleared_in_one_file(tmp_path):
    """`cost_basis_balance: ""` takes the figure off, and that is the whole fix.

    The receivable's posting split is then the single basis for that money,
    which is where the link should have left the book.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _linked_by_the_old_version(runner, book, with_fee=False)
    assert _stored_balance(book, DEPOSIT_SPLIT) == '2720.00'

    exported = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(exported)).exit_code == 0
    deposit = _block_for(exported.read_text(), '2026-08-13 * "Received')
    clear = tmp_path / 'clear.txt'
    clear.write_text(deposit.replace('\t\tcost_basis_balance: "2720.00"\n',
                                     '\t\tcost_basis_balance: ""\n'))
    assert 'cost_basis_balance: ""' in clear.read_text(), clear.read_text()

    result = _run(runner, 'import', str(book), str(clear),
                  '--strategy', 'update')
    assert result.exit_code == 0, result.output
    assert _stored_balance(book, DEPOSIT_SPLIT) is None

    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 0, verified.output
    assert 'every cost agrees' in verified.output, verified.output
    assert 'accounts hold' not in verified.output, verified.output


def test_a_disposal_must_be_deleted_before_the_balance_can_be_cleared(tmp_path):
    """Re-pointing it in place is refused, so it is deleted and written again.

    Deleting gives the stranded basis back what the disposal took, the balance
    is then cleared, and the disposal is imported again measured against the
    receivable's basis — where the money it spent actually is.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _linked_by_the_old_version(runner, book, with_fee=True)
    assert _stored_balance(book, DEPOSIT_SPLIT) == '2719.28'

    exported = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(exported)).exit_code == 0
    text = exported.read_text()
    ar_basis = re.search(
        r'Assets:Current assets:Accounts receivable:USD 2720\.00 USD\n'
        r'\t+guid: "([0-9a-f]{32})"', text).group(1)

    # Re-pointing in place: refused, and the refusal spells out what to do
    # instead.
    fee_block = _block_for(text, '2026-08-13 * "Charges')
    repoint = tmp_path / 'repoint.txt'
    repoint.write_text(fee_block.replace(DEPOSIT_SPLIT, ar_basis))
    refused = _run(runner, 'import', str(book), str(repoint),
                   '--strategy', 'update')
    assert refused.exit_code != 0, refused.output
    assert 'delete-transactions' in refused.output, refused.output

    # What to do instead.
    dropped = _run(runner, 'delete-transactions', str(book), FEE_TX,
                   '--by-guid', '-o', str(tmp_path / 'deleted.txt'))
    assert dropped.exit_code == 0, dropped.output

    deposit = _block_for(text, '2026-08-13 * "Received')
    clear = tmp_path / 'clear.txt'
    clear.write_text(re.sub(r'\t\tcost_basis_balance: "[^"]*"\n',
                            '\t\tcost_basis_balance: ""\n', deposit))
    result = _run(runner, 'import', str(book), str(clear),
                  '--strategy', 'update')
    assert result.exit_code == 0, result.output
    assert _stored_balance(book, DEPOSIT_SPLIT) is None

    again = tmp_path / 'again.txt'
    again.write_text(
        Path('tests/fixtures/fx_fee_drawn_from_the_deposits_basis.txt')
        .read_text().replace(DEPOSIT_SPLIT, ar_basis))
    result = _run(runner, 'import', str(book), str(again))
    assert result.exit_code == 0, result.output

    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 0, verified.output
    assert 'every cost agrees' in verified.output, verified.output
    assert 'accounts hold' not in verified.output, verified.output
