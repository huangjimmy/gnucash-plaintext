"""
Q-010 + Q-014: dedicated unpost commands for invoices and bills, with
orphan-bank-payment surfacing.

`unpost-invoices <book> <ID>...` and `unpost-bills <book> <ID>...` provide
a one-shot, plaintext-free way to unpost a posted invoice/bill. Unlike
the re-import path (where toggling `posted: { ... }` → `posted: none`
also unposts but rebuilds entries from the .txt), this path:

  - Does NOT consult any plaintext file.
  - Preserves entry GUIDs (no destroy + recreate cycle).
  - Touches only the posted state. The lot's posting transaction is
    destroyed; payment transactions in the bank account are orphaned
    (their AR/AP splits no longer link to a lot). This matches GnuCash
    UI's own Unpost behaviour exactly.

Q-014: just before `Unpost(False)` we walk the posted lot and capture
every payment-class transaction attached to it. Those transactions
survive the unpost as free-standing bank entries; the CLI surfaces
them so the user knows what's left behind and how to clean it up
(`delete-transactions --by-guid` or Q-004's `txn_guid:` retarget).

Use the re-import path when the .txt is the source of truth and you
want to also edit fields. Use these commands when the .txt is stale or
absent and you only want the unpost itself.
"""

import ctypes
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from typing import List

from gnucash import Book

from infrastructure.gnucash.engine import (
    GncNumericC,
    iterate_glist,
    load_gnc_engine,
    safe_ctypes_string,
)
from services.gnucash_importer import (
    _find_bill_by_guid,
    _find_bills_by_id,
    _find_invoice_by_guid,
    _find_invoices_by_id,
    _swig_invoice_guid_str,
)


class UnpostStatus(Enum):
    UNPOSTED = auto()
    NOT_POSTED = auto()
    NOT_FOUND = auto()
    AMBIGUOUS_ID = auto()  # legacy data: multiple records share one id


@dataclass
class OrphanPayment:
    """A payment-class bank-side transaction.

    Produced by two helpers in this module:

      - `find_lot_payment_transactions(rec)` captures payments *before*
        `Unpost(False)` while the lot still names them. Authoritative; the
        `owner_*` fields are left empty since the caller already knows the
        invoice/bill they're about to unpost.

      - `find_orphan_payments_in_book(book)` walks the whole book to find
        already-orphaned payments (records that were unposted in a prior
        run / session). The lot → invoice link is destroyed by unpost, so
        these can be pinned to a customer/vendor but not to a specific
        invoice. The `owner_*` fields are populated; `description` and
        `memo` may carry an invoice id if the user followed the convention,
        but that's not guaranteed.
    """
    tx_guid: str           # 32-hex (no hyphens), the form `delete-transactions --by-guid` accepts
    date: str              # YYYY-MM-DD
    bank_account: str      # full account path, e.g. "Assets:Bank"
    amount: str            # absolute value, formatted to 2 decimals, e.g. "100.00"
    currency: str          # 3-letter mnemonic, e.g. "CAD"
    description: str       # transaction description (typically the customer/vendor name)
    memo: str              # bank-side split memo (user-controlled; may be empty)
    owner_type: int = 0    # 0=unknown, 2=Customer, 4=Vendor (post-unpost helper only)
    owner_id: str = ''     # e.g. "C001" (post-unpost helper only)
    owner_name: str = ''   # e.g. "Acme" (post-unpost helper only)
    ar_ap_account: str = ''  # AR or AP account the now-detached lot lives in,
                             # e.g. "Assets:Accounts Receivable" — populated by
                             # the post-unpost helper so the CLI explanation can
                             # name the exact account the lot detached from.


@dataclass
class UnpostResult:
    id: str
    guid: str = ''
    status: UnpostStatus = None
    kind: str = 'invoice'                                  # 'invoice' or 'bill'
    orphans: List[OrphanPayment] = field(default_factory=list)

    def message(self) -> str:
        if self.status == UnpostStatus.UNPOSTED:
            return 'unposted'
        if self.status == UnpostStatus.NOT_POSTED:
            return ('failed — record has no posting transaction (never posted, '
                    'or already unposted by a previous run / GnuCash UI); '
                    'no action taken')
        if self.status == UnpostStatus.AMBIGUOUS_ID:
            return ('failed — multiple records share this id; rerun with '
                    '--by-guid')
        return 'not found'

    def label(self) -> str:
        if self.guid:
            return f'{self.id} ({self.guid})'
        return self.id


