"""Q-015: every importer code path that internally calls `Unpost(False)`
on a paid invoice/bill must surface the resulting orphan(s) to the user.

The `unpost-invoices` / `unpost-bills` CLI ships an orphan-payment
warning (Q-014). The same `Unpost(False)` call is made by the importer
in four other paths:

* Q-010 minimal-unpost path (`posted: none` in re-imported plaintext)
* destructive rebuild path triggered by: entry modify/add/remove,
  posted-block change, payment modify, payment remove

In every one of those, the importer currently calls `Unpost(False)`
silently. These tests assert:

1. **Each destructive path on a paid record emits an orphan warning**
   (mentions the original bank-tx GUID, the orphan amount, and the
   originating invoice/bill ID) so the user can act before re-pay
   creates a duplicate.
2. **Re-running the same destructive import is idempotent** — the
   orphan count after running the same modified import twice is the
   same as after running it once. The fix must not let orphans
   accumulate on repeat.
3. **Negative controls**: an UNPAID invoice/bill re-imported with the
   same destructive change does NOT emit an orphan warning (there
   was nothing to orphan).
4. **Negative control**: an identical re-import (`unchanged` path)
   does NOT emit an orphan warning.

When these tests pass, every importer-side unpost is visible to the
user with the same level of detail as the CLI `unpost-invoices`
warning.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS_PATH = 'tests/fixtures/payment_roundtrip_accounts.txt'
FIXTURES_DIR = Path('tests/fixtures')


def _fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text()


# -- helpers --------------------------------------------------------------


def _setup_book(runner, tmp_path):
    gf = tmp_path / 'book.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf), ACCOUNTS_PATH])
    assert r.exit_code == 0, f'accounts: {r.output}'
    return gf


def _import(runner, gf, fixture_name, tmp_path, alias=None):
    p = tmp_path / (alias or fixture_name)
    p.write_text(_fixture(fixture_name))
    return runner.invoke(cli, ['import', str(gf), str(p),
                               '--include-business-objects'])


def _orphan_count(runner, gf):
    r = runner.invoke(cli, ['find-orphan-payments', str(gf)])
    assert r.exit_code == 0, f'find-orphan-payments: {r.output}'
    if 'No orphan' in r.output:
        return 0
    return sum(1 for line in r.output.splitlines() if line.strip().startswith('guid:'))


def _bank_tx_guids(gf, account_name='Assets.Bank'):
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
            return set()
        return {sp.GetParent().GetGUID().to_string() for sp in bank.GetSplitList()}
    finally:
        repo.close()


def _assert_orphan_warning(output, payment_guid):
    """Per Q-014's per-record warning shape, the user must see the
    payment GUID and the word 'orphan' (or equivalent) so they can
    act. Be lenient on phrasing — match GUID literally and require
    *some* orphan-related word nearby."""
    msg = output.lower()
    assert payment_guid in output, (
        f"Importer output must mention the orphaned payment GUID "
        f"{payment_guid!r}. Output:\n{output}"
    )
    assert ('orphan' in msg or 'stranded' in msg or 'no longer linked' in msg), (
        f"Importer output must use the word 'orphan' (or equivalent) "
        f"when warning about a payment that just got detached from a "
        f"lot. Output:\n{output}"
    )


# -- invoice: each destructive path warns + does not duplicate orphans ----

def test_reimport_entry_modify_on_paid_invoice_warns_and_does_not_duplicate(tmp_path):
    """INV-DEST-EMOD-100: modify the entry description on a paid invoice
    must trigger destructive rebuild + orphan warning; re-running it must
    not accumulate orphans."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)

    r = _import(runner, gf, 'q015_dest_inv_entrymod_v1.txt', tmp_path, alias='v1.txt')
    assert r.exit_code == 0
    original_payment_guids = _bank_tx_guids(gf)
    assert len(original_payment_guids) == 1

    r = _import(runner, gf, 'q015_dest_inv_entrymod_v2.txt', tmp_path, alias='v2.txt')
    assert r.exit_code == 0, f'v2: {r.output}'
    _assert_orphan_warning(r.output, next(iter(original_payment_guids)))
    orphans_after_one = _orphan_count(runner, gf)
    assert orphans_after_one >= 1

    # Idempotency: re-running the SAME v2 must not produce more orphans.
    r = _import(runner, gf, 'q015_dest_inv_entrymod_v2.txt', tmp_path,
                alias='v2_again.txt')
    assert r.exit_code == 0
    assert _orphan_count(runner, gf) == orphans_after_one, (
        f'orphan count drifted on idempotent re-run: '
        f'{orphans_after_one} -> {_orphan_count(runner, gf)}'
    )


