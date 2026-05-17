"""Q-015 expanded scope: overpayment / pre-payment exports + retargeting.

When a customer pays more than the invoice total (or a bill is overpaid
to a vendor), GnuCash's `ApplyPayment` automatically splits the payment
transaction:

  * one AR/AP-side split for the invoice/bill total → into the invoice's
    posted lot (closes it),
  * a second AR/AP-side split for the residual → into a new pre-payment
    lot on the AR/AP account.

Our exporter currently only emits a single `payment:` line with the
total bank-side amount. The pre-payment lot is invisible in plaintext.
These tests pin the desired behavior of a `prepayment:` field in the
payment block:

* exporter emits `prepayment: N` when a payment tx has AR/AP-side splits
  outside the invoice/bill lot,
* round-trip preserves the value and the pre-payment lot,
* the `txn_guid:` retarget path requires `prepayment:` when the bank
  tx amount exceeds the invoice/bill remaining (otherwise an explicit
  error — silently retargeting an oversize counter-split would leave the
  lot in an undefined state).

Symmetric bill (AP) tests included.
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
    assert r.exit_code == 0, r.output
    time.sleep(1)
    return gf


def _import_text(runner, gf, content, name, tmp_path, biz=True):
    p = tmp_path / name
    p.write_text(content)
    args = ['import', str(gf), str(p)]
    if biz:
        args.append('--include-business-objects')
    return runner.invoke(cli, args)


def _import_fixture(runner, gf, fixture_name, tmp_path, biz=True, alias=None):
    return _import_text(runner, gf, _fixture(fixture_name),
                        alias or fixture_name, tmp_path, biz=biz)


def _export(runner, gf, tmp_path, name):
    out = tmp_path / name
    r = runner.invoke(cli, ['export', str(gf), str(out), '--include-business-objects'])
    return r, out.read_text() if r.exit_code == 0 else ''


def _ar_lot_state(gf, ar_account='Assets.Accounts Receivable'):
    """Return [{is_closed, balance, members_count}] for every lot on the
    AR/AP account that has at least one split."""
    from gnucash import GncLot, Split

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
        ar = find(repo.book.get_root_account(), ar_account)
        if ar is None:
            return []
        seen = set()
        out = []
        for s in ar.GetSplitList():
            raw_lot = s.GetLot()
            if raw_lot is None:
                continue
            key = int(raw_lot)
            if key in seen:
                continue
            seen.add(key)
            lot = GncLot(instance=raw_lot)
            members = list(lot.get_split_list())
            out.append({
                'is_closed': lot.is_closed(),
                'balance': lot.get_balance().to_double(),
                'members': len(members),
            })
        return sorted(out, key=lambda d: (d['is_closed'], d['balance']))
    finally:
        repo.close()


def _bank_tx_count(gf, bank='Assets.Bank'):
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
        b = find(repo.book.get_root_account(), bank)
        if b is None:
            return 0
        return len({sp.GetParent().GetGUID().to_string() for sp in b.GetSplitList()})
    finally:
        repo.close()


def _bank_tx_guid(gf, bank='Assets.Bank', amount=None):
    """Return the GUID of the (single, by default) bank tx, optionally
    filtered to a specific amount."""
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
        b = find(repo.book.get_root_account(), bank)
        for sp in b.GetSplitList():
            if amount is None or abs(sp.GetAmount().to_double() - amount) < 0.001:
                return sp.GetParent().GetGUID().to_string()
        return None
    finally:
        repo.close()


# -- 1. ApplyPayment overpayment: export must emit `prepayment:` ----------

def test_invoice_overpayment_export_emits_prepayment_field(tmp_path):
    """INV-OH-EXP-100 $100 paid $150 → exporter must emit `prepayment: 50`."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)

    r = _import_fixture(runner, gf, 'q015_oh_inv_export_emits.txt', tmp_path)
    assert r.exit_code == 0, r.output
    time.sleep(1)

    _, exported = _export(runner, gf, tmp_path, 'r1.txt')
    # The exported invoice block must include `prepayment: 50`.
    assert 'prepayment: 50' in exported, (
        f"Exporter must emit `prepayment: 50` for the $50 overpayment "
        f"residual. Exported plaintext:\n{exported}"
    )


