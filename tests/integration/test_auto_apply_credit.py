"""Q-015: invoice/bill-level `auto_apply_credit: true` consumes existing
pre-payment credit on the same owner via `gncInvoiceAutoApplyPayments`.

Setup (shared across most tests):
  - INV-001 for $100, paid $150 → bank tx for $150; AR has invoice lot
    (closed) and prepay lot (open, balance −$50).
  - INV-002 / BILL-001 / etc. is then imported with `auto_apply_credit: true`.

What we assert:
  * the flag triggers `inv.AutoApplyPayments()` after PostToAccount,
  * no new bank tx is created (no `payment:` block in the directive),
  * the consumed amount is taken from the prepay lot (split-in-place when
    credit > invoice; whole-split when credit ≤ invoice),
  * roundtrip emits the flag and re-importing is idempotent,
  * compose with a cash `payment:` block (credit covers part, bank covers
    the rest),
  * bill counterparts behave symmetrically (AP, opposite signs).
"""

import time
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS_PATH = 'tests/fixtures/payment_roundtrip_accounts.txt'
FIXTURES_DIR = Path('tests/fixtures')


def _fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text()


def _setup(runner, tmp_path, kind='invoice'):
    gf = tmp_path / 'book.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf), ACCOUNTS_PATH])
    assert r.exit_code == 0, r.output
    time.sleep(1)
    primer = ('q015_aac_primer_invoice.txt' if kind == 'invoice'
              else 'q015_aac_primer_bill.txt')
    primer_path = tmp_path / 'primer.txt'
    primer_path.write_text(_fixture(primer))
    r = runner.invoke(cli, ['import', str(gf), str(primer_path),
                            '--include-business-objects'])
    assert r.exit_code == 0, r.output
    time.sleep(1)
    return gf


def _import_fixture(runner, gf, fixture_name, tmp_path, alias=None):
    """Import a fixture by name (re-writes the .txt under tmp_path so
    `import` can read it inside CliRunner's environment)."""
    p = tmp_path / (alias or fixture_name)
    p.write_text(_fixture(fixture_name))
    return runner.invoke(cli, ['import', str(gf), str(p),
                               '--include-business-objects'])


def _import_text(runner, gf, content, name, tmp_path):
    p = tmp_path / name
    p.write_text(content)
    return runner.invoke(cli, ['import', str(gf), str(p),
                               '--include-business-objects'])


def _export(runner, gf, tmp_path, name):
    out = tmp_path / name
    r = runner.invoke(cli, ['export', str(gf), str(out), '--include-business-objects'])
    assert r.exit_code == 0, r.output
    return out.read_text()


def _ar_lot_summary(gf, ar_account='Assets.Accounts Receivable'):
    from gnucash import GncLot

    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        def find(a, n):
            if a.get_full_name() == n:
                return a
            for c in a.get_children():
                r = find(c, n)
                if r:
                    return r
            return None
        ar = find(repo.book.get_root_account(), ar_account)
        seen, lots = set(), []
        for sp in ar.GetSplitList():
            raw = sp.GetLot()
            if raw is None or int(raw) in seen:
                continue
            seen.add(int(raw))
            lot = GncLot(instance=raw)
            lots.append({'closed': lot.is_closed(),
                         'balance': lot.get_balance().to_double(),
                         'members': len(list(lot.get_split_list()))})
        return sorted(lots, key=lambda d: (d['closed'], d['balance']))
    finally:
        repo.close()


def _bank_tx_count(gf, bank='Assets.Bank'):
    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        def find(a, n):
            if a.get_full_name() == n:
                return a
            for c in a.get_children():
                r = find(c, n)
                if r:
                    return r
            return None
        b = find(repo.book.get_root_account(), bank)
        if b is None:
            return 0
        return len({sp.GetParent().GetGUID().to_string() for sp in b.GetSplitList()})
    finally:
        repo.close()


# ──────────────────────────────────────────────────────────────────────────
# Invoice — consume credit fully covers the invoice
# ──────────────────────────────────────────────────────────────────────────

