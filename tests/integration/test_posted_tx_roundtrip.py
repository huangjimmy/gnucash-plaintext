"""
Regression: posted-tx round-trip via export → fresh-book reimport.

Two properties guarded here:
  1. Posting-tx GUID is preserved across the roundtrip (the importer
     attaches the standalone-imported tx instead of minting a fresh one
     via PostToAccount).
  2. The book never ends up with duplicate posting txs OR orphan AR/AP
     splits (splits in an AR/AP account that don't belong to any lot).

Before this fix the exporter emitted the posting tx as a standalone `*`
block AND the invoice's `posted:` block, but the importer's POSTED
handler unconditionally called `invoice.PostToAccount(...)` — which
created a SECOND posting tx with a fresh GUID. The standalone-imported
original was left orphan (AR split with no lot), and AR/Income balances
silently doubled per roundtrip. The exporter now emits `posted_txn_guid:`
and the importer links the existing tx via gncInvoiceAttachToTxn +
gncInvoiceAttachToLot instead of re-posting.
"""

import gnucash.gnucash_business as gb
import gnucash.gnucash_core_c as gc
from click.testing import CliRunner
from gnucash import Query

from cli.main import cli
from infrastructure.gnucash.utils import get_account_full_name
from repositories.gnucash_repository import GnuCashRepository

ACCOUNTS = """\
2026-01-01 open Assets
\ttype: Asset
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Accounts Receivable
\ttype: Accounts Receivable
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Liabilities
\ttype: Liability
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Liabilities:Accounts Payable
\ttype: Accounts Payable
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Income
\ttype: Income
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Income:Sales
\ttype: Income
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Expenses
\ttype: Expense
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Expenses:Supplies
\ttype: Expense
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
"""

INVOICE_FIXTURE = ACCOUNTS + """
customer "C001"
\tname: "Acme"
\tcurrency: CAD

invoice "INV-001"
\tcustomer_id: "C001"
\tcurrency: CAD
\tdate_opened: 2026-01-01
\tentry:
\t\tdate: 2026-01-01
\t\tdescription: "Service"
\t\taction: "Hours"
\t\taccount: "Income:Sales"
\t\tquantity: 1
\t\tprice: 100
\t\ttaxable: false
\t\ttax_included: false
\tposted:
\t\tdate: 2026-01-01
\t\tdue: 2026-01-31
\t\tar_account: "Assets:Accounts Receivable"
\t\tmemo: "Invoice INV-001"
\t\taccumulate: true
\tpayment: none
"""

BILL_FIXTURE = ACCOUNTS + """
vendor "V001"
\tname: "Globex"
\tcurrency: CAD

bill "BILL-001"
\tvendor_id: "V001"
\tcurrency: CAD
\tdate_opened: 2026-01-05
\tentry:
\t\tdate: 2026-01-05
\t\tdescription: "Office supplies"
\t\taccount: "Expenses:Supplies"
\t\tquantity: 1
\t\tprice: 75
\t\ttaxable: false
\t\ttax_included: false
\tposted:
\t\tdate: 2026-01-05
\t\tdue: 2026-02-04
\t\tap_account: "Liabilities:Accounts Payable"
\t\tmemo: "Bill BILL-001"
\t\taccumulate: true
\tpayment: none
"""


def _find_account(root, fullname):
    if get_account_full_name(root) == fullname:
        return root
    for c in root.get_children():
        r = _find_account(c, fullname)
        if r is not None:
            return r
    return None


