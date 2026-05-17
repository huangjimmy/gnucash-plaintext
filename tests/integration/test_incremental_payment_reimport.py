"""Q-015: incremental payment re-import preserves GUIDs and bank txs.

When the user re-imports a posted invoice/bill whose only difference vs.
the existing record is "K additional `payment:` blocks appended at the
tail", the importer takes a fast path:

* no Unpost, so the posting transaction is preserved (same GUID)
* no entry rebuild, so entry GUIDs are preserved
* existing payment bank transactions are untouched (same GUIDs, same
  splits in the same lot — no orphans)
* the trailing K payment directives are applied via `ApplyPayment` on the
  still-posted invoice, adding exactly K new bank transactions

Any other shape of payment-list diff (count equal but a field changed,
existing payment removed, payment field modified) still falls through to
the destructive rebuild path the test suite already covers.
"""

import time
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS_PATH = 'tests/fixtures/payment_roundtrip_accounts.txt'
FIXTURES_DIR = Path('tests/fixtures')


def _fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text()


def _setup_book(runner, tmp_path):
    gf = tmp_path / 'book.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf), ACCOUNTS_PATH])
    assert r.exit_code == 0, f'accounts import: {r.output}'
    time.sleep(1)
    return gf


def _import_biz_fixture(runner, gf, fixture_name, tmp_path, alias=None):
    p = tmp_path / (alias or fixture_name)
    p.write_text(_fixture(fixture_name))
    return runner.invoke(cli, ['import', str(gf), str(p),
                               '--include-business-objects'])


def _snapshot(gf, business_id='INV-001', is_bill=False):
    """Return posting/entry GUIDs and bank-tx state for an invoice or bill."""
    from gnucash import Split
    from gnucash.gnucash_core_c import gncInvoiceGetInvoiceFromTxn

    from repositories.gnucash_repository import GnuCashRepository
    from services.gnucash_importer import _find_bills_by_id, _find_invoices_by_id

    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        book = repo.book
        lookups = _find_bills_by_id(book, business_id) if is_bill else _find_invoices_by_id(book, business_id)
        assert lookups, f"{'bill' if is_bill else 'invoice'} {business_id} not found"
        inv = lookups[0]
        posting_txn = inv.GetPostedTxn()
        posting_guid = posting_txn.GetGUID().to_string() if posting_txn else None
        entries = list(inv.GetEntries())
        entry_guids = sorted(e.GetGUID().to_string() for e in entries)

        lot = inv.GetPostedLot()
        lot_payment_tx_guids = []
        if lot is not None:
            for raw in lot.get_split_list():
                s = Split(instance=raw)
                tx = s.GetParent()
                if tx is None:
                    continue
                if gncInvoiceGetInvoiceFromTxn(tx.instance) is not None:
                    continue  # posting tx
                lot_payment_tx_guids.append(tx.GetGUID().to_string())

        def find(acct, name):
            if acct.get_full_name() == name:
                return acct
            for child in acct.get_children():
                r = find(child, name)
                if r:
                    return r
            return None

        bank = find(book.get_root_account(), 'Assets.Bank')
        bank_tx = {}
        if bank is not None:
            for split in bank.GetSplitList():
                tx = split.GetParent()
                bank_tx[tx.GetGUID().to_string()] = {
                    'date': tx.GetDate().strftime('%Y-%m-%d'),
                    'amount': split.GetAmount().to_double(),
                }
        return {
            'posting_guid': posting_guid,
            'entry_guids': entry_guids,
            'lot_payment_tx_guids': sorted(lot_payment_tx_guids),
            'bank_tx_by_guid': bank_tx,
        }
    finally:
        repo.close()


# -- tests ----------------------------------------------------------------

