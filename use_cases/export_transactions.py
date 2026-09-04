"""
Use case for exporting GnuCash transactions to plaintext format.

Exports complete GnuCash data including commodities, accounts, and transactions
with all metadata required for round-trip import.
"""

import datetime
import heapq
import os
from fractions import Fraction
from functools import cmp_to_key
from typing import Optional, Sequence

from gnucash import Transaction
from gnucash.gnucash_core_c import (
    GncGUID,
    string_to_guid,
    xaccAccountGetTypeStr,
    xaccTransGetIsClosingTxn,
    xaccTransLookup,
    xaccTransOrder,
)

from infrastructure.gnucash.kvp import get_custom_metadata
from infrastructure.gnucash.utils import (
    encode_value_as_string,
    get_account_full_name,
    get_commodity_ticker,
    get_parent_accounts_and_self,
    money_text,
    number_in_string_format_is_1,
    numeric_to_fraction,
    qof_pointer,
    to_string_with_decimal_point_placed,
)
from repositories.gnucash_repository import GnuCashRepository
from services.foreign_currency import (
    COST_BASIS_COST_KEY,
    COST_BASIS_SPLIT_KEY,
    derived_cost_of,
    establishes_cost_basis,
    is_a_spent_credit,
    split_guid,
)
from services.gnucash_importer import (
    ORPHANED_BY_UNPOST_KEY,
    _lot_guid_str,
    _the_split_this_book_holds,
    is_a_bank_paid_orphan,
)


class UnwritableFigureError(ValueError):
    """A figure the book holds that plaintext has no way of stating.

    Its own type rather than a bare `ValueError`, because callers act on it:
    `delete-transactions` goes ahead without an undo copy, and the export
    gathers every one in the book before refusing. `json.JSONDecodeError` is
    a `ValueError` too, so catching the base class would let a corrupt KVP
    slot be reported as a figure this format cannot write. A `ValueError`
    subclass all the same, so anything catching broadly still catches it.
    """


def refuse_a_figure_the_currency_cannot_hold(amount, account, what,
                                             where=''):
    """A figure an export cannot state, refused before it is written.

    A booked amount is a whole number of its currency's smallest unit. GnuCash
    stores a finer one — an account may be kept to a tenth of a cent — and the
    importer will not read it back, so writing it produced a file this tool
    could not import: the export said nothing and `import` on its own output
    dropped the entry.

    Currency only. `stated_money` judges a security against the account's
    unit alone, and `string_to_gnc_numeric` keeps a security quantity as the
    ratio it is; fund units are quoted to three decimals and more, and the
    beancount importer stores them that way on purpose, so refusing them here
    would reject on export what that importer had just written.

    One helper for all three exports — plaintext, beancount, and the business
    objects — because they write the same figures out of the same books, and
    the one that lacked the rule wrote payment and prepayment lines the other
    two would have refused.
    """
    commodity = account.GetCommodity() if account is not None else None
    if commodity is None:
        return
    if (commodity.get_namespace() or '').upper() != 'CURRENCY':
        return
    fraction = commodity.get_fraction()
    if (amount * fraction).denominator == 1:
        return
    scu = account.GetCommoditySCU() or fraction
    raise UnwritableFigureError(
        f'{what} on {get_account_full_name(account)!r}'
        + (f' in {where!r}' if where else '')
        + f' is {money_text(amount, scu)} {commodity.get_mnemonic()}, which '
        f'is finer than that currency: its smallest unit is '
        f'{money_text(Fraction(1, fraction), fraction)}. A booked amount is a '
        f'whole number of those, so this cannot be written — the file would '
        f'not import. Correct the amount in GnuCash (a unit price may carry '
        f'more decimals; the amount booked to the account may not).')


def _owner_of_a_bank_paid_orphan(splits, lib):
    """The owner on the lot an unpost left one of this transaction's splits in.

    For the `txn_type:` and `owner:` lines, where the engine answers neither.
    Both exist so that a payment whose lot was detached by an unpost is still
    found after a round-trip, and both are read from state a retargeted
    settlement never got: `xaccTransGetTxnType` derives 'P' from a
    lot-and-owner backref on GnuCash 4.13+ and reads a field nothing set on
    4.4 and 3.8, and the owner slot is written by `gncOwnerApplyPayment`,
    which never touched this transaction.

    So on those engines the two lines that exist to keep such a payment
    visible were the two the export omitted, and the money came back loose on
    a transaction the sweep does not examine — the receivable carrying a
    figure no command explains. The lot the unpost abandoned still names the
    owner, which is what `find-orphan-payments` reads on the same engines
    before the book is exported, and it answers here too.

    Read from a split the unpost marked and no other. Any owner lot on the
    transaction would take in an owner's parked credit sitting beside a
    payment, which is not what either line is about.

    Takes the caller's split list rather than asking for one, and settles the
    account type in `lib` before anything is read off a split. This runs for
    every transaction whose two readings came back empty — on a real ledger,
    nearly every transaction in it, none of which touches a receivable or
    payable at all — so a second `GetSplitList()` here would build a fresh
    wrapper per split of every grocery bill in the book, and an `Account`
    wrapper on top of it, to learn what one pointer read answers. Only a
    business split can carry the note. The orphan sweep filters the same way
    for the same reason.
    """
    import ctypes

    for split in splits:
        account = lib.xaccSplitGetAccount(int(split.instance))
        if not account or lib.xaccAccountGetType(account) not in (11, 12):
            continue                    # ACCT_TYPE_RECEIVABLE / PAYABLE
        if not is_a_bank_paid_orphan(split):
            continue
        lot = split.GetLot()
        if lot is None:
            continue
        buffer = ctypes.create_string_buffer(256)
        owner_ptr = ctypes.cast(buffer, ctypes.c_void_p)
        if lib.gncOwnerGetOwnerFromLot(
                ctypes.c_void_p(qof_pointer(lot)),
                owner_ptr) != 1:
            continue
        kind = {2: 'customer', 4: 'vendor'}.get(lib.gncOwnerGetType(owner_ptr))
        raw_id = lib.gncOwnerGetID(owner_ptr)
        owner_id = raw_id.decode('utf-8', errors='replace') if raw_id else ''
        if kind and owner_id:
            return kind, owner_id
    return '', ''


def _format_fraction_as_decimal(f: Fraction, decimal_places: int) -> str:
    """
    Format a Fraction as a fixed-point decimal string.

    GnuCash amounts always use power-of-10 denominators (100 for CAD, 1 for
    JPY, etc.), so multiplying by 10**decimal_places always yields an exact
    integer — no rounding is needed.

    Args:
        f: Fraction value to format
        decimal_places: Number of digits after the decimal point (0 for JPY, 2
            for CAD/USD, etc.)

    Returns:
        Formatted string, e.g. "1234.56", "-0.50", "12345"
    """
    if decimal_places == 0:
        return str(int(f))
    scale = 10 ** decimal_places
    scaled_int = int(f * scale)
    sign = '-' if scaled_int < 0 else ''
    abs_str = str(abs(scaled_int))
    if len(abs_str) > decimal_places:
        return sign + abs_str[:-decimal_places] + '.' + abs_str[-decimal_places:]
    else:
        return sign + '0.' + '0' * (decimal_places - len(abs_str)) + abs_str


def _stored_cost_is_ignorable(split) -> bool:
    """True iff a `cost_basis_cost` on this split is a figure nothing reads.

    Two shapes: a split its own transaction prices, where the transaction is
    consulted first and the stored copy is a second answer the importer
    refuses outright; and a split that is no cost basis at all — a spend, or
    a share — where nothing ever asks what it cost. Written out, either makes
    a file this tool then refuses to read.

    A cost that will not parse is kept, whatever else is true of its split.
    Asking whether the split is a basis reads that very cost, so answering
    the question is what took the export down — on the one book the report
    sends its reader here to fix. The file is where they fix it, so the bad
    figure has to be in it.
    """
    try:
        if derived_cost_of(split) is not None:
            return True
        if is_a_spent_credit(split):
            # An owner's credit this book has spent. It is no cost basis while
            # it settles the record, so the test below would drop its stored
            # cost — and that cost is the only thing pricing it, this shape
            # being a credit paid in the record's own currency with no
            # base-currency figure anywhere in its transaction. Dropped, the
            # rebuilt book cannot price the split at all, and unposting the
            # record there hands back currency nothing can value while the
            # book it came from hands back a cost basis. Kept, so the two
            # books answer alike.
            return False
        return not establishes_cost_basis(split)
    except Exception:
        return False