def _snapshot(gnc_path):
    """Capture state needed to detect duplicate posting txs + orphan AR/AP
    splits + balance drift across an export → reimport cycle."""
    repo = GnuCashRepository(str(gnc_path))
    repo.open()
    try:
        all_txs = repo.get_all_transactions()
        posting_tx_guids = sorted(
            tx.GetGUID().to_string()
            for tx in all_txs
            if (p := gc.gncInvoiceGetInvoiceFromTxn(tx.instance)) is not None
            and int(p) != 0
        )
        all_tx_guids = sorted(tx.GetGUID().to_string() for tx in all_txs)

        # Walk every AR/AP account; orphan = split with no lot.
        # Default to 0 for any account named but missing so a roundtrip
        # that silently drops an empty account doesn't masquerade as a
        # balance change.
        root = repo.book.get_root_account()
        orphan_splits = []
        balances = {
            'Assets:Accounts Receivable': 0.0,
            'Liabilities:Accounts Payable': 0.0,
            'Income:Sales': 0.0,
            'Expenses:Supplies': 0.0,
        }
        for acct_name in balances:
            a = _find_account(root, acct_name)
            if a is None:
                continue
            splits = a.GetSplitList() or []
            balances[acct_name] = round(
                sum(sp.GetAmount().to_double() for sp in splits), 2)
            if acct_name in ('Assets:Accounts Receivable',
                             'Liabilities:Accounts Payable'):
                for sp in splits:
                    if sp.GetLot() is None:
                        orphan_splits.append((
                            acct_name,
                            round(sp.GetAmount().to_double(), 2),
                            sp.GetParent().GetGUID().to_string()
                                if sp.GetParent() else None,
                        ))

        # Per-invoice/bill date_posted + date_due — catches TZ drift
        # between the link path and the PostToAccount fallback. Keyed by
        # the business-object id (e.g. "INV-001") so dst lookups match
        # src 1:1 regardless of GUID churn elsewhere. One QOF query
        # covers both invoices and bills (they share the gncInvoice QOF
        # type; the owner-side determines which kind they represent).
        # NO try/except — a query failure must surface, not silently
        # leave posted_dates empty and make the assertion trivially pass.
        posted_dates = {}
        q = Query()
        try:
            q.search_for('gncInvoice')
            q.set_book(repo.book)
            for raw in q.run():
                inv = gb.Invoice(instance=raw)
                if inv.GetPostedTxn() is None:
                    continue
                # Key by (owner-kind, id) so the equality check still
                # detects divergence when a future fixture happens to use
                # the same id for an invoice and a bill (both come back
                # from `search_for('gncInvoice')`; only the owner side
                # tells them apart).
                owner_kind = ('vendor'
                              if inv.GetOwner().GetVendor() is not None
                              else 'customer')
                posted_dates[(owner_kind, inv.GetID())] = (
                    inv.GetDatePosted().strftime('%Y-%m-%d'),
                    inv.GetDateDue().strftime('%Y-%m-%d'),
                )
        finally:
            q.destroy()

        return {
            'tx_guids': all_tx_guids,
            'posting_tx_guids': posting_tx_guids,
            'orphan_splits': orphan_splits,
            'balances': balances,
            'posted_dates': posted_dates,
        }
    finally:
        repo.close()


def _assert_clean_posted_roundtrip(tmp_path, fixture_text):
    """Build src book from fixture, export → re-import to fresh book,
    assert the dest book is byte-identical to src on the dimensions that
    matter for posting-tx integrity."""
    runner = CliRunner()

    src_path = tmp_path / 'source.txt'
    src_path.write_text(fixture_text)
    src_gnc = tmp_path / 'src.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(src_gnc), str(src_path),
                            '--include-business-objects'])
    assert r.exit_code == 0, r.output

    exported = tmp_path / 'exported.txt'
    r = runner.invoke(cli, ['export', str(src_gnc), str(exported),
                            '--include-business-objects'])
    assert r.exit_code == 0, r.output

    dst_gnc = tmp_path / 'dst.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(dst_gnc), str(exported),
                            '--include-business-objects'])
    assert r.exit_code == 0, r.output

    src = _snapshot(src_gnc)
    dst = _snapshot(dst_gnc)

    # No orphan AR/AP splits in either book.
    assert src['orphan_splits'] == [], (
        f"source already has orphan AR/AP splits — fixture is buggy: "
        f"{src['orphan_splits']}")
    assert dst['orphan_splits'] == [], (
        f"REGRESSION: dest book has orphan AR/AP splits after roundtrip "
        f"(split in AR/AP account not attached to any lot — typical sign "
        f"of duplicate posting txs from standalone-import + PostToAccount "
        f"both running): {dst['orphan_splits']}")

    # Tx count must not grow. A duplicate posting tx would push dst's
    # tx count above src's.
    assert len(dst['tx_guids']) == len(src['tx_guids']), (
        f"REGRESSION: tx count changed across roundtrip: "
        f"src={len(src['tx_guids'])} dst={len(dst['tx_guids'])} — "
        f"likely duplicate posting tx.\n"
        f"  src tx guids: {src['tx_guids']}\n"
        f"  dst tx guids: {dst['tx_guids']}")

    # Posting tx GUIDs preserved exactly.
    assert dst['posting_tx_guids'] == src['posting_tx_guids'], (
        f"REGRESSION: posting-tx GUID not preserved: "
        f"src={src['posting_tx_guids']} dst={dst['posting_tx_guids']}")

    # Exactly one wired-as-posting tx per posted invoice/bill (no spurious
    # extras carrying the same `txn_type: I` KVP).
    assert len(dst['posting_tx_guids']) == len(set(dst['posting_tx_guids'])), (
        f"REGRESSION: duplicate posting-tx GUIDs in dest book: "
        f"{dst['posting_tx_guids']}")

    # Account balances preserved — duplication would double them.
    assert dst['balances'] == src['balances'], (
        f"REGRESSION: account balances changed across roundtrip: "
        f"src={src['balances']} dst={dst['balances']}")

    # date_posted / date_due preserved per invoice/bill. Catches TZ drift
    # between the link path's `int(d.timestamp())` and SWIG's
    # PostToAccount-internal conversion (e.g. on HKT a naive
    # '2026-01-01' resolves to 2025-12-31 16:00 UTC; if the two paths
    # use different conversions, dst's date strings would shift by one
    # day relative to src). The fixtures always contain a posted invoice
    # or bill, so an empty `src['posted_dates']` means the query path
    # itself is broken — assert non-empty so the equality check below
    # doesn't pass trivially on `{} == {}`.
    assert src['posted_dates'], (
        "source has no posted invoices/bills — fixture or query is broken; "
        "the date assertion below would pass trivially.")
    assert dst['posted_dates'] == src['posted_dates'], (
        f"REGRESSION: posted/due dates changed across roundtrip — "
        f"likely a timezone or time64 conversion drift:\n"
        f"  src: {src['posted_dates']}\n"
        f"  dst: {dst['posted_dates']}")


