"""A taxed bill paid by a MIX of a fresh payment and a linked bank tx, then
peeled apart with `unapply-payment` and re-linked.

The bill: net 1000 + GST 5% ($50) + PST 7% ($70) = $1120 total. It is
settled by two partial payments of different kinds:

  * payment 1 — a fresh `ApplyPayment` of $1000 (no `txn_guid:`), which
    mints its own bank transaction,
  * payment 2 — a LINK of a pre-existing $120 bank transaction (a
    `payment:` block whose `txn_guid:` retargets that tx's AP split into
    the bill's lot).

From the fully-paid state this module exercises the real correction
workflows a user hits:

  * unapply only the linked $120 (they linked the wrong tx) → bill drops
    to partially-paid with $120 outstanding, the $120 bank tx survives,
  * unapply BOTH (`--all`) → bill fully outstanding at $1120,
  * unapply only the fresh $1000 → the linked $120 stays applied,
  * unapply the $1000 then LINK a different pre-existing $1000 bank tx →
    bill settled again by the new tx.

Sign convention (AP, per CLAUDE.md §7): the bill posts CR AP −1120; each
payment is DR AP +N into the lot; the posted-lot balance is 0 when
settled and negative while still owed.
"""
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.utils import wrap_invoice_or_bill

FIXTURES = Path('tests/fixtures')
ACCOUNTS = str(FIXTURES / 'q019_accounts.txt')
TO = 'Liabilities'  # re-home freed splits here (any account type is accepted)


def _fx(name):
    return (FIXTURES / name).read_text()


def _bank_tx_guid(gf, amount):
    """GUID of the bank transaction whose Assets:Bank split == amount."""
    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        from infrastructure.gnucash.utils import get_account_full_name

        def find(a, name):
            if get_account_full_name(a) == name:
                return a
            for c in a.get_children():
                g = find(c, name)
                if g:
                    return g
            return None
        bank = find(repo.book.get_root_account(), 'Assets:Bank')
        for s in bank.GetSplitList():
            if round(s.GetAmount().to_double(), 2) == round(amount, 2):
                return s.GetParent().GetGUID().to_string()
        return None
    finally:
        repo.close()


def _posted_lot_balance(gf, bill_id):
    import gnucash.gnucash_business as gb
    from gnucash import Query

    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        q = Query()
        q.search_for('gncInvoice')
        q.set_book(repo.book)
        bill = next((wrap_invoice_or_bill(r) for r in q.run()
                     if wrap_invoice_or_bill(r).GetID() == bill_id), None)
        q.destroy()
        assert bill is not None, f'{bill_id!r} not found'
        lot = bill.GetPostedLot()
        assert lot is not None, f'{bill_id!r} not posted'
        return round(lot.get_balance().to_double(), 2)
    finally:
        repo.close()


def _bank_tx_count(gf):
    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        from infrastructure.gnucash.utils import get_account_full_name

        def find(a, name):
            if get_account_full_name(a) == name:
                return a
            for c in a.get_children():
                g = find(c, name)
                if g:
                    return g
            return None
        bank = find(repo.book.get_root_account(), 'Assets:Bank')
        return len({s.GetParent().GetGUID().to_string()
                    for s in bank.GetSplitList()})
    finally:
        repo.close()


def _vendor_credit_total(gf, vendor_id):
    """Sum of the vendor's open pre-payment credit lots."""
    from repositories.gnucash_repository import GnuCashRepository
    from use_cases.unpost_business_objects import find_prepayments_in_book
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        return round(sum(float(c.amount) for c in find_prepayments_in_book(
            repo.book, vendor_id=vendor_id)), 2)
    finally:
        repo.close()


def _import(runner, gf, text, name, tmp_path, biz=True):
    p = tmp_path / name
    p.write_text(text)
    args = ['import', str(gf), str(p)]
    if biz:
        args.append('--include-business-objects')
    return runner.invoke(cli, args)


def _setup_fully_paid(runner, tmp_path):
    """Fresh book → accounts → pre-existing $120 bank tx → hero bill whose
    two payments are a fresh $1000 and a link of that $120 tx. Returns
    (gf, guid_1000_fresh, guid_120_linked)."""
    gf = tmp_path / 'book.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf), ACCOUNTS])
    assert r.exit_code == 0, r.output

    # Pre-existing $120 outgoing bank tx (Assets:Bank -120 / AP +120).
    r = _import(runner, gf, _fx('hero_bank_tx_120.txt'), 'bank120.txt',
                tmp_path, biz=False)
    assert r.exit_code == 0, r.output
    guid_120 = _bank_tx_guid(gf, -120.0)
    assert guid_120 is not None

    # Bill: fresh $1000 payment + linked $120 payment (retargets the tx above).
    bill_text = _fx('hero_taxed_bill_1120.txt').replace('{txn_guid}', guid_120)
    r = _import(runner, gf, bill_text, 'bill.txt', tmp_path)
    assert r.exit_code == 0, f'hero bill import: {r.output}'
    guid_1000 = _bank_tx_guid(gf, -1000.0)
    assert guid_1000 is not None
    return gf, guid_1000, guid_120


