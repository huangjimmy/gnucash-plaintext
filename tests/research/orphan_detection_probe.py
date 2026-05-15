"""
Orphan-bank-transaction back-reference probe.

The prior research (docs/research/2026-05-14-invoice-post-pay-unpost-cycle.md)
showed that `unpost-invoices` orphans the bank-side payment transaction.
This probe asks: *after the unpost, can we still link the orphan back to
the invoice it paid?*

Approach: walk every backref candidate on the bank tx — description, notes,
KVP slots, per-split memo/action/lot, GnuCash's own
`gncInvoiceGetInvoiceFromTxn` and lot reverse-lookups — both *before* and
*after* the unpost. The dump is written to `exports/orphan_backref_probe.txt`
for inclusion in the research doc.

Run via:

    ./scripts/test.sh latest tests/research/orphan_detection_probe.py
"""

import ctypes
import os
import shutil
import time

from click.testing import CliRunner

from cli.main import cli

WORKTREE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
EXPORTS_DIR = os.path.join(WORKTREE, "exports")


ACCOUNTS = """\
2026-01-01 open Assets
\ttype: Asset
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Bank
\ttype: Bank
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Accounts Receivable
\ttype: Accounts Receivable
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
"""

INV_POSTED_PAID = """\
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
\tpayment:
\t\tdate: 2026-01-15
\t\tamount: 100
\t\tbank_account: "Assets:Bank"
\t\tmemo: "Payment INV-001"
"""


def _load_lib():
    """Load libgnc-engine.so with the same RTLD_GLOBAL trick the project uses
    (see CLAUDE.md §2 — Ubuntu's RTLD_LOCAL default otherwise produces
    library-instance mismatches and segfaults inside gncTaxTableGetTables and
    friends)."""
    from infrastructure.gnucash.engine import load_gnc_engine
    lib = load_gnc_engine()
    # Functions used in this probe but not pre-typed by engine.py.
    # CRITICAL: argtypes MUST be set on every pointer arg (CLAUDE.md §1).
    for name, restype, argtypes in [
        ('xaccTransGetDescription', ctypes.c_char_p, [ctypes.c_void_p]),
        ('xaccTransGetNotes',       ctypes.c_char_p, [ctypes.c_void_p]),
        ('xaccTransGetTxnType',     ctypes.c_char,   [ctypes.c_void_p]),
        ('xaccTransGetNumSplits',   ctypes.c_int,    [ctypes.c_void_p]),
        ('xaccTransGetSplit',       ctypes.c_void_p, [ctypes.c_void_p, ctypes.c_int]),
        ('xaccTransCountSplits',    ctypes.c_int,    [ctypes.c_void_p]),
        ('xaccSplitGetMemo',        ctypes.c_char_p, [ctypes.c_void_p]),
        ('xaccSplitGetAction',      ctypes.c_char_p, [ctypes.c_void_p]),
        ('xaccSplitGetAccount',     ctypes.c_void_p, [ctypes.c_void_p]),
        ('xaccSplitGetLot',         ctypes.c_void_p, [ctypes.c_void_p]),
        ('xaccAccountGetType',      ctypes.c_int,    [ctypes.c_void_p]),
        ('gncInvoiceGetInvoiceFromTxn', ctypes.c_void_p, [ctypes.c_void_p]),
        ('gncInvoiceGetInvoiceFromLot', ctypes.c_void_p, [ctypes.c_void_p]),
        ('gncInvoiceGetID',         ctypes.c_char_p, [ctypes.c_void_p]),
        ('gncOwnerGetOwnerFromLot', ctypes.c_int,    [ctypes.c_void_p, ctypes.c_void_p]),
        ('gncOwnerGetID',           ctypes.c_char_p, [ctypes.c_void_p]),
        ('gncOwnerGetName',         ctypes.c_char_p, [ctypes.c_void_p]),
        ('gncOwnerGetType',         ctypes.c_int,    [ctypes.c_void_p]),
        # gncOwnerInitFromTxn — reads the KVP owner backref that
        # gncOwnerApplyPayment stashed on the transaction. Present on 4.x+
        # under one of these names depending on version:
        ('gncOwnerGetOwnerFromTxn', ctypes.c_int,    [ctypes.c_void_p, ctypes.c_void_p]),
        ('qof_instance_get_guid',   ctypes.c_void_p, [ctypes.c_void_p]),
        ('guid_to_string_buff',     ctypes.c_char_p, [ctypes.c_void_p, ctypes.c_char_p]),
    ]:
        try:
            f = getattr(lib, name)
            f.restype = restype
            f.argtypes = argtypes
        except AttributeError:
            pass  # missing symbols flagged at runtime by the probe loop
    return lib


