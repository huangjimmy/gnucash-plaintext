"""Re-pricing a cost basis is caught by the sales already measured against it.

`_require_stated_cost` asks of every sale in a file that it values what it sells
at what its basis cost. It asks it of the file, and only of the file, so a sale
already in the book is never asked again — and `import --atomic` defers
`_require_no_cost_basis_edit`, which is what otherwise stops a block restating a
basis transaction's `value:`.

So a basis can be re-priced under sales that are in no file. Every other check
is satisfied: the balance is inside its bounds, no stored cost disagrees because
there is none to disagree, the sale draws on a real basis, and the currency
totals level, because none of them looks at what the sale is valued at. The book
is saved, `--verify-costs` says every cost agrees, and the export is refused on
the way back in.

`what_the_disposals_get_wrong` asks it of the book instead, which is the only
place it can be asked of a sale nobody is importing.
"""

import re
import time
from pathlib import Path

from click.testing import CliRunner
from gnucash import GncNumeric

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import iter_splits, split_commodity

RATES = 'tests/fixtures/fx_rates_usd_dated.yaml'

def _run(runner, *args):
    time.sleep(1.1)
    return runner.invoke(cli, list(args))


def _a_basis_with_a_fee_drawn_on_it(runner, tmp_path):
    """100.00 USD bought at 1.40, with a 10.00 USD fee valued against it."""
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_buy_100_usd_into_a_usd_bank.txt',
        '--fx-rates', RATES])
    assert result.exit_code == 0, result.output

    out = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(out)).exit_code == 0
    basis = re.search(
        r'Assets:Bank:USD 100\.00 USD\n\t+guid: "([0-9a-f]{32})"',
        out.read_text()).group(1)

    fee = tmp_path / 'fee.txt'
    fee.write_text(
        Path('tests/fixtures/fx_fee_drawn_from_the_purchase.txt').read_text()
        .replace('{basis}', basis))
    assert _run(runner, 'import', str(book), str(fee),
                '--fx-rates', RATES).exit_code == 0
    return book


def _a_block_repricing_the_purchase(runner, book, tmp_path):
    """The purchase restated at 1.50, which the fee below it was not valued at."""
    out = tmp_path / 'before.txt'
    assert _run(runner, 'export', str(book), str(out)).exit_code == 0
    block = re.search(r'2026-02-01 \* "Buy 100 USD"[^\n]*\n(?:\t[^\n]*\n)*',
                      out.read_text()).group(0)
    # The export writes the rate at four decimals, so both spellings are
    # rewritten: a block stating a new value beside the old rate is a
    # contradiction the importer resolves in favour of the rate, and the
    # reprice silently does not happen.
    block = (block.replace('share_price: "1.4000"', 'share_price: "1.5000"')
                  .replace('share_price: "1.40"', 'share_price: "1.50"')
                  .replace('value: "140.00"', 'value: "150.00"')
                  .replace('-140.00 CAD', '-150.00 CAD')
                  .replace('value: "-140.00"', 'value: "-150.00"'))
    assert '1.5000' in block or '1.50' in block, block
    repriced = tmp_path / 'repriced.txt'
    repriced.write_text(block)
    return repriced


def _a_basis_with_a_usd_stated_fee_drawn_on_it(runner, tmp_path):
    """The same purchase, with the fee below it stated in USD.

    Its value is in no base-currency figure, so the finished book cannot ask
    whether it is still valued at what its basis cost — which is what
    `--atomic` leans on when it defers the in-place refusal.
    """
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_buy_100_usd_into_a_usd_bank.txt',
        '--fx-rates', RATES])
    assert result.exit_code == 0, result.output

    out = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(out)).exit_code == 0
    basis = re.search(
        r'Assets:Bank:USD 100\.00 USD\n\t+guid: "([0-9a-f]{32})"',
        out.read_text()).group(1)

    fee = tmp_path / 'fee.txt'
    fee.write_text(
        Path('tests/fixtures/fx_fee_stated_in_usd_drawn_from_the_purchase.txt')
        .read_text().replace('{basis}', basis))
    result = _run(runner, 'import', str(book), str(fee), '--fx-rates', RATES)
    assert result.exit_code == 0, result.output
    return book


def test_a_reprice_under_a_foreign_stated_sale_is_refused(tmp_path):
    """`--atomic` defers this refusal to a question that cannot be asked here.

    The commit-time stand-in is `a_sale_valued_against_another_cost`, and it
    answers only for a sale stated in the book's own currency: a transaction
    between two foreign currencies states its values in neither. So a basis
    with only foreign-stated sales beneath it could be re-priced under them,
    the run exited 0, the book was saved, and `--verify-costs` called it
    sound — the same fault this file is about, with the fee stated in USD.

    So the deferral is refused where the finished book cannot stand in, and
    the reader is told which disposal makes it so.
    """
    runner = CliRunner()
    book = _a_basis_with_a_usd_stated_fee_drawn_on_it(runner, tmp_path)
    repriced = _a_block_repricing_the_purchase(runner, book, tmp_path)

    result = _run(runner, 'import', str(book), str(repriced), '--atomic',
                  '--strategy', 'update', '--fx-rates', RATES)
    message = result.output + str(result.exception)
    assert result.exit_code != 0, message
    assert 'Changes saved' not in result.output, result.output
    assert 'A 10 USD fee, stated in USD' in message, message

    # And the book is as it was: 1.4, with 90.00 USD left of the basis.
    listing = _run(runner, 'fx-balances', str(book)).output
    assert '1.4 CAD/USD' in listing, listing
    assert '90.00 USD' in listing, listing