def format_orphan_warning_block(kind: str, orphans: List['OrphanPayment'],
                                 ident: str = '') -> str:
    """Render the per-record orphan-payment warning block.

    Used both by the `unpost-invoices` / `unpost-bills` CLI commands and
    by the Q-015 importer plumbing — every importer-side `Unpost(False)`
    on a paid record runs this through `cli/import_cmd.py`'s callback so
    the user sees the same warning shape as the dedicated CLI commands.

    Returns the empty string if `orphans` is empty (record posted but
    never paid — silent success). For invoices: "AR", "received". For
    bills: "AP", "sent".

    `ident` (e.g. "INV-001") is prepended to the lead-in when given so a
    multi-record import distinguishes which record each warning belongs
    to. The unpost CLI sets it to '' because its per-record output line
    immediately precedes the warning.
    """
    if not orphans:
        return ''

    n = len(orphans)
    noun = 'transaction' if n == 1 else 'transactions'
    is_invoice = (kind == 'invoice')
    side = 'AR' if is_invoice else 'AP'
    flow = 'received in' if is_invoice else 'sent from'
    record_word = kind
    label = f' for {kind} "{ident}"' if ident else ''

    lines = []
    lines.append('')
    lines.append(
        f'⚠  {n} bank-side payment {noun} {"is" if n == 1 else "are"} '
        f'now orphaned in the book{label}.'
    )
    lines.append(
        f'   GnuCash unpost destroys the {side} posting transaction but '
        f'leaves payment'
    )
    lines.append(
        f'   transactions intact — the money still shows as {flow} '
        f'your bank account.'
    )
    lines.append('')

    def _hyphenate(guid32: str) -> str:
        g = guid32
        return f'{g[0:8]}-{g[8:12]}-{g[12:16]}-{g[16:20]}-{g[20:32]}'

    for o in orphans:
        lines.append(
            f'   • {o.date}  {o.bank_account}  {o.currency} {o.amount}  '
            f'"{o.description}"'
        )
        if o.memo:
            lines.append(f'     memo: "{o.memo}"')
        lines.append(f'     guid: {_hyphenate(o.tx_guid)}')

    if n > 1:
        by_acct: dict = {}
        for o in orphans:
            by_acct.setdefault((o.bank_account, o.currency), 0.0)
            by_acct[(o.bank_account, o.currency)] += float(o.amount)
        if len(by_acct) == 1:
            (acct, ccy), total = next(iter(by_acct.items()))
            lines.append('')
            lines.append(f'   Total orphaned: {ccy} {total:.2f} in {acct}.')
        else:
            lines.append('')
            lines.append('   Total orphaned per bank account:')
            for (acct, ccy), total in sorted(by_acct.items()):
                lines.append(f'     {ccy} {total:.2f} in {acct}')

    lines.append('')
    lines.append(f'   If you intend to re-pay this {record_word}, either:')
    lines.append('     a) delete the orphan(s) first:')
    for o in orphans:
        lines.append(
            f'          gnucash-plaintext delete-transactions <book> '
            f'--by-guid {o.tx_guid}'
        )
    lines.append(
        f'        then re-import the {record_word} with a fresh '
        f'`payment:` block, or'
    )
    lines.append(
        f'     b) re-import the {record_word} with a `payment:` block '
        f'that includes'
    )
    if n == 1:
        lines.append(f'          txn_guid: "{orphans[0].tx_guid}"')
    else:
        lines.append('          txn_guid: "<orphan-guid>"  (one block per orphan)')
    lines.append(
        '        to retarget the existing bank transaction(s) into the '
        'new posted lot'
    )
    lines.append('        (see docs/issues/Q-004 for the retarget mechanism).')

    return '\n'.join(lines)