def _guid_of(lib, instance_ptr):
    if not instance_ptr:
        return None
    g = lib.qof_instance_get_guid(instance_ptr)
    if not g:
        return None
    buf = ctypes.create_string_buffer(40)
    lib.guid_to_string_buff(g, buf)
    return buf.value.decode('ascii')


def _decode(b):
    if not b:
        return None
    if isinstance(b, bytes):
        return b.decode('utf-8', errors='replace')
    return b


def _safe(call, *args):
    """Call a ctypes function; if the symbol is missing return the sentinel
    string instead of crashing the probe (older GnuCash versions may lack
    individual reverse-lookup helpers)."""
    try:
        return call(*args)
    except (AttributeError, OSError) as e:
        return f"<missing: {e!r}>"


def _dump_tx(lib, tx_ptr, label, out):
    """Dump every backref candidate for a transaction. Returns a dict of
    {field: value} so the test can also assert on them."""
    out.write(f"\n── {label}: tx @ {tx_ptr:#x} ──────────────────────────────\n")
    if not tx_ptr:
        out.write("  (null tx pointer)\n")
        return {}

    record = {}

    desc  = _decode(_safe(lib.xaccTransGetDescription, tx_ptr))
    notes = _decode(_safe(lib.xaccTransGetNotes, tx_ptr))
    txtype_raw = _safe(lib.xaccTransGetTxnType, tx_ptr)
    # xaccTransGetTxnType returns a char ('N','I','P','L'); under ctypes it
    # comes back as a 1-byte bytes object. Normalise to a string.
    if isinstance(txtype_raw, bytes):
        txtype = txtype_raw.decode('ascii', errors='replace')
    else:
        txtype = str(txtype_raw)
    nsplits = _safe(lib.xaccTransCountSplits, tx_ptr)
    tx_guid = _guid_of(lib, tx_ptr)

    record.update(
        description=desc, notes=notes, txn_type=txtype,
        num_splits=nsplits, tx_guid=tx_guid,
    )

    out.write(f"  description:          {desc!r}\n")
    out.write(f"  notes:                {notes!r}\n")
    out.write(f"  xaccTransGetTxnType:  {txtype!r}   "
              f"('I'=invoice posting, 'P'=payment, 'N'=normal, 'L'=link)\n")
    out.write(f"  tx guid:              {tx_guid}\n")
    out.write(f"  num_splits:           {nsplits}\n")

    # Try the GnuCash-provided reverse lookup: invoice-from-txn.
    inv_from_tx = _safe(lib.gncInvoiceGetInvoiceFromTxn, tx_ptr)
    if isinstance(inv_from_tx, int) and inv_from_tx:
        inv_id = _decode(_safe(lib.gncInvoiceGetID, inv_from_tx))
        inv_guid = _guid_of(lib, inv_from_tx)
        record.update(invoice_from_txn_id=inv_id, invoice_from_txn_guid=inv_guid)
        out.write(f"  gncInvoiceGetInvoiceFromTxn(tx) → invoice id={inv_id!r} guid={inv_guid}\n")
    else:
        record.update(invoice_from_txn_id=None, invoice_from_txn_guid=None)
        out.write(f"  gncInvoiceGetInvoiceFromTxn(tx) → {inv_from_tx!r}\n")

    # Try the KVP-owner-backref reverse lookup (set by gncOwnerApplyPayment).
    # Build a GncOwner struct large enough to hold the union (104 bytes is
    # safely larger than the real struct on every supported version).
    owner_buf = ctypes.create_string_buffer(256)
    owner_ptr = ctypes.cast(owner_buf, ctypes.c_void_p).value
    got_owner = _safe(lib.gncOwnerGetOwnerFromTxn, tx_ptr, owner_ptr)
    owner_id = None
    owner_name = None
    owner_type = None
    if got_owner is True or (isinstance(got_owner, int) and got_owner == 1):
        owner_id   = _decode(_safe(lib.gncOwnerGetID, owner_ptr))
        owner_name = _decode(_safe(lib.gncOwnerGetName, owner_ptr))
        owner_type = _safe(lib.gncOwnerGetType, owner_ptr)
    record.update(owner_from_txn_id=owner_id,
                  owner_from_txn_name=owner_name,
                  owner_from_txn_type=owner_type,
                  owner_from_txn_returned=got_owner)
    out.write(f"  gncOwnerGetOwnerFromTxn(tx, &owner) → returned={got_owner!r}\n")
    out.write(f"    owner.id={owner_id!r}  owner.name={owner_name!r}  owner.type={owner_type}\n")

    # Per-split walk
    splits = []
    for i in range(int(nsplits) if isinstance(nsplits, int) else 0):
        split_ptr = _safe(lib.xaccTransGetSplit, tx_ptr, i)
        if not isinstance(split_ptr, int) or not split_ptr:
            continue
        memo   = _decode(_safe(lib.xaccSplitGetMemo, split_ptr))
        action = _decode(_safe(lib.xaccSplitGetAction, split_ptr))
        acct_ptr = _safe(lib.xaccSplitGetAccount, split_ptr)
        lot_ptr  = _safe(lib.xaccSplitGetLot, split_ptr)
        acct_name = None
        acct_type = None
        if isinstance(acct_ptr, int) and acct_ptr:
            from infrastructure.gnucash.engine import safe_ctypes_string
            acct_name = safe_ctypes_string(lib.gnc_account_get_full_name, acct_ptr) \
                        or safe_ctypes_string(lib.xaccAccountGetName, acct_ptr)
            acct_type = _safe(lib.xaccAccountGetType, acct_ptr)
        lot_inv_id   = None
        lot_inv_guid = None
        lot_guid     = None
        lot_owner_id = None
        if isinstance(lot_ptr, int) and lot_ptr:
            lot_guid = _guid_of(lib, lot_ptr)
            inv_from_lot = _safe(lib.gncInvoiceGetInvoiceFromLot, lot_ptr)
            if isinstance(inv_from_lot, int) and inv_from_lot:
                lot_inv_id   = _decode(_safe(lib.gncInvoiceGetID, inv_from_lot))
                lot_inv_guid = _guid_of(lib, inv_from_lot)
            # Lot-owner reverse lookup — distinct from invoice-from-lot.
            got_owner = _safe(lib.gncOwnerGetOwnerFromLot, lot_ptr, owner_ptr)
            if got_owner is True or (isinstance(got_owner, int) and got_owner == 1):
                lot_owner_id = _decode(_safe(lib.gncOwnerGetID, owner_ptr))
        splits.append({
            "i": i, "memo": memo, "action": action,
            "account": acct_name, "account_type": acct_type,
            "lot_ptr": (lot_ptr if isinstance(lot_ptr, int) else None),
            "lot_guid": lot_guid,
            "invoice_from_lot_id": lot_inv_id,
            "invoice_from_lot_guid": lot_inv_guid,
            "owner_from_lot_id": lot_owner_id,
        })
        out.write(f"  split[{i}]:\n")
        out.write(f"    account:        {acct_name!r} (type={acct_type})\n")
        out.write(f"    memo:           {memo!r}\n")
        out.write(f"    action:         {action!r}\n")
        out.write(f"    lot ptr:        {lot_ptr!r}  (guid={lot_guid})\n")
        out.write(f"    gncInvoiceGetInvoiceFromLot(lot) → "
                  f"id={lot_inv_id!r} guid={lot_inv_guid}\n")
        out.write(f"    gncOwnerGetOwnerFromLot(lot,&o) → owner.id={lot_owner_id!r}\n")

    record["splits"] = splits
    return record