def the_order_the_book_keeps_them_in(one, other) -> int:
    """GnuCash's own comparison of two transactions, `xaccTransOrder`.

    The engine already answers "which of these comes first", and it is the
    answer every GnuCash register shows: the posted date, then `num` where the
    transactions carry one, then when each was entered, then the description,
    then the guid. An export reads a book and should say what the book says,
    so it asks rather than inventing an order of its own.

    It was sorted on the posted date alone before, which is the same order:
    `qof_query_run` returns transactions in `xaccTransOrder` already — measured
    in `tests/research/what_order_a_book_keeps_same_day_transactions_in_probe.py`,
    where the query hands over a same-day fee and deposit in the order the
    engine's own comparison puts them. Sorting says so, rather than leaning on
    a query whose order nothing had asked about.
    """
    return xaccTransOrder(one.instance, other.instance)


def _the_basis_a_sale_draws_on(split) -> Optional[str]:
    """The guid this split will state in `cost_basis_split_guid:`, or None.

    None where the split gives no guid, and where it gives one the export
    drops — so this asks exactly what the writer asks, and a line the file
    will not carry moves nothing.
    """
    given = get_custom_metadata(split).get(COST_BASIS_SPLIT_KEY)
    if not given or _the_basis_it_gives_was_spent(split, given):
        return None
    return str(given).replace('-', '').lower()


def each_basis_above_what_draws_on_it(transactions: list) -> list:
    """The book's order, with one exception: a transaction holding a cost
    basis is written above any transaction that draws on it.

    Given the transactions the file will carry, after any date or account
    filter, so that only an order the file can be read back in is asked
    about — and so that the running balances, which are added up over every
    transaction in the book's own order, are not asked to follow this one.

    `cost_basis_split_guid:` is resolved as each block is applied, so a sale
    whose basis the file states further down is refused with "matches no split
    in the book" and the import fails. The two transactions this was measured
    on share a posted date, carry no `num` and were entered in the same
    second, so the engine orders them by description — and "Charges for:
    TRANSFER-0000001" comes before the deposit it is drawn on. That book is
    sound: every figure in it agrees, and its own ledger did not rebuild it.

    Which of the two is dated first is not asked. A basis dated after the sale
    that draws on it is an odd book, but it is one this can still write a
    ledger for, and the alternative is a file that does not read back.

    Where two transactions draw on each other there is no order that reads
    back, and the book's own is returned untouched.

    One walk of the splits, and one read of each split's slot: most books hold
    no cost basis at all, and this runs on every export. `GetSplitList` is a
    fresh wrapper per call and the slot is a ctypes read and a `json.loads`,
    so both are taken once and the guid a sale gives is collected on the way
    past.
    """
    held_by = {}
    drawn_on = []
    for position, transaction in enumerate(transactions):
        for split in transaction.GetSplitList():
            held_by[split_guid(split)] = position
            basis = _the_basis_a_sale_draws_on(split)
            if basis is not None:
                drawn_on.append((position, basis))

    if not drawn_on:
        return transactions

    # A entry per transaction that waits for another, and per transaction
    # another waits for — not one per transaction in the book. A book of a
    # hundred thousand entries and one sale in it holds two of each here.
    waits_for: dict = {}
    holds_up: dict = {}
    for position, basis in drawn_on:
        above = held_by.get(basis)
        if above is None or above == position:
            continue
        waits_for.setdefault(position, set()).add(above)
        holds_up.setdefault(above, set()).add(position)

    if not waits_for:
        return transactions

    ready = [position for position in range(len(transactions))
             if position not in waits_for]
    heapq.heapify(ready)
    written = []
    while ready:
        position = heapq.heappop(ready)
        written.append(transactions[position])
        for below in sorted(holds_up.get(position, ())):
            waiting = waits_for[below]
            waiting.discard(position)
            if not waiting:
                del waits_for[below]
                heapq.heappush(ready, below)

    return written if len(written) == len(transactions) else transactions


def where_each_undo_block_goes(book, guids: Sequence[str]) -> dict:
    """A position per guid, for a command writing one block per transaction.

    `delete-transactions -o` writes an undo copy, one block per guid, in the
    order the guids were typed — and that order is not the writer's to choose.
    A cost basis cannot be deleted while a sale measures against it, so the
    sale is named first, and the copy stated the sale above the basis it draws
    on: a file whose opening block gives the guid of a split no block above it
    creates, refused on the way back in, with the transactions it was the only
    copy of already gone from the book.

    Asked before the transactions are deleted, because it reads them. A guid
    the book does not hold is left out, and so is the block it would have had:
    a caller writes a copy of what it deleted, and it deleted nothing.
    """
    found = {}
    for guid in guids:
        gnc_guid = GncGUID()
        if not string_to_guid(str(guid), gnc_guid):
            continue
        raw = xaccTransLookup(gnc_guid, book.instance)
        if raw is not None:
            found[guid] = Transaction(instance=raw)

    named_by = {id(transaction): guid for guid, transaction in found.items()}
    return {named_by[id(transaction)]: position for position, transaction
            in enumerate(each_basis_above_what_draws_on_it(
                list(found.values())))}


def _the_basis_it_gives_was_spent(split, basis_guid) -> bool:
    """True iff this sale's `cost_basis_split_guid` gives a pool this book has
    consumed — an owner's credit that has since settled a record.

    That happens with nothing wrong: spending the credit ends the pool, and the
    split that was the credit becomes the record's settlement. The sale keeps
    the guid, which is what the book knows about where its currency came from,
    and the file cannot carry it, because a rebuilt book has nothing to measure
    against it and `_validate_pick` refuses the line.

    **Only a consumed pool.** A split that is no cost basis for any other
    reason keeps its guid in the file, and must: a deposit whose basis a link
    stranded is the fault this issue is named for, and the export writing that
    guid is how the book's own ledger refuses to rebuild it — which is what
    `--verify-costs` reports and what a reader is sent to look at. Dropped
    here as well, the fault would export clean and the report would be the only
    thing that had ever seen it.

    A guid that gives no split at all is left alone for the same reason.
    """
    account = split.GetAccount()
    book = account.get_book() if account is not None else None
    if book is None:
        return False
    # Looked up rather than searched for: this is asked once per sale that
    # gives a guid, and a walk of the book would make an export cost the sales
    # times the splits.
    # Normalised the way `cost_basis_guid_of` and `find_split_by_guid`
    # normalise, because the key is stored exactly as a file spelled it and a
    # file may give a guid dashed. Measured on 5.10 in
    # `tests/research/how_a_dashed_guid_is_stored_probe.py`: the dashed
    # spelling is stored dashed, and `string_to_guid` reads it — so this is
    # GnuCash's parser answering rather than anything of ours, and the ten
    # supported builds do not have to agree about it. Unnormalised and given a
    # stricter parser, the lookup finds nothing, the answer is "no pool was
    # consumed", and the export writes a guid its own import refuses.
    other = _the_split_this_book_holds(
        book, str(basis_guid).replace('-', '').lower())
    if other is None:
        return False
    try:
        return not establishes_cost_basis(other) and is_a_spent_credit(other)
    except Exception:
        return False


class ExportResult:
    """Container for export data"""
    def __init__(self):
        self.commodities = []  # List of (commodity, first_transaction)
        self.accounts = []     # List of (account, first_transaction)
        self.transactions = [] # List of transactions
        self.commodity_seen = set()
        self.account_seen = set()
        # Running balance data: tx_guid -> {account_guid -> Fraction}
        # Populated by execute(with_balance=True); empty dict means no balances.
        self.account_balances_after_tx: dict = {}