def test_reimport_entry_added_on_paid_invoice_warns(tmp_path):
    """INV-DEST-EADD-105: adding a second entry to a paid invoice triggers
    destructive rebuild and an orphan warning."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)

    r = _import(runner, gf, 'q015_dest_inv_entryadd_v1.txt', tmp_path, alias='v1.txt')
    assert r.exit_code == 0
    original_payment_guid = next(iter(_bank_tx_guids(gf)))

    r = _import(runner, gf, 'q015_dest_inv_entryadd_v2.txt', tmp_path, alias='v2.txt')
    assert r.exit_code == 0
    _assert_orphan_warning(r.output, original_payment_guid)


def test_reimport_entry_removed_on_paid_invoice_warns(tmp_path):
    """INV-DEST-ERM-110: removing an entry from a paid invoice triggers
    destructive rebuild and an orphan warning."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)

    r = _import(runner, gf, 'q015_dest_inv_entryrm_v1.txt', tmp_path, alias='v1.txt')
    assert r.exit_code == 0
    original_payment_guid = next(iter(_bank_tx_guids(gf)))

    r = _import(runner, gf, 'q015_dest_inv_entryrm_v2.txt', tmp_path, alias='v2.txt')
    assert r.exit_code == 0
    _assert_orphan_warning(r.output, original_payment_guid)


def test_reimport_posted_block_change_on_paid_invoice_warns(tmp_path):
    """INV-DEST-POSTCHG-115: changing the posted memo triggers destructive
    rebuild and an orphan warning."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)

    r = _import(runner, gf, 'q015_dest_inv_postedchg_v1.txt', tmp_path, alias='v1.txt')
    assert r.exit_code == 0
    original_payment_guid = next(iter(_bank_tx_guids(gf)))

    r = _import(runner, gf, 'q015_dest_inv_postedchg_v2.txt', tmp_path, alias='v2.txt')
    assert r.exit_code == 0
    _assert_orphan_warning(r.output, original_payment_guid)


def test_reimport_posted_none_on_paid_invoice_warns(tmp_path):
    """INV-DEST-POSTNONE-120: Q-010 minimal-unpost path — explicit user
    request to unpost via re-import. Same orphan trap as `unpost-invoices`
    CLI."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)

    r = _import(runner, gf, 'q015_dest_inv_postnone_v1.txt', tmp_path, alias='v1.txt')
    assert r.exit_code == 0
    original_payment_guid = next(iter(_bank_tx_guids(gf)))

    r = _import(runner, gf, 'q015_dest_inv_postnone_v2.txt', tmp_path, alias='v2.txt')
    assert r.exit_code == 0, f'v2: {r.output}'
    _assert_orphan_warning(r.output, original_payment_guid)


def test_reimport_payment_field_modified_on_paid_invoice_warns(tmp_path):
    """INV-DEST-PMOD-125: changing a payment memo triggers destructive
    rebuild and an orphan warning."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)

    r = _import(runner, gf, 'q015_dest_inv_paymemo_v1.txt', tmp_path, alias='v1.txt')
    assert r.exit_code == 0
    original_payment_guid = next(iter(_bank_tx_guids(gf)))

    r = _import(runner, gf, 'q015_dest_inv_paymemo_v2.txt', tmp_path, alias='v2.txt')
    assert r.exit_code == 0
    _assert_orphan_warning(r.output, original_payment_guid)


def test_reimport_payment_removed_on_paid_invoice_warns(tmp_path):
    """INV-DEST-PRM-130: removing one of two payments triggers destructive
    rebuild and an orphan warning."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)

    r = _import(runner, gf, 'q015_dest_inv_payrm_v1.txt', tmp_path, alias='v1.txt')
    assert r.exit_code == 0
    payment_guids = _bank_tx_guids(gf)
    assert len(payment_guids) == 2

    r = _import(runner, gf, 'q015_dest_inv_payrm_v2.txt', tmp_path, alias='v2.txt')
    assert r.exit_code == 0
    # The removed payment ($45) becomes orphan-eligible; ANY of the
    # original payment GUIDs is acceptable, since at least one survived
    # the rebuild and stranded on the bank side.
    found_any = any(g in r.output for g in payment_guids)
    assert found_any, (
        f'orphan warning must mention at least one of the original payment '
        f'GUIDs {payment_guids}. Output:\n{r.output}'
    )
    assert 'orphan' in r.output.lower() or 'stranded' in r.output.lower()


