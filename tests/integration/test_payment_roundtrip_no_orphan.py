"""Q-015: roundtrip / double-roundtrip must not duplicate or create orphan bank txs.

The trap Q-015 closes is the destructive rebuild path that fires whenever
`_invoice_matches_directive` returns False on re-import. These tests
exercise the export → re-import cycle (and a second re-import on top of
the first) to assert:

* a paid invoice/bill exported and re-imported into the SAME book
  produces no new bank transactions and no orphans (round-trip is a
  no-op),
* doing it again on top of round-trip #1 stays a no-op (round-trip #2
  is idempotent),
* after legitimately adding a partial payment, the new total round-trips
  cleanly,
* a pre-existing orphan (e.g. left over from an `unpost-invoices` run)
  is preserved across round-trips — not duplicated, not silently
  collected, not turned into multiple orphans.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS_PATH = 'tests/fixtures/payment_roundtrip_accounts.txt'
FIXTURES_DIR = Path('tests/fixtures')


def _fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text()


# -- helpers ---------------------------------------------------------------


def _setup_book(runner, tmp_path):
    gf = tmp_path / 'book.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf), ACCOUNTS_PATH])
    assert r.exit_code == 0, f'accounts import: {r.output}'
    return gf


def _import_biz_fixture(runner, gf, fixture_name, tmp_path, alias=None):
    p = tmp_path / (alias or fixture_name)
    p.write_text(_fixture(fixture_name))
    return runner.invoke(cli, ['import', str(gf), str(p),
                               '--include-business-objects'])


def _import_biz_text(runner, gf, content, name, tmp_path):
    p = tmp_path / name
    p.write_text(content)
    return runner.invoke(cli, ['import', str(gf), str(p),
                               '--include-business-objects'])


def _export(runner, gf, tmp_path, name):
    out = tmp_path / name
    r = runner.invoke(cli, ['export', str(gf), str(out), '--include-business-objects'])
    assert r.exit_code == 0, f'export failed: {r.output}'
    return out.read_text()


def _bank_tx_state(gf, account_name='Assets.Bank'):
    """Return [{guid, date, amount, memo}] for every transaction touching
    the given bank account."""
    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        def find(acct, name):
            if acct.get_full_name() == name:
                return acct
            for child in acct.get_children():
                r = find(child, name)
                if r:
                    return r
            return None
        bank = find(repo.book.get_root_account(), account_name)
        if bank is None:
            return []
        out = []
        for split in bank.GetSplitList():
            tx = split.GetParent()
            out.append({
                'guid': tx.GetGUID().to_string(),
                'date': tx.GetDate().strftime('%Y-%m-%d'),
                'amount': split.GetAmount().to_double(),
                'memo': split.GetMemo() or '',
            })
        return sorted(out, key=lambda d: (d['date'], d['amount']))
    finally:
        repo.close()


def _orphan_count(runner, gf):
    """Run find-orphan-payments and return the orphan count from output."""
    r = runner.invoke(cli, ['find-orphan-payments', str(gf)])
    assert r.exit_code == 0, f'find-orphan-payments failed: {r.output}'
    if 'No orphan' in r.output:
        return 0
    # Count "guid:" lines (one per orphan)
    return sum(1 for line in r.output.splitlines() if line.strip().startswith('guid:'))


# -- tests -----------------------------------------------------------------

def test_paid_invoice_single_roundtrip_creates_no_orphan(tmp_path):
    """INV-PR-FULL-100 paid in full → export → re-import into same book:
    zero orphans, bank tx unchanged (same GUIDs)."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)

    r = _import_biz_fixture(runner, gf, 'q015_pr_inv_full_paid.txt', tmp_path,
                            alias='v1.txt')
    assert r.exit_code == 0, f'v1 import: {r.output}'

    bank_before = _bank_tx_state(gf)
    orphans_before = _orphan_count(runner, gf)
    assert orphans_before == 0
    assert len(bank_before) == 1, f'precondition: 1 bank tx, got {len(bank_before)}'

    exported = _export(runner, gf, tmp_path, 'round1.txt')
    r = _import_biz_text(runner, gf, exported, 'round1_reimport.txt', tmp_path)
    assert r.exit_code == 0, f'roundtrip 1 import: {r.output}'

    bank_after = _bank_tx_state(gf)
    orphans_after = _orphan_count(runner, gf)
    assert orphans_after == 0, f'roundtrip must NOT create orphans; got {orphans_after}'
    assert bank_after == bank_before, (
        f'roundtrip must NOT change bank txs.\n'
        f'before: {bank_before}\nafter:  {bank_after}'
    )


