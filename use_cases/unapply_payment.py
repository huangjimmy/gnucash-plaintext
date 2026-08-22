"""Unapply a payment from a posted invoice/bill — without unposting it.

This is the non-destructive inverse of applying a payment. It detaches a
payment's AR/AP split from the record's posted lot, so the lot reopens — the
invoice returns to **Outstanding** (or partially-paid if other payments remain)
— and re-homes that freed split to a user-named account (`--to`). The
invoice or bill itself is untouched and stays **posted**; the bank/income
transaction is never deleted. Only the freed split's *account* changes (its
amount is unchanged, so the transaction stays balanced).

Why `--to` is required: an applied payment's AR/AP split had some prior account
(Imbalance, Income, a clearing account, …) that the apply step overwrote and
that we never recorded. Money received that is no longer applied to an invoice
is, in accounting terms, something you may owe back — a payable — but only the
user knows which account represents that in their chart (it may be a `LIABILITY`
"Due to shareholder", or even an asset they carry negative). So the destination
is theirs to name; there is no defensible silent default.

Distinct from unpost: `unpost` drops the record to Draft and destroys the
posting transaction; `unapply-payment` keeps it posted and only peels off
payment(s).

Identity is by GUID, never by amount: two payments can share an amount, so the
selector (`--txn`) and every internal match key on the payment transaction's
GUID. Amounts are computed exactly (`gnc_numeric` → `Decimal`), never via
`to_double`. Mechanism (probed on all 10 supported GnuCash builds, no version
gate): `gnc_lot_remove_split(lot, ar_ap_split)` then
`xaccSplitSetAccount(split, to)`.
"""

import ctypes
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction
from typing import List, Optional

from gnucash.gnucash_core import Book

from infrastructure.gnucash.engine import GncNumericC, load_gnc_engine
from infrastructure.gnucash.utils import money_text
from services.gnucash_importer import (
    _find_bill_by_guid,
    _find_bills_by_id,
    _find_invoice_by_guid,
    _find_invoices_by_id,
)
from use_cases.unpost_business_objects import _resolve_one


@dataclass
class UnapplyResult:
    """Outcome of unapply-payment for one invoice/bill id."""
    id: str
    guid: str = ''
    kind: str = 'invoice'          # 'invoice' or 'bill'
    status: str = ''               # see below
    to_account: str = ''
    # one (tx_guid, amount_str, currency) per payment peeled off
    unapplied: List[tuple] = field(default_factory=list)
    remaining_balance: Decimal = Decimal('0')  # lot's outstanding after unapply
    # How finely the record's currency divides (GnuCash's commodity fraction):
    # 100 where there are hundredths, 1 for a currency with no minor unit.
    unit: int = 100
    detail: str = ''               # human note for error statuses

    # status values:
    #   'unapplied'      — one or more payments peeled off
    #   'not_found'      — no such invoice/bill id
    #   'ambiguous_id'   — legacy duplicate ids; rerun --by-guid
    #   'not_posted'     — record has no posted lot
    #   'no_payments'    — posted but nothing applied to peel
    #   'need_selector'  — >1 payment and neither --txn nor --all given
    #   'txn_not_found'  — --txn names a tx that is not a payment on this record


def _norm_guid(g: str) -> str:
    return (g or '').replace('-', '').lower()


def _amount(numc: GncNumericC) -> Decimal:
    """Exact value of a gnc_numeric, never via float."""
    if not numc.denom:
        return Decimal('0')
    return Decimal(numc.num) / Decimal(numc.denom)