def _find_bank_tx(book, bank_full_name="Assets:Bank"):
    """Return the ctypes pointer of the first transaction touching the named
    bank account. The probe creates only one bank tx, so this is unambiguous."""
    from infrastructure.gnucash.utils import find_account
    bank = find_account(book.get_root_account(), bank_full_name)
    assert bank is not None, f"Bank account {bank_full_name!r} not found"
    splits = bank.GetSplitList()
    assert splits, "Bank account has no splits — fixture wasn't paid?"
    return int(splits[0].parent.instance)


def test_orphan_backreference_probe(tmp_path):
    runner = CliRunner()
    gnc = tmp_path / "book.gnucash"

    # Set up the book in the posted+paid state (the "step C" world).
    fix = tmp_path / "in.txt"
    fix.write_text(ACCOUNTS + "\n" + INV_POSTED_PAID)
    r = runner.invoke(cli, ["import", "--new", str(gnc), str(fix),
                            "--include-business-objects"])
    assert r.exit_code == 0, r.output
    time.sleep(1)

    os.makedirs(EXPORTS_DIR, exist_ok=True)
    dump_path = os.path.join(EXPORTS_DIR, "orphan_backref_probe.txt")
    pre_record = {}
    post_record = {}

    with open(dump_path, "w") as out:
        out.write("Orphan-bank-tx back-reference probe\n")
        out.write("===================================\n")
        out.write("Fixture: one customer C001, one invoice INV-001 ($100), "
                  "paid in full from Assets:Bank on 2026-01-15.\n")

        # ── PRE-UNPOST ───────────────────────────────────────────────────────
        from gnucash import Session
        ses = Session(f"xml://{gnc}")
        try:
            lib = _load_lib()
            tx_ptr = _find_bank_tx(ses.book)
            pre_record = _dump_tx(lib, tx_ptr, "PRE-UNPOST  (step C world)", out)
        finally:
            ses.end()

        # ── UNPOST ───────────────────────────────────────────────────────────
        r = runner.invoke(cli, ["unpost-invoices", str(gnc), "INV-001"])
        assert r.exit_code == 0, r.output
        time.sleep(1)

        # ── POST-UNPOST ──────────────────────────────────────────────────────
        ses = Session(f"xml://{gnc}")
        try:
            lib = _load_lib()
            tx_ptr = _find_bank_tx(ses.book)
            post_record = _dump_tx(lib, tx_ptr, "POST-UNPOST (step D world)", out)
        finally:
            ses.end()

        # ── DIFF SUMMARY ─────────────────────────────────────────────────────
        out.write("\n── what changed ────────────────────────────────────────\n")
        for k in ("description", "notes", "txn_type",
                  "tx_guid", "invoice_from_txn_id", "invoice_from_txn_guid",
                  "owner_from_txn_id", "owner_from_txn_name",
                  "owner_from_txn_type", "owner_from_txn_returned"):
            before, after = pre_record.get(k), post_record.get(k)
            marker = "   " if before == after else " * "
            out.write(f"{marker}{k:32s} {before!r}  →  {after!r}\n")
        out.write("\n  per-split changes:\n")
        pre_splits = pre_record.get("splits", [])
        post_splits = post_record.get("splits", [])
        for i in range(max(len(pre_splits), len(post_splits))):
            pre_s = pre_splits[i] if i < len(pre_splits) else {}
            post_s = post_splits[i] if i < len(post_splits) else {}
            out.write(f"  split[{i}] (account={pre_s.get('account')!r}):\n")
            for k in ("memo", "action", "lot_ptr", "lot_guid",
                      "invoice_from_lot_id", "invoice_from_lot_guid",
                      "owner_from_lot_id"):
                b, a = pre_s.get(k), post_s.get(k)
                marker = "     " if b == a else "   * "
                out.write(f"{marker}{k:30s} {b!r}  →  {a!r}\n")

    # Smoke-level assertions: the dump file exists and the bank tx survived.
    assert os.path.exists(dump_path)
    assert pre_record.get("tx_guid") == post_record.get("tx_guid"), (
        "Bank-tx GUID should be unchanged by unpost — that's the whole "
        "premise of 'the orphan survives'."
    )
    # The two strong, surviving back-references we'll use for detection.
    assert post_record.get("owner_from_txn_id") == "C001"
    assert post_record.get("txn_type") == "P"