def test_invoice_adding_partial_payment_preserves_posting_and_entry_guids(tmp_path):
    """INV-INC-ADD-100: re-import adds a second `payment:` block. Posting tx
    + entry GUIDs must be unchanged."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)

    r = _import_biz_fixture(runner, gf, 'q015_inc_add_inv_v1.txt', tmp_path)
    assert r.exit_code == 0, f'v1: {r.output}'
    time.sleep(1)
    snap1 = _snapshot(gf, business_id='INV-INC-ADD-100')

    r = _import_biz_fixture(runner, gf, 'q015_inc_add_inv_v2.txt', tmp_path)
    assert r.exit_code == 0, f'v2: {r.output}'
    snap2 = _snapshot(gf, business_id='INV-INC-ADD-100')

    assert snap2['posting_guid'] == snap1['posting_guid'], (
        f"Posting GUID must NOT change on add-payment re-import. "
        f"Before {snap1['posting_guid']}, after {snap2['posting_guid']}"
    )
    assert snap2['entry_guids'] == snap1['entry_guids'], (
        f"Entry GUIDs must NOT change. Before {snap1['entry_guids']}, "
        f"after {snap2['entry_guids']}"
    )


def test_invoice_adding_partial_payment_does_not_orphan_existing_bank_tx(tmp_path):
    """INV-INC-ADD-100: the original $60 bank transaction must be in the lot
    AFTER the re-import (same GUID), and no orphan must be left behind."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)

    r = _import_biz_fixture(runner, gf, 'q015_inc_add_inv_v1.txt', tmp_path)
    assert r.exit_code == 0, f'v1: {r.output}'
    time.sleep(1)
    snap1 = _snapshot(gf, business_id='INV-INC-ADD-100')
    original_payment_guid = snap1['lot_payment_tx_guids'][0]

    r = _import_biz_fixture(runner, gf, 'q015_inc_add_inv_v2.txt', tmp_path)
    assert r.exit_code == 0, f'v2: {r.output}'
    snap2 = _snapshot(gf, business_id='INV-INC-ADD-100')

    assert original_payment_guid in snap2['lot_payment_tx_guids'], (
        f"Original $60 bank tx {original_payment_guid} must remain attached "
        f"to the lot. Lot now contains: {snap2['lot_payment_tx_guids']}"
    )
    assert len(snap2['lot_payment_tx_guids']) == 2, (
        f"Lot should hold exactly two payment txs after the add. "
        f"Got: {snap2['lot_payment_tx_guids']}"
    )
    assert len(snap2['bank_tx_by_guid']) == 2, (
        f"Bank account should hold exactly 2 transactions (original $60 + "
        f"new $40), not duplicates. Got {len(snap2['bank_tx_by_guid'])}: "
        f"{snap2['bank_tx_by_guid']}"
    )
    new_guids = set(snap2['bank_tx_by_guid']) - set(snap1['bank_tx_by_guid'])
    assert len(new_guids) == 1, (
        f"Exactly one new bank tx (the $40) must be created. "
        f"new_guids={new_guids}"
    )


