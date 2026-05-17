"""Q-015: `find-prepayments` CLI lists open customer/vendor credits
that aren't attached to any invoice/bill (i.e. pre-payment lots produced
by overpayment or standalone payments that haven't been applied yet).

Read-only command, parallel to Q-014's `find-orphan-payments`:
  - whole-book sweep by default
  - `--customer C001` filters to that customer's credits
  - `--vendor V001` filters to that vendor's credits
  - reports per-credit: owner type + id + name, currency + amount, source
    bank tx GUID + date, ar/ap account
"""

import time
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS_PATH = 'tests/fixtures/payment_roundtrip_accounts.txt'
FIXTURES_DIR = Path('tests/fixtures')


def _fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text()


def _setup_empty(runner, tmp_path):
    gf = tmp_path / 'book.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf), ACCOUNTS_PATH])
    assert r.exit_code == 0, r.output
    time.sleep(1)
    return gf


def _import_biz_fixture(runner, gf, fixture_name, tmp_path, alias=None):
    p = tmp_path / (alias or fixture_name)
    p.write_text(_fixture(fixture_name))
    r = runner.invoke(cli, ['import', str(gf), str(p),
                            '--include-business-objects'])
    assert r.exit_code == 0, f'{fixture_name}: {r.output}'
    time.sleep(1)


def _credit_count(output):
    """Count guid: lines in find-prepayments output (one per credit)."""
    if 'No pre-payment' in output or 'No prepayment' in output:
        return 0
    return sum(1 for line in output.splitlines() if line.strip().startswith('guid:'))


# ──────────────────────────────────────────────────────────────────────────

def test_find_prepayments_empty_book_reports_zero(tmp_path):
    runner = CliRunner()
    gf = _setup_empty(runner, tmp_path)
    r = runner.invoke(cli, ['find-prepayments', str(gf)])
    assert r.exit_code == 0, f'find-prepayments: {r.output}'
    assert _credit_count(r.output) == 0


def test_find_prepayments_lists_single_customer_credit(tmp_path):
    """INV-FP-SINGLE-100 $100 paid $150 → one $50 customer credit."""
    runner = CliRunner()
    gf = _setup_empty(runner, tmp_path)
    _import_biz_fixture(runner, gf, 'q015_fp_single_cust_credit.txt', tmp_path)
    r = runner.invoke(cli, ['find-prepayments', str(gf)])
    assert r.exit_code == 0, r.output
    assert _credit_count(r.output) == 1, (
        f'expected 1 credit (C001 -50). output:\n{r.output}'
    )
    # Output must surface customer id and the credit amount
    assert 'C001' in r.output and ('50' in r.output or '50.00' in r.output), r.output


def test_find_prepayments_lists_single_vendor_credit(tmp_path):
    """BILL-FP-SINGLE-100 $100 paid $150 → one $50 vendor credit."""
    runner = CliRunner()
    gf = _setup_empty(runner, tmp_path)
    _import_biz_fixture(runner, gf, 'q015_fp_single_vendor_credit.txt', tmp_path)
    r = runner.invoke(cli, ['find-prepayments', str(gf)])
    assert r.exit_code == 0, r.output
    assert _credit_count(r.output) == 1
    assert 'V001' in r.output and ('50' in r.output or '50.00' in r.output), r.output


def test_find_prepayments_multi_customer_credits(tmp_path):
    """C001 INV-FP-MULTI-100 $100/$150 + C002 INV-FP-MULTI-200 $200/$220."""
    runner = CliRunner()
    gf = _setup_empty(runner, tmp_path)
    _import_biz_fixture(runner, gf, 'q015_fp_multi_cust1.txt', tmp_path)
    _import_biz_fixture(runner, gf, 'q015_fp_multi_cust2.txt', tmp_path)
    r = runner.invoke(cli, ['find-prepayments', str(gf)])
    assert r.exit_code == 0, r.output
    assert _credit_count(r.output) == 2, (
        f'expected 2 credits (C001 -50, C002 -20). output:\n{r.output}'
    )
    assert 'C001' in r.output and 'C002' in r.output


def test_find_prepayments_customer_filter(tmp_path):
    """Same two-customer book; --customer C001 must filter to one credit."""
    runner = CliRunner()
    gf = _setup_empty(runner, tmp_path)
    _import_biz_fixture(runner, gf, 'q015_fp_multi_cust1.txt', tmp_path)
    _import_biz_fixture(runner, gf, 'q015_fp_multi_cust2.txt', tmp_path)
    r = runner.invoke(cli, ['find-prepayments', str(gf), '--customer', 'C001'])
    assert r.exit_code == 0, r.output
    assert _credit_count(r.output) == 1, (
        f'--customer C001 must filter to one credit. output:\n{r.output}'
    )
    assert 'C001' in r.output
    assert 'C002' not in r.output


def test_find_prepayments_vendor_filter(tmp_path):
    """V001 BILL-FP-FILTER-100 $100/$150 + V002 BILL-FP-FILTER-200 $200/$230;
    --vendor V002 must filter to one credit."""
    runner = CliRunner()
    gf = _setup_empty(runner, tmp_path)
    _import_biz_fixture(runner, gf, 'q015_fp_vendor_filter_v1.txt', tmp_path)
    _import_biz_fixture(runner, gf, 'q015_fp_vendor_filter_v2.txt', tmp_path)
    r = runner.invoke(cli, ['find-prepayments', str(gf), '--vendor', 'V002'])
    assert r.exit_code == 0, r.output
    assert _credit_count(r.output) == 1, (
        f'--vendor V002 must filter to one credit. output:\n{r.output}'
    )
    assert 'V002' in r.output
    assert 'V001' not in r.output


def test_find_prepayments_after_partial_consume_shows_residual(tmp_path):
    """C001 INV-FP-RESIDUAL-100 $100/$150 → $50 credit, then INV-FP-RESIDUAL-30
    with auto_apply_credit consumes $30, leaving $20 residual."""
    runner = CliRunner()
    gf = _setup_empty(runner, tmp_path)
    _import_biz_fixture(runner, gf, 'q015_fp_residual_primer.txt', tmp_path)
    _import_biz_fixture(runner, gf, 'q015_fp_residual_inv2.txt', tmp_path)

    r = runner.invoke(cli, ['find-prepayments', str(gf)])
    assert r.exit_code == 0, r.output
    assert _credit_count(r.output) == 1
    # The residual is $20
    assert '20' in r.output or '20.00' in r.output, (
        f'residual $20 credit must be reported. output:\n{r.output}'
    )
