"""Unapply a payment from a posted invoice/bill — without unposting it.

This is the non-destructive inverse of applying a payment. It detaches a
payment's AR/AP split from the record's posted lot, so the lot reopens — the
invoice returns to **Outstanding** (or partially-paid if other payments remain)
— and gives that payment split the account `--to` states. The invoice or
bill itself is untouched and stays **posted**; the bank/income transaction is
never deleted. Only the payment split's *account* changes, and its amount with
it where the two accounts are kept in different currencies — the split's value
is untouched either way, so the transaction stays balanced.

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
from datetime import datetime, timezone
from decimal import Decimal
from fractions import Fraction
from typing import Dict, List, Optional

from gnucash.gnucash_core import Book

from infrastructure.gnucash.engine import GncNumericC, load_gnc_engine
from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata
from infrastructure.gnucash.utils import (
    get_account_full_name,
    money_text,
    numeric_to_fraction,
)
from services.foreign_currency import (
    COST_BASIS_SPLIT_KEY,
    cost_basis_guid_of,
    establishes_cost_basis,
    give_back_to_cost_bases,
    iter_splits,
    open_cost_basis_balance_if_none_is_stored,
    split_guid,
)
from services.gnucash_importer import (
    _find_bill_by_guid,
    _find_bills_by_id,
    _find_invoice_by_guid,
    _find_invoices_by_id,
)
from services.payment_links import the_amount_the_new_account_takes
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
    # The record's own currency, which is what `remaining_balance` is in — a
    # figure printed without it reads as the reader's own currency, and on a
    # USD invoice in a CAD book that is the wrong money by a third.
    currency: str = ''
    # The transaction guids of the payments on the record, where knowing them
    # is the way out — `need_selector` asks the reader to pick one. Kept as
    # data rather than as a sentence because the sentence needs the command's
    # own verb, which this layer does not know.
    payments: List[str] = field(default_factory=list)
    detail: str = ''               # human note for error statuses

    # status values:
    #   'unapplied'      — one or more payments peeled off
    #   'not_found'      — no such invoice/bill id
    #   'ambiguous_id'   — legacy duplicate ids; rerun --by-guid
    #   'not_posted'     — record has no posted lot
    #   'no_payments'    — posted but nothing applied to peel
    #   'need_selector'  — >1 payment and neither --txn nor --all given
    #   'txn_not_found'  — --txn names a tx that is not a payment on this record


def the_reason_nothing_came_off(res: UnapplyResult, *, verb: str) -> str:
    """The sentence to print for every status but `unapplied`.

    `unapply-payment` and `unlink` run the same code and reach the same seven
    statuses, so they answer a refused run out of one place. Two of the seven
    carry no `detail` at all — `not_found` and `ambiguous_id` — and a command
    printing `res.detail or res.status` answers a duplicate id with the bare
    word `ambiguous_id`. That names the situation and not the way out of it,
    which is `--by-guid`, and a reader cannot guess a flag.

    `verb` is the command's own word, because the remedy differs by command
    and a reader of `unlink` told there is "nothing to unapply" has been
    handed the wrong manual page.

    `need_selector` is composed here for that reason. Built in the use case it
    read "pass --txn to peel specific ones, or --all to unapply all" whichever
    command a reader had typed, which is the same fault in the one status
    whose whole job is to say what to type next. `txn_not_found` keeps its
    `detail`, which states guids and no verb.
    """
    return {
        'not_found': f'{res.kind} {res.id!r} not found',
        'ambiguous_id': (f'{res.id!r} matches multiple records — rerun with '
                         f'--by-guid <guid>'),
        'not_posted': f'{res.id!r} is not posted — nothing to {verb}',
        'no_payments': f'{res.id!r} is posted but has no payments to {verb}',
        'need_selector': (f'{res.id} has {len(res.payments)} payments — pass '
                          f'--txn <guid> (repeatable) to {verb} specific ones, '
                          f'or --all to {verb} every payment. payments: '
                          + ', '.join(res.payments)),
        'txn_not_found': res.detail,
    }.get(res.status, f'{verb} failed: {res.status}')


def _norm_guid(g: str) -> str:
    return (g or '').replace('-', '').lower()


def _give_the_basis_back_what_the_settlement_took(book, drawn) -> None:
    """Raise each cost basis by the units the settlement taken off drew down.

    A settlement that converted currency lowered a cost basis balance by what
    it converted, and `_book_payment_fx_difference` wrote the basis's guid onto
    the settlement split so this could find it again. Taking that settlement
    off the record without giving the balance back leaves the book offering
    less currency than it holds.

    What that cost: a 100.00 USD invoice booked at 1.40 and settled into a CAD
    bank at 1.37 drives the posting split's basis balance to 0.00. Unapplied,
    the invoice is Outstanding for 100.00 USD again while `fx-balances` reports
    0.00 USD available against it — and re-applying the money to the right
    invoice, which is the whole reason to unapply, is then refused by
    `_draw_down_settled_basis`: "that USD has already been sold against it".
    The money was never sold; it went back to being owed.

    The key goes with the balance, and only where the balance came back. It
    says this split spent that basis; once the balance is returned the split
    has spent nothing, so leaving it would export a settlement as drawn from a
    basis it no longer draws from. Where the balance did *not* come back — the
    basis split gone from the book, or its stored balance unparseable, which
    is the fault `--verify-costs` reports — the key is the only thing left
    saying which basis was drawn down, and dropping it would leave the basis
    short with nothing able to say by how much.
    Not to stop a second give-back: `raise_cost_basis_balance` caps at what
    the basis brought in, and a second run finds no payment on the lot to take
    off in any case. The cost is what the file says, and that is enough.

    **Dropped from the slot, not emptied**, and the slot's other keys are read
    first. Writing `{KEY: ''}` would do both wrong things at once: the export
    writes every custom key it finds, so the book would emit
    `cost_basis_split_guid: ""` on that split for ever — a line nobody typed,
    which a rebuilt book does not hold, so the ledger and its own export build
    two different books — and `set_custom_metadata` replaces the slot, so a
    `department:` or anything else the split carried would go with nothing
    said. `_forget_orphaned_by_unpost` is the spelling this follows.

    Summed per basis, because two settlements of one record can name the same
    one, and `give_back_to_cost_bases` takes one amount per guid.

    **The `Income:FX Gain` split is not deleted and its figure is not
    reversed**, and that is not an omission. A settlement that converts at a
    rate other than the `share_price:` of the split that opened the basis
    realizes a difference, and the payment block has to say where it belongs —
    `_book_payment_fx_difference` refuses the block otherwise, naming
    `Income:FX Gain $residual$ CAD`. So the split is the *file's*, in the
    transaction the file wrote, and taking a payment off does not rewrite
    that: a transaction surviving whole is this command's whole promise.

    It is also what the `--to` account absorbs. The entry is quoted in the
    book's currency and the settlement split's value is written at the cost of
    the basis it draws down, so a CAD account takes −140.00 where the bank
    received 137.00 — the
    only figure that leaves the entry balancing while the file's own line
    holds the 3.00 between them.

    Measured on `fx_invoice_usd_paid_from_cad_bank.txt`: after the give-back
    the basis reads 100.00 USD undisposed while the income statement still
    carries −3.00 CAD realized on disposing of it. Both describe what
    happened — the money converted, and it no longer settles this invoice —
    and nothing here can decide whose line to rewrite. README and Q-039 say so,
    and say that money applied to another record with another `$residual$`
    line records the difference twice, the first line being the reader's to
    remove.
    """
    if not drawn:
        return
    totals: Dict[str, Fraction] = {}
    for _split, basis_guid, units in drawn:
        totals[basis_guid] = totals.get(basis_guid, Fraction(0)) + units
    restored = give_back_to_cost_bases(book, totals)
    for split, basis_guid, _units in drawn:
        # Only where the balance came back. A basis whose split the book no
        # longer holds, or whose stored balance will not parse, is left
        # lowered — and the key is the only thing saying which basis this
        # settlement drew from, so dropping it there would leave the basis
        # short with nothing able to say by how much or against what.
        if basis_guid not in restored:
            continue
        # Bracketed, or the slot reads back as its old value after a save —
        # CLAUDE.md finding 11, which is about an object the book already held,
        # and every split here is one.
        metadata = get_custom_metadata(split)
        remaining = {key: val for key, val in metadata.items()
                     if key != COST_BASIS_SPLIT_KEY}
        parent = split.GetParent()
        parent.BeginEdit()
        set_custom_metadata(split, remaining)
        # Dropping the key can make the split a cost basis of its own, and one
        # created here has to be opened here. `establishes_cost_basis` returns
        # False for a settlement *because* of that key, so a split given an
        # account kept in its own foreign currency clears every other gate the
        # moment the key goes: currency, non-base commodity, a debit that
        # raises a foreign balance, and a cost the requoted entry now supplies.
        #
        # Measured on the bill fixture, unlinked `--to Assets:Bank:USD`:
        # `fx-balances` grew a 100.00 USD basis on that account reading `none
        # recorded`, left out of the total, under the sentence "this tool
        # never wrote one for them" — which this command had just done. A
        # later sale naming it was refused for the same untrue reason.
        #
        # Opened, never reopened: `open_cost_basis_balance_if_none_is_stored`
        # leaves a stored figure alone, so a split that already carried a
        # balance keeps the one it had, disposals included.
        if establishes_cost_basis(split):
            open_cost_basis_balance_if_none_is_stored(split)
        parent.CommitEdit()


def _numeric(value: Fraction) -> GncNumericC:
    """A `Fraction` as GnuCash's own numerator/denominator pair.

    Exactly, never through a float: the figure being written is money the book
    will hold, and `to_double` is what every other money path here avoids.
    """
    return GncNumericC(num=value.numerator, denom=value.denominator)


def _amount(numc: GncNumericC) -> Decimal:
    """Exact value of a gnc_numeric, never via float."""
    if not numc.denom:
        return Decimal('0')
    return Decimal(numc.num) / Decimal(numc.denom)


def unapply_payments(book: Book, record, to_account, *, kind='invoice',
                     txn_guids: Optional[List[str]] = None,
                     unapply_all: bool = False, fx_rates=None,
                     report_id: str = '', report_guid: str = '') -> UnapplyResult:
    """Peel payment(s) off `record`'s posted lot and put `to_account` (a SWIG
    Account) on the payment split(s). Mutates the book in place; the
    caller is responsible for saving."""
    currency = record.GetCurrency()
    res = UnapplyResult(id=report_id or record.GetID(), guid=report_guid,
                        # Colons, as every other surface writes an account
                        # path: GnuCash's own `get_full_name` separates with
                        # whatever the book's separator is, a dot in these
                        # images, so the reported account did not match the
                        # `--to` the reader had just typed.
                        kind=kind,
                        to_account=get_account_full_name(to_account),
                        unit=currency.get_fraction() if currency else 100,
                        currency=currency.get_mnemonic() if currency else '')

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

    def _guid_of(instance_ptr) -> str:
        """Any QOF instance's guid — a transaction's here, and a split's below.

        `qof_instance_get_guid` asks the instance, not the type, so one reader
        answers for both.
        """
        gp = lib.qof_instance_get_guid(instance_ptr)
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
        tg = _guid_of(tx)
        if tg == posting_guid:
            continue                      # the invoice/bill's own posting split
        entry = payments.get(tg)
        if entry is None:
            # The record's currency, not the transaction's. `amount` below is
            # the AR/AP split's, which is denominated in what the record is,
            # and `res.unit` is the record's too — so quoting the
            # transaction's currency beside them named a currency the figure
            # was not in. On a USD invoice settled by a CAD-quoted entry it
            # reported `100.00 CAD` for 100.00 US dollars.
            entry = {'splits': [], 'amount': Decimal('0'),
                     'currency': currency.get_mnemonic() if currency else ''}
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
            # The guids, not a sentence: the sentence tells the reader to pass
            # `--all` to take every payment off, and the word for taking one
            # off is the command's. Written here it said "--all to unapply
            # all" under `unlink` as well.
            res.payments = sorted(payments)
            return res
        targets = set(payments)

    to_ptr = int(to_account.instance)

    def _mnemonic(commodity_ptr) -> str:
        raw = lib.gnc_commodity_get_mnemonic(commodity_ptr) if commodity_ptr else None
        return raw.decode('ascii', 'replace') if raw else ''

    def _rate_for_on(day):
        """The rates file's answer for a currency, on the transaction's day.

        `None` where no rates were given, which is what turns the third
        currency into a refusal rather than a guess. Dated, so a settlement
        converts at the rate that held when it happened.
        """
        if fx_rates is None:
            return None

        def rate_for(currency: str) -> Fraction:
            return fx_rates.rate_fraction(currency, day)

        return rate_for

    # Every figure is worked out before the first account changes, so an
    # account this cannot convert into leaves the book as it was found rather
    # than part way through. The same discipline the linking branch keeps, and
    # for the same reason.
    takings = []
    for tg in sorted(targets):
        for sp in payments[tg]['splits']:
            tx = lib.xaccSplitGetParent(sp)
            held = _mnemonic(lib.xaccAccountGetCommodity(lib.xaccSplitGetAccount(sp)))
            quoted = _mnemonic(lib.xaccTransGetCurrency(tx))
            day = datetime.fromtimestamp(lib.xaccTransGetDate(tx),
                                         timezone.utc).date()
            # `numeric_to_fraction`, not `Fraction(_amount(...))`: `_amount`
            # goes through `Decimal`, which is inexact for any denominator
            # that is not a power of ten and would hand a 28-digit numerator
            # to a figure this writes back into the book. The reporting
            # figures above may take the Decimal route; this one may not.
            takings.append((sp, the_amount_the_new_account_takes(
                held, quoted, to_account,
                numeric_to_fraction(lib.xaccSplitGetAmount(sp)),
                numeric_to_fraction(lib.xaccSplitGetValue(sp)),
                where=f'{kind} {res.id}',
                rate_for=_rate_for_on(day))))

    # What these settlements drew out of a cost basis, read while they are
    # still on the receivable — the amount is in the record's currency only
    # until the account changes, and it is that figure the basis lost.
    #
    # A cost basis is a KVP, and reading one wants a wrapped split rather than
    # a raw pointer. `lot.get_split_list()` does not supply one: it hands back
    # `SwigPyObject` pointers on eight of the ten supported builds and wrapped
    # `GncLot`/`Split` objects on the other two (CLAUDE.md finding 17), so a
    # reader written against either half raises on the other. The guid is the
    # way across — asked of the pointer this already holds, and looked up in
    # the book.
    wanted = {_guid_of(sp) for tg in targets for sp in payments[tg]['splits']}
    # One pass over the book's splits, not one per settlement:
    # `find_split_by_guid` walks them all, so calling it in the loop made
    # `--all` on a record with several payments a full scan per split.
    drawn = []
    for split in iter_splits(book):
        if split_guid(split) not in wanted:
            continue
        basis_guid = cost_basis_guid_of(split)
        if basis_guid:
            drawn.append((split, basis_guid,
                          abs(numeric_to_fraction(split.GetAmount()))))

    for sp, takes in takings:
        tx = lib.xaccSplitGetParent(sp)
        lib.xaccTransBeginEdit(tx)
        lib.gnc_lot_remove_split(int(lot.instance), sp)   # reopen the lot
        lib.xaccSplitSetAccount(sp, to_ptr)               # off AR/AP
        # And restate it for the account it now carries. The value — the
        # transaction's side of the split — is untouched either way, so the
        # entry goes on balancing whichever figure the amount takes.
        lib.xaccSplitSetAmount(sp, _numeric(takes))
        lib.xaccTransCommitEdit(tx)

    _give_the_basis_back_what_the_settlement_took(book, drawn)

    for tg in sorted(targets):
        # Written at the record currency's own decimals — quantizing every
        # amount to hundredths invents a minor unit that a yen does not have.
        res.unapplied.append((tg,
                              money_text(Fraction(payments[tg]['amount']), res.unit),
                              payments[tg]['currency']))

    res.remaining_balance = _amount(lib.gnc_lot_get_balance(int(lot.instance)))
    res.status = 'unapplied'
    return res


def execute_unapply(book: Book, ident: str, to_account, *, is_bill=False,
                    by_guid=False, txn_guids=None, unapply_all=False,
                    fx_rates=None) -> UnapplyResult:
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
                            unapply_all=unapply_all, fx_rates=fx_rates,
                            report_id=rid, report_guid=rguid)