def test_invoice_repeated_identical_reimport_is_unchanged(tmp_path):
    """INV-INC-IDENT-100: re-importing the same file (no new payments)
    must hit the existing `unchanged` fast path, not the new add-payment
    fast path."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)

    r = _import_biz_fixture(runner, gf, 'q015_inc_identical.txt', tmp_path,
                            alias='v1.txt')
    assert r.exit_code == 0, f'v1: {r.output}'
    time.sleep(1)
    snap1 = _snapshot(gf, business_id='INV-INC-IDENT-100')

    r = _import_biz_fixture(runner, gf, 'q015_inc_identical.txt', tmp_path,
                            alias='v1_again.txt')
    assert r.exit_code == 0, f'v1 second import: {r.output}'
    assert 'unchanged' in r.output, (
        f"Second import of identical fixture must report 'unchanged'. "
        f"Got:\n{r.output}"
    )
    snap2 = _snapshot(gf, business_id='INV-INC-IDENT-100')
    assert snap1 == snap2, 'snapshots must be identical after no-op re-import'


def test_invoice_modifying_existing_payment_memo_still_uses_destructive_rebuild(tmp_path):
    """INV-INC-MEMO-100: changing an existing payment's memo is NOT
    'adding payments at the tail'; the fast path must NOT fire. The
    rebuild path runs as before (and produces an orphan — that's the
    existing Q-014 trap, separate from Q-015). This test guards against
    the fast-path classifier being too permissive."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)

    r = _import_biz_fixture(runner, gf, 'q015_inc_memo_v1.txt', tmp_path)
    assert r.exit_code == 0, f'v1: {r.output}'
    time.sleep(1)
    snap1 = _snapshot(gf, business_id='INV-INC-MEMO-100')

    r = _import_biz_fixture(runner, gf, 'q015_inc_memo_v2.txt', tmp_path)
    assert r.exit_code == 0, f'v2: {r.output}'
    snap2 = _snapshot(gf, business_id='INV-INC-MEMO-100')

    # The fast path MUST NOT fire — that would silently mishandle the
    # memo change. The classifier returns False, the rebuild path runs,
    # so the posting GUID changes.
    assert snap2['posting_guid'] != snap1['posting_guid'], (
        "Modifying an existing payment's memo must take the destructive "
        "rebuild path (posting GUID changes), NOT the Q-015 fast path. "
        "If this assertion fires, the classifier is too permissive."
    )


def test_invoice_removing_payment_via_reimport_still_uses_destructive_rebuild(tmp_path):
    """INV-INC-REMOVE-100: directive has FEWER payments than existing.
    Q-015's fast path is strictly 'add at tail'; removal is out of scope
    and must still take the rebuild path."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)

    r = _import_biz_fixture(runner, gf, 'q015_inc_remove_v1.txt', tmp_path)
    assert r.exit_code == 0, f'v1: {r.output}'
    time.sleep(1)
    snap1 = _snapshot(gf, business_id='INV-INC-REMOVE-100')

    r = _import_biz_fixture(runner, gf, 'q015_inc_remove_v2.txt', tmp_path)
    assert r.exit_code == 0, f'v2: {r.output}'
    snap2 = _snapshot(gf, business_id='INV-INC-REMOVE-100')

    assert snap2['posting_guid'] != snap1['posting_guid'], (
        'Removing a payment must take the rebuild path (posting GUID changes).'
    )


def test_bill_adding_partial_payment_preserves_posting_and_entry_guids(tmp_path):
    """BILL-INC-ADD-100: symmetric bill test — adding a partial payment
    preserves posting + entry GUIDs and leaves existing AP bank tx in place."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)

    r = _import_biz_fixture(runner, gf, 'q015_inc_add_bill_v1.txt', tmp_path)
    assert r.exit_code == 0, f'v1: {r.output}'
    time.sleep(1)
    snap1 = _snapshot(gf, business_id='BILL-INC-ADD-100', is_bill=True)

    r = _import_biz_fixture(runner, gf, 'q015_inc_add_bill_v2.txt', tmp_path)
    assert r.exit_code == 0, f'v2: {r.output}'
    snap2 = _snapshot(gf, business_id='BILL-INC-ADD-100', is_bill=True)

    assert snap2['posting_guid'] == snap1['posting_guid'], (
        f"Bill posting GUID must NOT change. Before {snap1['posting_guid']}, "
        f"after {snap2['posting_guid']}"
    )
    assert snap2['entry_guids'] == snap1['entry_guids'], (
        'Bill entry GUIDs must NOT change.'
    )
    original_payment_guid = snap1['lot_payment_tx_guids'][0]
    assert original_payment_guid in snap2['lot_payment_tx_guids'], (
        f"Original bill payment {original_payment_guid} must remain attached "
        f"to the AP lot. Got: {snap2['lot_payment_tx_guids']}"
    )
    assert len(snap2['bank_tx_by_guid']) == 2, (
        f"Bank account should hold exactly 2 transactions for the bill "
        f"(original $60 + new $40), not duplicates. "
        f"Got {len(snap2['bank_tx_by_guid'])}"
    )