# ── Mixed apply + link settles the taxed bill ──────────────────────

def test_taxed_bill_settled_by_fresh_1000_and_linked_120(tmp_path):
    """The two-kind payment set (fresh $1000 + linked $120) fully settles
    the $1120 taxed bill: posted lot balance 0, and the two bank txs
    (fresh $1000 out + linked $120) are both present."""
    runner = CliRunner()
    gf, _guid_1000, _guid_120 = _setup_fully_paid(runner, tmp_path)
    assert _posted_lot_balance(gf, 'BILL-HERO-1120') == 0.00
    assert _bank_tx_count(gf) == 2


# ── Unapply the linked tax payment (linked the wrong tx) ───────────

def test_unapply_linked_120_leaves_fresh_1000_applied(tmp_path):
    """Peel only the linked $120: the bill drops to partially-paid with
    $120 outstanding (AP lot −120), the $1000 stays applied, and the
    $120 bank tx is re-homed (not deleted)."""
    runner = CliRunner()
    gf, _guid_1000, guid_120 = _setup_fully_paid(runner, tmp_path)

    r = runner.invoke(cli, ['unapply-payment', str(gf), 'BILL-HERO-1120',
                            '--bill', '--txn', guid_120, '--to', TO])
    assert r.exit_code == 0, r.output
    assert 'unapplied 1 payment' in r.output, r.output
    assert _posted_lot_balance(gf, 'BILL-HERO-1120') == -120.00
    assert _bank_tx_count(gf) == 2, 'no bank tx deleted'


# ── Unapply BOTH (→ fully outstanding, e.g. to pay from a credit) ──

def test_unapply_all_returns_bill_fully_outstanding(tmp_path):
    """Peel every payment: the bill returns to fully outstanding at
    −$1120 (the point from which a prior vendor credit could settle it
    via `auto_apply_credit: true`)."""
    runner = CliRunner()
    gf, _guid_1000, _guid_120 = _setup_fully_paid(runner, tmp_path)

    r = runner.invoke(cli, ['unapply-payment', str(gf), 'BILL-HERO-1120',
                            '--bill', '--all', '--to', TO])
    assert r.exit_code == 0, r.output
    assert 'unapplied 2 payments' in r.output, r.output
    assert _posted_lot_balance(gf, 'BILL-HERO-1120') == -1120.00


# ── Unapply the fresh net payment (linked tax stays) ───────────────

def test_unapply_fresh_1000_leaves_linked_120_applied(tmp_path):
    """Peel only the fresh $1000: the linked $120 stays applied, leaving
    $1000 outstanding (AP lot −1000)."""
    runner = CliRunner()
    gf, guid_1000, _guid_120 = _setup_fully_paid(runner, tmp_path)

    r = runner.invoke(cli, ['unapply-payment', str(gf), 'BILL-HERO-1120',
                            '--bill', '--txn', guid_1000, '--to', TO])
    assert r.exit_code == 0, r.output
    assert _posted_lot_balance(gf, 'BILL-HERO-1120') == -1000.00


# ── Unapply the fresh $1000, then LINK a different $1000 bank tx ────

def test_unapply_1000_then_relink_to_another_bank_tx(tmp_path):
    """Unapply the fresh $1000, then settle the re-opened $1000 by LINKING
    a different pre-existing $1000 bank tx (the 'I applied the wrong bank
    tx' fix). The bill returns to settled (lot 0) via the new tx, and the
    original $1000 tx survives (re-homed by the unapply)."""
    runner = CliRunner()
    gf, guid_1000, guid_120 = _setup_fully_paid(runner, tmp_path)

    # Peel the fresh $1000 → $1000 outstanding.
    r = runner.invoke(cli, ['unapply-payment', str(gf), 'BILL-HERO-1120',
                            '--bill', '--txn', guid_1000, '--to', TO])
    assert r.exit_code == 0, r.output
    assert _posted_lot_balance(gf, 'BILL-HERO-1120') == -1000.00

    # Import a DIFFERENT pre-existing $1000 outgoing bank tx.
    new_bank = ('2026-05-20 * "Correct wire for the net 1000"\n'
                '\tcurrency.mnemonic: "CAD"\n'
                '\tAssets:Bank -1000.00 CAD\n'
                '\tLiabilities:Accounts Payable 1000.00 CAD\n')
    r = _import(runner, gf, new_bank, 'newbank.txt', tmp_path, biz=False)
    assert r.exit_code == 0, r.output
    guid_new_1000 = next(g for g in [_bank_tx_guid(gf, -1000.0)] if g)

    # Re-import the bill with BOTH payments: the already-applied $120
    # (matched by its tx guid) and the new $1000 linked to the new tx.
    relink = f'''vendor "V-HERO"
\tname: "Hero Supplier"
\tcurrency: CAD

bill "BILL-HERO-1120"
\tvendor_id: "V-HERO"
\tcurrency: CAD
\tdate_opened: 2026-05-10
\tentry:
\t\tdate: 2026-05-10
\t\tdescription: "Materials (net 1000 + GST 50 + PST 70 = 1120)"
\t\taccount: "Expenses:Office Supplies"
\t\tquantity: 1
\t\tprice: 1000
\t\ttaxable: true
\t\ttax_included: false
\t\ttax_table: "GST+PST"
\tposted:
\t\tdate: 2026-05-10
\t\tdue: 2026-06-09
\t\tap_account: "Liabilities:Accounts Payable"
\t\tmemo: "Bill BILL-HERO-1120"
\t\taccumulate: true
\tpayment:
\t\tdate: 2026-05-15
\t\tamount: 120
\t\tbank_account: "Assets:Bank"
\t\ttxn_guid: "{guid_120}"
\t\tmemo: "Linked existing bank tx for the 120 tax portion"
\tpayment:
\t\tdate: 2026-05-20
\t\tamount: 1000
\t\tbank_account: "Assets:Bank"
\t\ttxn_guid: "{guid_new_1000}"
\t\tmemo: "Relinked net 1000 to the correct bank tx"
'''
    r = _import(runner, gf, relink, 'relink.txt', tmp_path)
    assert r.exit_code == 0, f'relink import: {r.output}'
    assert _posted_lot_balance(gf, 'BILL-HERO-1120') == 0.00, 'settled by new tx'