def test_invoice_posted_tx_roundtrip(tmp_path):
    """Posted invoice round-trips without duplicating the posting tx or
    orphaning the AR side."""
    _assert_clean_posted_roundtrip(tmp_path, INVOICE_FIXTURE)


def test_bill_posted_tx_roundtrip(tmp_path):
    """Posted bill round-trips without duplicating the posting tx or
    orphaning the AP side."""
    _assert_clean_posted_roundtrip(tmp_path, BILL_FIXTURE)


def test_user_kvp_on_posting_tx_survives_attach(tmp_path):
    """A user-authored custom KVP key on the standalone posting-tx block
    must survive the linked-attach path. Regression for the
    `set_custom_metadata` non-merge bug: the attach helper plants the
    `business_generated` marker into the tx's KVP slot, and if it
    overwrites (vs merges) the slot the user's key gets nuked.

    Drives a hand-authored fixture (no source-book intermediary needed)
    that has both the standalone posting tx block with a custom KVP key
    AND the invoice's `posted:` block with `posted_txn_guid:` pointing
    at it. After import, the dst book's posting tx must carry both
    `business_generated: true` and `audit_note` from the user.
    """
    fixture = ACCOUNTS + """
customer "C001"
\tname: "Acme"
\tcurrency: CAD

2026-01-01 * "INV-001" "Invoice INV-001"
\tguid: "11111111111111111111111111111111"
\taudit_note: "verified by auditor on 2026-01-02"
\ttxn_type: I
\towner: customer:C001
\tAssets:Accounts Receivable 100.00 CAD
\t\tguid: "22222222222222222222222222222222"
\t\taction: "Invoice"
\t\tmemo:"Invoice INV-001"
\tIncome:Sales -100.00 CAD
\t\tguid: "33333333333333333333333333333333"
\t\taction: "Invoice"
\t\tmemo:"Invoice INV-001"

invoice "INV-001"
\tcustomer_id: "C001"
\tcurrency: CAD
\tdate_opened: 2026-01-01
\tentry:
\t\tdate: 2026-01-01
\t\tdescription: "Service"
\t\taction: "Hours"
\t\taccount: "Income:Sales"
\t\tquantity: 1
\t\tprice: 100
\t\ttaxable: false
\t\ttax_included: false
\tposted:
\t\tdate: 2026-01-01
\t\tdue: 2026-01-31
\t\tar_account: "Assets:Accounts Receivable"
\t\tmemo: "Invoice INV-001"
\t\tposted_txn_guid: "11111111111111111111111111111111"
\t\taccumulate: true
\tpayment: none
"""

    runner = CliRunner()
    src_path = tmp_path / 'source.txt'
    src_path.write_text(fixture)
    gnc = tmp_path / 'k.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gnc), str(src_path),
                            '--include-business-objects'])
    assert r.exit_code == 0, r.output

    # Inspect the posting tx's KVP directly via the same infrastructure
    # the importer uses, so the test fails sharply if the merge path is
    # broken.
    from infrastructure.gnucash.kvp import get_custom_metadata
    repo = GnuCashRepository(str(gnc))
    repo.open()
    try:
        posting_tx = None
        for tx in repo.get_all_transactions():
            inv_ptr = gc.gncInvoiceGetInvoiceFromTxn(tx.instance)
            if inv_ptr is not None and int(inv_ptr) != 0:
                posting_tx = tx
                break
        assert posting_tx is not None, "no posting tx found after import"
        meta = get_custom_metadata(posting_tx)
        assert meta.get('business_generated') == 'true', (
            f"`business_generated` marker missing — attach helper didn't "
            f"plant the KVP: {meta!r}")
        assert meta.get('audit_note') == 'verified by auditor on 2026-01-02', (
            f"REGRESSION: user-authored `audit_note` KVP on the standalone "
            f"posting tx was lost by the attach path — `set_custom_metadata` "
            f"must merge with the existing slot, not overwrite it. "
            f"Got: {meta!r}")
    finally:
        repo.close()
