"""Q-015: the two code paths for invoice payment must produce
equivalent book state across roundtrip and double-roundtrip.

Path A — ApplyPayment:
  `payment: amount=N` (no txn_guid) → GnuCash creates the bank tx via
  `inv.ApplyPayment(N)`. Handles exact, partial, and overpayment via
  GnuCash's native splitting.

Path B — retarget:
  The user pre-creates the bank tx (e.g. from QFX import), then posts
  the invoice with `payment: amount=N txn_guid=<bank>` (plus
  `prepayment: M` for overpayment). Our `_retarget_*` mechanic
  re-routes the existing counter-split.

Four scenarios with distinct amounts so a reader can tell at a glance
which fixture each test uses:

  * basic overpayment  — INV-001 $100 paid $150 (prepayment 50)
  * exact payment      — INV-EXACT-123 $123 paid $123
  * partial payment    — INV-PARTIAL-200 $200 paid $77
  * two overpayments   — INV-DOUBLE-A $80 paid $130; INV-DOUBLE-B
                         $250 paid $300; both with prepayment 50

For each scenario the user-facing outcome must be semantically
identical between the two paths after initial import, after the 1st
roundtrip, and after the 2nd roundtrip. Split GUIDs may legitimately
differ; what must match is bank tx amounts, AR lot count, lot
balances, and lot member amounts.
"""
import time
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS_PATH = 'tests/fixtures/payment_roundtrip_accounts.txt'
FIXTURES_DIR = Path('tests/fixtures')


def _write(p, t):
    with open(p, 'w') as f:
        f.write(t)
    return str(p)


def _fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text()


def _import_new(runner, gf, fixture_path, tmp_path):
    args = ['import', '--new', str(gf), fixture_path]
    r = runner.invoke(cli, args)
    assert r.exit_code == 0, f'import --new: {r.output}'
    time.sleep(1)


def _import(runner, gf, content, name, tmp_path, biz=True):
    args = ['import', str(gf),
            _write(tmp_path / name, content)]
    if biz:
        args.append('--include-business-objects')
    return runner.invoke(cli, args)


def _bank_tx_guids_sorted(gf, bank='Assets.Bank'):
    """Return list of (date, amount, tx_guid) sorted by date — lets us
    pin a known fixture amount to its actual GUID for retarget substitution."""
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
        out = []
        for sp in b.GetSplitList():
            tx = sp.GetParent()
            out.append((tx.GetDate(), sp.GetAmount().to_double(),
                        tx.GetGUID().to_string()))
        return sorted(out, key=lambda x: x[0])
    finally:
        repo.close()


def _semantic_state(gf):
    """Book state for equivalence comparison: amounts, balances, lot
    structure. Ignores split/tx GUIDs (legitimately differ between the
    two paths)."""
    from gnucash import GncLot, Split

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
        ar = find(repo.book.get_root_account(), 'Assets.Accounts Receivable')
        bank = find(repo.book.get_root_account(), 'Assets.Bank')
        bank_amounts = sorted(
            round(sp.GetAmount().to_double(), 2)
            for sp in bank.GetSplitList()
        )
        seen, lots = set(), []
        for sp in ar.GetSplitList():
            raw = sp.GetLot()
            if raw is None or int(raw) in seen:
                continue
            seen.add(int(raw))
            lot = GncLot(instance=raw)
            members = sorted(
                round(Split(instance=m).GetAmount().to_double(), 2)
                for m in lot.get_split_list()
            )
            lots.append({
                'closed': lot.is_closed(),
                'balance': round(lot.get_balance().to_double(), 2),
                'members': members,
            })
        return {
            'bank_amounts': bank_amounts,
            'ar_lots': sorted(lots, key=lambda d: (d['closed'], d['balance'], d['members'])),
        }
    finally:
        repo.close()


def _roundtrip(runner, gf, tmp_path, suffix):
    out = tmp_path / f'export_{suffix}.txt'
    r = runner.invoke(cli, ['export', str(gf), str(out),
                            '--include-business-objects'])
    assert r.exit_code == 0, f'export {suffix}: {r.output}'
    content = out.read_text()
    r = _import(runner, gf, content, f'reimport_{suffix}.txt', tmp_path)
    assert r.exit_code == 0, f'reimport {suffix}: {r.output}'
    time.sleep(1)