# ── Unapply BOTH, then settle the bill from a PRIOR vendor credit ───

def test_unapply_all_then_settle_from_prior_vendor_credit(tmp_path):
    """The full 'I meant to pay this from the credit' workflow: the vendor
    already holds a $1200 credit from an earlier overpayment; the $1120
    bill was paid in cash (fresh $1000 + linked $120); unapply BOTH, then
    re-import with `auto_apply_credit: true` so the bill is settled from
    the credit instead. The bill lot closes and the credit drops
    $1200 → $80."""
    runner = CliRunner()
    gf = tmp_path / 'book.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf), ACCOUNTS])
    assert r.exit_code == 0, r.output

    # Prior $1200 vendor credit for V-HERO (earlier bill overpaid).
    r = _import(runner, gf, _fx('hero_prior_credit_primer.txt'),
                'primer.txt', tmp_path)
    assert r.exit_code == 0, r.output
    assert _vendor_credit_total(gf, 'V-HERO') == 1200.00

    # The $1120 bill, paid in cash: fresh $1000 + linked $120.
    r = _import(runner, gf, _fx('hero_bank_tx_120.txt'), 'bank120.txt',
                tmp_path, biz=False)
    assert r.exit_code == 0, r.output
    guid_120 = _bank_tx_guid(gf, -120.0)
    bill_text = _fx('hero_taxed_bill_1120.txt').replace('{txn_guid}', guid_120)
    r = _import(runner, gf, bill_text, 'bill.txt', tmp_path)
    assert r.exit_code == 0, r.output
    assert _posted_lot_balance(gf, 'BILL-HERO-1120') == 0.00
    assert _vendor_credit_total(gf, 'V-HERO') == 1200.00  # credit untouched by cash

    # Unapply both cash payments → bill fully outstanding again.
    r = runner.invoke(cli, ['unapply-payment', str(gf), 'BILL-HERO-1120',
                            '--bill', '--all', '--to', TO])
    assert r.exit_code == 0, r.output
    assert _posted_lot_balance(gf, 'BILL-HERO-1120') == -1120.00

    # Re-import with auto_apply_credit → settle from the prior credit.
    settle_from_credit = '''taxtable "GST+PST"
\tentry:
\t\taccount: "Liabilities:Tax:GST"
\t\trate: 5.0%
\t\ttype: PERCENT
\tentry:
\t\taccount: "Liabilities:Tax:PST"
\t\trate: 7.0%
\t\ttype: PERCENT

vendor "V-HERO"
\tname: "Hero Supplier"
\tcurrency: CAD

bill "BILL-HERO-1120"
\tvendor_id: "V-HERO"
\tcurrency: CAD
\tdate_opened: 2026-05-10
\tauto_apply_credit: true
\tentry:
\t\tdate: 2026-05-10
\t\tdescription: "Materials (net 1000 + GST 50 + PST 70 = 1120)"
\t\taccount: "Expenses:Office Supplies"
\t\tquantity: 1
\t\tprice: 1000
\t\ttaxable: true
\t\ttax_included: false
\t\ttax_table: "GST+PST"
\tposted:
\t\tdate: 2026-05-10
\t\tdue: 2026-06-09
\t\tap_account: "Liabilities:Accounts Payable"
\t\tmemo: "Bill BILL-HERO-1120"
\t\taccumulate: true
\tpayment: none
'''
    r = _import(runner, gf, settle_from_credit, 'settle.txt', tmp_path)
    assert r.exit_code == 0, f'settle-from-credit import: {r.output}'
    assert _posted_lot_balance(gf, 'BILL-HERO-1120') == 0.00, 'settled from credit'
    assert _vendor_credit_total(gf, 'V-HERO') == 80.00, '1200 credit − 1120 bill = 80'
