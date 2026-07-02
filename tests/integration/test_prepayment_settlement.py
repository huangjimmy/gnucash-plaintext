"""A standalone transaction whose AR/AP split carries `lot_owner: kind:id[:guid]`
settles that owner's open prepayment credit.

The split joins the owner's open prepayment lot via the primitive lot-split path
(not gncOwnerApplyPaymentSecs, which segfaults on GnuCash 4.4/4.8). The counter
split's account decides the meaning — a bank account is a refund, an expense a
vendor bad-debt write-off, an income a customer forfeit — but every case is the
same "join the open prepayment lot". A clearing-shaped split with no credit to
reduce is rejected, and a `lot_owner:` guid that disagrees with the id is a hard
error. Closed credits round-trip: the clearing exports as `lot_owner:` and a
fresh re-import rebuilds the settlement.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS_PATH = 'tests/fixtures/payment_roundtrip_accounts.txt'
FIXTURES_DIR = Path('tests/fixtures')


def _fixture(name):
    return (FIXTURES_DIR / name).read_text()


def _new_book(runner, tmp_path, name='book.gnucash'):
    gf = tmp_path / name
    r = runner.invoke(cli, ['import', '--new', str(gf), ACCOUNTS_PATH])
    assert r.exit_code == 0, r.output
    return gf


def _import_fixture(runner, gf, fixture_name, tmp_path, alias=None):
    p = tmp_path / (alias or fixture_name)
    p.write_text(_fixture(fixture_name))
    return runner.invoke(cli, ['import', str(gf), str(p),
                               '--include-business-objects'])


def _import_primer(runner, gf, fixture_name, tmp_path):
    r = _import_fixture(runner, gf, fixture_name, tmp_path, alias='primer.txt')
    assert r.exit_code == 0, r.output


def _setup_customer_credit(runner, tmp_path):
    """C001 (Acme) holds a −$50 open AR credit (INV-001 $100 paid $150)."""
    gf = _new_book(runner, tmp_path)
    _import_primer(runner, gf, 'q015_aac_primer_invoice.txt', tmp_path)
    return gf


def _setup_vendor_credit(runner, tmp_path):
    """V001 (Supplier) holds a +$50 open AP credit (BILL-001 $100 paid $150)."""
    gf = _new_book(runner, tmp_path)
    _import_primer(runner, gf, 'q015_aac_primer_bill.txt', tmp_path)
    return gf


def _lots(gf, account):
    """List of {closed, balance} for every lot on the named account."""
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
        acct = find(repo.book.get_root_account(), account)
        seen, lots = set(), []
        for sp in acct.GetSplitList():
            raw = sp.GetLot()
            if raw is None or int(raw) in seen:
                continue
            seen.add(int(raw))
            lot = GncLot(instance=raw)
            lots.append({'closed': lot.is_closed(),
                         'balance': round(lot.get_balance().to_double(), 2)})
        return lots
    finally:
        repo.close()


def _open_nonzero(lots):
    return [lt for lt in lots if not lt['closed'] and abs(lt['balance']) > 0.001]


def _balances(gf, names=('Assets.Bank', 'Assets.Accounts Receivable',
                         'Liabilities.Accounts Payable', 'Income',
                         'Expenses.Supplies')):
    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        out = {}

        def walk(a):
            out[a.get_full_name()] = round(a.GetBalance().to_double(), 2)
            for c in a.get_children():
                walk(c)
        walk(repo.book.get_root_account())
        return {n: out.get(n, 0.0) for n in names}
    finally:
        repo.close()


# --------------------------------------------------------------------------
# Clearing closes the credit, every counter-account flavour and both owners.
# --------------------------------------------------------------------------

def test_customer_refund_closes_credit(tmp_path):
    runner = CliRunner()
    gf = _setup_customer_credit(runner, tmp_path)
    assert any(not lt['closed'] and lt['balance'] == -50.0
               for lt in _lots(gf, 'Assets.Accounts Receivable'))
    r = _import_fixture(runner, gf, 'q_refund_prepayment.txt', tmp_path)
    assert r.exit_code == 0, r.output
    assert _open_nonzero(_lots(gf, 'Assets.Accounts Receivable')) == []


def test_customer_forfeit_to_income_closes_credit(tmp_path):
    runner = CliRunner()
    gf = _setup_customer_credit(runner, tmp_path)
    r = _import_fixture(runner, gf, 'q_customer_forfeit.txt', tmp_path)
    assert r.exit_code == 0, r.output
    assert _open_nonzero(_lots(gf, 'Assets.Accounts Receivable')) == []
    # The forfeited credit became income (a gain).
    assert _balances(gf)['Income'] <= -50.0


def test_vendor_refund_received_closes_credit(tmp_path):
    runner = CliRunner()
    gf = _setup_vendor_credit(runner, tmp_path)
    assert any(not lt['closed'] and lt['balance'] == 50.0
               for lt in _lots(gf, 'Liabilities.Accounts Payable'))
    r = _import_fixture(runner, gf, 'q_vendor_refund.txt', tmp_path)
    assert r.exit_code == 0, r.output
    assert _open_nonzero(_lots(gf, 'Liabilities.Accounts Payable')) == []


def test_vendor_bad_debt_writes_off_credit(tmp_path):
    runner = CliRunner()
    gf = _setup_vendor_credit(runner, tmp_path)
    r = _import_fixture(runner, gf, 'q_vendor_bad_debt.txt', tmp_path)
    assert r.exit_code == 0, r.output
    assert _open_nonzero(_lots(gf, 'Liabilities.Accounts Payable')) == []
    # The unrecoverable overpayment was booked as an expense (our loss):
    # +100 from the posted bill plus +50 from the write-off.
    assert _balances(gf)['Expenses.Supplies'] >= 50.0


def test_partial_refund_leaves_residual_credit(tmp_path):
    runner = CliRunner()
    gf = _setup_customer_credit(runner, tmp_path)
    r = _import_fixture(runner, gf, 'q_partial_refund.txt', tmp_path)
    assert r.exit_code == 0, r.output
    open_lots = _open_nonzero(_lots(gf, 'Assets.Accounts Receivable'))
    assert open_lots == [{'closed': False, 'balance': -30.0}], open_lots


# --------------------------------------------------------------------------
# Rejections — clear error, book left untouched.
# --------------------------------------------------------------------------

def test_clearing_rejected_when_no_open_credit(tmp_path):
    runner = CliRunner()
    gf = _setup_customer_credit(runner, tmp_path)
    r = _import_fixture(runner, gf, 'q_refund_prepayment.txt', tmp_path, alias='r1.txt')
    assert r.exit_code == 0, r.output
    settled_lots = _lots(gf, 'Assets.Accounts Receivable')
    settled_bal = _balances(gf)

    # No credit left → the clearing-shaped split has nothing to reduce.
    r = _import_fixture(runner, gf, 'q_refund_prepayment.txt', tmp_path, alias='r2.txt')
    assert r.exit_code == 0, r.output
    assert 'Errors:       1' in r.output, r.output
    assert 'no open credit' in r.output.lower(), r.output
    assert _lots(gf, 'Assets.Accounts Receivable') == settled_lots
    assert _balances(gf) == settled_bal


def test_customer_lot_owner_on_ap_split_is_rejected(tmp_path):
    runner = CliRunner()
    gf = _setup_customer_credit(runner, tmp_path)
    before = _balances(gf)
    r = _import_fixture(runner, gf, 'q_lot_owner_ap_mismatch.txt', tmp_path)
    assert r.exit_code == 0, r.output
    assert 'Errors:       1' in r.output, r.output
    assert 'receivable' in r.output.lower(), r.output
    assert _balances(gf) == before


def test_lot_owner_guid_mismatch_is_rejected(tmp_path):
    runner = CliRunner()
    gf = _setup_customer_credit(runner, tmp_path)
    before = _balances(gf)
    r = _import_fixture(runner, gf, 'q_lot_owner_guid_mismatch.txt', tmp_path)
    assert r.exit_code == 0, r.output
    assert 'Errors:       1' in r.output, r.output
    assert 'guid' in r.output.lower(), r.output
    assert _balances(gf) == before


# --------------------------------------------------------------------------
# Standalone credit (no invoice): lot_owner CREATE makes the credit, then a
# clearing JOINs it — and the whole thing survives export → fresh re-import.
# --------------------------------------------------------------------------

def _setup_standalone_credit(runner, tmp_path):
    """C001 holds a −$50 open AR credit created directly via `lot_owner`
    (a standalone prepayment received before any invoice)."""
    gf = _new_book(runner, tmp_path)
    r = _import_fixture(runner, gf, 'q_customer_only.txt', tmp_path, alias='cust.txt')
    assert r.exit_code == 0, r.output
    r = _import_fixture(runner, gf, 'q_standalone_credit.txt', tmp_path, alias='credit.txt')
    assert r.exit_code == 0, r.output
    return gf


def test_standalone_credit_created_then_settled(tmp_path):
    runner = CliRunner()
    gf = _setup_standalone_credit(runner, tmp_path)
    # The lot_owner CREATE branch made a −50 credit from a plaintext tx.
    assert any(not lt['closed'] and lt['balance'] == -50.0
               for lt in _lots(gf, 'Assets.Accounts Receivable'))
    r = _import_fixture(runner, gf, 'q_refund_prepayment.txt', tmp_path)
    assert r.exit_code == 0, r.output
    assert _open_nonzero(_lots(gf, 'Assets.Accounts Receivable')) == []


def test_clearing_roundtrips_into_fresh_book(tmp_path):
    runner = CliRunner()
    gf = _setup_standalone_credit(runner, tmp_path)
    r = _import_fixture(runner, gf, 'q_refund_prepayment.txt', tmp_path)
    assert r.exit_code == 0, r.output
    assert _open_nonzero(_lots(gf, 'Assets.Accounts Receivable')) == []

    # Export the settled book; both the origin and the clearing carry lot_owner.
    exported = tmp_path / 'export.txt'
    r = runner.invoke(cli, ['export', str(gf), str(exported),
                            '--include-business-objects'])
    assert r.exit_code == 0, r.output
    text = exported.read_text()
    assert 'lot_owner: customer:C001:' in text, text

    # Re-import into a brand-new empty book: CREATE then JOIN, same end-state.
    gf2 = tmp_path / 'fresh.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf2), str(exported),
                            '--include-business-objects'])
    assert r.exit_code == 0, r.output
    assert _open_nonzero(_lots(gf2, 'Assets.Accounts Receivable')) == []


# --------------------------------------------------------------------------
# Per-account open_prepayment summary: emitted on export (incl. export-accounts),
# informational, ignored on re-import.
# --------------------------------------------------------------------------

def test_open_prepayment_summary_in_export_accounts(tmp_path):
    runner = CliRunner()
    gf = _setup_standalone_credit(runner, tmp_path)  # C001 holds a −50 credit
    out = tmp_path / 'accounts.txt'
    r = runner.invoke(cli, ['export-accounts', str(gf), str(out)])
    assert r.exit_code == 0, r.output
    text = out.read_text()
    assert 'open_prepayment:' in text, text
    assert 'customer: "C001"' in text, text
    assert 'customer_guid:' in text, text
    assert 'amount: 50.00 CAD' in text, text


def test_open_prepayment_summary_roundtrips(tmp_path):
    runner = CliRunner()
    gf = _setup_standalone_credit(runner, tmp_path)
    exported = tmp_path / 'export.txt'
    r = runner.invoke(cli, ['export', str(gf), str(exported),
                            '--include-business-objects'])
    assert r.exit_code == 0, r.output
    assert 'open_prepayment:' in exported.read_text()

    # Re-import: the open_prepayment block is parsed and ignored (informational);
    # the credit is rebuilt from the lot_owner markers, not from the summary.
    gf2 = tmp_path / 'fresh.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf2), str(exported),
                            '--include-business-objects'])
    assert r.exit_code == 0, r.output
    assert any(not lt['closed'] and lt['balance'] == -50.0
               for lt in _lots(gf2, 'Assets.Accounts Receivable'))


def test_open_prepayment_mismatch_warns_but_does_not_fail(tmp_path):
    runner = CliRunner()
    gf = _setup_standalone_credit(runner, tmp_path)
    exported = tmp_path / 'export.txt'
    r = runner.invoke(cli, ['export', str(gf), str(exported),
                            '--include-business-objects'])
    assert r.exit_code == 0, r.output
    text = exported.read_text()
    assert 'amount: 50.00 CAD' in text, text

    # Tamper the (informational) summary to a wrong figure, then re-import: the
    # book's actual credit is still 50, so the import warns and still succeeds.
    tampered = tmp_path / 'tampered.txt'
    tampered.write_text(text.replace('amount: 50.00 CAD', 'amount: 99.00 CAD'))
    gf2 = tmp_path / 'fresh.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf2), str(tampered),
                            '--include-business-objects'])
    assert r.exit_code == 0, r.output
    assert 'warning' in r.output.lower() and 'open_prepayment' in r.output.lower(), r.output
    # The book reflects reality (50), not the tampered figure.
    assert any(not lt['closed'] and lt['balance'] == -50.0
               for lt in _lots(gf2, 'Assets.Accounts Receivable'))
