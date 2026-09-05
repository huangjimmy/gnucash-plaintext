"""`import --atomic` commits a file or rolls it back, like a database.

An ordinary import keeps the blocks that worked and reports the rest. That is
right for a bank feed — a statement of two hundred lines should not be thrown
away over one account nobody has opened yet — and wrong for a correction, whose
blocks are parts of one change. Half a correction applied leaves a book in a
state nobody chose, and the reader then has to work out which half landed.

Q-040 is where this was measured. Repairing a cost basis an old link left
behind takes a change to the deposit and a change to the disposal that drew on
it, and the file with both in it kept the first and refused the second, at exit
1, with `Saving changes… ✓ Changes saved` in between.

The cost-basis questions asked at commit time are asked of the book before the
file is read as well, and only what the file *adds* is a reason to roll back.
A book being repaired is often wrong somewhere else too, and a fault the file
neither caused nor claimed to fix must not stop it landing — that would leave
the damaged book unable to accept any import at all.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import iter_splits, split_guid
from tests.conftest import _run

ACCOUNTS = 'tests/fixtures/an_atomic_run_accounts.txt'
# The second posts to an account the book has not got.
ONE_GOOD_ONE_BAD = 'tests/fixtures/an_atomic_run_one_good_one_bad.txt'
BOTH_GOOD = 'tests/fixtures/an_atomic_run_both_good.txt'
A_THIRD_GOOD_ONE = 'tests/fixtures/an_atomic_run_a_third_good_one.txt'
AN_ORDINARY_CAD_EXPENSE = 'tests/fixtures/an_ordinary_cad_expense.txt'


def _book(runner, tmp_path):
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(book), ACCOUNTS])
    assert result.exit_code == 0, result.output
    return book


def _exported(runner, book, path):
    result = _run(runner, 'export', str(book), str(path))
    assert result.exit_code == 0, result.output
    return path.read_text()


def test_without_the_flag_the_good_one_is_kept(tmp_path):
    """The behaviour a bank feed wants, unchanged."""
    runner = CliRunner()
    book = _book(runner, tmp_path)

    result = _run(runner, 'import', str(book), ONE_GOOD_ONE_BAD)
    assert result.exit_code == 1, result.output
    assert 'Changes saved' in result.output, result.output

    text = _exported(runner, book, tmp_path / 'after.txt')
    assert 'A good one' in text, text
    assert 'A bad one' not in text, text


def test_atomic_keeps_neither(tmp_path):
    runner = CliRunner()
    book = _book(runner, tmp_path)

    result = _run(runner, 'import', str(book), ONE_GOOD_ONE_BAD, '--atomic')
    assert result.exit_code == 1, result.output
    assert 'Changes saved' not in result.output, result.output
    assert 'Rolled back' in result.output, result.output
    assert '--atomic' in result.output, result.output

    text = _exported(runner, book, tmp_path / 'after.txt')
    assert 'A good one' not in text, (
        'one block of the file failed, so the whole file should have rolled '
        f'back:\n{text}')
    assert 'A bad one' not in text, text


def test_atomic_changes_nothing_when_the_file_is_sound(tmp_path):
    """The flag is about what happens on failure; a clean file is unaffected."""
    runner = CliRunner()
    book = _book(runner, tmp_path)

    result = _run(runner, 'import', str(book), BOTH_GOOD, '--atomic')
    assert result.exit_code == 0, result.output
    assert 'Changes saved' in result.output, result.output

    text = _exported(runner, book, tmp_path / 'after.txt')
    assert 'A good one' in text, text
    assert 'Another good one' in text, text


def test_the_book_can_still_be_read_after_a_rollback(tmp_path):
    """A rollback leaves the book exactly as it was before the run."""
    runner = CliRunner()
    book = _book(runner, tmp_path)
    assert _run(runner, 'import', str(book), BOTH_GOOD).exit_code == 0
    before = _exported(runner, book, tmp_path / 'before.txt')

    # One that applies ahead of one that fails, so the rollback has something
    # already written to take back out.
    mixed = tmp_path / 'mixed.txt'
    mixed.write_text(Path(A_THIRD_GOOD_ONE).read_text() + '\n'
                     + Path(ONE_GOOD_ONE_BAD).read_text())
    result = _run(runner, 'import', str(book), str(mixed), '--atomic')
    assert result.exit_code == 1, result.output

    after = _exported(runner, book, tmp_path / 'after.txt')
    assert 'A third good one' not in after, after
    assert after.count('Another good one') == before.count('Another good one')


RATES = 'tests/fixtures/fx_rates_usd_two_invoice_dates.yaml'
DEPOSIT_SPLIT = '00e958a8d56547d484d7629000292dc3'


def _a_book_already_wrong(runner, tmp_path):
    """Two USD invoices and a deposit, then a cost basis left where nothing
    reads it — the state an older link left, and the state a repair starts in.
    """
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_two_usd_invoices_posted.txt',
        '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output
    result = _run(runner, 'import', str(book),
                  'tests/fixtures/fx_usd_deposit_against_due_from_director.txt')
    assert result.exit_code == 0, result.output

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
    return book


def test_a_fault_already_in_the_book_does_not_block_an_unrelated_file(tmp_path):
    """The book has a cost basis nothing reads. An ordinary CAD expense, which
    touches no foreign currency at all, must still commit.

    Read whole and judged whole, that pre-existing fault is in the finished
    book, so the run rolled back and the book could never accept an `--atomic`
    file again — including the one repairing it.
    """
    runner = CliRunner()
    book = _a_book_already_wrong(runner, tmp_path)

    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 1, verified.output
    assert DEPOSIT_SPLIT in verified.output, verified.output

    result = _run(runner, 'import', str(book), AN_ORDINARY_CAD_EXPENSE,
                  '--atomic')
    assert result.exit_code == 0, result.output
    assert 'Changes saved' in result.output, result.output
    assert 'Rolled back' not in result.output, result.output

    text = _exported(runner, book, tmp_path / 'after.txt')
    assert 'An ordinary CAD expense' in text, text


def test_the_exemption_is_only_for_what_was_already_there(tmp_path):
    """The pre-existing fault is exempt; the book must still hold it after.

    A file is not being given a licence to leave new faults — that is
    `test_a_rollback_does_not_sign_off_with_a_tick` below, which states a
    balance the finished book contradicts and is rolled back for it. What this
    pins is the other half: the exempted fault is still there afterwards, so
    the run has not quietly accepted it as correct.
    """
    runner = CliRunner()
    book = _a_book_already_wrong(runner, tmp_path)

    assert _run(runner, 'import', str(book), AN_ORDINARY_CAD_EXPENSE,
                '--atomic').exit_code == 0

    still_wrong = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert still_wrong.exit_code == 1, still_wrong.output
    assert DEPOSIT_SPLIT in still_wrong.output, still_wrong.output


def test_a_file_that_moves_the_figures_of_an_exempt_fault_still_commits(tmp_path):
    """The exemption is on the fault, not on the sentence that describes it.

    A currency total is reported as "the USD cost bases hold X … the ledger
    says Y — a difference of Z", and X and Y move whenever anything USD is
    imported. Compared as text, an unrelated USD purchase turned an untouched
    disagreement into a fault the file had introduced, and the file was rolled
    back over a book it neither broke nor claimed to fix — which is the whole
    thing the exemption exists to prevent. What is compared is the currency and
    the size of the disagreement, so leaving it where it was is the same fault.
    """
    runner = CliRunner()
    book = _a_book_already_wrong(runner, tmp_path)

    # Lower a cost basis balance with no sale to account for it, which is what puts
    # the two sides of the currency total out. `_a_book_already_wrong` on its
    # own has a stranded balance and totals that still level.
    out = _exported(runner, book, tmp_path / 'out.txt')
    posting = re.search(
        r'Assets:Current assets:Accounts receivable:USD 2720\.00 USD\n'
        r'(?:\t\t[^\n]*\n)*', out).group(0)
    lowered = tmp_path / 'lowered.txt'
    lowered.write_text(re.sub(r'cost_basis_balance: "[^"]*"',
                              'cost_basis_balance: "2000.00"',
                              re.search(
                                  r'2026-07-31 \* [^\n]*\n(?:\t[^\n]*\n)*',
                                  out).group(0)))
    assert 'cost_basis_balance' in posting, posting
    assert _run(runner, 'import', str(book), str(lowered),
                '--strategy', 'update').exit_code == 0

    before = _run(runner, 'fx-balances', str(book), '--verify-costs').output
    assert 'accounted for by no cost basis' in before, before

    # USD, so both sides of the currency total move, and unrelated to either
    # fault: currency bought outright, bringing its own cost with it. The
    # difference is left exactly where it was, so this is the same fault.
    result = _run(runner, 'import', str(book),
                  'tests/fixtures/fx_buy_50_usd_unrelated.txt', '--atomic',
                  '--fx-rates', RATES)
    assert result.exit_code == 0, result.output
    assert 'Changes saved' in result.output, result.output
    assert 'Rolled back' not in result.output, result.output


def test_a_rollback_does_not_sign_off_with_a_tick(tmp_path):
    """"Nothing to import" and "nothing could be imported" are different
    answers, and a rollback is the second one.

    This file is refused as the block lands — a balance far above what its
    split brought in is what `_check_stated_balances` asks about, and it asks
    per block — so the run is rolled back with an error to its name. The other
    arm, where every block applies and only the finished book refuses, is
    `test_a_repriced_basis_is_caught_under_its_sales.py::
    test_an_atomic_reprice_is_rolled_back`, and the tick is asserted absent in
    both.
    """
    runner = CliRunner()
    book = _a_book_already_wrong(runner, tmp_path)

    out = _exported(runner, book, tmp_path / 'out.txt')
    block = re.search(r'2026-08-13 \* "Received[^\n]*\n(?:\t[^\n]*\n)*',
                      out).group(0)
    # A balance the finished book contradicts: stated far above what the
    # basis brought in, so every block applies and the book is refused.
    wrong = tmp_path / 'wrong.txt'
    wrong.write_text(re.sub(r'cost_basis_balance: "[^"]*"',
                            'cost_basis_balance: "9999.00"', block))
    result = _run(runner, 'import', str(book), str(wrong), '--atomic',
                  '--strategy', 'update')

    assert result.exit_code != 0, result.output
    assert 'Rolled back' in result.output, result.output
    assert '✓ Nothing to import' not in result.output, result.output
    assert 'Changes saved' not in result.output, result.output


def test_a_dry_run_that_would_roll_back_does_not_sign_off_either(tmp_path):
    """`--dry-run` applies the whole file in memory, so it reaches the same
    answer — and it has its own tick to withhold.

    The same file as above, refused as the block lands. The book is not
    written either way, so what is being pinned is what the run tells its
    reader: a file this would refuse must not be reported as one that would
    have gone in. The dry run of a file only the finished book refuses is
    `test_a_repriced_basis_is_caught_under_its_sales.py::
    test_a_dry_run_of_the_same_reprice_says_the_same`.
    """
    runner = CliRunner()
    book = _a_book_already_wrong(runner, tmp_path)

    out = _exported(runner, book, tmp_path / 'out.txt')
    block = re.search(r'2026-08-13 \* "Received[^\n]*\n(?:\t[^\n]*\n)*',
                      out).group(0)
    wrong = tmp_path / 'wrong.txt'
    wrong.write_text(re.sub(r'cost_basis_balance: "[^"]*"',
                            'cost_basis_balance: "9999.00"', block))
    result = _run(runner, 'import', str(book), str(wrong), '--atomic',
                  '--dry-run', '--strategy', 'update')

    assert result.exit_code != 0, result.output
    assert 'Rolled back' in result.output, result.output
    assert '✓ Dry run' not in result.output, result.output
    assert 'Changes saved' not in result.output, result.output

    # And the book is untouched, which a dry run promises whatever it finds.
    after = _exported(runner, book, tmp_path / 'after.txt')
    assert '9999.00' not in after, after