def find_lot_payment_transactions(rec) -> List[OrphanPayment]:
    """Return every payment-class transaction attached to `rec`'s posted lot.

    Must be called BEFORE `rec.Unpost(False)` — once unposted, the lot's
    invoice association is destroyed and the lot can no longer be walked
    from the record. Returns [] if `rec.GetPostedLot()` is None (the record
    is not currently posted, so there's no lot to walk).

    The walk yields each payment transaction exactly once (a payment tx has
    two splits — bank and AR/AP — both on the lot's split list).

    Zero false positives: lot membership is set by `gncOwnerApplyPayment`
    when the payment is recorded; non-payment transactions on the lot are
    excluded by the `xaccTransGetTxnType == 'P'` filter (payment-class
    only — distinct from `'I'` for the invoice's own posting tx).

    Identification of the bank-side split: a payment transaction has one
    split on an A/Receivable (account type 11) or A/Payable (12) account
    and one split elsewhere. The "elsewhere" split is the bank-side; we
    report its account, memo, and the absolute amount.
    """
    lot = rec.GetPostedLot()
    if lot is None:
        return []

    lib = load_gnc_engine()
    # Lazily configure ctypes function signatures used in the walk.
    # argtypes is non-optional for every pointer arg (CLAUDE.md §1).
    # GncNumeric returns must use `restype=GncNumericC` (ctypes marshals the
    # 16-byte struct value, NOT a pointer to it).
    for name, restype, argtypes in [
        ('gnc_lot_get_split_list',     ctypes.c_void_p, [ctypes.c_void_p]),
        ('xaccSplitGetParent',         ctypes.c_void_p, [ctypes.c_void_p]),
        ('xaccSplitGetAmount',         GncNumericC,     [ctypes.c_void_p]),
        ('xaccTransGetTxnType',        ctypes.c_char,   [ctypes.c_void_p]),
        ('xaccTransCountSplits',       ctypes.c_int,    [ctypes.c_void_p]),
        ('xaccTransGetSplit',          ctypes.c_void_p, [ctypes.c_void_p, ctypes.c_int]),
        ('xaccTransGetDate',           ctypes.c_int64,  [ctypes.c_void_p]),
        ('xaccTransGetDescription',    ctypes.c_char_p, [ctypes.c_void_p]),
        ('xaccTransGetCurrency',       ctypes.c_void_p, [ctypes.c_void_p]),
        ('xaccSplitGetAccount',        ctypes.c_void_p, [ctypes.c_void_p]),
        ('xaccSplitGetMemo',           ctypes.c_char_p, [ctypes.c_void_p]),
        ('xaccAccountGetType',         ctypes.c_int,    [ctypes.c_void_p]),
        ('gnc_commodity_get_mnemonic', ctypes.c_char_p, [ctypes.c_void_p]),
        ('qof_instance_get_guid',      ctypes.c_void_p, [ctypes.c_void_p]),
        ('guid_to_string_buff',        ctypes.c_char_p, [ctypes.c_void_p, ctypes.c_char_p]),
        ('xaccAccountGetName',         ctypes.c_char_p, [ctypes.c_void_p]),
        ('gnc_account_get_parent',     ctypes.c_void_p, [ctypes.c_void_p]),
    ]:
        try:
            f = getattr(lib, name)
            f.restype = restype
            f.argtypes = argtypes
        except AttributeError:
            pass

    def _acct_full_name(acct_ptr) -> str:
        """Build the account's full path using `:` as separator, the project's
        plaintext convention. Avoids `gnc_account_get_full_name` because that
        function uses the book's configured separator (defaults to `.`),
        which doesn't match the plaintext format. Same parent-walk pattern as
        `services/gnucash_importer.py:_acct_name`."""
        parts = []
        ptr = acct_ptr
        while ptr:
            name = safe_ctypes_string(lib.xaccAccountGetName, ptr)
            if name:
                parts.append(name)
            parent = lib.gnc_account_get_parent(ptr)
            if not parent:
                break
            # Stop at the root account (which has no parent of its own).
            if not lib.gnc_account_get_parent(parent):
                break
            ptr = parent
        parts.reverse()
        return ':'.join(parts)

    splits_glist = lib.gnc_lot_get_split_list(int(lot.instance))

    results: List[OrphanPayment] = []
    seen_tx: set = set()
    for split_ptr in iterate_glist(lib, splits_glist, lambda lib, p: p):
        if not split_ptr:
            continue
        tx_ptr = lib.xaccSplitGetParent(split_ptr)
        if not tx_ptr or tx_ptr in seen_tx:
            continue
        seen_tx.add(tx_ptr)

        # Filter to payment-class transactions only. The lot also contains
        # the invoice's own posting tx (txn_type 'I') — we don't want that.
        tx_type = lib.xaccTransGetTxnType(tx_ptr)
        if isinstance(tx_type, bytes):
            tx_type = tx_type.decode('ascii', errors='replace')
        if tx_type != 'P':
            continue

        # Find the bank-side split: any split NOT on an AR/AP account.
        bank_acct_name = ''
        bank_memo = ''
        bank_amount = 0.0
        nsplits = lib.xaccTransCountSplits(tx_ptr)
        for j in range(nsplits):
            s_ptr = lib.xaccTransGetSplit(tx_ptr, j)
            a_ptr = lib.xaccSplitGetAccount(s_ptr)
            a_type = lib.xaccAccountGetType(a_ptr)
            if a_type in (11, 12):                         # A/Receivable, A/Payable
                continue
            bank_acct_name = _acct_full_name(a_ptr)
            bank_memo_raw = lib.xaccSplitGetMemo(s_ptr)
            bank_memo = (bank_memo_raw.decode('utf-8', errors='replace')
                         if bank_memo_raw else '')
            amt = lib.xaccSplitGetAmount(s_ptr)
            bank_amount = abs(amt.num / amt.denom) if amt.denom else 0.0
            break

        # Tx-level fields, all via ctypes.
        # xaccTransGetDate returns time64 (seconds since epoch, UTC).
        epoch = lib.xaccTransGetDate(tx_ptr)
        date_str = datetime.fromtimestamp(epoch, tz=timezone.utc).strftime('%Y-%m-%d')
        desc_raw = lib.xaccTransGetDescription(tx_ptr)
        description = desc_raw.decode('utf-8', errors='replace') if desc_raw else ''
        commodity_ptr = lib.xaccTransGetCurrency(tx_ptr)
        mnemonic_raw = (lib.gnc_commodity_get_mnemonic(commodity_ptr)
                        if commodity_ptr else None)
        currency = (mnemonic_raw.decode('ascii', errors='replace')
                    if mnemonic_raw else '')

        # tx_guid in the form `delete-transactions --by-guid` accepts:
        # 32-hex, no hyphens, lowercase.
        guid_ptr = lib.qof_instance_get_guid(tx_ptr)
        buf = ctypes.create_string_buffer(40)
        lib.guid_to_string_buff(guid_ptr, buf)
        tx_guid = buf.value.decode('ascii').replace('-', '')

        results.append(OrphanPayment(
            tx_guid=tx_guid,
            date=date_str,
            bank_account=bank_acct_name,
            amount=f'{bank_amount:.2f}',
            currency=currency,
            description=description,
            memo=bank_memo,
        ))
    return results


