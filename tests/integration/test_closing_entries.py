"""Q-032: closing entries are first-class — `close-books` flags them, the income
statement excludes them (so it's correct closed or not), and the flag round-trips
through plaintext.

Book: Income 1000, Expenses 300 in 2026 → net income 700.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

BOOK = str(Path('tests/fixtures/closing_book.txt'))


def _new_book(runner, tmp_path, name='book.gnucash'):
    gf = tmp_path / name
    assert runner.invoke(cli, ['import', '--new', str(gf), BOOK]).exit_code == 0
    return gf


def _income_statement(runner, gf):
    r = runner.invoke(cli, ['income-statement', str(gf), '--fiscal-year-end', '2026-12-31'])
    assert r.exit_code == 0, r.output
    return r.output


def _close(runner, gf):
    r = runner.invoke(cli, ['close-books', str(gf), '--closing-date', '2026-12-31'])
    assert r.exit_code == 0, r.output


def _closing_flags(gf):
    """{tx description: xaccTransGetIsClosingTxn(tx)} — the authoritative flag."""
    from gnucash.gnucash_core_c import xaccTransGetIsClosingTxn

    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        seen = {}
        for a in repo.book.get_root_account().get_descendants():
            for s in a.GetSplitList():
                t = s.GetParent()
                seen[t.GetDescription()] = bool(xaccTransGetIsClosingTxn(t.instance))
        return seen
    finally:
        repo.close()


def test_income_statement_identical_before_and_after_close(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    before = _income_statement(runner, gf)
    assert '700.00' in before
    _close(runner, gf)
    after = _income_statement(runner, gf)
    # Closing zeroes Income/Expense, but the statement excludes closing entries —
    # so it is byte-for-byte identical whether the books are closed or not.
    assert after == before


def test_close_books_flags_the_closing_transaction(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    _close(runner, gf)
    flags = _closing_flags(gf)
    assert flags.get('Closing entry (CAD)') is True   # authoritative GnuCash flag
    assert flags.get('Sale') is False                 # real activity is not flagged


def test_closing_flag_survives_plaintext_roundtrip(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    _close(runner, gf)
    before = _income_statement(runner, gf)

    exp = tmp_path / 'exp.txt'
    assert runner.invoke(cli, ['export', str(gf), str(exp)]).exit_code == 0
    assert 'closing: #True' in exp.read_text()        # exporter emits the flag

    gf2 = tmp_path / 'B.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(gf2), str(exp)]).exit_code == 0
    # The flag (not just the description) is re-applied in the fresh book…
    assert _closing_flags(gf2).get('Closing entry (CAD)') is True
    # …and the income statement is still correct after the roundtrip.
    assert _income_statement(runner, gf2) == before


def test_reclose_finds_prior_closing_by_flag(tmp_path):
    """`--force` re-close must find the existing closing — by the flag, robust to
    the description."""
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    _close(runner, gf)
    # A second close without --force is refused (already closed); --force re-closes.
    r = runner.invoke(cli, ['close-books', str(gf), '--closing-date', '2026-12-31'])
    assert r.exit_code != 0  # already closed
    r2 = runner.invoke(cli, ['close-books', str(gf), '--closing-date', '2026-12-31', '--force'])
    assert r2.exit_code == 0, r2.output
    # Still exactly one flagged closing (the old one was replaced, not duplicated).
    flags = _closing_flags(gf)
    assert list(flags.values()).count(True) == 1
    assert _income_statement(runner, gf).__contains__('700.00')