def test_paid_invoice_double_roundtrip_is_idempotent(tmp_path):
    """INV-PR-FULL-100 roundtripped twice. State after round 2 == state after
    round 1 == initial state. No orphan accumulation."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)

    r = _import_biz_fixture(runner, gf, 'q015_pr_inv_full_paid.txt', tmp_path,
                            alias='v1.txt')
    assert r.exit_code == 0, f'v1 import: {r.output}'
    initial_bank = _bank_tx_state(gf)

    exported_1 = _export(runner, gf, tmp_path, 'r1.txt')
    r = _import_biz_text(runner, gf, exported_1, 'r1_in.txt', tmp_path)
    assert r.exit_code == 0
    bank_r1 = _bank_tx_state(gf)
    assert bank_r1 == initial_bank, f'round 1 changed bank txs: {bank_r1} vs {initial_bank}'

    exported_2 = _export(runner, gf, tmp_path, 'r2.txt')
    r = _import_biz_text(runner, gf, exported_2, 'r2_in.txt', tmp_path)
    assert r.exit_code == 0
    bank_r2 = _bank_tx_state(gf)

    assert bank_r2 == initial_bank, f'round 2 changed bank txs: {bank_r2} vs {initial_bank}'
    assert _orphan_count(runner, gf) == 0


def test_partial_paid_invoice_single_roundtrip_no_orphan(tmp_path):
    """INV-PR-PARTIAL-100 partially paid: roundtrip must NOT create an
    orphan even though the lot isn't closed."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)

    r = _import_biz_fixture(runner, gf, 'q015_pr_inv_partial_paid.txt', tmp_path,
                            alias='v1.txt')
    assert r.exit_code == 0, f'v1 import: {r.output}'
    bank_before = _bank_tx_state(gf)

    exported = _export(runner, gf, tmp_path, 'r1.txt')
    r = _import_biz_text(runner, gf, exported, 'r1_in.txt', tmp_path)
    assert r.exit_code == 0
    bank_after = _bank_tx_state(gf)

    assert bank_after == bank_before, (
        f'partial-paid roundtrip changed bank state.\n'
        f'before: {bank_before}\nafter:  {bank_after}'
    )
    assert _orphan_count(runner, gf) == 0


