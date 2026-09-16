"""F-002 + report: `balance-sheet` balances whether or not the books are closed, and `report` runs named statements against one open book.

Book (tests/fixtures/closing_book.txt): Sales 1,000.00 and Office 300.00 in 2026,
so Assets 700.00 and net income 700.00. The figures are GnuCash's, from the
plain text report, measured on GnuCash 5.10.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from tests.integration.text_report_pages import amount_of as _amount
from tests.integration.text_report_pages import directives_of as _directives
from tests.integration.text_report_pages import key_of as _key

BOOK = str(Path('tests/fixtures/closing_book.txt'))


def _new_book(runner, tmp_path):
    gf = tmp_path / 'book.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(gf), BOOK]).exit_code == 0
    return gf


def _balance_sheet(runner, gf):
    r = runner.invoke(cli, ['balance-sheet', str(gf), '--as-of', '2026-12-31'])
    assert r.exit_code == 0, r.output
    return r.output


def _close(runner, gf):
    assert runner.invoke(cli, ['close-books', str(gf),
                               '--closing-date', '2026-12-31']).exit_code == 0


def test_balance_sheet_balances_before_close(tmp_path):
    """Net income is not in an account yet, so it is the block's own key."""
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    out = _balance_sheet(runner, gf)
    assert _key(out, 'total_assets') == '700.00 CAD'
    assert _key(out, 'retained_earnings') == '700.00 CAD'
    assert _key(out, 'total_liabilities_and_equity') == '700.00 CAD'


def test_balance_sheet_balances_after_close(tmp_path):
    """Closed, the 700.00 sits in Equity:Retained Earnings:CAD, the account close-books opens.

    An account holds it now, so it is an account line and the block states no
    `retained_earnings` key: that key is for what no account holds.
    """
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    _close(runner, gf)
    out = _balance_sheet(runner, gf)
    assert _key(out, 'total_assets') == '700.00 CAD'
    assert 'retained_earnings' not in out, out
    assert _amount(out, 'Equity:Retained Earnings:CAD') == '700.00 CAD'
    assert _key(out, 'total_liabilities_and_equity') == '700.00 CAD'


def test_report_runs_both_statements_in_one_invocation(tmp_path):
    """One page, a block per statement, each opened by its own dated directive."""
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    r = runner.invoke(cli, ['report', str(gf), 'income-statement', 'balance-sheet',
                            '--fiscal-year-end', '2026-12-31'])
    assert r.exit_code == 0, r.output
    assert _directives(r.output) == ['2026-01-01 income-statement',
                                     '2026-12-31 balance-sheet']
    assert 'net_income: 700.00 CAD' in r.output, r.output
    assert 'Assets 700.00 CAD' in r.output, r.output


def test_report_rejects_unknown_statement(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    r = runner.invoke(cli, ['report', str(gf), 'cash-flow',
                            '--fiscal-year-end', '2026-12-31'])
    assert r.exit_code != 0
    assert 'unknown statement' in r.output and 'cash-flow' in r.output