def test_invoice_auto_apply_credit_consumes_partial_credit(tmp_path):
    """INV-002 for $30 with credit of $50 available — auto-apply
    consumes $30, leaves $20 still open as residual prepay credit."""
    runner = CliRunner()
    gf = _setup(runner, tmp_path, kind='invoice')

    r = _import_fixture(runner, gf, 'q015_aac_inv002_partial_credit.txt', tmp_path)
    assert r.exit_code == 0, f'import: {r.output}'
    time.sleep(1)

    # Expect: no new bank tx, INV-002's lot closed (credit consumed),
    # residual prepay lot open with -$20.
    assert _bank_tx_count(gf) == 1, 'auto-apply must not create a new bank tx'
    lots = _ar_lot_summary(gf)
    assert len(lots) == 3, f'expected 3 AR lots (INV-001, ex-prepay-now-closed, residual). got {lots}'
    closed = [lot for lot in lots if lot['closed']]
    open_ = [lot for lot in lots if not lot['closed']]
    assert len(closed) == 2, f'two closed lots (INV-001 + INV-002 ex-prepay). got: {lots}'
    assert all(lot['balance'] == 0.0 for lot in closed)
    assert len(open_) == 1 and open_[0]['balance'] == -20.0, (
        f'residual prepay lot must be open at -20. got: {open_}'
    )


def test_invoice_auto_apply_credit_over_consumes_partial_pay(tmp_path):
    """INV-002 for $200 with credit of $50 available — credit < invoice.
    Auto-apply consumes the full $50, INV-002 lot still open at +$150."""
    runner = CliRunner()
    gf = _setup(runner, tmp_path, kind='invoice')

    r = _import_fixture(runner, gf, 'q015_aac_inv002_over_consumes.txt', tmp_path)
    assert r.exit_code == 0, f'import: {r.output}'
    time.sleep(1)

    assert _bank_tx_count(gf) == 1
    lots = _ar_lot_summary(gf)
    # Expect: INV-001 closed; ex-prepay lot now contains the full -50 + INV-002 partial +50? Actually:
    #   - INV-001 closed at 0
    #   - ex-prepay lot closed at 0 (had -50; INV-002 posting +200 added; lot now needs balance 0;
    #     GnuCash splits invoice posting? or moves entire -50 into INV-002 lot?)
    # The exact lot reorg is what AutoApplyPayments decides — at minimum:
    #   * INV-002 must reflect $150 remaining,
    #   * no prepay lot still open with -50 (the credit was fully consumed).
    open_lots = [lot for lot in lots if not lot['closed']]
    open_balances = sorted(lot['balance'] for lot in open_lots)
    assert -50.0 not in open_balances, (
        f'-50 prepay lot must have been consumed entirely. got: {lots}'
    )
    # The invoice (or what remains of it) must show a net +150 unpaid.
    open_positive = [lot for lot in open_lots if lot['balance'] > 0]
    assert open_positive, f'expected an open lot for the unpaid balance. got: {lots}'
    assert sum(lot['balance'] for lot in open_positive) == 150.0


def test_invoice_auto_apply_credit_roundtrip_emits_flag_and_idempotent(tmp_path):
    """After auto-apply, export must emit `auto_apply_credit: true`; re-import
    is unchanged (no further consumption, no drift)."""
    runner = CliRunner()
    gf = _setup(runner, tmp_path, kind='invoice')

    r = _import_fixture(runner, gf, 'q015_aac_inv002_partial_credit.txt', tmp_path)
    assert r.exit_code == 0
    time.sleep(1)
    initial_lots = _ar_lot_summary(gf)

    exported = _export(runner, gf, tmp_path, 'r1.txt')
    # Exporter must surface the flag on INV-002.
    assert 'auto_apply_credit: true' in exported, (
        f'exporter must emit auto_apply_credit flag. exported:\n{exported}'
    )

    r = _import_text(runner, gf, exported, 'r1_in.txt', tmp_path)
    assert r.exit_code == 0, f're-import: {r.output}'
    final_lots = _ar_lot_summary(gf)
    assert final_lots == initial_lots, (
        f'roundtrip drifted.\nbefore: {initial_lots}\nafter:  {final_lots}'
    )
    assert _bank_tx_count(gf) == 1, 'roundtrip must not add a bank tx'