def test_partial_paid_invoice_double_roundtrip_no_orphan_accumulation(tmp_path):
    """INV-PR-PARTIAL-100 two rounds of export → re-import on a still-outstanding
    invoice. Bank state must be stable; orphan count stays at 0."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)

    r = _import_biz_fixture(runner, gf, 'q015_pr_inv_partial_paid.txt', tmp_path,
                            alias='v1.txt')
    assert r.exit_code == 0, f'v1 import: {r.output}'
    initial = _bank_tx_state(gf)

    for i in (1, 2):
        exported = _export(runner, gf, tmp_path, f'r{i}.txt')
        r = _import_biz_text(runner, gf, exported, f'r{i}_in.txt', tmp_path)
        assert r.exit_code == 0, f'round {i} import: {r.output}'
        current = _bank_tx_state(gf)
        assert current == initial, (
            f'round {i} drifted bank state.\nstart: {initial}\nnow:  {current}'
        )
        assert _orphan_count(runner, gf) == 0, (
            f'round {i} produced orphans (count={_orphan_count(runner, gf)})'
        )


def test_add_partial_payment_then_roundtrip_no_orphan(tmp_path):
    """INV-PR-ADD-100: the intended Q-015 workflow — pay partial $60, then
    add a second partial $40, then export and re-import. Final state must
    have exactly the two payments and zero orphans."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)

    # Step 1: invoice + $60 partial
    r = _import_biz_fixture(runner, gf, 'q015_pr_add_partial_v1.txt', tmp_path)
    assert r.exit_code == 0

    # Step 2: add the $40 (Q-015 fast path)
    r = _import_biz_fixture(runner, gf, 'q015_pr_add_partial_v2.txt', tmp_path)
    assert r.exit_code == 0

    bank_after_add = _bank_tx_state(gf)
    assert len(bank_after_add) == 2, (
        f'after add-payment must have exactly 2 bank txs, got {len(bank_after_add)}: '
        f'{bank_after_add}'
    )
    assert _orphan_count(runner, gf) == 0

    # Step 3: roundtrip
    exported = _export(runner, gf, tmp_path, 'r1.txt')
    r = _import_biz_text(runner, gf, exported, 'r1_in.txt', tmp_path)
    assert r.exit_code == 0
    final = _bank_tx_state(gf)

    assert final == bank_after_add, (
        f'roundtrip after add-payment drifted.\n'
        f'before: {bank_after_add}\nafter:  {final}'
    )
    assert _orphan_count(runner, gf) == 0


def test_paid_bill_single_roundtrip_creates_no_orphan(tmp_path):
    """BILL-PR-FULL-100: paid bill roundtrip is a no-op."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)

    r = _import_biz_fixture(runner, gf, 'q015_pr_bill_full_paid.txt', tmp_path,
                            alias='v1.txt')
    assert r.exit_code == 0
    bank_before = _bank_tx_state(gf)
    assert len(bank_before) == 1

    exported = _export(runner, gf, tmp_path, 'r1.txt')
    r = _import_biz_text(runner, gf, exported, 'r1_in.txt', tmp_path)
    assert r.exit_code == 0
    bank_after = _bank_tx_state(gf)

    assert bank_after == bank_before, (
        f'bill roundtrip changed bank state.\nbefore: {bank_before}\nafter:  {bank_after}'
    )
    assert _orphan_count(runner, gf) == 0


def test_partial_paid_bill_double_roundtrip_no_orphan(tmp_path):
    """BILL-PR-PARTIAL-100 bill counterpart of the partial-paid double
    roundtrip test."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)

    r = _import_biz_fixture(runner, gf, 'q015_pr_bill_partial_paid.txt', tmp_path,
                            alias='v1.txt')
    assert r.exit_code == 0
    initial = _bank_tx_state(gf)

    for i in (1, 2):
        exported = _export(runner, gf, tmp_path, f'r{i}.txt')
        r = _import_biz_text(runner, gf, exported, f'r{i}_in.txt', tmp_path)
        assert r.exit_code == 0
        current = _bank_tx_state(gf)
        assert current == initial, (
            f'bill roundtrip {i} drifted.\nstart: {initial}\nnow:  {current}'
        )
        assert _orphan_count(runner, gf) == 0


# -- pre-existing orphan preservation across roundtrips -------------------

def _create_orphan_via_unpost(runner, gf, tmp_path, kind='invoice'):
    """Create an orphan bank tx the legitimate way: post + pay + unpost.
    Returns the orphan tx GUID."""
    if kind == 'invoice':
        fixture = 'q015_pr_orphan_inv_setup.txt'
        unpost_cmd = ['unpost-invoices', str(gf), 'INV-PR-ORPHAN-100']
    else:
        fixture = 'q015_pr_orphan_bill_setup.txt'
        unpost_cmd = ['unpost-bills', str(gf), 'BILL-PR-ORPHAN-100']
    r = _import_biz_fixture(runner, gf, fixture, tmp_path,
                            alias='orphan_setup.txt')
    assert r.exit_code == 0, f'setup import: {r.output}'
    bank_before_unpost = _bank_tx_state(gf)
    assert len(bank_before_unpost) == 1
    orphan_guid = bank_before_unpost[0]['guid']
    r = runner.invoke(cli, unpost_cmd)
    assert r.exit_code == 0, f'unpost: {r.output}'
    assert _orphan_count(runner, gf) == 1, 'precondition: exactly 1 orphan after unpost'
    return orphan_guid