def unapply_payments(book: Book, record, to_account, *, kind='invoice',
                     txn_guids: Optional[List[str]] = None,
                     unapply_all: bool = False,
                     report_id: str = '', report_guid: str = '') -> UnapplyResult:
    """Peel payment(s) off `record`'s posted lot and re-home the freed AR/AP
    split(s) to `to_account` (a SWIG Account). Mutates the book in place; the
    caller is responsible for saving."""
    currency = record.GetCurrency()
    res = UnapplyResult(id=report_id or record.GetID(), guid=report_guid,
                        kind=kind, to_account=to_account.get_full_name(),
                        unit=currency.get_fraction() if currency else 100)

    lot = record.GetPostedLot()
    if lot is None:
        res.status = 'not_posted'
        return res

    posting = record.GetPostedTxn()
    posting_guid = _norm_guid(posting.GetGUID().to_string()) if posting else ''

    lib = load_gnc_engine()
    for name, restype, argtypes in [
        ('gnc_lot_get_split_list',   ctypes.c_void_p, [ctypes.c_void_p]),
        ('gnc_lot_remove_split',     None,            [ctypes.c_void_p, ctypes.c_void_p]),
        ('gnc_lot_get_balance',      GncNumericC,     [ctypes.c_void_p]),
        ('xaccSplitGetParent',       ctypes.c_void_p, [ctypes.c_void_p]),
        ('xaccSplitGetAccount',      ctypes.c_void_p, [ctypes.c_void_p]),
        ('xaccSplitSetAccount',      None,            [ctypes.c_void_p, ctypes.c_void_p]),
        ('xaccSplitGetAmount',       GncNumericC,     [ctypes.c_void_p]),
        ('xaccAccountGetType',       ctypes.c_int,    [ctypes.c_void_p]),
        ('xaccTransGetCurrency',     ctypes.c_void_p, [ctypes.c_void_p]),
        ('gnc_commodity_get_mnemonic', ctypes.c_char_p, [ctypes.c_void_p]),
        ('xaccTransBeginEdit',       None,            [ctypes.c_void_p]),
        ('xaccTransCommitEdit',      None,            [ctypes.c_void_p]),
        ('qof_instance_get_guid',    ctypes.c_void_p, [ctypes.c_void_p]),
        ('guid_to_string_buff',      ctypes.c_char_p, [ctypes.c_void_p, ctypes.c_char_p]),
    ]:
        f = getattr(lib, name)
        f.restype = restype
        f.argtypes = argtypes

    def _txg(tx_ptr) -> str:
        gp = lib.qof_instance_get_guid(tx_ptr)
        buf = ctypes.create_string_buffer(40)
        lib.guid_to_string_buff(gp, buf)
        return buf.value.decode('ascii').replace('-', '')

    # Walk the lot's AR/AP-side splits and group them by parent transaction.
    # A payment is ANY transaction with a split in the lot other than the
    # record's own posting transaction — no dependence on txn_type 'P' (which
    # isn't reliably set on every version for retargeted/shared-tx payments).
    # Keyed by transaction GUID, never by amount (amounts can collide).
    payments = {}   # tx_guid -> {'splits': [ptr], 'amount': Decimal, 'currency': str}
    g = lib.gnc_lot_get_split_list(int(lot.instance))
    seen = set()
    while g:
        arr = ctypes.cast(g, ctypes.POINTER(ctypes.c_void_p * 2)).contents
        sp = arr[0]
        g = arr[1]
        if not sp or sp in seen:
            continue
        seen.add(sp)
        if lib.xaccAccountGetType(lib.xaccSplitGetAccount(sp)) not in (11, 12):
            continue
        tx = lib.xaccSplitGetParent(sp)
        tg = _txg(tx)
        if tg == posting_guid:
            continue                      # the invoice/bill's own posting split
        entry = payments.get(tg)
        if entry is None:
            cur = lib.xaccTransGetCurrency(tx)
            mn = lib.gnc_commodity_get_mnemonic(cur) if cur else None
            entry = {'splits': [], 'amount': Decimal('0'),
                     'currency': mn.decode('ascii', 'replace') if mn else ''}
            payments[tg] = entry
        entry['splits'].append(sp)
        entry['amount'] += abs(_amount(lib.xaccSplitGetAmount(sp)))

    if not payments:
        res.status = 'no_payments'
        return res

    if unapply_all:
        targets = set(payments)
    elif txn_guids:
        wants = {_norm_guid(g) for g in txn_guids}
        missing = wants - set(payments)
        if missing:
            res.status = 'txn_not_found'
            res.detail = ('not payments on ' + res.id + ': '
                          + ', '.join(sorted(missing))
                          + '; payments: ' + ', '.join(sorted(payments)))
            return res
        targets = wants                       # peel exactly the named subset
    else:
        if len(payments) > 1:
            res.status = 'need_selector'
            res.detail = (f'{res.id} has {len(payments)} payments — pass '
                          f'--txn <guid> (repeatable) to peel specific ones, or '
                          f'--all to unapply all. payments: '
                          + ', '.join(sorted(payments)))
            return res
        targets = set(payments)

    to_ptr = int(to_account.instance)
    for tg in sorted(targets):
        for sp in payments[tg]['splits']:
            tx = lib.xaccSplitGetParent(sp)
            lib.xaccTransBeginEdit(tx)
            lib.gnc_lot_remove_split(int(lot.instance), sp)   # reopen the lot
            lib.xaccSplitSetAccount(sp, to_ptr)               # re-home off AR/AP
            lib.xaccTransCommitEdit(tx)
        # Written at the record currency's own decimals — quantizing every
        # amount to hundredths invents a minor unit that a yen does not have.
        res.unapplied.append((tg,
                              money_text(Fraction(payments[tg]['amount']), res.unit),
                              payments[tg]['currency']))

    res.remaining_balance = _amount(lib.gnc_lot_get_balance(int(lot.instance)))
    res.status = 'unapplied'
    return res


def execute_unapply(book: Book, ident: str, to_account, *, is_bill=False,
                    by_guid=False, txn_guids=None, unapply_all=False) -> UnapplyResult:
    """Resolve one invoice/bill id (or guid) and unapply payment(s) from it."""
    kind = 'bill' if is_bill else 'invoice'
    by_id_fn = _find_bills_by_id if is_bill else _find_invoices_by_id
    by_guid_fn = _find_bill_by_guid if is_bill else _find_invoice_by_guid
    rec, rid, rguid = _resolve_one(book, ident, by_guid, by_id_fn, by_guid_fn)
    if rec is None and rguid == '__ambiguous__':
        return UnapplyResult(id=rid, kind=kind, status='ambiguous_id')
    if rec is None:
        return UnapplyResult(id=rid, kind=kind, status='not_found')
    return unapply_payments(book, rec, to_account, kind=kind, txn_guids=txn_guids,
                            unapply_all=unapply_all, report_id=rid, report_guid=rguid)