def bank_paid_orphan_share_of(account):
    """{lot pointer: signed amount} an unpost loosened that no credit paid.

    A lot an unpost abandoned is live, names no invoice and does name an owner —
    the three things an owner's credit is — so every listing of credits would
    report what is in it as the owner's to spend. For the part a bank paid it
    is not: that is a settlement waiting to be put back, which is what all
    three settlement spellings say when a file tries to spend it.

    A *share* and not a verdict on the lot, because one invoice can be
    settled both ways — a bank block and a `from_credit:` block, which is what
    `_cash_before_credit` orders — and unposting marks every split in the lot.
    Excluding the whole lot then hid credit the settling paths still allow:
    100.00 settled 60.00 by bank and 40.00 out of credit, unposted, and the
    customer's real 40.00 became spendable but invisible. Subtracting only the
    bank's 60.00 leaves the 40.00 listed, which is what it is.

    The same predicate the importer asks of the same split
    (`_sits_in_an_owners_credit`), read here so the listing and the settling
    cannot disagree about one split — offering money as spendable and then
    refusing it is worse than either answer on its own.
    """
    share = {}
    for split in account.GetSplitList():
        lot = split.GetLot()
        if lot is None or not is_a_bank_paid_orphan(split):
            continue
        key = qof_pointer(lot)
        share[key] = share.get(key, Fraction(0)) + numeric_to_fraction(
            split.GetAmount())
    return share


def lot_holdings_of(account):
    """{lot pointer: (balance, earliest transaction date)} for one AR/AP account.

    Read from the account's splits and grouped by the lot each one says it is
    in — never from `gnc_lot_get_balance`, which sums the lot's own split list.
    A split moved with `xaccSplitSetLot` is not taken out of that list until
    the book has been written and read back (CLAUDE.md finding 9), so in the
    session that applies a credit the lot it came from still reports it.

    Every reader of "what does this lot hold" in this file goes through here,
    so the file cannot answer that question two ways: the summary an export
    writes, the check an import makes against it, and the ownerless-lot warning
    all agree, in a fresh session and in the one that just moved a split.

    `gnc_lot_is_closed` is the same stale reading — a lot is closed when it
    holds nothing — so a balance of zero answers that too.
    """
    held = {}
    for split in account.GetSplitList():
        lot = split.GetLot()
        if lot is None:
            continue
        key = qof_pointer(lot)
        balance, earliest = held.get(key, (Fraction(0), None))
        balance += numeric_to_fraction(split.GetAmount())
        parent = split.GetParent()
        when = parent.GetDate() if parent is not None else None
        if when is not None and (earliest is None or when < earliest):
            earliest = when
        held[key] = (balance, earliest)
    return held


def open_prepayments_for_account(account):
    """Open prepayment credits on an AR/AP account, as (kind, owner_id,
    owner_guid, amount) tuples — one per open, owner-attached, non-invoice lot,
    oldest first. Shared by the exporter (the `open_prepayment:` summary) and
    the import-time consistency check, so both see credits the same way (owner
    resolved via the lot, which catches standalone credits)."""
    import ctypes as _ctypes

    from infrastructure.gnucash.engine import load_gnc_engine as _load

    # Nothing declared here. Every signature this needs is set once in
    # `_setup_lib_restypes`, because the handle is cached process-wide and a
    # local `restype` rewrites what every other caller is holding: this
    # function used to declare `gnc_lot_get_balance` as a locally defined
    # struct while `engine.py` declared it as `GncNumericC`, and the two agreed
    # only because they happen to have the same fields. Five of the names it
    # set are gone with the reading that called them.
    _lib = _load()

    held = lot_holdings_of(account)
    orphan_share = bank_paid_orphan_share_of(account)

    creds = []  # (when, kind, oid, guid, amount)
    g = _lib.xaccAccountGetLotList(int(account.instance))
    while g:
        node = _ctypes.cast(g, _ctypes.POINTER(_ctypes.c_void_p * 3)).contents
        lot = node[0]
        if lot:
            # Exact: a lot's balance is a rational, so "still has a balance" is
            # `!= 0`, not a comparison against an epsilon chosen to cover what a
            # float could not represent. A lot holding nothing is a closed one,
            # which is the same question `gnc_lot_is_closed` answers off the
            # same stale list.
            bal, when = held.get(int(lot), (Fraction(0), None))
            # What an unpost loosened and a bank had paid is not credit,
            # however much it looks like it — taken off rather than the whole
            # lot disqualified, since one lot can hold both kinds. See
            # `bank_paid_orphan_share_of`.
            bal -= orphan_share.get(int(lot), Fraction(0))
            if bal != 0 and not _lib.gncInvoiceGetInvoiceFromLot(lot):
                obuf = _ctypes.create_string_buffer(256)
                op = _ctypes.cast(obuf, _ctypes.c_void_p).value
                if _lib.gncOwnerGetOwnerFromLot(lot, op) == 1:
                    kind = {2: 'customer', 4: 'vendor'}.get(_lib.gncOwnerGetType(op))
                    oid_raw = _lib.gncOwnerGetID(op)
                    oid = oid_raw.decode('utf-8', errors='replace') if oid_raw else ''
                    guid = ''
                    gp = _lib.gncOwnerGetGUID(op)
                    if gp:
                        gbuf = _ctypes.create_string_buffer(40)
                        _lib.guid_to_string_buff(gp, gbuf)
                        guid = gbuf.value.decode('ascii').replace('-', '')
                    if kind and oid:
                        # Oldest first, from the same splits the balance came
                        # from — `gnc_lot_get_earliest_split` reads the lot's
                        # own list, which is what is stale here.
                        creds.append((when, kind, oid, guid, abs(bal)))
        g = node[1]
    return [(kind, oid, guid, amount)
            for _when, kind, oid, guid, amount
            in sorted(creds, key=lambda c: (c[0] is None, c[0]))]


def _ownerless_open_credit_lots(account):
    """Open, non-invoice credit lots on an AR/AP account whose LOT carries no
    owner (gncOwnerGetOwnerFromLot fails) — the inverse of
    open_prepayments_for_account. Such a lot holds a real credit balance but is
    invisible to the `open_prepayment:` summary and unattributable to any
    customer/vendor, so it always signals a bug in whatever created the lot
    (every legitimate path attaches the owner). Returns absolute balances."""
    import ctypes as _ctypes

    from infrastructure.gnucash.engine import load_gnc_engine as _load

    # Nothing to declare: `xaccAccountGetLotList`, `gncInvoiceGetInvoiceFromLot`
    # and `gncOwnerGetOwnerFromLot` are all set once in `_setup_lib_restypes`,
    # and declaring them again here would rewrite the process-wide handle every
    # other caller is holding.
    _lib = _load()

    # Through `lot_holdings_of`, like the summary above it. Both answer "what
    # does this lot hold", and a file that answers that two ways will drift:
    # the reading this replaces is short by any split moved with
    # `xaccSplitSetLot` in this session, which is exactly the case the summary
    # was changed away from.
    held = lot_holdings_of(account)

    bad = []
    g = _lib.xaccAccountGetLotList(int(account.instance))
    while g:
        node = _ctypes.cast(g, _ctypes.POINTER(_ctypes.c_void_p * 3)).contents
        lot = node[0]
        if lot:
            # Exact: a lot's balance is a rational, so "still has a balance" is
            # `!= 0`, not a comparison against an epsilon chosen to cover what a
            # float could not represent — and a lot holding nothing is a closed
            # one, which is what `gnc_lot_is_closed` reads off the same list.
            bal = held.get(int(lot), (Fraction(0), None))[0]
            if bal != 0 and not _lib.gncInvoiceGetInvoiceFromLot(lot):
                obuf = _ctypes.create_string_buffer(256)
                op = _ctypes.cast(obuf, _ctypes.c_void_p).value
                if _lib.gncOwnerGetOwnerFromLot(lot, op) != 1:
                    bad.append(abs(bal))
        g = node[1]
    return bad


def find_ownerless_credit_lots(book):
    """Every open non-invoice AR/AP credit lot in the book whose lot has no
    owner — a data defect (a credit that belongs to no customer/vendor, hidden
    from the open_prepayment summary). Returns (account_full_name, amount,
    mnemonic, unit) tuples: the amount exact, and the unit its account is kept
    to so a caller can write it at that account's own decimals. An empty list
    is the healthy invariant."""
    out = []

    def walk(acct):
        if acct.GetType() in (11, 12):  # ACCT_TYPE_RECEIVABLE / PAYABLE
            commodity = acct.GetCommodity()
            mnem = commodity.get_mnemonic() if commodity else ''
            # The account's own unit, not the commodity's — an account may be
            # kept finer than its currency, and this warning is about money
            # nobody has. Stated at the cent, a 20.005 credit on an account
            # kept to the tenth of one reads as 20.01: a figure the book does
            # not hold, in the line whose whole job is to be believed.
            unit = (acct.GetCommoditySCU()
                    or (commodity.get_fraction() if commodity else 100))
            for amount in _ownerless_open_credit_lots(acct):
                out.append((acct.get_full_name(), amount, mnem, unit))
        for child in acct.get_children():
            walk(child)

    walk(book.get_root_account())
    return out


