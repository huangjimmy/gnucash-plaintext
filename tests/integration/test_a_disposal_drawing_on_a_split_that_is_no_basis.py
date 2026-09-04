"""`--verify-costs` reports a disposal that draws on a split which is no basis.

The other half of the same fault. A link can leave a split holding a
`cost_basis_balance` it can no longer justify — reported already — and clearing
that balance leaves the disposal below it still giving that split's guid in
`cost_basis_split_guid:`. Nothing is stored where nothing reads it any more, so
the balance check is silent, and the book reads clean while a disposal is
measured against something that is not a cost basis.

It shows up on the way out: the export writes the guid, and re-importing that
ledger is refused with "matches a split that is no USD cost basis". A book
whose own export cannot rebuild it should not be reported as sound.
"""

import re
import time
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import iter_splits, split_guid

RATES = 'tests/fixtures/fx_rates_usd_two_invoice_dates.yaml'
DEPOSIT_SPLIT = '00e958a8d56547d484d7629000292dc3'


def _run(runner, *args):
    time.sleep(1.1)
    return runner.invoke(cli, list(args))


def _block_for(text, opening):
    return re.search(rf'{re.escape(opening)}[^\n]*\n(?:\t[^\n]*\n)*', text).group(0)


def _a_fee_drawing_on_a_split_that_is_no_basis(runner, tmp_path):
    """Two invoices, a deposit, a fee drawn on the deposit — then the CAD side
    taken away and the stranded balance cleared.

    What is left is a fee giving a guid that is no cost basis, and nothing
    else wrong that any existing check can see.
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
    assert _run(runner, 'import', str(book),
                'tests/fixtures/fx_fee_drawn_from_the_deposits_basis.txt'
                ).exit_code == 0

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        for split in iter_splits(repo.book):
            if split_guid(split) != DEPOSIT_SPLIT:
                continue
            account = split.GetAccount()
            transaction = split.GetParent()
            transaction.BeginEdit()
            for other in transaction.GetSplitList():
                if split_guid(other) != DEPOSIT_SPLIT:
                    other.SetAccount(account)
            transaction.SetCurrency(account.GetCommodity())
            transaction.CommitEdit()
    finally:
        repo.save()
        repo.close()

    out = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(out)).exit_code == 0
    clear = tmp_path / 'clear.txt'
    clear.write_text(re.sub(r'\t\tcost_basis_balance: "[^"]*"\n',
                            '\t\tcost_basis_balance: ""\n',
                            _block_for(out.read_text(),
                                       '2026-08-13 * "Received')))
    assert _run(runner, 'import', str(book), str(clear),
                '--strategy', 'update').exit_code == 0
    return book


def test_the_disposal_is_reported(tmp_path):
    runner = CliRunner()
    book = _a_fee_drawing_on_a_split_that_is_no_basis(runner, tmp_path)

    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    message = verified.output
    assert verified.exit_code == 1, message
    assert DEPOSIT_SPLIT in message, message
    assert 'no cost basis' in message, message
    # And it says why that split is not one, as the balance finding does.
    assert 'every split in its transaction is USD' in message, message


def test_the_export_of_that_book_does_not_re_import(tmp_path):
    """Which is what the finding is warning about."""
    runner = CliRunner()
    book = _a_fee_drawing_on_a_split_that_is_no_basis(runner, tmp_path)

    out = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(out)).exit_code == 0
    fresh = tmp_path / 'fresh.gnucash'
    result = _run(runner, 'import', '--new', str(fresh), str(out))
    message = result.output + str(result.exception)
    assert result.exit_code != 0, message
    assert 'no USD cost basis' in message, message


def test_a_sound_book_is_not_reported(tmp_path):
    """A disposal drawing on a real cost basis says nothing."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_buy_and_borrow_usd.txt'])
    assert result.exit_code == 0, result.output

    out = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(out)).exit_code == 0
    basis = re.findall(
        r'Assets:Bank:USD 100\.00 USD\n\t+guid: "([0-9a-f]{32})"',
        out.read_text())[0]
    sale = tmp_path / 'sale.txt'
    sale.write_text(
        Path('tests/fixtures/fx_sell_usd_partial.txt')
        .read_text().replace('{basis_a}', basis))
    assert _run(runner, 'import', str(book), str(sale)).exit_code == 0

    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 0, verified.output
    assert 'every cost agrees' in verified.output, verified.output