def test_pre_existing_invoice_orphan_survives_single_roundtrip_without_duplication(tmp_path):
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)
    orphan_guid = _create_orphan_via_unpost(runner, gf, tmp_path, 'invoice')
    bank_before = _bank_tx_state(gf)

    exported = _export(runner, gf, tmp_path, 'r1.txt')
    r = _import_biz_text(runner, gf, exported, 'r1_in.txt', tmp_path)
    assert r.exit_code == 0, f'roundtrip: {r.output}'
    bank_after = _bank_tx_state(gf)

    assert _orphan_count(runner, gf) == 1, (
        'roundtrip must preserve the single existing orphan, not duplicate '
        'it. Current count: ' + str(_orphan_count(runner, gf))
    )
    assert any(t['guid'] == orphan_guid for t in bank_after), (
        f'orphan GUID {orphan_guid} must still be present in bank after roundtrip; '
        f'got {[t["guid"] for t in bank_after]}'
    )
    assert bank_after == bank_before, (
        f'roundtrip must not change bank state.\nbefore: {bank_before}\nafter:  {bank_after}'
    )


def test_pre_existing_invoice_orphan_survives_double_roundtrip_without_duplication(tmp_path):
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)
    _create_orphan_via_unpost(runner, gf, tmp_path, 'invoice')
    initial_bank = _bank_tx_state(gf)
    initial_orphans = _orphan_count(runner, gf)

    for i in (1, 2):
        exported = _export(runner, gf, tmp_path, f'r{i}.txt')
        r = _import_biz_text(runner, gf, exported, f'r{i}_in.txt', tmp_path)
        assert r.exit_code == 0, f'round {i}: {r.output}'
        current_bank = _bank_tx_state(gf)
        current_orphans = _orphan_count(runner, gf)
        assert current_orphans == initial_orphans, (
            f'round {i} changed orphan count: {initial_orphans} -> {current_orphans}'
        )
        assert current_bank == initial_bank, (
            f'round {i} changed bank state.\nstart: {initial_bank}\nnow:  {current_bank}'
        )


def test_pre_existing_bill_orphan_survives_single_roundtrip_without_duplication(tmp_path):
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)
    orphan_guid = _create_orphan_via_unpost(runner, gf, tmp_path, 'bill')
    bank_before = _bank_tx_state(gf)

    exported = _export(runner, gf, tmp_path, 'r1.txt')
    r = _import_biz_text(runner, gf, exported, 'r1_in.txt', tmp_path)
    assert r.exit_code == 0, f'bill roundtrip: {r.output}'
    bank_after = _bank_tx_state(gf)

    assert _orphan_count(runner, gf) == 1, (
        'bill roundtrip must not duplicate the existing orphan'
    )
    assert any(t['guid'] == orphan_guid for t in bank_after)
    assert bank_after == bank_before


def test_pre_existing_bill_orphan_survives_double_roundtrip_without_duplication(tmp_path):
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)
    _create_orphan_via_unpost(runner, gf, tmp_path, 'bill')
    initial_bank = _bank_tx_state(gf)
    initial_orphans = _orphan_count(runner, gf)

    for i in (1, 2):
        exported = _export(runner, gf, tmp_path, f'r{i}.txt')
        r = _import_biz_text(runner, gf, exported, f'r{i}_in.txt', tmp_path)
        assert r.exit_code == 0, f'bill round {i}: {r.output}'
        assert _orphan_count(runner, gf) == initial_orphans
        assert _bank_tx_state(gf) == initial_bank