def test_the_book_starts_sound(tmp_path):
    runner = CliRunner()
    book = _a_basis_with_a_fee_drawn_on_it(runner, tmp_path)
    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 0, verified.output


def test_repricing_it_in_place_is_refused_without_the_flag(tmp_path):
    """The per-block guard, which is what `--atomic` defers."""
    runner = CliRunner()
    book = _a_basis_with_a_fee_drawn_on_it(runner, tmp_path)
    repriced = _a_block_repricing_the_purchase(runner, book, tmp_path)

    result = _run(runner, 'import', str(book), str(repriced),
                  '--strategy', 'update', '--fx-rates', RATES)
    message = result.output + str(result.exception)
    assert 'cannot be edited in place' in message, message


def test_an_atomic_reprice_is_rolled_back(tmp_path):
    """Deferred to commit time, and the finished book is what refuses it."""
    runner = CliRunner()
    book = _a_basis_with_a_fee_drawn_on_it(runner, tmp_path)
    repriced = _a_block_repricing_the_purchase(runner, book, tmp_path)

    result = _run(runner, 'import', str(book), str(repriced), '--atomic',
                  '--strategy', 'update', '--fx-rates', RATES)
    assert result.exit_code != 0, result.output
    assert 'Rolled back' in result.output, result.output
    assert 'Changes saved' not in result.output, result.output
    assert 'value what is sold at the basis it picks' in result.output, \
        result.output
    # Every block applied, so the run reaches the end with no per-block error
    # to its name — which is the shape that printed a tick under the refusal.
    assert '✓ Nothing to import' not in result.output, result.output

    # And the book is as it was.
    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 0, verified.output


def test_a_dry_run_of_the_same_reprice_says_the_same(tmp_path):
    """A dry run applies the file in memory and reaches the same answer.

    Its own sign-off is the one to withhold here: no block failed, so the arm
    that prints `✓ Dry run` is the one this reaches, and a file the finished
    book refuses must not be reported as one that would have gone in.
    """
    runner = CliRunner()
    book = _a_basis_with_a_fee_drawn_on_it(runner, tmp_path)
    repriced = _a_block_repricing_the_purchase(runner, book, tmp_path)

    result = _run(runner, 'import', str(book), str(repriced), '--atomic',
                  '--dry-run', '--strategy', 'update', '--fx-rates', RATES)
    assert result.exit_code != 0, result.output
    assert 'Rolled back' in result.output, result.output
    assert '✓ Dry run' not in result.output, result.output
    assert 'Changes saved' not in result.output, result.output

    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 0, verified.output


def test_verify_costs_reports_a_book_already_re_priced(tmp_path):
    """A book already in that state, which is how one arrives without `--atomic`.

    Nothing this tool does now writes it — the per-block guard refuses the edit
    and `--atomic` rolls the run back — so the state is reached the way a book
    from before those guards reached it: the figures are written straight into
    the book. That is the book a user brings, and until this check it read as
    sound. Every other question passes: the balance is within its bounds, no
    stored cost disagrees because there is none, and the fee draws on a real
    cost basis.
    """
    runner = CliRunner()
    book = _a_basis_with_a_fee_drawn_on_it(runner, tmp_path)
    assert _run(runner, 'fx-balances', str(book),
                '--verify-costs').exit_code == 0

    # 100.00 USD bought for 140.00 CAD, restated as bought for 150.00.
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        for split in iter_splits(repo.book):
            transaction = split.GetParent()
            if transaction.GetDescription() != 'Buy 100 USD':
                continue
            transaction.BeginEdit()
            for each in transaction.GetSplitList():
                # The value on both sides, and the amount on the CAD side too:
                # that account is kept in the transaction's own currency, so
                # its amount and value are the same figure, and moving one
                # alone says 140.00 CAD is worth 150.00.
                usd = split_commodity(each) == 'USD'
                figure = GncNumeric(15000 if usd else -15000, 100)
                each.SetValue(figure)
                if not usd:
                    each.SetAmount(figure)
            transaction.CommitEdit()
    finally:
        repo.save()
        repo.close()

    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 1, verified.output
    assert '10.00 USD valued at' in verified.output, verified.output
    assert '15.00 CAD' in verified.output, verified.output
    assert 'value what is sold at the basis it picks' in verified.output, \
        verified.output


def test_the_re_priced_books_export_does_not_re_import(tmp_path):
    """Which is what the check is warning about."""
    runner = CliRunner()
    book = _a_basis_with_a_fee_drawn_on_it(runner, tmp_path)
    repriced = _a_block_repricing_the_purchase(runner, book, tmp_path)
    # Without `--atomic` the per-block guard refuses it, which is the state
    # this book must not reach by any ordinary route.
    refused = _run(runner, 'import', str(book), str(repriced),
                   '--strategy', 'update', '--fx-rates', RATES)
    assert refused.exit_code != 0, refused.output
