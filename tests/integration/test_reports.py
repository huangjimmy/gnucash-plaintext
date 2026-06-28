"""F-002 + report: `balance-sheet` balances (closed or not), and `report` runs
named statements against one open book.

Book (tests/fixtures/closing_book.txt): Assets 700, net income 700.
"""

import time
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

BOOK = str(Path('tests/fixtures/closing_book.txt'))


def _new_book(runner, tmp_path):
    gf = tmp_path / 'book.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(gf), BOOK]).exit_code == 0
    time.sleep(1)
    return gf


def _balance_sheet(runner, gf):
    r = runner.invoke(cli, ['balance-sheet', str(gf), '--as-of', '2026-12-31'])
    assert r.exit_code == 0, r.output
    return r.output


def _close(runner, gf):
    assert runner.invoke(cli, ['close-books', str(gf),
                               '--closing-date', '2026-12-31']).exit_code == 0
    time.sleep(1)


def test_balance_sheet_balances_before_close(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    out = _balance_sheet(runner, gf)
    assert 'NOT BALANCED' not in out          # Assets = Liabilities + Equity holds
    assert '700.00' in out
    assert 'Current Year Earnings' in out     # net income not yet in equity


def test_balance_sheet_balances_after_close(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    _close(runner, gf)
    out = _balance_sheet(runner, gf)
    assert 'NOT BALANCED' not in out          # still balances
    assert '700.00' in out
    assert 'Retained Earnings' in out         # net income now sits in equity


def test_report_runs_both_statements_in_one_invocation(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    r = runner.invoke(cli, ['report', str(gf), 'income-statement', 'balance-sheet',
                            '--fiscal-year-end', '2026-12-31'])
    assert r.exit_code == 0, r.output
    assert 'INCOME STATEMENT' in r.output and 'BALANCE SHEET' in r.output
    assert 'NET INCOME' in r.output and 'NOT BALANCED' not in r.output
    assert r.output.count('700.00') >= 2      # IS net income + BS


def test_report_rejects_unknown_statement(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    r = runner.invoke(cli, ['report', str(gf), 'cash-flow',
                            '--fiscal-year-end', '2026-12-31'])
    assert r.exit_code != 0
    assert 'unknown statement' in r.output and 'cash-flow' in r.output
