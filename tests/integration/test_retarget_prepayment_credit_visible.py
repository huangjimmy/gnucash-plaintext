"""Linking an over-paying existing deposit to an invoice must leave the residual
credit **owner-attached**, so it is visible to `find-prepayments` /
`export-accounts` (which only surface credits on owner-attached lots).

The `ApplyPayment` overpayment path attaches the owner automatically, and the
standalone-credit `lot_owner:` path attaches it explicitly. The `txn_guid:`
retarget-with-prepayment path (`_retarget_with_prepayment_split`) creates the
residual pre-payment lot but historically forgot to attach the owner, so the
credit existed in the book yet was invisible to the credit-listing commands —
no badge for downstream tools. This pins that the retarget residual is surfaced.
"""

import time
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS_PATH = 'tests/fixtures/payment_roundtrip_accounts.txt'
FIXTURES_DIR = Path('tests/fixtures')


def _fixture(name):
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


def _bank_tx_guid(gf, amount, bank='Assets.Bank'):
    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        def find(acct, name):
            if acct.get_full_name() == name:
                return acct
            for child in acct.get_children():
                got = find(child, name)
                if got:
                    return got
            return None
        b = find(repo.book.get_root_account(), bank)
        for sp in b.GetSplitList():
            if abs(sp.GetAmount().to_double() - amount) < 0.001:
                return sp.GetParent().GetGUID().to_string()
        return None
    finally:
        repo.close()


def _ownerless_credit_lots(gf):
    """The book's open AR/AP credit lots that have no owner — the healthy
    invariant is an empty list."""
    from repositories.gnucash_repository import GnuCashRepository
    from use_cases.export_transactions import find_ownerless_credit_lots
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        return find_ownerless_credit_lots(repo.book)
    finally:
        repo.close()


def _craft_ownerless_ar_credit(gf, amount=-77.0):
    """Directly park an AR credit split in a lot with NO owner attached — the
    exact defect the guard must catch (what a buggy import path would leave)."""
    import ctypes

    from gnucash import GncNumeric, Split, Transaction

    from infrastructure.gnucash.engine import load_gnc_engine
    from repositories.gnucash_repository import GnuCashRepository

    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        book = repo.book

        def find(acct, name):
            if acct.get_full_name() == name:
                return acct
            for child in acct.get_children():
                got = find(child, name)
                if got:
                    return got
            return None

        root = book.get_root_account()
        ar = find(root, 'Assets.Accounts Receivable')
        bank = find(root, 'Assets.Bank')
        comm = ar.GetCommodity()

        trans = Transaction(book)
        trans.BeginEdit()
        trans.SetCurrency(comm)
        trans.SetDate(1, 1, 2026)
        cents = int(round(amount * 100))
        s_ar = Split(book)
        s_ar.SetParent(trans)
        s_ar.SetAccount(ar)
        s_ar.SetValue(GncNumeric(cents, 100))
        s_ar.SetAmount(GncNumeric(cents, 100))
        s_bk = Split(book)
        s_bk.SetParent(trans)
        s_bk.SetAccount(bank)
        s_bk.SetValue(GncNumeric(-cents, 100))
        s_bk.SetAmount(GncNumeric(-cents, 100))
        trans.CommitEdit()

        lib = load_gnc_engine()
        lib.gnc_lot_new.argtypes = [ctypes.c_void_p]
        lib.gnc_lot_new.restype = ctypes.c_void_p
        lib.xaccAccountInsertLot.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.xaccAccountInsertLot.restype = None
        lib.gnc_lot_add_split.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.gnc_lot_add_split.restype = None
        lot = lib.gnc_lot_new(int(book.instance))
        lib.xaccAccountInsertLot(int(ar.instance), lot)
        lib.gnc_lot_add_split(lot, int(s_ar.instance))

        repo.save()
    finally:
        repo.close()