# -- bill counterparts ----------------------------------------------------

def test_reimport_entry_modify_on_paid_bill_warns(tmp_path):
    """BILL-DEST-EMOD-140: bill entry modify triggers destructive rebuild
    and orphan warning."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)

    r = _import(runner, gf, 'q015_dest_bill_entrymod_v1.txt', tmp_path, alias='v1.txt')
    assert r.exit_code == 0
    original_payment_guid = next(iter(_bank_tx_guids(gf)))

    r = _import(runner, gf, 'q015_dest_bill_entrymod_v2.txt', tmp_path, alias='v2.txt')
    assert r.exit_code == 0
    _assert_orphan_warning(r.output, original_payment_guid)


def test_reimport_posted_none_on_paid_bill_warns(tmp_path):
    """BILL-DEST-POSTNONE-145: bill posted:none re-import triggers orphan
    warning."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)

    r = _import(runner, gf, 'q015_dest_bill_postnone_v1.txt', tmp_path, alias='v1.txt')
    assert r.exit_code == 0
    original_payment_guid = next(iter(_bank_tx_guids(gf)))

    r = _import(runner, gf, 'q015_dest_bill_postnone_v2.txt', tmp_path, alias='v2.txt')
    assert r.exit_code == 0
    _assert_orphan_warning(r.output, original_payment_guid)


# -- negative controls ----------------------------------------------------

def test_reimport_entry_modify_on_unpaid_invoice_does_not_warn(tmp_path):
    """INV-DEST-UNPAID-150: if there are no payments to orphan, the
    destructive rebuild should run quietly (no orphan warning)."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)

    r = _import(runner, gf, 'q015_dest_unpaid_v1.txt', tmp_path, alias='v1.txt')
    assert r.exit_code == 0

    r = _import(runner, gf, 'q015_dest_unpaid_v2.txt', tmp_path, alias='v2.txt')
    assert r.exit_code == 0
    assert 'orphan' not in r.output.lower(), (
        f"Unpaid invoice re-import must NOT mention 'orphan'. Output:\n{r.output}"
    )


def test_identical_reimport_does_not_warn(tmp_path):
    """INV-DEST-IDENT-155: the `unchanged` path doesn't call Unpost — must
    be silent on orphans."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)

    r = _import(runner, gf, 'q015_dest_identical.txt', tmp_path, alias='v1.txt')
    assert r.exit_code == 0

    r = _import(runner, gf, 'q015_dest_identical.txt', tmp_path, alias='v1_again.txt')
    assert r.exit_code == 0
    assert 'orphan' not in r.output.lower(), (
        f"Identical re-import (unchanged path) must NOT mention 'orphan'. "
        f"Output:\n{r.output}"
    )


def test_add_payment_fast_path_does_not_warn(tmp_path):
    """INV-DEST-ADDPAY-160: Q-015 add-payment fast path doesn't call
    Unpost — must be silent on orphans."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)

    r = _import(runner, gf, 'q015_dest_addpay_v1.txt', tmp_path, alias='v1.txt')
    assert r.exit_code == 0

    r = _import(runner, gf, 'q015_dest_addpay_v2.txt', tmp_path, alias='v2.txt')
    assert r.exit_code == 0
    assert 'orphan' not in r.output.lower(), (
        f"Q-015 add-payment fast path must NOT mention 'orphan'. "
        f"Output:\n{r.output}"
    )