def test_invoice_overpayment_roundtrip_preserves_prepayment_lot(tmp_path):
    """INV-OH-RT-110 $110 paid $160 → prepayment lot of $50 must round-trip."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)

    r = _import_fixture(runner, gf, 'q015_oh_inv_roundtrip_preserves.txt', tmp_path)
    assert r.exit_code == 0, r.output
    time.sleep(1)
    initial_lots = _ar_lot_state(gf)
    initial_bank = _bank_tx_count(gf)
    assert initial_bank == 1
    assert len(initial_lots) == 2, f'expected 2 AR lots (invoice + prepayment), got: {initial_lots}'
    # invoice lot: closed, balance 0; prepayment lot: open, balance -50
    assert any(lot['is_closed'] and lot['balance'] == 0.0 for lot in initial_lots)
    assert any(not lot['is_closed'] and lot['balance'] == -50.0 for lot in initial_lots)

    _, exported = _export(runner, gf, tmp_path, 'r1.txt')
    r = _import_text(runner, gf, exported, 'r1_in.txt', tmp_path)
    assert r.exit_code == 0, f're-import: {r.output}'

    final_lots = _ar_lot_state(gf)
    final_bank = _bank_tx_count(gf)
    assert final_bank == 1, (
        f'roundtrip must not duplicate the bank tx for overpayment. '
        f'before={initial_bank} after={final_bank}'
    )
    assert final_lots == initial_lots, (
        f'AR lot state changed after roundtrip.\nbefore: {initial_lots}\nafter:  {final_lots}'
    )


def test_invoice_overpayment_double_roundtrip_no_lot_accumulation(tmp_path):
    """INV-OH-DBL-120 $120 paid $170 → two roundtrips must not accumulate lots."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)
    r = _import_fixture(runner, gf, 'q015_oh_inv_double_roundtrip.txt', tmp_path)
    assert r.exit_code == 0
    time.sleep(1)
    initial = _ar_lot_state(gf)

    for i in (1, 2):
        _, exported = _export(runner, gf, tmp_path, f'r{i}.txt')
        r = _import_text(runner, gf, exported, f'r{i}_in.txt', tmp_path)
        assert r.exit_code == 0, f'round {i}: {r.output}'
        time.sleep(1)
        current = _ar_lot_state(gf)
        assert current == initial, (
            f'double roundtrip drifted AR lots.\nstart: {initial}\nround{i}: {current}'
        )
        assert _bank_tx_count(gf) == 1


# -- 2. Retarget path overpayment: explicit `prepayment:` required --------