# ─── Prototype helpers ────────────────────────────────────────────────────────


def find_pre_unpost_payments(book, invoice):
    """Pre-unpost orphan-preview: list the bank-side payment txs attached to
    the invoice's posted lot. This is the *strong* path — the lot still
    points to the invoice, so the result has zero false positives.

    Returns a list of dicts:
        [{'tx_guid': str, 'date': str, 'amount': str, 'bank_account': str,
          'description': str, 'memo': str}, …]

    Intended to be called *before* `invoice.Unpost(False)`. After unpost,
    the lot→invoice association is destroyed and this function cannot run
    (the lot is detached).
    """
    lib = _load_lib()
    lot = invoice.GetPostedLot()
    if lot is None:
        return []
    lot_ptr = int(lot.instance)
    from infrastructure.gnucash.engine import iterate_glist

    # gnc_lot_get_split_list returns a GList* of Split*.
    lib.gnc_lot_get_split_list.restype  = ctypes.c_void_p
    lib.gnc_lot_get_split_list.argtypes = [ctypes.c_void_p]
    splits_glist = lib.gnc_lot_get_split_list(lot_ptr)

    results = []
    seen_tx = set()
    for split_ptr in iterate_glist(lib, splits_glist, lambda lib, p: p):
        if not split_ptr:
            continue
        tx_ptr = _safe(lib.xaccSplitGetParent if hasattr(lib, 'xaccSplitGetParent')
                       else lib.xaccSplitGetParent, split_ptr)
        # Resolve xaccSplitGetParent argtypes lazily.
        try:
            lib.xaccSplitGetParent.restype = ctypes.c_void_p
            lib.xaccSplitGetParent.argtypes = [ctypes.c_void_p]
            tx_ptr = lib.xaccSplitGetParent(split_ptr)
        except AttributeError:
            continue
        if not tx_ptr or tx_ptr in seen_tx:
            continue
        seen_tx.add(tx_ptr)
        # Skip the posting tx itself (txn_type 'I'); we only want payments ('P').
        tx_type = lib.xaccTransGetTxnType(tx_ptr)
        if isinstance(tx_type, bytes):
            tx_type = tx_type.decode('ascii', errors='replace')
        if tx_type != 'P':
            continue
        # Find this tx's bank-side split (i.e. the one *not* on the AR account).
        bank_acct_name = None
        bank_memo = None
        for j in range(lib.xaccTransCountSplits(tx_ptr)):
            s = lib.xaccTransGetSplit(tx_ptr, j)
            a = lib.xaccSplitGetAccount(s)
            t = lib.xaccAccountGetType(a)
            # Account-type 11 is A/Receivable, 12 is A/Payable.
            if t in (11, 12):
                continue
            from infrastructure.gnucash.engine import safe_ctypes_string
            bank_acct_name = safe_ctypes_string(lib.gnc_account_get_full_name, a)
            bank_memo = _decode(lib.xaccSplitGetMemo(s))
        results.append({
            'tx_guid': _guid_of(lib, tx_ptr),
            'description': _decode(lib.xaccTransGetDescription(tx_ptr)),
            'bank_account': bank_acct_name,
            'memo': bank_memo,
        })
    return results