def find_prepayments_in_book(book: Book,
                              customer_id: str = None,
                              vendor_id: str = None) -> List['OrphanPayment']:
    """Walk the book and return every open AR/AP lot that holds an
    unconsumed customer/vendor credit (a "pre-payment").

    A prepayment lot is the residual GnuCash creates when a customer
    overpays an invoice (or a vendor is overpaid on a bill), or when a
    standalone payment is recorded without an invoice to attach to. The
    lot stays open on the AR/AP account until consumed by a future
    invoice via `gncInvoiceAutoApplyPayments` (or by the GnuCash UI's
    Process Payment).

    Criteria — every lot must satisfy all of them:

      1. Lives on an A/Receivable or A/Payable account.
      2. `gncInvoiceGetInvoiceFromLot` returns NULL (no invoice/bill is
         the source of the lot's existence — distinguishes prepay lots
         from invoice/bill lots that happen to still be open from
         partial payment).
      3. Lot balance != 0 (excludes empty lots that haven't been
         garbage-collected yet).
      4. We can identify the owner (customer/vendor) from the parent
         payment tx of one of the lot's splits, via
         `gncOwnerGetOwnerFromTxn` (or the custom-KVP fallback that
         Q-014 introduced for roundtripped payments).

    Returns `List[OrphanPayment]` — the dataclass is reused because the
    surface fields (owner, source tx, amount, currency, bank account)
    are the same as for orphan payments. The `amount` field is the
    *lot's balance* (the unconsumed credit), not the original payment
    amount.

    Filters:
      - `customer_id` restricts to that customer's credits.
      - `vendor_id` restricts to that vendor's credits.
      - Pass neither for the whole-book sweep.
    """
    import gnucash.gnucash_core_c as _gc
    from gnucash import GncLot, Split

    lib = load_gnc_engine()
    for name, restype, argtypes in [
        ('xaccAccountGetType',         ctypes.c_int,    [ctypes.c_void_p]),
        ('xaccSplitGetAccount',        ctypes.c_void_p, [ctypes.c_void_p]),
        ('xaccSplitGetAmount',         GncNumericC,     [ctypes.c_void_p]),
        ('xaccTransGetDate',           ctypes.c_int64,  [ctypes.c_void_p]),
        ('xaccTransGetDescription',    ctypes.c_char_p, [ctypes.c_void_p]),
        ('xaccTransGetCurrency',       ctypes.c_void_p, [ctypes.c_void_p]),
        ('gnc_commodity_get_mnemonic', ctypes.c_char_p, [ctypes.c_void_p]),
        ('qof_instance_get_guid',      ctypes.c_void_p, [ctypes.c_void_p]),
        ('guid_to_string_buff',        ctypes.c_char_p, [ctypes.c_void_p, ctypes.c_char_p]),
        ('xaccAccountGetName',         ctypes.c_char_p, [ctypes.c_void_p]),
        ('gnc_account_get_parent',     ctypes.c_void_p, [ctypes.c_void_p]),
        ('gncOwnerGetOwnerFromTxn',    ctypes.c_int,    [ctypes.c_void_p, ctypes.c_void_p]),
        ('gncOwnerGetID',              ctypes.c_char_p, [ctypes.c_void_p]),
        ('gncOwnerGetName',            ctypes.c_char_p, [ctypes.c_void_p]),
        ('gncOwnerGetType',            ctypes.c_int,    [ctypes.c_void_p]),
    ]:
        try:
            f = getattr(lib, name)
            f.restype = restype
            f.argtypes = argtypes
        except AttributeError:
            pass

    def _acct_full_name(acct_ptr) -> str:
        parts = []
        ptr = acct_ptr
        while ptr:
            name = safe_ctypes_string(lib.xaccAccountGetName, ptr)
            if name:
                parts.append(name)
            parent = lib.gnc_account_get_parent(ptr)
            if not parent or not lib.gnc_account_get_parent(parent):
                break
            ptr = parent
        parts.reverse()
        return ':'.join(parts)

    owner_buf = ctypes.create_string_buffer(256)
    owner_ptr = ctypes.cast(owner_buf, ctypes.c_void_p).value

    from gnucash import (
        ACCT_TYPE_PAYABLE,
        ACCT_TYPE_RECEIVABLE,
    )

    from infrastructure.gnucash.kvp import get_custom_metadata
    from infrastructure.gnucash.utils import get_account_full_name

    results: List[OrphanPayment] = []

    def walk(acct):
        atype = lib.xaccAccountGetType(int(acct.instance))
        if atype in (11, 12):  # AR, AP
            for raw_lot in acct.GetLotList():
                lot = GncLot(instance=raw_lot)
                # Criterion 2: no invoice attached.
                if _gc.gncInvoiceGetInvoiceFromLot(raw_lot):
                    continue
                # Criterion 3: nonzero balance (unconsumed credit).
                balance = lot.get_balance().to_double()
                if abs(balance) < 1e-6:
                    continue

                # Identify owner via the parent tx of the first split.
                members = list(lot.get_split_list())
                if not members:
                    continue
                first = Split(instance=members[0])
                tx = first.GetParent()
                tx_ptr = int(tx.instance)

                got = lib.gncOwnerGetOwnerFromTxn(tx_ptr, owner_ptr)
                owner_id = ''
                owner_type = 0
                owner_name = ''
                if got == 1:
                    oid_raw = lib.gncOwnerGetID(owner_ptr)
                    owner_id = oid_raw.decode('utf-8', errors='replace') if oid_raw else ''
                    owner_type = lib.gncOwnerGetType(owner_ptr)
                    name_raw = lib.gncOwnerGetName(owner_ptr)
                    owner_name = name_raw.decode('utf-8', errors='replace') if name_raw else ''
                else:
                    # Custom-KVP fallback (Q-014 plaintext roundtrip).
                    kvp = get_custom_metadata(tx) or {}
                    kvp_owner = kvp.get('owner', '')
                    if kvp_owner and ':' in kvp_owner:
                        kind, _, oid = kvp_owner.partition(':')
                        kind, oid = kind.strip(), oid.strip()
                        if kind == 'customer' and oid:
                            cust = book.CustomerLookupByID(oid)
                            if cust is not None and cust.GetID():
                                owner_type, owner_id, owner_name = 2, oid, cust.GetName() or ''
                        elif kind == 'vendor' and oid:
                            vend = book.VendorLookupByID(oid)
                            if vend is not None and vend.GetID():
                                owner_type, owner_id, owner_name = 4, oid, vend.GetName() or ''
                if not owner_id:
                    continue
                if customer_id and not (owner_type == 2 and owner_id == customer_id):
                    continue
                if vendor_id and not (owner_type == 4 and owner_id == vendor_id):
                    continue

                # Source tx fields. Find the bank-side split of the original
                # payment tx (for the user's reference back to where the
                # credit came from).
                bank_acct_name = ''
                bank_memo = ''
                for i in range(tx.CountSplits()):
                    sp = tx.GetSplit(i)
                    sp_acct = sp.GetAccount()
                    if sp_acct is None:
                        continue
                    sp_atype = sp_acct.GetType()
                    if sp_atype in (ACCT_TYPE_RECEIVABLE, ACCT_TYPE_PAYABLE):
                        continue
                    bank_acct_name = get_account_full_name(sp_acct)
                    bank_memo = sp.GetMemo() or ''
                    break

                date_str = tx.GetDate().strftime('%Y-%m-%d')
                description = tx.GetDescription() or ''
                commodity_ptr = lib.xaccTransGetCurrency(tx_ptr)
                mnemonic_raw = (lib.gnc_commodity_get_mnemonic(commodity_ptr)
                                if commodity_ptr else None)
                currency = (mnemonic_raw.decode('ascii', errors='replace')
                            if mnemonic_raw else '')
                guid_ptr = lib.qof_instance_get_guid(tx_ptr)
                buf = ctypes.create_string_buffer(40)
                lib.guid_to_string_buff(guid_ptr, buf)
                tx_guid = buf.value.decode('ascii').replace('-', '')

                results.append(OrphanPayment(
                    tx_guid=tx_guid,
                    date=date_str,
                    bank_account=bank_acct_name,
                    amount=f'{abs(balance):.2f}',
                    currency=currency,
                    description=description,
                    memo=bank_memo,
                    owner_type=owner_type,
                    owner_id=owner_id,
                    owner_name=owner_name,
                    ar_ap_account=get_account_full_name(acct),
                ))

        for child in acct.get_children():
            walk(child)

    walk(book.get_root_account())
    return results