def test_retarget_overpayment_with_explicit_prepayment_succeeds(tmp_path):
    """Bank tx for $150 retargeted to a $100 invoice — must split the
    counter-split: $100 to invoice lot, $50 to a new pre-payment lot."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)

    # Pre-create the bank tx for $150
    r = _import_fixture(runner, gf, 'q015_oh_retarget_over_pre_bank.txt',
                        tmp_path, biz=False, alias='pre_bank.txt')
    assert r.exit_code == 0, r.output
    time.sleep(1)
    bank_guid = _bank_tx_guid(gf, amount=150.0)
    assert bank_guid is not None

    # Now import the invoice that retargets that bank tx, declaring a $50 prepayment.
    biz = _fixture('q015_oh_retarget_over_biz.txt').replace('{txn_guid}', bank_guid)
    r = _import_text(runner, gf, biz, 'inv.txt', tmp_path)
    assert r.exit_code == 0, f'retarget+prepayment import failed: {r.output}'
    time.sleep(1)

    assert _bank_tx_count(gf) == 1, 'no new bank tx must be created on retarget'
    assert _bank_tx_guid(gf, amount=150.0) == bank_guid, 'original bank tx GUID preserved'

    lots = _ar_lot_state(gf)
    assert len(lots) == 2, f'must create 2 AR lots (invoice + prepayment); got {lots}'
    assert any(lot['is_closed'] and lot['balance'] == 0.0 for lot in lots), (
        f'invoice lot must close at balance 0: {lots}'
    )
    assert any(not lot['is_closed'] and lot['balance'] == -50.0 for lot in lots), (
        f'prepayment lot must be open with balance -50: {lots}'
    )


def test_retarget_overpayment_without_prepayment_fails_with_clear_error(tmp_path):
    """Bank tx for $150 retargeted to a $100 invoice without specifying
    `prepayment: 50` — silently retargeting an oversize counter-split
    leaves the invoice lot at balance -$50, semantically broken. The
    importer must refuse and tell the user what's wrong."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)
    r = _import_fixture(runner, gf, 'q015_oh_retarget_nopre_pre_bank.txt',
                        tmp_path, biz=False, alias='pre_bank.txt')
    assert r.exit_code == 0, r.output
    time.sleep(1)
    bank_guid = _bank_tx_guid(gf, amount=150.0)

    biz = _fixture('q015_oh_retarget_nopre_biz.txt').replace('{txn_guid}', bank_guid)
    r = _import_text(runner, gf, biz, 'inv.txt', tmp_path)
    assert r.exit_code != 0, (
        f'retargeting $150 to a $100 invoice without `prepayment:` must fail. '
        f'Got exit={r.exit_code}, output:\n{r.output}'
    )
    msg = r.output.lower()
    assert ('prepayment' in msg or 'overpay' in msg
            or 'exceeds' in msg or 'remaining' in msg), (
        f'error must explain the amount mismatch and point at `prepayment:`. '
        f'Output:\n{r.output}'
    )


def test_retarget_exact_amount_still_works(tmp_path):
    """Sanity: when the bank tx amount equals the invoice remaining,
    the retarget path with no `prepayment:` field works as before."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)

    r = _import_fixture(runner, gf, 'q015_oh_retarget_exact_pre_bank.txt',
                        tmp_path, biz=False, alias='pre.txt')
    assert r.exit_code == 0
    time.sleep(1)
    bank_guid = _bank_tx_guid(gf, amount=100.0)

    biz = _fixture('q015_oh_retarget_exact_biz.txt').replace('{txn_guid}', bank_guid)
    r = _import_text(runner, gf, biz, 'inv.txt', tmp_path)
    assert r.exit_code == 0, f'exact retarget: {r.output}'
    lots = _ar_lot_state(gf)
    assert len(lots) == 1
    assert lots[0]['is_closed']
    assert lots[0]['balance'] == 0.0


def test_retarget_underpayment_still_works(tmp_path):
    """Bank tx for $60 retargeted to a $100 invoice — partial payment
    via retarget; lot remains open with balance +$40 (invoice $100 − paid $60)."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)

    r = _import_fixture(runner, gf, 'q015_oh_retarget_under_pre_bank.txt',
                        tmp_path, biz=False, alias='pre.txt')
    assert r.exit_code == 0
    time.sleep(1)
    bank_guid = _bank_tx_guid(gf, amount=60.0)

    biz = _fixture('q015_oh_retarget_under_biz.txt').replace('{txn_guid}', bank_guid)
    r = _import_text(runner, gf, biz, 'inv.txt', tmp_path)
    assert r.exit_code == 0, f'partial retarget: {r.output}'
    lots = _ar_lot_state(gf)
    assert len(lots) == 1, f'partial payment must produce 1 lot, got {lots}'
    assert not lots[0]['is_closed']
    assert lots[0]['balance'] == 40.0, (
        f'partial payment lot should have +$40 remaining (invoice $100 - paid $60), '
        f'got balance={lots[0]["balance"]}'
    )


# -- 3. Bill counterparts -------------------------------------------------