def find_orphan_payments_post_unpost(book, invoice_id=None, customer_id=None):
    """Post-unpost recovery: best-effort match by combining surviving
    back-references. **This is the weak path** — use only when the pre-unpost
    list wasn't captured. False-positive risk depends on how many other
    payment txs the same customer has in the book.

    Criteria, strongest → weakest:
      1. txn_type == 'P'            (strong filter; payment-class only)
      2. gncOwnerGetOwnerFromTxn    (strong; survives unpost)
      3. one split on AR/AP, the   (strong; payment shape)
         other on a Bank/Asset acct
      4. AR-side split's lot has no (strong; invoice lots have it set)
         invoice attached
      5. invoice_id given AND memo  (medium; user-controlled)
         contains "<invoice_id>"
      6. lot.gnc_owner.id == customer_id  (medium; survives unpost)
    """
    lib = _load_lib()
    from gnucash import Query, Transaction
    q = Query()
    q.search_for('Trans')
    q.set_book(book)

    owner_buf = ctypes.create_string_buffer(256)
    owner_ptr = ctypes.cast(owner_buf, ctypes.c_void_p).value

    out = []
    for r in q.run():
        tx_ptr = int(r) if isinstance(r, int) else int(Transaction(instance=r).instance)
        t = lib.xaccTransGetTxnType(tx_ptr)
        if isinstance(t, bytes):
            t = t.decode('ascii', errors='replace')
        if t != 'P':
            continue                                                   # crit 1

        got = lib.gncOwnerGetOwnerFromTxn(tx_ptr, owner_ptr)            # crit 2
        if got != 1:
            continue
        this_customer = _decode(lib.gncOwnerGetID(owner_ptr))
        if customer_id and this_customer != customer_id:
            continue

        # Payment shape: one AR/AP split (type 11/12), one non-AR/AP split.
        nsplits = lib.xaccTransCountSplits(tx_ptr)
        ar_split = None
        bank_split = None
        for j in range(nsplits):
            s = lib.xaccTransGetSplit(tx_ptr, j)
            atype = lib.xaccAccountGetType(lib.xaccSplitGetAccount(s))
            if atype in (11, 12):
                ar_split = s
            else:
                bank_split = s
        if not (ar_split and bank_split):
            continue                                                   # crit 3

        # AR-side lot must have NO invoice attached (i.e. orphaned).
        lot = lib.xaccSplitGetLot(ar_split)
        if not lot:
            continue
        if lib.gncInvoiceGetInvoiceFromLot(lot):
            continue                                                   # crit 4

        # Optional invoice-id memo match.
        memo_hit = True
        if invoice_id:
            memo = _decode(lib.xaccSplitGetMemo(ar_split)) or ''
            memo_hit = invoice_id in memo                              # crit 5

        out.append({
            'tx_guid':       _guid_of(lib, tx_ptr),
            'description':   _decode(lib.xaccTransGetDescription(tx_ptr)),
            'memo':          _decode(lib.xaccSplitGetMemo(ar_split)),
            'customer_id':   this_customer,
            'invoice_id_memo_match': memo_hit if invoice_id else None,
        })
    q.destroy()
    return out