def find_orphan_payments_in_book(book: Book,
                                 customer_id: str = None,
                                 vendor_id: str = None) -> List[OrphanPayment]:
    """Walk the book and return every payment-class bank-side transaction
    that no longer points at any invoice/bill lot.

    Use this for after-the-fact recovery — books where an invoice/bill was
    unposted in a prior session and the user wants to see what bank-side
    entries are sitting around unattached. (For the live unpost flow, the
    CLI already shows the same info up-front via `find_lot_payment_transactions`.)

    Criteria — every transaction must satisfy all of them:

      1. `xaccTransGetTxnType(tx) == 'P'` — payment-class only. Excludes the
         invoice's own posting tx ('I') and manual deposits ('N').
      2. `gncOwnerGetOwnerFromTxn` returns success — the KVP customer/vendor
         backref set by `gncOwnerApplyPayment` survives unpost.
      3. Payment shape — exactly one split on an AR/AP account (type 11/12)
         and exactly one split elsewhere (the bank side). Excludes hand-
         crafted multi-split exotica.
      4. The AR/AP-side split's lot has no invoice/bill attached — i.e.
         the lot is detached, which is exactly what unpost does. Skips
         payments that are still attached to a currently-posted record.

    False-positive risk: when a customer has multiple orphan payments from
    different (now-unposted) invoices in the same book, this helper lists
    them all but cannot say *which* invoice each one originally paid. The
    user-controlled memo / description fields may carry an invoice id by
    convention, but the helper does not assume so.

    Filters:
      - `customer_id` (e.g. "C001") restricts the result to that customer's
        orphans.
      - `vendor_id` (e.g. "V001") restricts to that vendor's orphans.
      - Pass neither for the full book sweep.
    """
    lib = load_gnc_engine()
    for name, restype, argtypes in [
        ('xaccTransGetTxnType',        ctypes.c_char,   [ctypes.c_void_p]),
        ('xaccTransCountSplits',       ctypes.c_int,    [ctypes.c_void_p]),
        ('xaccTransGetSplit',          ctypes.c_void_p, [ctypes.c_void_p, ctypes.c_int]),
        ('xaccTransGetDate',           ctypes.c_int64,  [ctypes.c_void_p]),
        ('xaccTransGetDescription',    ctypes.c_char_p, [ctypes.c_void_p]),
        ('xaccTransGetCurrency',       ctypes.c_void_p, [ctypes.c_void_p]),
        ('xaccSplitGetAccount',        ctypes.c_void_p, [ctypes.c_void_p]),
        ('xaccSplitGetMemo',           ctypes.c_char_p, [ctypes.c_void_p]),
        ('xaccSplitGetAmount',         GncNumericC,     [ctypes.c_void_p]),
        ('xaccSplitGetLot',            ctypes.c_void_p, [ctypes.c_void_p]),
        ('xaccAccountGetType',         ctypes.c_int,    [ctypes.c_void_p]),
        ('gnc_commodity_get_mnemonic', ctypes.c_char_p, [ctypes.c_void_p]),
        ('gncInvoiceGetInvoiceFromLot', ctypes.c_void_p, [ctypes.c_void_p]),
        ('gncOwnerGetOwnerFromTxn',    ctypes.c_int,    [ctypes.c_void_p, ctypes.c_void_p]),
        ('gncOwnerGetID',              ctypes.c_char_p, [ctypes.c_void_p]),
        ('gncOwnerGetName',            ctypes.c_char_p, [ctypes.c_void_p]),
        ('gncOwnerGetType',            ctypes.c_int,    [ctypes.c_void_p]),
        ('qof_instance_get_guid',      ctypes.c_void_p, [ctypes.c_void_p]),
        ('guid_to_string_buff',        ctypes.c_char_p, [ctypes.c_void_p, ctypes.c_char_p]),
        ('xaccAccountGetName',         ctypes.c_char_p, [ctypes.c_void_p]),
        ('gnc_account_get_parent',     ctypes.c_void_p, [ctypes.c_void_p]),
    ]:
        try:
            f = getattr(lib, name)
            f.restype = restype
            f.argtypes = argtypes
        except AttributeError:
            pass

    def _acct_full_name(acct_ptr) -> str:
        parts = []
        ptr = acct_ptr
        while ptr:
            name = safe_ctypes_string(lib.xaccAccountGetName, ptr)
            if name:
                parts.append(name)
            parent = lib.gnc_account_get_parent(ptr)
            if not parent or not lib.gnc_account_get_parent(parent):
                break
            ptr = parent
        parts.reverse()
        return ':'.join(parts)

    # Reusable GncOwner scratch buffer. 256 bytes is safely larger than the
    # real struct on every supported GnuCash version (per the probe).
    owner_buf = ctypes.create_string_buffer(256)
    owner_ptr = ctypes.cast(owner_buf, ctypes.c_void_p).value

    from gnucash import Query, Transaction

    from infrastructure.gnucash.kvp import get_custom_metadata
    q = Query()
    try:
        q.search_for('Trans')
        q.set_book(book)

        results: List[OrphanPayment] = []
        for r in q.run():
            tx = Transaction(instance=r)
            tx_ptr = int(tx.instance)

            # Criterion 1: payment-class. The C-side `xaccTransGetTxnType`
            # is HEURISTIC-driven in GnuCash 5.x (per `Transaction.h`:
            # "derived from the transaction splits according to
            # heuristics ... does not query the transaction kvp slots").
            # The heuristic returns 'P' only when the AR-side split has a
            # lot + owner backref attached — both of which survive an
            # in-file unpost but are LOST across a plaintext roundtrip.
            # So we fall back to the exporter's `txn_type:` line, which
            # the importer preserved as a custom KVP because `txn_type`
            # is deliberately NOT in KNOWN_TX_METADATA_KEYS.
            t = lib.xaccTransGetTxnType(tx_ptr)
            if isinstance(t, bytes):
                t = t.decode('ascii', errors='replace')
            tx_kvp = get_custom_metadata(tx) or {}
            tx_kvp_type = tx_kvp.get('txn_type', '')
            if t != 'P' and tx_kvp_type != 'P':
                continue

            # Criterion 2: customer/vendor backref. Same story —
            # `gncOwnerGetOwnerFromTxn` reads the gncOwner KVP slot
            # (set in C by `gncOwnerApplyPayment`); the slot survives
            # unpost in-file but cannot be re-set from Python after a
            # roundtrip (both ctypes `gncOwnerCopyOnTxn` and SWIG
            # equivalents are silent no-ops in 5.x). Fall back to the
            # exporter's `owner: customer:<id>` / `owner: vendor:<id>`
            # line, preserved as a custom KVP.
            got = lib.gncOwnerGetOwnerFromTxn(tx_ptr, owner_ptr)
            this_owner_id = ''
            this_owner_type = 0
            this_owner_name = ''
            if got == 1:
                owner_id_raw = lib.gncOwnerGetID(owner_ptr)
                this_owner_id = (owner_id_raw.decode('utf-8', errors='replace')
                                 if owner_id_raw else '')
                this_owner_type = lib.gncOwnerGetType(owner_ptr)
                owner_name_raw = lib.gncOwnerGetName(owner_ptr)
                this_owner_name = (owner_name_raw.decode('utf-8', errors='replace')
                                   if owner_name_raw else '')
            else:
                # Try the custom-KVP fallback. Format: "customer:<id>"
                # or "vendor:<id>". Name isn't preserved across roundtrip
                # so we look it up by id.
                kvp_owner = tx_kvp.get('owner', '')
                if kvp_owner and ':' in kvp_owner:
                    kind, _, oid = kvp_owner.partition(':')
                    kind = kind.strip()
                    oid = oid.strip()
                    if kind == 'customer' and oid:
                        cust = book.CustomerLookupByID(oid)
                        if cust is not None and cust.GetID():
                            this_owner_type = 2
                            this_owner_id = oid
                            this_owner_name = cust.GetName() or ''
                    elif kind == 'vendor' and oid:
                        vend = book.VendorLookupByID(oid)
                        if vend is not None and vend.GetID():
                            this_owner_type = 4
                            this_owner_id = oid
                            this_owner_name = vend.GetName() or ''
            if not this_owner_id:
                continue
            if customer_id and not (this_owner_type == 2 and this_owner_id == customer_id):
                continue
            if vendor_id and not (this_owner_type == 4 and this_owner_id == vendor_id):
                continue

            # Criterion 3: payment shape — one AR/AP split, one elsewhere.
            ar_s = None
            bank_s = None
            nsplits = lib.xaccTransCountSplits(tx_ptr)
            for j in range(nsplits):
                s_ptr = lib.xaccTransGetSplit(tx_ptr, j)
                a_ptr = lib.xaccSplitGetAccount(s_ptr)
                a_type = lib.xaccAccountGetType(a_ptr)
                if a_type in (11, 12):
                    ar_s = s_ptr
                else:
                    bank_s = s_ptr
            if not (ar_s and bank_s):
                continue

            # Criterion 4: AR/AP-side lot has no invoice attached → orphan.
            # Three states are accepted:
            #   - lot exists and has NO invoice → unposted-in-file orphan
            #   - no lot at all → roundtripped orphan (plaintext doesn't
            #     carry lots, so the importer recreates the tx with
            #     loose splits)
            # Lot exists AND has invoice → still attached, skip.
            lot_ptr = lib.xaccSplitGetLot(ar_s)
            if lot_ptr and lib.gncInvoiceGetInvoiceFromLot(lot_ptr):
                continue                       # still attached to a posted record

            ar_ap_a_ptr = lib.xaccSplitGetAccount(ar_s)
            ar_ap_acct_name = _acct_full_name(ar_ap_a_ptr)
            bank_a_ptr = lib.xaccSplitGetAccount(bank_s)
            bank_acct_name = _acct_full_name(bank_a_ptr)
            memo_raw = lib.xaccSplitGetMemo(bank_s)
            memo = memo_raw.decode('utf-8', errors='replace') if memo_raw else ''
            amt = lib.xaccSplitGetAmount(bank_s)
            amount = abs(amt.num / amt.denom) if amt.denom else 0.0

            epoch = lib.xaccTransGetDate(tx_ptr)
            date_str = datetime.fromtimestamp(epoch, tz=timezone.utc).strftime('%Y-%m-%d')
            desc_raw = lib.xaccTransGetDescription(tx_ptr)
            description = desc_raw.decode('utf-8', errors='replace') if desc_raw else ''
            commodity_ptr = lib.xaccTransGetCurrency(tx_ptr)
            mnemonic_raw = (lib.gnc_commodity_get_mnemonic(commodity_ptr)
                            if commodity_ptr else None)
            currency = (mnemonic_raw.decode('ascii', errors='replace')
                        if mnemonic_raw else '')

            guid_ptr = lib.qof_instance_get_guid(tx_ptr)
            buf = ctypes.create_string_buffer(40)
            lib.guid_to_string_buff(guid_ptr, buf)
            tx_guid = buf.value.decode('ascii').replace('-', '')

            results.append(OrphanPayment(
                tx_guid=tx_guid,
                date=date_str,
                bank_account=bank_acct_name,
                amount=f'{amount:.2f}',
                currency=currency,
                description=description,
                memo=memo,
                owner_type=this_owner_type,
                owner_id=this_owner_id,
                owner_name=this_owner_name,
                ar_ap_account=ar_ap_acct_name,
            ))
        return results
    finally:
        q.destroy()