def test_bill_overpayment_export_emits_prepayment_field(tmp_path):
    """BILL-OH-EXP-100 $100 paid $150 → exporter must emit `prepayment: 50`."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)
    r = _import_fixture(runner, gf, 'q015_oh_bill_export_emits.txt', tmp_path)
    assert r.exit_code == 0, r.output
    time.sleep(1)

    _, exported = _export(runner, gf, tmp_path, 'r1.txt')
    assert 'prepayment: 50' in exported, (
        f'bill overpayment must export `prepayment: 50`. exported:\n{exported}'
    )


def test_bill_overpayment_roundtrip_preserves_prepayment_lot(tmp_path):
    """BILL-OH-RT-110 $110 paid $160 → prepayment lot of $50 must round-trip."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)
    r = _import_fixture(runner, gf, 'q015_oh_bill_roundtrip_preserves.txt', tmp_path)
    assert r.exit_code == 0, r.output
    time.sleep(1)
    initial_lots = _ar_lot_state(gf, ar_account='Liabilities.Accounts Payable')
    assert _bank_tx_count(gf) == 1
    assert len(initial_lots) == 2, (
        f'bill overpayment must produce 2 AP lots (bill + prepayment), got {initial_lots}'
    )
    # AP signs are opposite to AR: bill posts CR AP -100, payment DR AP +100,
    # extra overpayment DR AP +50 in a new lot (positive balance).
    assert any(lot['is_closed'] and lot['balance'] == 0.0 for lot in initial_lots)
    assert any(not lot['is_closed'] and lot['balance'] == 50.0 for lot in initial_lots)

    _, exported = _export(runner, gf, tmp_path, 'r1.txt')
    r = _import_text(runner, gf, exported, 'r1_in.txt', tmp_path)
    assert r.exit_code == 0, f'bill re-import: {r.output}'

    final_lots = _ar_lot_state(gf, ar_account='Liabilities.Accounts Payable')
    assert _bank_tx_count(gf) == 1
    assert final_lots == initial_lots, (
        f'bill overpayment roundtrip drifted.\nbefore: {initial_lots}\nafter: {final_lots}'
    )


def test_bill_retarget_overpayment_with_explicit_prepayment_succeeds(tmp_path):
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)
    r = _import_fixture(runner, gf, 'q015_oh_bill_retarget_over_pre_bank.txt',
                        tmp_path, biz=False, alias='pre_bank.txt')
    assert r.exit_code == 0, r.output
    time.sleep(1)
    bank_guid = _bank_tx_guid(gf, amount=-150.0)
    assert bank_guid is not None

    biz = _fixture('q015_oh_bill_retarget_over_biz.txt').replace('{txn_guid}', bank_guid)
    r = _import_text(runner, gf, biz, 'bill.txt', tmp_path)
    assert r.exit_code == 0, f'bill retarget+prepayment failed: {r.output}'
    time.sleep(1)

    assert _bank_tx_count(gf) == 1
    lots = _ar_lot_state(gf, ar_account='Liabilities.Accounts Payable')
    assert len(lots) == 2
    assert any(lot['is_closed'] and lot['balance'] == 0.0 for lot in lots)
    assert any(not lot['is_closed'] and lot['balance'] == 50.0 for lot in lots)


def test_bill_retarget_overpayment_without_prepayment_fails(tmp_path):
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)
    r = _import_fixture(runner, gf, 'q015_oh_bill_retarget_nopre_pre_bank.txt',
                        tmp_path, biz=False, alias='pre_bank.txt')
    assert r.exit_code == 0
    time.sleep(1)
    bank_guid = _bank_tx_guid(gf, amount=-150.0)

    biz = _fixture('q015_oh_bill_retarget_nopre_biz.txt').replace('{txn_guid}', bank_guid)
    r = _import_text(runner, gf, biz, 'bill.txt', tmp_path)
    assert r.exit_code != 0, (
        f'bill retarget overpayment without `prepayment:` must fail. '
        f'Got exit={r.exit_code}'
    )