BILL_ACCOUNTS = """\
2026-01-01 open Assets
\ttype: Asset
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Bank
\ttype: Bank
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
2026-01-01 open Expenses
\ttype: Expense
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Expenses:Supplies
\ttype: Expense
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
"""


BILL_POSTED_PAID = """\
vendor "V001"
\tname: "Supplier"
\tcurrency: CAD

bill "BILL-001"
\tvendor_id: "V001"
\tcurrency: CAD
\tdate_opened: 2026-01-01
\tentry:
\t\tdate: 2026-01-01
\t\tdescription: "Supplies"
\t\taccount: "Expenses:Supplies"
\t\tquantity: 1
\t\tprice: 100
\t\ttaxable: true
\t\ttax_included: false
\tposted:
\t\tdate: 2026-01-01
\t\tdue: 2026-01-31
\t\tap_account: "Liabilities:Accounts Payable"
\t\tmemo: "Bill BILL-001"
\t\taccumulate: true
\tpayment:
\t\tdate: 2026-01-15
\t\tamount: 100
\t\tbank_account: "Assets:Bank"
\t\tmemo: "Payment BILL-001"
"""


def test_orphan_backreference_probe_bill(tmp_path):
    """Mirror of test_orphan_backreference_probe but for a vendor bill.
    Confirms the same backrefs survive on the bill orphan and identifies
    any AP-side asymmetries (owner type 4 instead of 2, sign flips,
    account-type 12 instead of 11)."""
    runner = CliRunner()
    gnc = tmp_path / "book.gnucash"

    fix = tmp_path / "in.txt"
    fix.write_text(BILL_ACCOUNTS + "\n" + BILL_POSTED_PAID)
    r = runner.invoke(cli, ["import", "--new", str(gnc), str(fix),
                            "--include-business-objects"])
    assert r.exit_code == 0, r.output
    time.sleep(1)

    os.makedirs(EXPORTS_DIR, exist_ok=True)
    bill_exports_dir = os.path.join(WORKTREE, "exports", "bill")
    os.makedirs(bill_exports_dir, exist_ok=True)
    dump_path = os.path.join(bill_exports_dir, "orphan_backref_probe.txt")
    pre_record = {}
    post_record = {}

    with open(dump_path, "w") as out:
        out.write("Bill-side orphan-bank-tx back-reference probe\n")
        out.write("=============================================\n")
        out.write("Fixture: one vendor V001, one bill BILL-001 ($100), "
                  "paid in full from Assets:Bank on 2026-01-15.\n")

        from gnucash import Session
        ses = Session(f"xml://{gnc}")
        try:
            lib = _load_lib()
            tx_ptr = _find_bank_tx(ses.book)
            pre_record = _dump_tx(lib, tx_ptr, "PRE-UNPOST  (bill step C)", out)
        finally:
            ses.end()

        r = runner.invoke(cli, ["unpost-bills", str(gnc), "BILL-001"])
        assert r.exit_code == 0, r.output
        time.sleep(1)

        ses = Session(f"xml://{gnc}")
        try:
            lib = _load_lib()
            tx_ptr = _find_bank_tx(ses.book)
            post_record = _dump_tx(lib, tx_ptr, "POST-UNPOST (bill step D)", out)
        finally:
            ses.end()

        out.write("\n── what changed ────────────────────────────────────────\n")
        for k in ("description", "notes", "txn_type",
                  "tx_guid", "invoice_from_txn_id", "invoice_from_txn_guid",
                  "owner_from_txn_id", "owner_from_txn_name",
                  "owner_from_txn_type", "owner_from_txn_returned"):
            before, after = pre_record.get(k), post_record.get(k)
            marker = "   " if before == after else " * "
            out.write(f"{marker}{k:32s} {before!r}  →  {after!r}\n")
        out.write("\n  per-split changes:\n")
        pre_splits = pre_record.get("splits", [])
        post_splits = post_record.get("splits", [])
        for i in range(max(len(pre_splits), len(post_splits))):
            pre_s = pre_splits[i] if i < len(pre_splits) else {}
            post_s = post_splits[i] if i < len(post_splits) else {}
            out.write(f"  split[{i}] (account={pre_s.get('account')!r}, "
                      f"type={pre_s.get('account_type')}):\n")
            for k in ("memo", "action", "lot_ptr", "lot_guid",
                      "invoice_from_lot_id", "invoice_from_lot_guid",
                      "owner_from_lot_id"):
                b, a = pre_s.get(k), post_s.get(k)
                marker = "     " if b == a else "   * "
                out.write(f"{marker}{k:30s} {b!r}  →  {a!r}\n")

    # The four assertions that matter for symmetry with the invoice probe.
    assert pre_record.get("tx_guid") == post_record.get("tx_guid")
    # Owner type 4 = Vendor (vs. 2 = Customer for the invoice case).
    assert post_record.get("owner_from_txn_id") == "V001"
    assert post_record.get("owner_from_txn_type") == 4, (
        f"Expected vendor type=4, got {post_record.get('owner_from_txn_type')!r}"
    )
    # txn_type is 'P' for both invoice and bill payments — symmetric.
    assert post_record.get("txn_type") == "P"
    # AP-side split has account-type 12 (vs 11 = A/Receivable for invoices).
    ap_split = next((s for s in post_record["splits"]
                     if s["account_type"] == 12), None)
    assert ap_split is not None, "No A/Payable split found on bill payment"
    # Same lot-owner trick fires on bill side too: invoice-from-lot is None
    # post-unpost, but owner-from-lot returns the vendor.
    assert ap_split["invoice_from_lot_id"] is None
    assert ap_split["owner_from_lot_id"] == "V001"