def test_invoice_auto_apply_credit_composes_with_cash_payment(tmp_path):
    """INV-002 for $80 with credit of $50 + an additional cash payment of $30 →
    invoice closes via credit ($50) + bank payment ($30)."""
    runner = CliRunner()
    gf = _setup(runner, tmp_path, kind='invoice')

    r = _import_fixture(runner, gf, 'q015_aac_inv002_composed_cash.txt', tmp_path)
    assert r.exit_code == 0, f'import: {r.output}'
    time.sleep(1)

    assert _bank_tx_count(gf) == 2, (
        f'expect 2 bank txs (original $150 + new $30). got {_bank_tx_count(gf)}'
    )
    lots = _ar_lot_summary(gf)
    open_lots = [lot for lot in lots if not lot['closed']]
    assert open_lots == [], (
        f'invoice + credit + cash must close all lots; left open: {open_lots}'
    )


# ──────────────────────────────────────────────────────────────────────────
# Bill — symmetric overpayment credit consumption
# ──────────────────────────────────────────────────────────────────────────

def test_bill_auto_apply_credit_consumes_partial_credit(tmp_path):
    """BILL-002 for $30 against existing vendor credit of $50 → consume
    $30, leaves $20 credit residual."""
    runner = CliRunner()
    gf = _setup(runner, tmp_path, kind='bill')

    r = _import_fixture(runner, gf, 'q015_aac_bill002_partial_credit.txt', tmp_path)
    assert r.exit_code == 0, f'import: {r.output}'
    time.sleep(1)

    assert _bank_tx_count(gf) == 1
    lots = _ar_lot_summary(gf, ar_account='Liabilities.Accounts Payable')
    closed = [lot for lot in lots if lot['closed']]
    open_ = [lot for lot in lots if not lot['closed']]
    assert len(closed) == 2 and all(lot['balance'] == 0.0 for lot in closed)
    assert len(open_) == 1 and open_[0]['balance'] == 20.0, (
        f'bill prepay residual must be open at +20 (AP sign). got: {open_}'
    )


def test_bill_auto_apply_credit_roundtrip_emits_flag(tmp_path):
    runner = CliRunner()
    gf = _setup(runner, tmp_path, kind='bill')

    r = _import_fixture(runner, gf, 'q015_aac_bill002_partial_credit.txt', tmp_path)
    assert r.exit_code == 0, f'import: {r.output}'
    time.sleep(1)

    exported = _export(runner, gf, tmp_path, 'r1.txt')
    # The flag on BILL-002 must round-trip.
    bill_block_starts = [i for i, ln in enumerate(exported.splitlines())
                         if ln.startswith('bill "BILL-002"')]
    assert bill_block_starts, 'BILL-002 missing from export'
    start = bill_block_starts[0]
    bill_block = '\n'.join(exported.splitlines()[start:start + 30])
    assert 'auto_apply_credit: true' in bill_block, (
        f'BILL-002 export must emit auto_apply_credit. block:\n{bill_block}'
    )


# ──────────────────────────────────────────────────────────────────────────
# Negative control
# ──────────────────────────────────────────────────────────────────────────

def test_invoice_no_flag_does_not_consume_credit(tmp_path):
    """Without the flag, INV-002 stays open at its full amount; no credit consumed."""
    runner = CliRunner()
    gf = _setup(runner, tmp_path, kind='invoice')

    r = _import_fixture(runner, gf, 'q015_aac_inv002_no_flag.txt', tmp_path)
    assert r.exit_code == 0
    time.sleep(1)

    lots = _ar_lot_summary(gf)
    open_lots = [lot for lot in lots if not lot['closed']]
    open_balances = sorted(lot['balance'] for lot in open_lots)
    assert open_balances == [-50.0, 30.0], (
        f'without auto_apply_credit, prepay -50 and INV-002 +30 must both stay open. '
        f'got: {open_balances}'
    )