def _make_book(runner, tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    gf = tmp_path / 'book.gnucash'
    _import_new(runner, gf, ACCOUNTS_PATH, tmp_path)
    return gf


def _build_via_apply(runner, tmp_path, apply_fixture: str):
    """Build a book via the ApplyPayment path using a single biz fixture
    (customer + invoice with payment block, no pre-existing bank tx)."""
    gf = _make_book(runner, tmp_path)
    r = _import(runner, gf, _fixture(apply_fixture), 'apply_biz.txt', tmp_path)
    assert r.exit_code == 0, f'{apply_fixture}: {r.output}'
    time.sleep(1)
    return gf


def _build_via_retarget(runner, tmp_path, pre_bank_fixture: str,
                         retarget_fixture: str, guid_placeholders=None):
    """Build a book via the retarget path: (1) pre-create one or more
    bank txs from `pre_bank_fixture`, (2) import the retarget biz file
    after substituting bank tx GUIDs into its `{txn_guid...}`
    placeholders."""
    gf = _make_book(runner, tmp_path)
    r = _import(runner, gf, _fixture(pre_bank_fixture), 'pre_bank.txt', tmp_path,
                biz=False)
    assert r.exit_code == 0, f'{pre_bank_fixture}: {r.output}'
    time.sleep(1)
    bank_entries = _bank_tx_guids_sorted(gf)
    biz = _fixture(retarget_fixture)
    placeholders = guid_placeholders or ['txn_guid']
    for i, key in enumerate(placeholders):
        biz = biz.replace('{' + key + '}', bank_entries[i][2])
    r = _import(runner, gf, biz, 'retarget_biz.txt', tmp_path)
    assert r.exit_code == 0, f'{retarget_fixture}: {r.output}'
    time.sleep(1)
    return gf


def _assert_paths_equivalent_across_roundtrips(runner, gf_a, gf_b, label):
    a_dir = gf_a.parent
    b_dir = gf_b.parent
    state_a_0 = _semantic_state(gf_a)
    state_b_0 = _semantic_state(gf_b)
    assert state_a_0 == state_b_0, (
        f'[{label}] initial state diverges.\n'
        f'  apply:    {state_a_0}\n  retarget: {state_b_0}'
    )

    _roundtrip(runner, gf_a, a_dir, 'r1')
    _roundtrip(runner, gf_b, b_dir, 'r1')
    state_a_r1 = _semantic_state(gf_a)
    state_b_r1 = _semantic_state(gf_b)
    assert state_a_r1 == state_b_r1, (
        f'[{label}] diverged after 1st roundtrip.\n'
        f'  apply:    {state_a_r1}\n  retarget: {state_b_r1}'
    )

    _roundtrip(runner, gf_a, a_dir, 'r2')
    _roundtrip(runner, gf_b, b_dir, 'r2')
    state_a_r2 = _semantic_state(gf_a)
    state_b_r2 = _semantic_state(gf_b)
    assert state_a_r2 == state_a_r1, f'[{label}] apply path drifted on r2.'
    assert state_b_r2 == state_b_r1, f'[{label}] retarget path drifted on r2.'
    assert state_a_r2 == state_b_r2, (
        f'[{label}] diverged after 2nd roundtrip.\n'
        f'  apply:    {state_a_r2}\n  retarget: {state_b_r2}'
    )


# ────────────────────────────────────────────────────────────────────────────
# Scenarios
# ────────────────────────────────────────────────────────────────────────────

def test_basic_overpayment_paths_equivalent(tmp_path):
    """INV-001 $100 paid $150 (prepayment 50)."""
    runner = CliRunner()
    gf_a = _build_via_apply(runner, tmp_path / 'apply',
                            'q015_eq_basic_apply.txt')
    gf_b = _build_via_retarget(runner, tmp_path / 'retarget',
                               'q015_eq_basic_pre_bank.txt',
                               'q015_eq_basic_retarget.txt')
    _assert_paths_equivalent_across_roundtrips(runner, gf_a, gf_b, 'basic')


def test_exact_payment_paths_equivalent(tmp_path):
    """INV-EXACT-123 $123 paid $123."""
    runner = CliRunner()
    gf_a = _build_via_apply(runner, tmp_path / 'apply',
                            'q015_eq_exact_apply.txt')
    gf_b = _build_via_retarget(runner, tmp_path / 'retarget',
                               'q015_eq_exact_pre_bank.txt',
                               'q015_eq_exact_retarget.txt')
    _assert_paths_equivalent_across_roundtrips(runner, gf_a, gf_b, 'exact')


def test_partial_payment_paths_equivalent(tmp_path):
    """INV-PARTIAL-200 $200 paid $77 — partial leaves lot open at +$123."""
    runner = CliRunner()
    gf_a = _build_via_apply(runner, tmp_path / 'apply',
                            'q015_eq_partial_apply.txt')
    gf_b = _build_via_retarget(runner, tmp_path / 'retarget',
                               'q015_eq_partial_pre_bank.txt',
                               'q015_eq_partial_retarget.txt')
    _assert_paths_equivalent_across_roundtrips(runner, gf_a, gf_b, 'partial')


def test_two_overpayments_paths_equivalent(tmp_path):
    """INV-DOUBLE-A $80 paid $130 + INV-DOUBLE-B $250 paid $300 — both
    overpayments produce separate $50 credits; no credit merging."""
    runner = CliRunner()
    gf_a = _build_via_apply(runner, tmp_path / 'apply',
                            'q015_eq_two_over_apply.txt')
    gf_b = _build_via_retarget(runner, tmp_path / 'retarget',
                               'q015_eq_two_over_pre_bank.txt',
                               'q015_eq_two_over_retarget.txt',
                               guid_placeholders=['txn_guid_a', 'txn_guid_b'])
    _assert_paths_equivalent_across_roundtrips(runner, gf_a, gf_b, 'two_over')

    # Bonus assertion on user-visible outcome — two separate $50 credits.
    state = _semantic_state(gf_a)
    open_balances = sorted(lot['balance'] for lot in state['ar_lots'] if not lot['closed'])
    assert open_balances == [-50.0, -50.0], (
        f'two overpayments must produce two $50 credits (no merging). '
        f'got: {open_balances}'
    )