def test_find_orphan_payments_prototype_bill(tmp_path):
    """Confirms the two prototype helpers from the invoice-side test work
    on the bill side without code changes — the symmetry claim from the
    research doc."""
    runner = CliRunner()
    gnc = tmp_path / "book.gnucash"
    fix = tmp_path / "in.txt"
    fix.write_text(BILL_ACCOUNTS + "\n" + BILL_POSTED_PAID)
    r = runner.invoke(cli, ["import", "--new", str(gnc), str(fix),
                            "--include-business-objects"])
    assert r.exit_code == 0, r.output
    time.sleep(1)

    from gnucash import Query, Session
    from gnucash.gnucash_business import Invoice  # bills use the same SWIG type
    ses = Session(f"xml://{gnc}")
    try:
        q = Query()
        q.search_for('gncInvoice')
        q.set_book(ses.book)
        bill = next(Invoice(instance=res) for res in q.run()
                    if Invoice(instance=res).GetID() == "BILL-001")
        pre_list = find_pre_unpost_payments(ses.book, bill)
        q.destroy()
    finally:
        ses.end()

    assert len(pre_list) == 1, f"Expected one pre-unpost bill payment, got {pre_list}"
    assert pre_list[0]['bank_account'] == 'Assets.Bank'
    assert pre_list[0]['memo'] == 'Payment BILL-001'
    assert pre_list[0]['tx_guid']

    r = runner.invoke(cli, ["unpost-bills", str(gnc), "BILL-001"])
    assert r.exit_code == 0, r.output
    time.sleep(1)

    ses = Session(f"xml://{gnc}")
    try:
        # Same call signature works because the helper filters by AP/AR
        # account-type (11 or 12), customer_id treats V001/C001 identically.
        post_list = find_orphan_payments_post_unpost(
            ses.book, invoice_id="BILL-001", customer_id="V001")
    finally:
        ses.end()

    assert len(post_list) == 1, f"Expected one bill orphan, got {post_list}"
    assert post_list[0]['customer_id'] == 'V001'
    assert post_list[0]['invoice_id_memo_match'] is True
    assert post_list[0]['tx_guid'] == pre_list[0]['tx_guid']


