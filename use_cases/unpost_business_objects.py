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
from fractions import Fraction
from typing import List

from gnucash import Book

from infrastructure.gnucash.engine import (
    GncNumericC,
    iterate_glist,
    load_gnc_engine,
    safe_ctypes_string,
)
from infrastructure.gnucash.utils import (
    money_text,
    numeric_to_fraction,
    qof_instance,
    qof_pointer,
)
from services.foreign_currency import require_cost_basis_unused
from services.gnucash_importer import (
    _find_bill_by_guid,
    _find_bills_by_id,
    _find_invoice_by_guid,
    _find_invoices_by_id,
    _swig_invoice_guid_str,
    mark_splits_orphaned_by_unpost,
)


def _commodity_unit(lib, commodity_ptr) -> int:
    """The commodity's smallest unit, or 100 when it cannot be read."""
    if not commodity_ptr:
        return 100
    return lib.gnc_commodity_get_fraction(commodity_ptr) or 100


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
    marked_by_unpost: bool = False  # The split carries the note an unpost
                                    # leaves. Often true alongside the type
                                    # reading below; the only evidence there is
                                    # for a settlement attached by retarget,
                                    # whose transaction has neither slot set.
    shares_its_transaction: bool = False  # Another orphan sits on the same
                                          # transaction, so deleting the guid
                                          # takes that one too. Recorded before
                                          # any owner filter, or narrowing to
                                          # one customer would hide the warning
                                          # on exactly the path a reader
                                          # cleaning up follows.
    owner_source: str = ''  # Where whose-money-this-is came from, so the CLI
                            # can name the reading rather than guess at it:
                            # 'lot' (this row's own split's lot), 'txn'
                            # (`gncOwnerGetOwnerFromTxn`), 'kvp' (the
                            # exporter's `owner:` line, which is what answers
                            # on a round-tripped book), or 'another_lot' (a
                            # sibling orphan's lot, when this row's cannot
                            # say). A boolean collapsed the last three, and the
                            # block claimed a backref "set at payment time"
                            # for an owner the exporter had written.
    typed_by_engine: bool = False   # `xaccTransGetTxnType` returned 'P'.
    typed_by_kvp: bool = False      # The exporter's `txn_type:` line did.
                                    # Different evidence: on a round-tripped
                                    # book the engine says 'N' and only the
                                    # KVP answers, so they are reported apart.
    amount_account: str = ''  # The account `amount`/`currency` are of. Empty
                              # means the bank account, which is where the
                              # figure came from before an orphan's own split
                              # could be the one reported: on a foreign
                              # invoice settled from a base-currency bank the
                              # two are different money, and naming the bank
                              # beside a USD figure describes an account that
                              # never held it.


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
        # Exact throughout: each amount is already text at its own currency's
        # decimals, so the total adds those figures rather than their nearest
        # doubles, and is written back the same way.
        by_acct: dict = {}
        units: dict = {}
        for o in orphans:
            key = (o.bank_account, o.currency)
            by_acct[key] = by_acct.get(key, Fraction(0)) + Fraction(o.amount)
            # The amounts are already written at their currency's decimals, so
            # the total keeps the same ones: 200.00 CAD, 206 JPY.
            units[key] = 10 ** len(o.amount.partition('.')[2])
        if len(by_acct) == 1:
            (acct, ccy), total = next(iter(by_acct.items()))
            lines.append('')
            lines.append(f'   Total orphaned: {ccy} '
                         f'{money_text(total, units[(acct, ccy)])} in {acct}.')
        else:
            lines.append('')
            lines.append('   Total orphaned per bank account:')
            for (acct, ccy), total in sorted(by_acct.items()):
                lines.append(f'     {ccy} {money_text(total, units[(acct, ccy)])} '
                             f'in {acct}')

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
        ('gnc_commodity_get_fraction', ctypes.c_int,    [ctypes.c_void_p]),
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
        `services/gnucash_importer.py:_acct_name`.

        The condition is "this account has a parent", asked once: having one
        is what distinguishes an account from the root, and the root is where
        the walk stops. Written as a walk that broke out of itself, three of
        its branches could not be taken — an account with no name, an account
        with no parent at all, and the loop ending any way other than by
        breaking — and an unreachable branch is a claim about the book that
        nothing can check.
        """
        # Every segment, including an empty one. An account may have no name —
        # `beancount_account_name_ending_in_a_separator.beancount` measures a
        # child with none under `Assets:Bank` — and dropping those made this
        # walk answer `Assets:Bank` for it while `get_account_full_name`, which
        # every other reader uses, answers `Assets:Bank:`. Two names for one
        # account is worse than an odd-looking one.
        parts = []
        ptr = acct_ptr
        while lib.gnc_account_get_parent(ptr):
            parts.append(safe_ctypes_string(lib.xaccAccountGetName, ptr))
            ptr = lib.gnc_account_get_parent(ptr)
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
        # Compared as the byte it is: the declaration above asks for
        # `c_char`, so ctypes hands back a one-byte `bytes` and never a `str`,
        # and the decode that guarded against one could only ever run.
        if lib.xaccTransGetTxnType(tx_ptr) != b'P':
            continue

        # Find the bank-side split: any split NOT on an AR/AP account.
        bank_acct_name = ''
        bank_memo = ''
        bank_amount = Fraction(0)
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
            bank_amount = abs(numeric_to_fraction(amt)) if amt.denom else Fraction(0)
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
            amount=money_text(bank_amount, _commodity_unit(lib, commodity_ptr)),
            currency=currency,
            description=description,
            memo=bank_memo,
        ))
    return results


def _commodity_of(lib, split_ptr) -> str:
    """The mnemonic of the account this split sits on, or ''."""
    commodity = lib.xaccAccountGetCommodity(lib.xaccSplitGetAccount(split_ptr))
    if not commodity:
        return ''
    raw = lib.gnc_commodity_get_mnemonic(commodity)
    return raw.decode('ascii', errors='replace') if raw else ''


def _owner_of_one_split(lib, split_ptr, book):
    """(type, id, name) of the owner recorded on this split's own lot.

    One transaction can carry two owners' money — a deposit covering two
    customers — and the owner GnuCash records on the transaction is whichever
    of them it happened to record. The lot is where a *portion* is attributed,
    so a listing that reports per split has to ask per split.
    """
    lot_ptr = lib.xaccSplitGetLot(split_ptr)
    if not lot_ptr:
        return 0, '', ''
    owner_buf = ctypes.create_string_buffer(256)
    owner_p = ctypes.cast(owner_buf, ctypes.c_void_p)
    if lib.gncOwnerGetOwnerFromLot(ctypes.c_void_p(int(lot_ptr)), owner_p) != 1:
        return 0, '', ''
    kind = lib.gncOwnerGetType(owner_p)
    oid_raw = lib.gncOwnerGetID(owner_p)
    oid = oid_raw.decode('utf-8', errors='replace') if oid_raw else ''
    if not oid:
        return 0, '', ''
    if kind == 2:
        found = book.CustomerLookupByID(oid)
    elif kind == 4:
        found = book.VendorLookupByID(oid)
    else:
        return 0, '', ''
    if found is None or not found.GetID():
        return 0, '', ''
    return kind, oid, (found.GetName() or '')


def _owner_from_an_orphans_lot(lib, transaction, book):
    """(type, id, name) of the owner whose lot holds this transaction's
    orphaned settlement, or (0, '', '').

    Only for a split an unpost marked, so this cannot answer for an ordinary
    deposit whose lot happens to name somebody — the lot on a shared deposit
    belongs to one of several owners, and reading it for the wrong split is
    the misattribution `_recorded_owner_of` is careful about.
    """
    from services.gnucash_importer import is_a_bank_paid_orphan

    owner_buf = ctypes.create_string_buffer(256)
    owner_p = ctypes.cast(owner_buf, ctypes.c_void_p)
    for split in transaction.GetSplitList():
        if not is_a_bank_paid_orphan(split):
            continue
        lot = split.GetLot()
        if lot is None:
            continue
        raw = ctypes.c_void_p(qof_pointer(lot))
        if lib.gncOwnerGetOwnerFromLot(raw, owner_p) != 1:
            continue
        kind = lib.gncOwnerGetType(owner_p)
        oid_raw = lib.gncOwnerGetID(owner_p)
        oid = oid_raw.decode('utf-8', errors='replace') if oid_raw else ''
        if not oid:
            continue
        if kind == 2:
            found = book.CustomerLookupByID(oid)
        elif kind == 4:
            found = book.VendorLookupByID(oid)
        else:
            continue
        if found is not None and found.GetID():
            return kind, oid, (found.GetName() or '')
    return 0, '', ''


def _marked_orphan_split_ptrs(transaction) -> set:
    """Raw pointers of the splits an unpost left loose on this transaction.

    One transaction can carry several — a deposit covering two invoices, both
    since unposted — and it can carry one among splits that still settle
    others, which is why the shape checks below have to be told which split
    the row is about rather than taking whichever came last.
    """
    from services.gnucash_importer import is_a_bank_paid_orphan

    return {int(split.instance) for split in transaction.GetSplitList()
            if is_a_bank_paid_orphan(split)}


def _holds_a_marked_orphan(transaction, lib) -> bool:
    """Whether an unpost left one of this transaction's splits loose.

    Read off the split, where the unpost wrote it, so it answers the same on
    every supported engine — unlike `xaccTransGetTxnType`, whose 5.x heuristic
    wants a lot-and-owner backref a retargeted settlement never had, and unlike
    the `txn_type:` KVP, which only exists once a book has been through an
    export.

    A split that came out of credit is not one of these: it was the owner's
    money and still is, loose again rather than orphaned.

    Which split is on a receivable or payable is settled in `lib` before any
    wrapper is built, and only those are wrapped. This is asked of every
    transaction a book-wide sweep does not otherwise recognise — on a real
    ledger, nearly every transaction in it, none of which touches a business
    account at all — and the whole cost of answering "no" for one is a handful
    of pointer reads. Wrapping first and filtering after put a fresh Python
    object on every split of every grocery bill in the book, to read an
    account type off it that ctypes had already been asked for.
    """
    from services.gnucash_importer import is_a_bank_paid_orphan

    tx_ptr = int(transaction.instance)
    for index in range(lib.xaccTransCountSplits(tx_ptr)):
        account = lib.xaccSplitGetAccount(lib.xaccTransGetSplit(tx_ptr, index))
        if not account or lib.xaccAccountGetType(account) not in (11, 12):
            continue
        # By index into the same list `lib` just walked — `xaccTransGetSplit`
        # is what the binding calls, so the two agree — rather than by handing
        # a pointer ctypes returned to a SWIG constructor.
        if is_a_bank_paid_orphan(transaction.GetSplit(index)):
            return True
    return False


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
        ('gnc_commodity_get_fraction', ctypes.c_int,    [ctypes.c_void_p]),
        ('qof_instance_get_guid',      ctypes.c_void_p, [ctypes.c_void_p]),
        ('guid_to_string_buff',        ctypes.c_char_p, [ctypes.c_void_p, ctypes.c_char_p]),
        # gncOwnerGetOwnerFromLot/FromTxn/GetID/GetType are set in
        # `_setup_lib_restypes`, on the same cached handle, for every caller.
        ('gncOwnerGetName',            ctypes.c_char_p, [ctypes.c_void_p]),
    ]:
        try:
            f = getattr(lib, name)
            f.restype = restype
            f.argtypes = argtypes
        except AttributeError:
            pass

    owner_buf = ctypes.create_string_buffer(256)
    owner_ptr = ctypes.cast(owner_buf, ctypes.c_void_p).value

    from gnucash import (
        ACCT_TYPE_PAYABLE,
        ACCT_TYPE_RECEIVABLE,
    )

    from infrastructure.gnucash.kvp import get_custom_metadata
    from infrastructure.gnucash.utils import get_account_full_name
    from services.gnucash_importer import is_a_bank_paid_orphan
    from use_cases.export_transactions import (
        bank_paid_orphan_share_of,
        lot_holdings_of,
    )

    results: List[OrphanPayment] = []

    def walk(acct):
        atype = lib.xaccAccountGetType(int(acct.instance))
        if atype in (11, 12):  # AR, AP
            # Once per account, not once per lot: it reads every split on the
            # account, and a receivable carries the whole history of the
            # business.
            orphan_share = bank_paid_orphan_share_of(acct)
            held = lot_holdings_of(acct)
            for held_lot in acct.GetLotList():
                # Through `qof_instance`, because this list holds wrapped
                # `GncLot`s on some builds and raw pointers on others — and
                # as the instance rather than the integer, because the SWIG
                # calls below take a `GNCLot *` and refuse an int.
                raw_lot = qof_instance(held_lot)
                lot = GncLot(instance=raw_lot)
                # Criterion 2: no invoice attached.
                if _gc.gncInvoiceGetInvoiceFromLot(raw_lot):
                    continue
                # Q-035: what an unpost loosened and a bank had paid comes off
                # first. Such a lot is live, names no invoice, and names an
                # owner — every test here passes — but that money is a
                # settlement waiting to be put back, not the owner's to spend,
                # and all three settlement spellings refuse it as credit.
                # Subtracted rather than disqualifying the lot, since one lot
                # can hold a bank-settled split and a credit-settled one both.
                #
                # `qof_pointer`: `GetLotList` yields raw pointers on GnuCash
                # 3.8, 4.4, 4.8, 4.13, 5.5, 5.10, 5.13 and 5.14, and `GncLot`
                # wrappers on 5.15 and 5.16, which `int()` refuses outright.
                # Measured on all ten
                # (tests/research/a_lot_can_be_named_probe.py).
                lot_key = qof_pointer(raw_lot)

                # Criterion 3: nonzero balance (unconsumed credit). The balance
                # is an exact rational, so "nonzero" is exactly that — no
                # epsilon standing in for a float's inability to hit zero.
                #
                # Both halves read from the account's splits, as the sibling
                # listing does. `gnc_lot_get_balance` sums the lot's own list,
                # which does not include a split attached with
                # `xaccSplitSetLot` in this session (finding 9), while the
                # share subtracted from it is derived from the account — so on
                # a book this process has just written, the subtraction could
                # take off more than the balance it was taken from. This
                # command opens a fresh book so the two agree today; matching
                # them removes the question.
                balance = (held.get(lot_key, (Fraction(0), None))[0]
                           - orphan_share.get(lot_key, Fraction(0)))
                if balance == 0:
                    continue

                # Identify the credit by a split that is *part of* it. The
                # first in the lot is the ordinary answer, but a lot can hold a
                # bank-settled split beside a credit-settled one — an invoice
                # paid part in cash and part out of credit, then unposted — and
                # `_cash_before_credit` puts the cash in first. Reporting that
                # one names the credit's remaining balance against the bank
                # payment's transaction, date and account, and a `from_credit:`
                # block written from that guid is refused as a bank payment.
                members = list(lot.get_split_list())
                if not members:
                    continue
                # Asked of each split directly. A lot's splits span
                # transactions, so a set built from one of their parents knows
                # nothing about the rest: with cash on two transactions and the
                # credit on a third, the filter saw only the first and picked
                # the second — a bank-paid orphan — reporting the credit's
                # balance against that payment's date and account, and a
                # `from_credit:` block written from its guid is then refused.
                #
                # `test_a_credit_in_a_lot_spanning_three_transactions_is_named_
                # by_its_own_split` builds that lot but does not pin the order:
                # GnuCash lists the credit split first there, so it passes
                # either way. What is fixed is the dependence on an order no
                # test can choose — the same reason the receivable walk below
                # asks each split rather than the first one's siblings.
                candidates = [Split(instance=m) for m in members]
                first = next((split for split in candidates
                              if not is_a_bank_paid_orphan(split)),
                             candidates[0])
                tx = first.GetParent()
                tx_ptr = int(tx.instance)

                # The lot first, because the lot is where an owner is recorded
                # when a credit is given one — `lot_owner:` attaches the owner
                # to the lot, not to the transaction. Asking the transaction
                # alone dropped such a credit from the listing entirely on
                # GnuCash 4.13 and 3.8, where `gncOwnerGetOwnerFromTxn` wants
                # a transaction whose type reads `TXN_TYPE_PAYMENT` and that
                # type is read from a slot rather than derived: a book holding
                # two open credits reported one, and the customer's money was
                # visible nowhere.
                # The address, however this binding hands the lot over:
                # `GetLotList` yields raw pointers on most builds and wrapped
                # `GncLot`s on others (Arch), where `int()` on the wrapper
                # raises rather than converting. The same idiom the rest of
                # the tree uses for this.
                got = lib.gncOwnerGetOwnerFromLot(
                    qof_pointer(raw_lot), owner_ptr)
                if got != 1:
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
                # No null-account check: a split with none cannot be here to
                # be skipped. Handed a book edited to remove one, GnuCash 5.x
                # drops the whole transaction while loading and 4.x and
                # earlier segfault before this code runs at all (CLAUDE.md
                # §12), so on every supported version each split has one.
                for i in range(tx.CountSplits()):
                    sp = tx.GetSplit(i)
                    sp_acct = sp.GetAccount()
                    sp_atype = sp_acct.GetType()
                    if sp_atype in (ACCT_TYPE_RECEIVABLE, ACCT_TYPE_PAYABLE):
                        continue
                    bank_acct_name = get_account_full_name(sp_acct)
                    bank_memo = sp.GetMemo() or ''
                    break

                date_str = tx.GetDate().strftime('%Y-%m-%d')
                description = tx.GetDescription() or ''
                # Of the account the balance is on, not of the transaction.
                # The figure comes from the lot on the receivable and is
                # already formatted at that account's unit; labelling it with
                # the transaction's currency called a 100.00 USD credit
                # "CAD 100.00" whenever the money arrived through a CAD bank,
                # and the per-owner totals then added it to that customer's
                # real CAD credits. The same correction as the orphan listing
                # below.
                commodity_ptr = lib.xaccAccountGetCommodity(int(acct.instance))
                if not commodity_ptr:
                    commodity_ptr = lib.xaccTransGetCurrency(tx_ptr)
                mnemonic_raw = (lib.gnc_commodity_get_mnemonic(commodity_ptr)
                                if commodity_ptr else None)
                currency = (mnemonic_raw.decode('ascii', errors='replace')
                            if mnemonic_raw else '')
                guid_ptr = lib.qof_instance_get_guid(tx_ptr)
                buf = ctypes.create_string_buffer(40)
                lib.guid_to_string_buff(guid_ptr, buf)
                tx_guid = buf.value.decode('ascii').replace('-', '')

                # The balance is a lot on this account, so it is held to the
                # account's own unit — a receivable kept to a tenth of a cent
                # holds 20.005, and reporting the commodity's two places says
                # 20.01 for money nobody has.
                lot_unit = (acct.GetCommoditySCU()
                            or _commodity_unit(lib, commodity_ptr))
                results.append(OrphanPayment(
                    tx_guid=tx_guid,
                    date=date_str,
                    bank_account=bank_acct_name,
                    amount=money_text(abs(balance), lot_unit),
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
        ('gnc_commodity_get_fraction', ctypes.c_int,    [ctypes.c_void_p]),
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
        """As `find_lot_payment_transactions` builds it, and for the reason
        given there: the walk stops at the root, and "has a parent" is what
        says an account is not it."""
        # Every segment, including an empty one. An account may have no name —
        # `beancount_account_name_ending_in_a_separator.beancount` measures a
        # child with none under `Assets:Bank` — and dropping those made this
        # walk answer `Assets:Bank` for it while `get_account_full_name`, which
        # every other reader uses, answers `Assets:Bank:`. Two names for one
        # account is worse than an odd-looking one.
        parts = []
        ptr = acct_ptr
        while lib.gnc_account_get_parent(ptr):
            parts.append(safe_ctypes_string(lib.xaccAccountGetName, ptr))
            ptr = lib.gnc_account_get_parent(ptr)
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
            # Q-035: or this tool wrote down that an unpost orphaned one of its
            # splits, which says the same thing and says it on every version.
            # The two readings above both miss a settlement attached by
            # retarget rather than by `gncOwnerApplyPayment`: the heuristic
            # wants a lot-and-owner backref it never got, and the KVP is
            # written by the exporter, so a book that has not been through a
            # round-trip has neither. On GnuCash 4.4 and 3.8 that left an
            # orphaned settlement listed by no command at all, while every
            # refusal about it tells the reader to name its transaction with
            # `txn_guid:` — a guid they had nowhere to get.
            # Kept apart, because they are different evidence and the reader is
            # shown which one answered. On a round-tripped book the engine says
            # 'N' — its heuristic wants a lot-and-owner backref the restored
            # loose split has not got — and the 'P' comes from the `txn_type:`
            # line the exporter wrote; saying `xaccTransGetTxnType(tx) == 'P'`
            # there describes a call that returned something else.
            typed_by_engine = (t == 'P')
            typed_by_kvp = (tx_kvp_type == 'P')
            typed_as_payment = typed_by_engine or typed_by_kvp
            if not typed_as_payment and not _holds_a_marked_orphan(tx, lib):
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
            tx_owner_source = ''
            if got == 1:
                tx_owner_source = 'txn'
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
                if this_owner_id:
                    tx_owner_source = 'kvp'
                if not this_owner_id:
                    # Q-035: and the lot, for a settlement an unpost orphaned.
                    # Neither reading above can answer for one: the transaction
                    # gets its owner slot from `gncOwnerApplyPayment`, which
                    # never touched a retargeted deposit, and the KVP is the
                    # exporter's, so a book that has not been round-tripped has
                    # no owner on the transaction at all. The lot the unpost
                    # left it in does have one — that is half of why it looks
                    # like a credit — and on GnuCash 4.4 and 3.8 it is the only
                    # thing that can say whose the money is.
                    this_owner_type, this_owner_id, this_owner_name = (
                        _owner_from_an_orphans_lot(lib, tx, book))
                    if this_owner_id:
                        tx_owner_source = 'another_lot'
            # Not filtered here. One transaction can hold two owners' orphans
            # — a deposit covering two customers, both invoices since
            # unposted — and the answer above is the transaction's, which is
            # one of them at best. Each row asks its own split below; filtering
            # on the transaction's answer hid the second owner's money
            # entirely and reported it under the first owner's name.
            tx_owner = (this_owner_type, this_owner_id, this_owner_name)

            # Criterion 3: payment shape — one AR/AP split, one elsewhere.
            #
            # Q-035: a deposit covering two invoices has several AR splits,
            # and taking whichever came last could report the wrong one — the
            # split still settling the *other* one, whose lot holds an
            # invoice, so criterion 4 below skips the transaction and the
            # orphan is listed nowhere. Where the unpost marked one, that is
            # the split this row is about, whatever order they come in.
            #
            # The test for this shape (`test_a_rebuild_takes_its_own_orphan_
            # over_a_loose_sibling`) does not pin the ordering: GnuCash hands
            # the marked split over first there, so it passes either way. What
            # is fixed here is the dependence on that order, which no test can
            # choose.
            #
            # And one row per orphan, not per transaction: a deposit whose
            # portions settled two invoices, both since unposted, carries two
            # marked splits and is two orphans. Reported once it named the
            # last of them, and the other one's money was listed nowhere
            # while every refusal about it asked for a guid — the same "listed
            # by no command" hole, one split further in. It is why the mark
            # stores an invoice's guid rather than `true`.
            marked = _marked_orphan_split_ptrs(tx)
            ar_candidates = []
            bank_s = None
            nsplits = lib.xaccTransCountSplits(tx_ptr)
            for j in range(nsplits):
                s_ptr = lib.xaccTransGetSplit(tx_ptr, j)
                a_ptr = lib.xaccSplitGetAccount(s_ptr)
                a_type = lib.xaccAccountGetType(a_ptr)
                if a_type in (11, 12):
                    ar_candidates.append(s_ptr)
                else:
                    bank_s = s_ptr
            if not (ar_candidates and bank_s):
                continue
            # Every marked split is its own row; with none marked the
            # transaction is a roundtripped orphan and answers as one row from
            # whichever receivable split it has.
            def _in_a_lot_naming_nothing(split_ptr):
                lot = lib.xaccSplitGetLot(split_ptr)
                return bool(lot) and not lib.gncInvoiceGetInvoiceFromLot(lot)

            # Where anything is marked, the marked splits are the rows and
            # nothing else is. Merging in the unmarked ones whose lot names
            # nothing looked like it closed a gap and re-opened the one the
            # mark exists for: an owner's parked credit names nothing either —
            # that is finding 10 entire — so a deposit that settled an invoice
            # and parked a credit listed the credit as an orphan as well, at the
            # bank's whole figure, and the same money was offered by
            # `find-prepayments` to spend and by this to clean up.
            #
            # The cost is a legacy shape: a deposit settling two invoices,
            # one unposted by an earlier version and one under this, lists
            # only the newer. Under-reporting a book that cannot be marked is
            # the lesser of the two, and unposting the older one again
            # under this version gives it a mark.
            reported_splits = [s for s in ar_candidates if int(s) in marked]
            if not reported_splits:
                # The first that is *orphaned*, not simply the first. Criterion
                # 4 below drops a split whose lot still names an invoice, so
                # taking the first outright made the whole transaction vanish
                # whenever that one came first — hiding a genuine orphan
                # beside it. Reachable without a mark: a book unposted by an
                # earlier version, where a payment settled two invoices and
                # only one was unposted.
                reported_splits = [
                    s for s in ar_candidates
                    if _in_a_lot_naming_nothing(s) or not lib.xaccSplitGetLot(s)
                ][:1]

            for ar_s in reported_splits:
                # Whose this one is, asked of this one. The lot a split sits in
                # is where an owner is recorded, so a deposit covering two
                # customers answers twice — and the transaction's own answer,
                # which names whichever GnuCash put on it, is the fallback for
                # a split whose lot cannot say.
                own_type, own_id, own_name = _owner_of_one_split(lib, ar_s, book)
                owner_source = 'lot' if own_id else tx_owner_source
                if not own_id:
                    own_type, own_id, own_name = tx_owner
                if not own_id:
                    continue
                if customer_id and not (own_type == 2 and own_id == customer_id):
                    continue
                if vendor_id and not (own_type == 4 and own_id == vendor_id):
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
                    continue                   # still attached to a posted record

                ar_ap_a_ptr = lib.xaccSplitGetAccount(ar_s)
                ar_ap_acct_name = _acct_full_name(ar_ap_a_ptr)
                bank_a_ptr = lib.xaccSplitGetAccount(bank_s)
                bank_acct_name = _acct_full_name(bank_a_ptr)
                memo_raw = lib.xaccSplitGetMemo(bank_s)
                memo = memo_raw.decode('utf-8', errors='replace') if memo_raw else ''
                # The orphaned split's own figure where the unpost named one:
                # on a deposit covering two invoices the bank side is the
                # whole 220, and reporting that for one invoice's orphaned
                # 100 names money the rest of which settles the other.
                reported_s = ar_s if int(ar_s) in marked else bank_s
                amt = lib.xaccSplitGetAmount(reported_s)
                amount = abs(numeric_to_fraction(amt)) if amt.denom else Fraction(0)

                epoch = lib.xaccTransGetDate(tx_ptr)
                date_str = datetime.fromtimestamp(
                    epoch, tz=timezone.utc).strftime('%Y-%m-%d')
                desc_raw = lib.xaccTransGetDescription(tx_ptr)
                description = (desc_raw.decode('utf-8', errors='replace')
                               if desc_raw else '')
                # Of the account the reported figure is *on*, not of the
                # transaction. A split's amount is in its account's commodity,
                # and the two part company on a foreign invoice settled from a
                # base-currency bank: a USD receivable paid out of a CAD bank
                # has a CAD transaction, so a −100.00 USD orphan read out under
                # the transaction's currency reported "100.00 CAD" — the wrong
                # money, at the wrong number of decimals. They agreed while
                # this always reported the bank split, which is what changed.
                commodity_ptr = lib.xaccAccountGetCommodity(
                    lib.xaccSplitGetAccount(reported_s))
                if not commodity_ptr:
                    commodity_ptr = lib.xaccTransGetCurrency(tx_ptr)
                mnemonic_raw = (lib.gnc_commodity_get_mnemonic(commodity_ptr)
                                if commodity_ptr else None)
                currency = (mnemonic_raw.decode('ascii', errors='replace')
                            if mnemonic_raw else '')

                guid_ptr = lib.qof_instance_get_guid(tx_ptr)
                buf = ctypes.create_string_buffer(40)
                lib.guid_to_string_buff(guid_ptr, buf)
                tx_guid = buf.value.decode('ascii').replace('-', '')

                # At the unit the account is kept to, not the currency's. A
                # receivable held to a tenth of a cent holds 20.005, and the
                # commodity's two places say 20.01 for money nobody has — the
                # same correction the sibling listing above carries. It matters
                # here now because the figure reported moved from the bank side
                # to the account side.
                reported_unit = (lib.xaccAccountGetCommoditySCU(
                    lib.xaccSplitGetAccount(reported_s))
                    or _commodity_unit(lib, commodity_ptr))

                results.append(OrphanPayment(
                    tx_guid=tx_guid,
                    date=date_str,
                    bank_account=bank_acct_name,
                    amount=money_text(amount, reported_unit),
                    currency=currency,
                    description=description,
                    memo=memo,
                    owner_type=own_type,
                    owner_id=own_id,
                    owner_name=own_name,
                    ar_ap_account=ar_ap_acct_name,
                    marked_by_unpost=int(ar_s) in marked,
                    typed_by_engine=typed_by_engine,
                    typed_by_kvp=typed_by_kvp,
                    owner_source=owner_source,
                    # Any other receivable or payable split on the transaction,
                    # not just another orphan row. What the warning guards is
                    # "deleting this guid destroys money that is not this
                    # row's", and a portion nobody has claimed yet counts:
                    # deleting a deposit covering Alpha and Beta while only
                    # Alpha's invoice exists takes Beta's money out of the
                    # bank, and re-importing Alpha puts back less than it took.
                    shares_its_transaction=len(ar_candidates) > 1,
                    # Only where naming the bank would be wrong about the
                    # money. This is a bank-side listing and says so; the
                    # figure is the orphan's own, which on an ordinary book is
                    # the bank's currency too. It parts company on a foreign
                    # invoice settled from a base-currency bank, and there
                    # "USD 100.00 in Assets:Bank" names an account that never
                    # held a dollar of it.
                    amount_account=(
                        ar_ap_acct_name
                        if (int(ar_s) in marked
                            and _commodity_of(lib, ar_s)
                            != _commodity_of(lib, bank_s))
                        else ''),
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
        # Q-035: a foreign-currency record's A/R or A/P split *is* a cost
        # basis. Unposting destroys it, so anything measured against it is
        # refused loudly rather than left naming a split the book no longer
        # holds.
        require_cost_basis_unused(book, rec, kind, rid)
        # Q-035: the lot survives the unpost holding whatever settled the
        # record, and a lot naming nothing is what an owner's credit
        # looks like. Written down here, or a later import re-attaching the
        # orphan reads it as credit being spent and takes the cost basis off
        # currency the bank really paid.
        mark_splits_orphaned_by_unpost(rec)
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
