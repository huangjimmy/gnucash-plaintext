"""F-002 + report: `balance-sheet` balances whether or not the books are closed, and `report` runs named statements against one open book.

Book (tests/fixtures/closing_book.txt): Sales 1,000.00 and Office 300.00 in 2026,
so Assets 700.00 and net income 700.00. The figures are GnuCash's, from the
plain text report, measured on GnuCash 5.10.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from tests.integration.text_report_pages import figures

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
    """Net income is not in an account yet, so GnuCash shows it as Retained Earnings."""
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    out = _balance_sheet(runner, gf)
    assert figures(out, 'Total Assets') == ['C$700.00']
    assert figures(out, 'Retained Earnings') == ['C$700.00']
    assert figures(out, 'Total Liabilities & Equity') == ['C$700.00']


def test_balance_sheet_balances_after_close(tmp_path):
    """Closed, the 700.00 sits in Equity:Retained Earnings:CAD, the account close-books opens."""
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    _close(runner, gf)
    out = _balance_sheet(runner, gf)
    assert figures(out, 'Total Assets') == ['C$700.00']
    assert figures(out, 'Retained Earnings') == ['C$0.00']
    assert figures(out, 'CAD') == ['C$700.00']
    assert figures(out, 'Total Liabilities & Equity') == ['C$700.00']


def test_report_runs_both_statements_in_one_invocation(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    r = runner.invoke(cli, ['report', str(gf), 'income-statement', 'balance-sheet',
                            '--fiscal-year-end', '2026-12-31'])
    assert r.exit_code == 0, r.output
    lines = r.output.splitlines()
    assert lines[0].startswith('Income Statement For Period Covering'), r.output
    assert any(line.startswith('Balance Sheet') for line in lines), r.output
    assert figures(r.output, 'Net income for Period') == ['C$700.00']
    assert figures(r.output, 'Total Assets') == ['C$700.00']


def test_report_rejects_unknown_statement(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    r = runner.invoke(cli, ['report', str(gf), 'cash-flow',
                            '--fiscal-year-end', '2026-12-31'])
    assert r.exit_code != 0
    assert 'unknown statement' in r.output and 'cash-flow' in r.output