def test_find_orphan_payments_prototype(tmp_path):
    """Smoke-test both prototype helpers against the step-C → step-D world."""
    runner = CliRunner()
    gnc = tmp_path / "book.gnucash"
    fix = tmp_path / "in.txt"
    fix.write_text(ACCOUNTS + "\n" + INV_POSTED_PAID)
    r = runner.invoke(cli, ["import", "--new", str(gnc), str(fix),
                            "--include-business-objects"])
    assert r.exit_code == 0, r.output
    time.sleep(1)

    # PRE-UNPOST: list the about-to-be-orphan payments from the lot.
    from gnucash import Query, Session
    from gnucash.gnucash_business import Invoice
    ses = Session(f"xml://{gnc}")
    try:
        q = Query()
        q.search_for('gncInvoice')
        q.set_book(ses.book)
        inv = next(Invoice(instance=res) for res in q.run()
                   if Invoice(instance=res).GetID() == "INV-001")
        pre_list = find_pre_unpost_payments(ses.book, inv)
        q.destroy()
    finally:
        ses.end()

    assert len(pre_list) == 1, f"Expected one pre-unpost payment, got {pre_list}"
    assert pre_list[0]['bank_account'] == 'Assets.Bank'
    assert pre_list[0]['memo'] == 'Payment INV-001'
    assert pre_list[0]['tx_guid']

    # Now unpost and run the post-unpost recovery path.
    r = runner.invoke(cli, ["unpost-invoices", str(gnc), "INV-001"])
    assert r.exit_code == 0, r.output
    time.sleep(1)

    ses = Session(f"xml://{gnc}")
    try:
        post_list = find_orphan_payments_post_unpost(
            ses.book, invoice_id="INV-001", customer_id="C001")
    finally:
        ses.end()

    assert len(post_list) == 1, f"Expected one orphan, got {post_list}"
    assert post_list[0]['customer_id'] == 'C001'
    assert post_list[0]['invoice_id_memo_match'] is True
    assert post_list[0]['tx_guid'] == pre_list[0]['tx_guid'], (
        "Both paths must agree on which tx is the orphan."
    )