def _resolve_one(book: Book, id_or_guid: str, by_guid: bool, by_id_fn, by_guid_fn):
    """Look up exactly one invoice/bill. Returns (record, report_id, report_guid).

    On miss: (None, original_input, '').
    On ambiguous (legacy duplicates): (None, original_input, '__ambiguous__')
    so the caller can map to AMBIGUOUS_ID. We refuse to silently pick one.
    """
    if by_guid:
        rec = by_guid_fn(book, id_or_guid)
        if rec is None:
            return None, id_or_guid, ''
        return rec, rec.GetID(), id_or_guid
    matches = by_id_fn(book, id_or_guid)
    if not matches:
        return None, id_or_guid, ''
    if len(matches) > 1:
        return None, id_or_guid, '__ambiguous__'
    rec = matches[0]
    return rec, rec.GetID(), _swig_invoice_guid_str(rec)


def _execute_unpost(book: Book, ids: List[str], by_guid: bool,
                    by_id_fn, by_guid_fn, kind: str) -> List[UnpostResult]:
    """Shared body for UnpostInvoicesUseCase and UnpostBillsUseCase.

    Captures the lot's payment transactions BEFORE `Unpost(False)` so the
    caller can warn the user about what's about to be orphaned.
    """
    results = []
    for arg in ids:
        rec, rid, rguid = _resolve_one(book, arg, by_guid, by_id_fn, by_guid_fn)
        if rec is None and rguid == '__ambiguous__':
            results.append(UnpostResult(
                id=rid, status=UnpostStatus.AMBIGUOUS_ID, kind=kind))
            continue
        if rec is None:
            results.append(UnpostResult(
                id=rid, status=UnpostStatus.NOT_FOUND, kind=kind))
            continue
        if rec.GetPostedTxn() is None:
            results.append(UnpostResult(
                id=rid, guid=rguid, status=UnpostStatus.NOT_POSTED, kind=kind))
            continue
        orphans = find_lot_payment_transactions(rec)
        rec.Unpost(False)
        results.append(UnpostResult(
            id=rid, guid=rguid, status=UnpostStatus.UNPOSTED,
            kind=kind, orphans=orphans))
    return results


class UnpostInvoicesUseCase:
    """Unpost one or more posted customer invoices."""

    def __init__(self, book: Book):
        self.book = book

    def execute(self, ids: List[str], by_guid: bool = False) -> List[UnpostResult]:
        return _execute_unpost(
            self.book, ids, by_guid,
            _find_invoices_by_id, _find_invoice_by_guid, kind='invoice')


class UnpostBillsUseCase:
    """Unpost one or more posted vendor bills."""

    def __init__(self, book: Book):
        self.book = book

    def execute(self, ids: List[str], by_guid: bool = False) -> List[UnpostResult]:
        return _execute_unpost(
            self.book, ids, by_guid,
            _find_bills_by_id, _find_bill_by_guid, kind='bill')