def _setup_retarget_overpayment(runner, tmp_path):
    """Build the book where an external $150 deposit is linked to a $100 invoice
    for customer C004, declaring the $50 residual as a pre-payment (the
    `txn_guid:` retarget-with-prepayment path). Returns the book path."""
    gf = _setup_book(runner, tmp_path)
    # Pre-create the external $150 deposit (bank-side tx with an Imbalance
    # counter-split), the way a bank-feed import would.
    r = _import_text(runner, gf, _fixture('q015_oh_retarget_over_pre_bank.txt'),
                     'pre_bank.txt', tmp_path, biz=False)
    assert r.exit_code == 0, r.output
    time.sleep(1)
    bank_guid = _bank_tx_guid(gf, 150.0)
    assert bank_guid is not None
    biz = _fixture('q015_oh_retarget_over_biz.txt').replace('{txn_guid}', bank_guid)
    r = _import_text(runner, gf, biz, 'inv.txt', tmp_path)
    assert r.exit_code == 0, f'retarget+prepayment import failed: {r.output}'
    time.sleep(1)
    return gf


def test_retarget_overpayment_residual_credit_in_export_accounts(tmp_path):
    """`export-accounts` emits the per-account `open_prepayment:` summary from
    owner-attached AR/AP lots (gncOwnerGetOwnerFromLot). The retargeted residual
    must carry its owner so the credit shows up here — otherwise it is a silent
    open credit invisible to downstream badge tooling."""
    runner = CliRunner()
    gf = _setup_retarget_overpayment(runner, tmp_path)

    out = tmp_path / 'accounts.txt'
    r = runner.invoke(cli, ['export-accounts', str(gf), str(out)])
    assert r.exit_code == 0, r.output
    text = out.read_text()

    assert 'open_prepayment:' in text, (
        f'the retargeted $50 residual must surface as an open_prepayment block; '
        f'export-accounts output:\n{text}'
    )
    assert 'customer: "C004"' in text, text
    assert 'amount: 50.00 CAD' in text, text


def test_bill_retarget_overpayment_residual_credit_in_export_accounts(tmp_path):
    """Symmetric vendor case: linking an over-paying outflow to a bill must
    leave the residual vendor credit owner-attached and visible."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)

    r = _import_text(runner, gf, _fixture('q015_oh_bill_retarget_over_pre_bank.txt'),
                     'pre_bank.txt', tmp_path, biz=False)
    assert r.exit_code == 0, r.output
    time.sleep(1)
    bank_guid = _bank_tx_guid(gf, -150.0)
    assert bank_guid is not None
    biz = _fixture('q015_oh_bill_retarget_over_biz.txt').replace('{txn_guid}', bank_guid)
    r = _import_text(runner, gf, biz, 'bill.txt', tmp_path)
    assert r.exit_code == 0, f'bill retarget+prepayment import failed: {r.output}'
    time.sleep(1)

    out = tmp_path / 'accounts.txt'
    r = runner.invoke(cli, ['export-accounts', str(gf), str(out)])
    assert r.exit_code == 0, r.output
    text = out.read_text()
    assert 'open_prepayment:' in text, (
        f'the retargeted $50 vendor residual must surface; output:\n{text}'
    )
    assert 'vendor: "V003"' in text, text
    assert 'amount: 50.00 CAD' in text, text


def test_retarget_overpayment_leaves_no_ownerless_credit_lot(tmp_path):
    """Structural invariant: a residual credit must always be owner-attached.
    Catches the bug class directly — on the pre-fix code the residual lot was
    ownerless and this list was non-empty."""
    runner = CliRunner()
    gf = _setup_retarget_overpayment(runner, tmp_path)
    assert _ownerless_credit_lots(gf) == [], (
        f'a retarget overpayment must not leave an ownerless credit lot; '
        f'found: {_ownerless_credit_lots(gf)}'
    )


def test_find_prepayments_warns_on_ownerless_credit_lot(tmp_path):
    """The CLI guard: if an ownerless credit lot ever exists, find-prepayments
    must surface it loudly rather than let it hide. Crafts the defect directly."""
    runner = CliRunner()
    gf = _setup_book(runner, tmp_path)
    _craft_ownerless_ar_credit(gf, amount=-77.0)
    time.sleep(1)

    # The guard sees the ownerless lot...
    found = _ownerless_credit_lots(gf)
    assert len(found) == 1 and abs(found[0][1] - 77.0) < 0.01, found

    # ...and find-prepayments warns about it.
    r = runner.invoke(cli, ['find-prepayments', str(gf)])
    assert r.exit_code == 0, r.output
    out = r.output.lower()
    assert 'no owner' in out or 'ownerless' in out, r.output
    assert '77' in r.output, r.output