class ExportTransactionsUseCase:
    """Use case for exporting transactions to plaintext with full metadata"""

    def __init__(self, repository: GnuCashRepository):
        """
        Initialize use case.

        Args:
            repository: GnuCash repository instance
        """
        self.repository = repository

    def execute(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        account_filter: Optional[str] = None,
        all_accounts: bool = False,
        with_balance: bool = False,
    ) -> ExportResult:
        """
        Export transactions with ALL commodities and accounts.

        IMPORTANT: When filtering transactions, we still export ALL commodities
        and ALL accounts. This is required for successful import - commodities
        and accounts are declarations that must exist before transactions can
        reference them.

        Args:
            start_date: Optional start date for filtering TRANSACTIONS only
            end_date: Optional end date for filtering TRANSACTIONS only
            account_filter: Optional account path for filtering TRANSACTIONS only
            all_accounts: If True, export ALL accounts regardless of transactions
            with_balance: If True, compute running per-account balances so that
                format_as_plaintext() can emit a ``balance:`` line on every
                split.  Balances are calculated over ALL transactions (not just
                the filtered subset) so the values are always correct even when
                a date or account filter is in effect.

        Returns:
            ExportResult with:
            - ALL commodities (not filtered, or all from accounts if all_accounts=True)
            - ALL accounts (not filtered, or all from repository if all_accounts=True)
            - Filtered transactions (by date/account if specified)
            - account_balances_after_tx populated when with_balance=True
        """
        # Get ALL transactions first (we'll filter them later)
        all_transactions = self.repository.get_all_transactions()

        all_transactions.sort(key=cmp_to_key(the_order_the_book_keeps_them_in))

        # Filter transactions by date range if specified
        if start_date and end_date:
            filtered_transactions = []
            for tx in all_transactions:
                tx_date = tx.GetDate().strftime("%Y-%m-%d")
                if start_date <= tx_date <= end_date:
                    filtered_transactions.append(tx)
            transactions = filtered_transactions
        else:
            transactions = all_transactions

        # Filter transactions by account if specified
        if account_filter:
            filtered = []
            for tx in transactions:
                for split in tx.GetSplitList():
                    account = split.GetAccount()
                    account_name = get_account_full_name(account)
                    if account_name.startswith(account_filter):
                        filtered.append(tx)
                        break
            transactions = filtered

        # Last, so that only what the file will carry is asked about, and so
        # that `all_transactions` stays in the book's own order: it is what
        # the running balances are added up over, and a balance is a figure
        # as at a date, whatever order the file states the transactions in.
        transactions = each_basis_above_what_draws_on_it(transactions)

        result = ExportResult()

        if all_accounts:
            # Collect ALL accounts and their commodities directly from repository
            for account in self.repository.get_all_accounts():
                commodity = account.GetCommodity()
                if commodity is None:
                    continue
                ticker = get_commodity_ticker(commodity)
                if ticker not in result.commodity_seen:
                    result.commodity_seen.add(ticker)
                    result.commodities.append((commodity, None))
                account_guid = account.GetGUID().to_string()
                if account_guid not in result.account_seen:
                    result.account_seen.add(account_guid)
                    result.accounts.append((account, None))
        else:
            # Collect ALL commodities and ALL accounts (not just from filtered transactions)
            # This is critical - without all declarations, import will fail
            for transaction in all_transactions:
                self._collect_transaction_data(transaction, result)

        # Only include the filtered transactions in the result
        result.transactions = transactions

        # Pre-compute running balances across ALL transactions when requested so
        # that filtered exports still show correct cumulative account balances.
        if with_balance:
            result.account_balances_after_tx = self._compute_running_balances(
                all_transactions
            )

        return result

    def _compute_running_balances(self, all_transactions_sorted: list) -> dict:
        """
        Compute the per-account running balance after each transaction.

        Iterates every transaction in chronological order (caller must pre-sort)
        and accumulates split amounts using exact Fraction arithmetic.  The
        result is a mapping from tx_guid to a nested dict of
        {account_guid -> Fraction} holding the account balance *after* that
        transaction has been applied.

        Only accounts that appear in a given transaction are stored for that
        transaction; the caller looks up the balance for (tx_guid, account_guid)
        at format time.

        Args:
            all_transactions_sorted: All transactions, already sorted by date.

        Returns:
            dict mapping tx_guid (str) -> dict[account_guid (str) -> Fraction]
        """
        running: dict = {}   # account_guid -> Fraction (cumulative)
        result: dict = {}    # tx_guid -> {account_guid -> Fraction}

        for tx in all_transactions_sorted:
            tx_guid = tx.GetGUID().to_string()
            tx_accounts: set = set()

            for split in tx.GetSplitList():
                account = split.GetAccount()
                account_guid = account.GetGUID().to_string()
                amount = split.GetAmount()
                delta = Fraction(int(amount.num()), int(amount.denom()))
                running[account_guid] = running.get(account_guid, Fraction(0)) + delta
                tx_accounts.add(account_guid)

            result[tx_guid] = {guid: running[guid] for guid in tx_accounts}

        return result

    def _collect_transaction_data(self, transaction, result: ExportResult):
        """
        Collect commodity, account, and transaction data.

        Args:
            transaction: GnuCash Transaction object
            result: ExportResult to populate
        """
        splits = transaction.GetSplitList()

        # Collect commodities and accounts from splits
        for split in splits:
            split_account = split.GetAccount()
            commodity = split_account.GetCommodity()
            ticker = get_commodity_ticker(commodity)

            # Collect commodity if not seen
            if ticker not in result.commodity_seen:
                result.commodity_seen.add(ticker)
                result.commodities.append((commodity, transaction))

            # Collect account hierarchy if not seen
            accounts = get_parent_accounts_and_self(split_account)
            for account in accounts:
                account_guid = account.GetGUID().to_string()
                if account_guid not in result.account_seen:
                    result.account_seen.add(account_guid)
                    result.accounts.append((account, transaction))

        # Add transaction
        result.transactions.append(transaction)

    def format_as_plaintext(self, result: ExportResult) -> str:
        """
        Format export result as plaintext string with full legacy format.

        When result.account_balances_after_tx is non-empty (i.e. execute() was
        called with with_balance=True), each split line will be followed by a
        ``balance:`` metadata line showing the cumulative account balance after
        that transaction, expressed in the account's own commodity.

        Args:
            result: ExportResult with commodities, accounts, and transactions

        Returns:
            Formatted plaintext string with all metadata
        """
        lines = []

        # Output commodities
        for commodity, transaction in result.commodities:
            self._format_commodity(commodity, transaction, lines)

        # Output accounts
        for account, transaction in result.accounts:
            self._format_account(account, transaction, lines)

        # Output transactions. Collected the same way as the section-only
        # path above: every transaction the format cannot express is named,
        # and none is written, rather than the first one ending the run.
        refusals = []
        for transaction in result.transactions:
            tx_guid = transaction.GetGUID().to_string()
            balance_map = result.account_balances_after_tx.get(tx_guid)
            try:
                self._format_transaction(transaction, lines,
                                         balance_map=balance_map)
            except UnwritableFigureError as exc:
                refusals.append(str(exc))
        if refusals:
            raise UnwritableFigureError(
                f'{len(refusals)} transaction(s) hold figures this format '
                f'cannot write, and nothing was exported:\n  - '
                + '\n  - '.join(refusals))

        # Join lines and add trailing newline to match legacy format
        return '\n'.join(lines) + '\n' if lines else ''

    def execute_accounts_only(self) -> ExportResult:
        """
        Export all accounts and their commodities without loading any transactions.

        Much faster than execute() for account-structure-only exports since it
        never touches the transaction log.

        The open date for each declaration is determined at format time by
        format_accounts_only(as_of_date=...).  This method only populates the
        account and commodity lists — it carries no date information.

        Returns:
            ExportResult with all accounts and commodities; no transactions.
        """
        result = ExportResult()
        for account in self.repository.get_all_accounts():
            commodity = account.GetCommodity()
            if commodity is None:
                continue
            ticker = get_commodity_ticker(commodity)
            if ticker not in result.commodity_seen:
                result.commodity_seen.add(ticker)
                result.commodities.append((commodity, None))
            account_guid = account.GetGUID().to_string()
            if account_guid not in result.account_seen:
                result.account_seen.add(account_guid)
                result.accounts.append((account, None))
        return result

    def format_accounts_only(self, result: ExportResult, as_of_date: Optional[str] = None) -> str:
        """Format commodities and accounts using as_of_date (or file mtime) for open dates."""
        lines = []
        for commodity, transaction in result.commodities:
            self._format_commodity(commodity, transaction, lines, date_override=as_of_date)
        for account, transaction in result.accounts:
            self._format_account(account, transaction, lines, date_override=as_of_date)
        return '\n'.join(lines) + '\n' if lines else ''

    def format_accounts_section(self, result: ExportResult) -> str:
        """Format only commodities and accounts (no transactions)."""
        lines = []
        for commodity, transaction in result.commodities:
            self._format_commodity(commodity, transaction, lines)
        for account, transaction in result.accounts:
            self._format_account(account, transaction, lines)
        return '\n'.join(lines) + '\n' if lines else ''

    def format_transactions_section(self, result: ExportResult) -> str:
        """Format only transactions (no commodities or accounts).

        A transaction the format cannot express stops the export, and every
        such transaction is named before it does. Skipping them instead would
        write a file that is a *smaller* ledger than the book — re-imported,
        the missing ones are gone and nothing says so — which is the opposite
        of what an import error means, where the book is untouched and the
        file is the thing to fix. So the export refuses, and the reader gets
        the whole list rather than one offender per run through a book that
        may hold thousands.
        """
        lines = []
        refusals = []
        for transaction in result.transactions:
            tx_guid = transaction.GetGUID().to_string()
            balance_map = result.account_balances_after_tx.get(tx_guid)
            try:
                self._format_transaction(transaction, lines,
                                         balance_map=balance_map)
            except UnwritableFigureError as exc:
                refusals.append(str(exc))
        if refusals:
            raise UnwritableFigureError(
                f'{len(refusals)} transaction(s) hold figures this format '
                f'cannot write, and nothing was exported:\n  - '
                + '\n  - '.join(refusals))
        return '\n'.join(lines) + '\n' if lines else ''

    def format_transaction_list(self, transactions: list) -> str:
        """
        Format a list of Transaction objects as plaintext (transaction blocks only).

        Collects all required data from the transactions and returns their
        plaintext representation without commodity or account preamble.
        Useful for outputting newly imported transactions with their GUIDs.
        """
        result = ExportResult()
        for tx in transactions:
            self._collect_transaction_data(tx, result)
        return self.format_transactions_section(result)

    def _file_date_str(self) -> str:
        """Return GnuCash file modification date as YYYY-MM-DD string."""
        mtime = os.path.getmtime(self.repository.file_path)
        return datetime.date.fromtimestamp(mtime).strftime("%Y-%m-%d")

    def _format_commodity(self, commodity, transaction, lines: list, date_override: Optional[str] = None):
        """Format commodity declaration"""
        mnemonic = commodity.get_mnemonic()
        namespace = commodity.get_namespace()
        fraction = commodity.get_fraction()
        fullname = commodity.get_fullname()

        if date_override is not None:
            date_str = date_override
        elif transaction is not None:
            date_str = transaction.GetDate().strftime("%Y-%m-%d")
        else:
            date_str = self._file_date_str()
        ticker = get_commodity_ticker(commodity)

        lines.append(f'{date_str} commodity {ticker}')
        lines.append(f'\tmnemonic: {encode_value_as_string(mnemonic)}')
        lines.append(f'\tfullname: {encode_value_as_string(fullname)}')
        lines.append(f'\tnamespace: {encode_value_as_string(namespace)}')
        lines.append(f'\tfraction: {fraction}')

    def _format_account(self, account, transaction, lines: list, date_override: Optional[str] = None):
        """Format account declaration"""
        commodity = account.GetCommodity()
        if commodity is None:
            return

        mnemonic = commodity.get_mnemonic()
        namespace = commodity.get_namespace()
        fraction = commodity.get_fraction()
        commodity_scu = account.GetCommoditySCU()

        if date_override is not None:
            date_str = date_override
        elif transaction is not None:
            date_str = transaction.GetDate().strftime("%Y-%m-%d")
        else:
            date_str = self._file_date_str()
        account_full_name = get_account_full_name(account)
        account_guid = account.GetGUID()
        account_type = account.GetType()
        account_type_str = xaccAccountGetTypeStr(account_type)
        is_placeholder = account.GetPlaceholder()
        code = account.GetCode()
        description = account.GetDescription()
        color = account.GetColor()
        notes = account.GetNotes()
        tax_related = account.GetTaxRelated()

        lines.append(f'{date_str} open {account_full_name}')
        lines.append(f'\tguid: "{account_guid.to_string()}"')
        lines.append(f'\ttype: "{account_type_str}"')

        for (key, value) in [
            ('placeholder', is_placeholder),
            ('code', code),
            ('description', description),
            ('color', color),
            ('notes', notes),
            ('tax_related', tax_related),
        ]:
            if value is not None:
                lines.append(f'\t{key}: {encode_value_as_string(value)}')

        lines.append(f'\tcommodity.namespace: {encode_value_as_string(namespace)}')
        lines.append(f'\tcommodity.mnemonic: {encode_value_as_string(mnemonic)}')
        if commodity_scu != fraction:
            lines.append(f'\tcommodity_scu: {encode_value_as_string(commodity_scu)}')

        custom_meta = get_custom_metadata(account)
        for k, v in sorted(custom_meta.items()):
            lines.append(f'\t{k}: {encode_value_as_string(v)}')

        # Per-account open-credit summary: on AR/AP accounts, list every open
        # owner-attached lot with no invoice (a prepayment credit). Recomputed
        # from the live lots on each export. The authoritative data is the
        # per-split `lot_owner` KVPs, but this figure is read back on import
        # and compared exactly — a book that states it at a coarser unit than
        # the account is kept to warns about itself on every import.
        if account_type in (11, 12):  # ACCT_TYPE_RECEIVABLE / PAYABLE
            self._append_open_prepayments(account, mnemonic, lines)

    def _append_open_prepayments(self, account, mnemonic, lines):
        """Emit one `open_prepayment:` block per open credit on an AR/AP account
        (oldest first)."""
        unit = account.GetCommoditySCU() or account.GetCommodity().get_fraction()
        for kind, oid, guid, amount in open_prepayments_for_account(account):
            lines.append('\topen_prepayment:')
            lines.append(f'\t\t{kind}: {encode_value_as_string(oid)}')
            if guid and guid != '0' * 32:
                lines.append(f'\t\t{kind}_guid: "{guid}"')
            lines.append(f'\t\tamount: {money_text(amount, unit)} {mnemonic}')

    def _format_transaction(
        self,
        transaction,
        lines: list,
        balance_map: Optional[dict] = None,
    ):
        """
        Format transaction with all metadata.

        Args:
            transaction: GnuCash Transaction object
            lines: Output lines list to append to
            balance_map: Optional {account_guid -> Fraction} of running balances
                after this transaction.  When provided, each split gets a
                ``balance:`` metadata line.
        """
        tx_guid = transaction.GetGUID()
        tx_splits = transaction.GetSplitList()
        date_str = transaction.GetDate().strftime("%Y-%m-%d")
        tx_num = transaction.GetNum()
        tx_desc = transaction.GetDescription()
        tx_notes = transaction.GetNotes()
        tx_currency = transaction.GetCurrency()
        tx_currency_namespace = tx_currency.get_namespace()
        tx_currency_symbol = tx_currency.get_mnemonic()

        # GetAssociation was renamed to GetDocLink in GnuCash 4.x
        try:
            tx_doc_link = transaction.GetDocLink()
        except AttributeError:
            # Fall back to older GnuCash API (< 4.0)
            tx_doc_link = transaction.GetAssociation()

        # Transaction header. When tx_num is set, always emit the desc slot
        # too (with "" if desc is empty); otherwise the parser sees `* "X"`
        # as desc=X (single quoted string → desc) and Num gets silently
        # relabeled as Description on re-import — Q-020.
        line = f'{date_str} *'
        if tx_num and tx_num.strip() != "":
            line += f' {encode_value_as_string(tx_num)}'
            line += f' {encode_value_as_string(tx_desc or "")}'
        elif tx_desc and tx_desc.strip() != "":
            line += f' {encode_value_as_string(tx_desc)}'
        lines.append(line)

        # Transaction metadata
        lines.append(f'\tguid: {encode_value_as_string(tx_guid.to_string())}')
        if tx_currency_namespace != 'CURRENCY':
            lines.append(f'\tcurrency.namespace: {encode_value_as_string(tx_currency_namespace)}')

        # Check if multi-currency transaction
        split_currencies = [
            (split.GetAccount().GetCommodity().get_namespace(),
             split.GetAccount().GetCommodity().get_mnemonic())
            for split in tx_splits
        ]
        split_currencies = list(set(split_currencies))
        if len(split_currencies) > 1:
            lines.append(f'\tcurrency.mnemonic: {encode_value_as_string(tx_currency_symbol)}')

        if tx_doc_link is not None:
            lines.append(f'\tdoc_link: {encode_value_as_string(tx_doc_link)}')
        if tx_notes and tx_notes.strip() != "":
            lines.append(f'\tnotes: {encode_value_as_string(tx_notes)}')

        # Q-032: preserve the book-closing flag across a plaintext roundtrip
        # (only emitted on closing transactions).
        if xaccTransGetIsClosingTxn(transaction.instance):
            lines.append('\tclosing: #True')

        # txn_type + owner: GnuCash internal classifier + customer/vendor
        # KVP backref set by the business-object machinery (txn_type='I'
        # on invoice/bill posting transactions and 'P' on payments
        # created by `gncOwnerApplyPayment`; the gncOwner KVP slot names
        # the customer/vendor that the payment paid). Default txn_type
        # is 'N' (normal); only emit non-N values so old plaintext files
        # round-trip unchanged. Both fields are needed so that orphan
        # bank-side payment transactions (whose AR/AP lot was detached
        # by unpost) can still be detected by `find-orphan-payments`
        # after a plaintext roundtrip — without these fields the
        # restored tx defaults to txn_type='N' and no owner ref, so
        # criteria 1 and 2 of the classifier fail.
        import ctypes as _ctypes

        from infrastructure.gnucash.engine import load_gnc_engine as _load
        _lib = _load()
        _tx_ptr = int(transaction.instance)
        _emitted_txn_type = False
        _emitted_owner = False
        try:
            _lib.xaccTransGetTxnType.restype = _ctypes.c_char
            _lib.xaccTransGetTxnType.argtypes = [_ctypes.c_void_p]
            _t = _lib.xaccTransGetTxnType(_tx_ptr)
            if isinstance(_t, bytes):
                _t = _t.decode('ascii', errors='replace')
            # 'N' is normal and so is an unset field, which older GnuCash
            # hands back as NUL rather than 'N'. Emitting that wrote a literal
            # NUL byte into the file as `txn_type: \x00`.
            if _t and _t not in ('N', '\x00'):
                lines.append(f'\ttxn_type: {_t}')
                _emitted_txn_type = True
        except AttributeError:
            pass

        try:
            _lib.gncOwnerGetOwnerFromTxn.argtypes = [_ctypes.c_void_p, _ctypes.c_void_p]
            _lib.gncOwnerGetOwnerFromTxn.restype = _ctypes.c_int
            _lib.gncOwnerGetID.argtypes = [_ctypes.c_void_p]
            _lib.gncOwnerGetID.restype = _ctypes.c_char_p
            _lib.gncOwnerGetType.argtypes = [_ctypes.c_void_p]
            _lib.gncOwnerGetType.restype = _ctypes.c_int
            _owner_buf = _ctypes.create_string_buffer(256)
            _owner_p = _ctypes.cast(_owner_buf, _ctypes.c_void_p).value
            if _lib.gncOwnerGetOwnerFromTxn(_tx_ptr, _owner_p) == 1:
                _otype = _lib.gncOwnerGetType(_owner_p)
                _oid_raw = _lib.gncOwnerGetID(_owner_p)
                _oid = (_oid_raw.decode('utf-8', errors='replace')
                        if _oid_raw else '')
                _kind = {2: 'customer', 4: 'vendor'}.get(_otype)
                if _kind and _oid:
                    lines.append(f'\towner: {_kind}:{_oid}')
                    _emitted_owner = True
        except AttributeError:
            pass

        # Q-035: where the engine answered neither, a split the unpost marked
        # can. Both lines exist so an orphaned payment survives a round-trip,
        # and on GnuCash 4.4 and 3.8 a settlement attached by retarget is
        # exactly the payment neither reading recognises — so the two lines
        # that keep it visible were the two omitted, and the restored book
        # carried a receivable no command explained. The mark itself may not
        # travel; what it says about the transaction may.
        if not (_emitted_txn_type and _emitted_owner):
            _orphan_kind, _orphan_id = _owner_of_a_bank_paid_orphan(
                tx_splits, _lib)
            if _orphan_id:
                if not _emitted_txn_type:
                    lines.append('\ttxn_type: P')
                    _emitted_txn_type = True
                if not _emitted_owner:
                    lines.append(f'\towner: {_orphan_kind}:{_orphan_id}')
                    _emitted_owner = True

        # Emit custom KVP metadata. Skip Q-014's `txn_type` and `owner`
        # slots — they're already emitted above as dedicated lines based
        # on the live C state, and re-emitting from the KVP slot would
        # produce duplicate lines on the second pass of an export → import
        # → export roundtrip (the importer stores `txn_type:` and `owner:`
        # from the plaintext as custom KVPs, and additionally applies
        # `txn_type` to the transaction itself with `xaccTransSetTxnType`,
        # which the reader honours on GnuCash 3.8/4.4 and not on 4.13+, where
        # the type is derived from the splits instead — hence the fallback
        # below when the C field reads unset).
        # `orphaned_by_unpost` for the reason the split side filters it: the
        # import refuses a file stating it, so writing one out would be a book
        # with no way back in. Older builds kept a transaction-level copy of a
        # key that never belonged there, and nothing reads it off a
        # transaction — both consumers take a split — so dropping it here
        # loses nothing and lets such a book export and re-import.
        _q014_reserved_tx = {'txn_type', 'owner', ORPHANED_BY_UNPOST_KEY}
        custom_meta = get_custom_metadata(transaction)
        for key, value in sorted(custom_meta.items()):
            if key == 'txn_type' and not _emitted_txn_type:
                # The C field is unset, so this is the only copy left. On
                # GnuCash 4.13+ `xaccTransGetTxnType` derives the type from
                # the transaction's splits and never reads the slot that
                # `xaccTransSetTxnType` writes, so a `txn_type: P` re-imported
                # from plaintext lives only here —
                # dropping it would lose the classification silently, where
                # before it at least came back as a visible NUL byte.
                #
                # One consequence: where the C field carries the value (3.8,
                # 4.4) the line is written above, before `owner:`; where this
                # fallback carries it (4.13+) it lands here, after. Stable on
                # any one version, so a roundtrip is byte-identical, but the
                # same book exported on two versions differs in line order.
                #
                # Filtered the same way as the C field, and for a reason that
                # outlives the field's own bug: every earlier version wrote the
                # unset field out as a NUL, so files exist that read
                # `txn_type: \x00`, and importing one stores that byte here as
                # an ordinary KVP. Emitting it again would carry it through
                # every future round trip.
                if value in ('N', '\x00'):
                    continue
                lines.append(f'\ttxn_type: {value}')
                continue
            if key == 'owner' and not _emitted_owner:
                # Same story as `txn_type` above, and for the same pair of
                # readings: the C owner slot is `gncOwnerApplyPayment`'s and
                # cannot be set from Python after a round-trip, so on a
                # restored book this KVP is the only copy of it left. Skipped
                # outright, the line survived one round-trip and vanished on
                # the next — the orphan visible in the book you restored and
                # gone from the one you restored from that.
                lines.append(f'\towner: {value}')
                continue
            if key in _q014_reserved_tx:
                continue
            lines.append(f'\t{key}: {encode_value_as_string(value)}')

        # Splits
        for split in tx_splits:
            balance: Optional[Fraction] = None
            if balance_map is not None:
                account_guid = split.GetAccount().GetGUID().to_string()
                balance = balance_map.get(account_guid)
            self._format_split(
                split, tx_currency_namespace, tx_currency_symbol, lines,
                balance=balance,
            )

    def _format_split(
        self,
        split,
        tx_currency_namespace,
        tx_currency_symbol,
        lines: list,
        balance: Optional[Fraction] = None,
    ):
        """
        Format split with all metadata.

        Args:
            split: GnuCash Split object
            tx_currency_namespace: Transaction currency namespace
            tx_currency_symbol: Transaction currency mnemonic
            lines: Output lines list to append to
            balance: Optional running balance (Fraction) of this account after
                the parent transaction.  When provided, a ``balance:`` metadata
                line is emitted as the last item of the split's metadata block.
        """
        split_account = split.GetAccount()
        split_currency = split_account.GetCommodity()
        split_currency_namespace = split_currency.get_namespace()
        split_currency_symbol = split_currency.get_mnemonic()

        split_account_full_name = get_account_full_name(split_account)
        action = split.GetAction()
        memo = split.GetMemo()

        # The amount is in the account's own commodity and the value in the
        # transaction's, so each is written at that commodity's decimals. The
        # share price is a rate, not money: it has no smallest unit and is
        # written at whatever it needs.
        # No null guard on the parent: this is only ever called while walking a
        # transaction's own splits, so there is one. The guard that stood here
        # was already contradicted three lines down, where the refusal below
        # reads the description without asking — and a branch that cannot be
        # reached is one nothing keeps honest.
        transaction = split.GetParent()
        transaction_currency = transaction.GetCurrency()
        # The account's own smallest unit, which is not always the currency's:
        # GnuCash keeps it per account, this exporter emits it as
        # `commodity_scu:` when it differs, and an account kept to tenths of a
        # cent — fuel at 1.819 a litre — would otherwise have its amounts
        # rounded away on the way out.
        account_scu = split_account.GetCommoditySCU()
        split_amount = numeric_to_fraction(split.GetAmount())
        # Written at the account's unit, so 18.190 keeps its third place and
        # comes back with the denominator it left with. That is a trailing
        # zero on a figure the currency holds perfectly well.
        #
        # A figure that genuinely *needs* the extra digit is different: 1.819
        # CAD is not a number of cents, and the import refuses it. Emitting it
        # anyway wrote a file this tool cannot read — `export` said nothing,
        # and `import --new` on its own output dropped the transaction. Said
        # here instead, against the split that holds it.
        refuse_a_figure_the_currency_cannot_hold(
            split_amount, split_account, 'the split',
            transaction.GetDescription())
        formatted_amount = money_text(split_amount, account_scu)
        share_price = to_string_with_decimal_point_placed(split.GetSharePrice())
        # A split in the transaction's own currency has one figure, not two:
        # its value is its amount. Writing the value at the currency's unit
        # while the amount used the account's finer one made them differ by the
        # rounding — 18.190 with `value: "18.19"` — so the exporter emitted a
        # `value:` line for a split that never needed one, and every re-import
        # booked a value half a thousandth off its own amount.
        # No guard on the value, where the amount above has one, and the
        # asymmetry is the engine's rather than this exporter's: measured,
        # `SetValue(GncNumeric(135005, 1000))` on a CAD transaction reads back
        # as `13501/100`. GnuCash normalises a value to the transaction
        # currency's denominator as it is written, so no book holds one finer
        # than that and this `money_text` is rounding a figure already round.
        #
        # An amount is different, which is why it needs the guard: an account
        # may legitimately be kept finer than its currency (`commodity_scu:`),
        # so GnuCash stores what it is given and the check has something to
        # catch. Pinned by `test_a_value_the_currency_cannot_hold.py`.
        value_scu = (account_scu
                     if split_currency.get_mnemonic() == transaction_currency.get_mnemonic()
                     else transaction_currency.get_fraction())
        split_value = money_text(numeric_to_fraction(split.GetValue()), value_scu)

        # Split line
        currency_ticker = get_commodity_ticker(split_currency)
        if ' ' in currency_ticker or '\t' in currency_ticker:
            currency_ticker = encode_value_as_string(currency_ticker)
        lines.append(f'\t{split_account_full_name} {formatted_amount} {currency_ticker}')

        # Q-016: emit per-split GUID so a payment block (or any other
        # downstream reference) can identify this specific split on the
        # tx by GUID — critical for the multi-invoice-1-bank-tx case
        # where the same tx has multiple AR/AP-side splits, each routed
        # to a different invoice's lot. The split identifies *itself*
        # here, so the field name is `guid:` (same convention as the
        # transaction-level `guid:`); only foreign references (like
        # `txn_split_guid:` in a payment block) carry a typed
        # `split_` prefix.
        lines.append(f'\t\tguid: {encode_value_as_string(split.GetGUID().to_string())}')

        # Split metadata
        split_currency_not_match_tx = (
            split_currency_symbol != tx_currency_symbol or
            split_currency_namespace != tx_currency_namespace
        )

        if split_currency_not_match_tx:
            lines.append(f'\t\taccount.commodity.mnemonic: {encode_value_as_string(split_currency_symbol)}')
            if split_currency_namespace != 'CURRENCY':
                lines.append(f'\t\taccount.commodity.namespace: {encode_value_as_string(split_currency_namespace)}')

        if not number_in_string_format_is_1(share_price) or split_currency_not_match_tx:
            lines.append(f'\t\tshare_price: {encode_value_as_string(share_price)}')

        if split_value != formatted_amount:
            lines.append(f'\t\tvalue: {encode_value_as_string(split_value)}')

        if action is not None and action != "":
            lines.append(f'\t\taction: {encode_value_as_string(action)}')

        if memo and memo != "":
            lines.append(f'\t\tmemo:{encode_value_as_string(memo)}')

        # Q-014: orphan-lot reconstruction KVP. When this split is on
        # the AR/AP side of an unposted/orphan payment lot (lot exists,
        # is owner-attached, but has no invoice), emit the owner so the
        # importer can re-create the orphan lot — that's what makes the
        # GnuCash 5.x txn-type heuristic return 'P' on the restored book
        # (the heuristic is "AR/AP split's lot has an invoice OR an
        # owner"; the second arm covers our case).
        import ctypes as _ctypes

        from infrastructure.gnucash.engine import load_gnc_engine as _load
        _lib = _load()
        try:
            _lib.xaccSplitGetLot.argtypes = [_ctypes.c_void_p]
            _lib.xaccSplitGetLot.restype = _ctypes.c_void_p
            _lib.gncInvoiceGetInvoiceFromLot.argtypes = [_ctypes.c_void_p]
            _lib.gncInvoiceGetInvoiceFromLot.restype = _ctypes.c_void_p
            _lib.gncOwnerGetOwnerFromLot.argtypes = [_ctypes.c_void_p, _ctypes.c_void_p]
            _lib.gncOwnerGetOwnerFromLot.restype = _ctypes.c_int
            _lib.gncOwnerGetID.argtypes = [_ctypes.c_void_p]
            _lib.gncOwnerGetID.restype = _ctypes.c_char_p
            _lib.gncOwnerGetType.argtypes = [_ctypes.c_void_p]
            _lib.gncOwnerGetType.restype = _ctypes.c_int
            _lot_ptr = _lib.xaccSplitGetLot(int(split.instance))
            # Q-035: not for a settlement an unpost loosened. `lot_owner:` is
            # how a file says "this split is an owner's credit, put it in a lot
            # of theirs", and restoring one into a fresh book does exactly
            # that. A bank paid this money, so writing the line would rebuild
            # it as a credit somewhere else — listed as spendable, acceptable
            # to a `from_credit:` block, and stripped of its basis by a bare
            # `txn_guid:` retarget. The mark itself cannot travel in a file
            # (a file may not assert it), so the fix is to stop the file
            # asserting the thing the mark contradicts.
            #
            # What the split becomes on the way back is loose: in no lot, whose
            # money nothing claims to know. That is what it is — what
            # it settled is unposted, and nobody's credit has been invented.
            if _lot_ptr and not is_a_bank_paid_orphan(split):
                _inv = _lib.gncInvoiceGetInvoiceFromLot(_lot_ptr)
                if not _inv:                       # owner lot, no invoice
                    _owner_buf = _ctypes.create_string_buffer(256)
                    _owner_p = _ctypes.cast(_owner_buf, _ctypes.c_void_p).value
                    if _lib.gncOwnerGetOwnerFromLot(_lot_ptr, _owner_p) == 1:
                        _otype = _lib.gncOwnerGetType(_owner_p)
                        _oid_raw = _lib.gncOwnerGetID(_owner_p)
                        _oid = (_oid_raw.decode('utf-8', errors='replace')
                                if _oid_raw else '')
                        _kind = {2: 'customer', 4: 'vendor'}.get(_otype)
                        if _kind and _oid:
                            # Append the owner's guid (authoritative) as a third
                            # segment: `kind:id:guid`. Guarded so a build without
                            # the guid accessors still emits `kind:id`.
                            _lo = f'{_kind}:{_oid}'
                            try:
                                _lib.gncOwnerGetGUID.argtypes = [_ctypes.c_void_p]
                                _lib.gncOwnerGetGUID.restype = _ctypes.c_void_p
                                _lib.guid_to_string_buff.argtypes = [
                                    _ctypes.c_void_p, _ctypes.c_char_p]
                                _lib.guid_to_string_buff.restype = _ctypes.c_char_p
                                _gp = _lib.gncOwnerGetGUID(_owner_p)
                                if _gp:
                                    _gb = _ctypes.create_string_buffer(40)
                                    _lib.guid_to_string_buff(_gp, _gb)
                                    _g = _gb.value.decode('ascii').replace('-', '')
                                    if _g and _g != '0' * 32:
                                        _lo = f'{_kind}:{_oid}:{_g}'
                            except AttributeError:
                                pass
                            lines.append(f'\t\tlot_owner: {_lo}')
                            # And which of the owner's credits it is. An
                            # owner may hold several, so `lot_owner:` alone
                            # left the import to choose — the oldest open lot
                            # the split would reduce — and a book rebuilt
                            # from this file put a settlement on a different
                            # credit from the one it came off.
                            _lg = _lot_guid_str(_lot_ptr)
                            if _lg and _lg != '0' * 32:
                                lines.append(f'\t\tlot_guid: "{_lg}"')
        except AttributeError:
            pass

        # Emit custom split KVP metadata. Skip Q-014's `lot_owner` slot
        # for the same reason as the tx-level reserved keys above:
        # the importer stores `lot_owner:` as a custom KVP AND uses it
        # to reconstruct an orphan lot; on re-export we already emit it
        # from the live lot state via the block above.
        # Q-035: `orphaned_by_unpost` never leaves the book either. It is the
        # unpost's own note about a lot it abandoned — true of this book only,
        # and only until that record is rebuilt. Written into a file it would
        # come back as an ordinary custom key on whatever split the file lands
        # on, and a split so marked is read as *not* an owner's credit — so a
        # settlement really spent from a credit would skip taking the basis
        # off, which is the thing that note exists to get right.
        # `lot_guid` with them: it became a reserved key in this release, so
        # a book written before it may hold one as an ordinary custom slot,
        # and the slot is not dropped by the migration that handles a key
        # which has since become a field. Emitted from both, a split carried
        # two `lot_guid:` lines — the live lot's and the stale slot's, the
        # stale one last, which is the one a re-import reads. Well-formed,
        # it puts the settlement on a credit the book never named; malformed,
        # the export refuses to re-import at all.
        _q014_reserved_split = {'lot_owner', 'lot_guid', 'guid',
                                ORPHANED_BY_UNPOST_KEY}
        custom_split_meta = get_custom_metadata(split)
        for key, value in sorted(custom_split_meta.items()):
            if key in _q014_reserved_split:
                continue
            # Q-035: a cost stored on a split whose transaction prices it is a
            # copy nothing reads, and the importer refuses a file that states
            # one — so writing it out here produced an export this tool cannot
            # read back, on exactly the books `--verify-costs` tells the user
            # to correct. Dropped, like the `txn_type` NUL: the one shape that
            # needs a stored cost is a transaction with no base-currency
            # figure in it, and that one keeps it.
            if key == COST_BASIS_COST_KEY and _stored_cost_is_ignorable(split):
                continue
            # And the same rule for the guid a sale gives, for the same
            # reason. Spending an owner's credit on their next invoice ends
            # the pool a sale drew on, and the split that was the credit is
            # that record's settlement afterwards — no cost basis. The guid
            # stays on the sale, which is the book's own record of where its
            # currency came from, but written into a file it is a line the
            # import refuses: nothing in the rebuilt book can be measured
            # against a split that is no basis. So the sale exports the way a
            # sale that draws on nothing exports, which is what it now is.
            if (key == COST_BASIS_SPLIT_KEY
                    and _the_basis_it_gives_was_spent(split, value)):
                continue
            lines.append(f'\t\t{key}: {encode_value_as_string(value)}')

        # Running balance — emitted last so it reads as a post-transaction annotation
        if balance is not None:
            fraction = split_currency.get_fraction()
            decimal_places = len(str(fraction)) - 1
            balance_str = _format_fraction_as_decimal(balance, decimal_places)
            balance_ticker = get_commodity_ticker(split_currency)
            lines.append(f'\t\tbalance: "{balance_str} {balance_ticker}"')

    def execute_by_guids(self, guids: Sequence[str]) -> ExportResult:
        """
        Export one or more transactions identified by their GUIDs in one pass.

        Looks up each GUID with xaccTransLookup (O(1) per lookup), then feeds
        every transaction into a single ExportResult via _collect_transaction_data.
        Commodities and accounts are deduplicated naturally by the seen-sets in
        ExportResult — no post-hoc merging needed.

        Duplicate GUIDs in the input are silently ignored (each transaction
        appears exactly once in the result).

        Args:
            guids: sequence of 32-character hex GUID strings

        Returns:
            ExportResult containing all matched transactions plus the union of
            their commodity and account declarations

        Raises:
            ValueError: if any GUID is malformed or not found in the book
        """
        result = ExportResult()
        seen_guids = set()
        for guid in guids:
            if guid in seen_guids:
                continue
            seen_guids.add(guid)
            gnc_guid = GncGUID()
            if not string_to_guid(guid, gnc_guid):
                raise ValueError(f"Invalid GUID format: {guid}")
            raw = xaccTransLookup(gnc_guid, self.repository.book.instance)
            if raw is None:
                raise ValueError(f"No transaction found with GUID: {guid}")
            self._collect_transaction_data(Transaction(instance=raw), result)

        # A cost basis above whatever draws on it, as the whole-book export
        # states them. The guids are given in whatever order the caller typed,
        # so `export-transaction --guid <sale> --guid <basis>` wrote a ledger
        # whose opening block gives the guid of a split no block above it
        # creates — refused on the way into a fresh book.
        result.transactions = each_basis_above_what_draws_on_it(
            result.transactions)
        return result

    def execute_by_guid(self, guid: str) -> ExportResult:
        """
        Export a single transaction identified by its GUID.

        Convenience wrapper around execute_by_guids for the single-item case.

        Args:
            guid: 32-character hex GUID string of the transaction to export

        Returns:
            ExportResult containing the single transaction plus its
            commodities and accounts

        Raises:
            ValueError: if the GUID string is malformed or no transaction
                        with that GUID exists
        """
        return self.execute_by_guids([guid])

    def export_to_file(
        self,
        output_path: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        account_filter: Optional[str] = None,
        all_accounts: bool = False,
        with_balance: bool = False,
    ) -> int:
        """
        Export transactions to file.

        Args:
            output_path: Path for output file
            start_date: Optional start date
            end_date: Optional end date
            account_filter: Optional account filter
            all_accounts: If True, export all accounts even without transactions
            with_balance: If True, include running account balance per split

        Returns:
            Number of transactions exported
        """
        result = self.execute(
            start_date, end_date, account_filter, all_accounts,
            with_balance=with_balance,
        )
        plaintext = self.format_as_plaintext(result)

        # UTF-8 stated: this format is written and read as UTF-8, and taking
        # the locale's answer makes an account named `Achats — fournitures`
        # unwritable on some machines and unreadable on others.
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(plaintext)

        return len(result.transactions)
