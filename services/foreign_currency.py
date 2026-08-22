"""
Foreign-currency cost bases and their balances (Q-035).

A split that brings foreign currency into the book — an invoice's A/R split, a
bill's A/P split, currency bought or borrowed — establishes a **cost basis**:
so many units of that currency, at a stated cost in the book's own currency.
Two facts describe it:

- **the cost**, which the transaction already carries as `share_price`: on the
  split itself when the transaction is in the book's currency, or on the
  base-currency split facing it when the transaction is in the foreign one.
  Nothing is stored for it;
- **the balance of that basis**, how much of it has not yet been used. The
  `cost_basis_balance` KVP on the split is that balance: it opens at
  everything the split brought in, each sale lowers it, and giving a sale
  back — deleting it — raises it again.

The balance of a cost basis is not the balance of an account, and the two are
never interchangeable. An account balance is how much currency an account
holds right now; a cost basis's balance is how much of *one split's* currency,
at *that split's* cost, has not yet been sold. A USD invoice paid into a USD
bank leaves the bank holding the money while the A/R split remains the cost
basis that money carries, and one bank account can hold currency belonging to
several cost bases at different costs.

Selling foreign currency picks a cost basis: the sale's foreign-currency split
names the basis split with `cost_basis_split_guid`, and its own amount is how
much of that basis the sale uses. A sale measured against two bases is written
as two foreign-currency splits, one naming each. A sale cannot pick more from a
basis than that basis has left.

**A basis is lowered only by something that names it.** Currency can leave an
account without naming one — a bank fee taken in the foreign currency, a
payment block whose bank split GnuCash writes, an ordinary transfer — and
nothing draws the basis down for it. So what `fx-balances` reports is what the
book *acquired and has not sold against*, which is a different figure from what
the accounts hold, and it can be the larger of the two. Measured: an account
that received 60.00 USD and paid an 8.00 USD fee out of the same transaction
holds 52.00 and offers 60.00, and that book is correct by every rule here.

The consequence is worth stating plainly, because it is not obvious and it is
reachable by ordering alone: settle a bill out of a foreign account whose cost
bases have nothing left, then settle an invoice into the same account, and the
account nets to zero while the arriving side opens its full amount. A later
sale naming that basis is then accepted, and takes money the account does not
hold. `_refuse_a_payment_block_spending_a_cost_basis_balance` closes the door
the other way round — a payment block cannot spend a cost basis balance — but
no check at the moment cash leaves can see this one, because the outgoing
payment came first, out of an account whose bases were empty.

Nothing here treats that as an error, because "an account may not offer more
than it holds" is not an invariant this model keeps: the fee case above breaks
it legitimately, and a check on it would report ordinary books. Making the two
agree means deciding what an outflow that names no basis does to the bases on
its account, which is a change to the model rather than a fix to it.
"""

from __future__ import annotations

import traceback
from fractions import Fraction
from typing import Dict, Iterator, List, Optional

import gnucash.gnucash_core_c as _gc
from gnucash import GncLot
from gnucash.gnucash_core_c import (
    ACCT_TYPE_ASSET,
    ACCT_TYPE_BANK,
    ACCT_TYPE_CASH,
    ACCT_TYPE_CREDIT,
    ACCT_TYPE_LIABILITY,
    ACCT_TYPE_MUTUAL,
    ACCT_TYPE_PAYABLE,
    ACCT_TYPE_RECEIVABLE,
    ACCT_TYPE_STOCK,
)

from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata
from infrastructure.gnucash.utils import (
    exact_text,
    get_account_full_name,
    is_power_of_ten,
    money_text,
    numeric_to_fraction,
    to_money,
)

# The currency the book reports in. Hardcoded tool-wide (see `services/fx_rates.py`,
# which quotes every rate in CAD).
BASE_CURRENCY = 'CAD'

# KVP on a foreign-currency split: how much of the cost basis it established is
# still available, in the split's own commodity. Named for the cost basis, not
# for the split's account: `balance:` on an exported split is that account's
# running balance, a different figure that this must never be read as.
COST_BASIS_BALANCE_KEY = 'cost_basis_balance'

# KVP on a sale's foreign-currency split: the guid of the split whose cost
# basis this sale picks.
COST_BASIS_SPLIT_KEY = 'cost_basis_split_guid'

# KVP on a sale's foreign-currency split: measure against a receivable that has
# not been collected yet, deliberately.
COST_BASIS_FORCE_KEY = 'cost_basis_force'

# What a unit of this split's currency cost, in the book's currency, for the
# one case where the transaction cannot say it: both sides in the same foreign
# currency. USD paid into a USD bank — an overpaid invoice, or a USD borrowing
# held in an A/P USD account — has no base-currency figure anywhere in it,
# so there is no value to divide by an amount and `share_price` describes a
# USD/USD rate of 1. The cost is real all the same, and it is written here.
# Everywhere else it stays derived: a stored cost that could have been read
# from the transaction is a second copy waiting to disagree with it.
COST_BASIS_COST_KEY = 'cost_basis_cost'

# Account types whose balance a positive amount increases (assets, receivables)
# and those a negative amount increases (liabilities, payables). Used to tell a
# split that establishes a cost basis from one that spends the currency.
#
# Stock and mutual-fund accounts are here because the type is a classification
# and the commodity is what decides: an account typed `Stock` can be
# denominated in USD, and the currency in it is held and sellable like any
# other. Securities are excluded by the namespace guard in
# `establishes_cost_basis`, which is about what the account holds — dropping
# these two types instead left a USD holding in a `Stock` account with no cost
# basis at all.
#
# Receivable and payable appear for the sign convention they state; the branch
# for those two answers before these sets are consulted.
_DEBIT_TYPES = frozenset({
    ACCT_TYPE_BANK, ACCT_TYPE_CASH, ACCT_TYPE_ASSET,
    ACCT_TYPE_STOCK, ACCT_TYPE_MUTUAL, ACCT_TYPE_RECEIVABLE,
})
_CREDIT_TYPES = frozenset({
    ACCT_TYPE_LIABILITY, ACCT_TYPE_PAYABLE, ACCT_TYPE_CREDIT,
})


def _fraction(num) -> Fraction:
    """A GncNumeric as an exact Fraction."""
    return Fraction(num.num(), num.denom())


def split_guid(split) -> str:
    return split.GetGUID().to_string().replace('-', '').lower()


def split_commodity(split) -> str:
    """The mnemonic of the commodity this split's account is denominated in.

    No null-account guard: a split without one cannot be in a book this reads.
    GnuCash 5.x drops the whole transaction while loading and 4.x and earlier
    segfault inside `qof_session_load` (CLAUDE.md §12), so the empty string it
    answered for one was a value nothing could ask for.
    """
    commodity = split.GetAccount().GetCommodity()
    return commodity.get_mnemonic() if commodity is not None else ''


def transaction_currency(transaction) -> str:
    commodity = transaction.GetCurrency()
    return commodity.get_mnemonic() if commodity is not None else ''


def iter_splits(book) -> Iterator:
    """Every split in the book, walking the account tree."""
    root = book.get_root_account()

    def walk(account):
        yield from account.GetSplitList()
        for child in account.get_children():
            yield from walk(child)

    yield from walk(root)


def cost_of(split) -> Optional[Fraction]:
    """What this split's currency cost, in the book's currency, per unit.

    Read from the transaction, never stored, and always from *this* split:
    its value divided by its amount, converted into the book's currency if the
    transaction is not already stated there.

    Where the transaction is stated in the book's own currency, nothing is
    pooled: each split is already valued in CAD, so its own value over its own
    amount is its cost and nothing beside it can move that. One transaction
    can bring in two currencies at once — 99.90 CAD sold for both 40.00 USD
    and 261.63 HKD — and each has its own cost, 1.35 CAD/USD and 1/5.7
    CAD/HKD; charging either with the whole CAD that left would price it as if
    it had bought everything. Nor is every base-currency split part of what
    was bought: a 2.00 CAD bank fee is an expense, and adding it in would
    report 40.00 USD as costing 1.45 rather than 1.35, overstating the cost of
    that currency for as long as the basis lives.

    Where the transaction is stated in the *foreign* currency, this split's
    own value is in that currency too, and the rate has to come from the
    base-currency splits — pooled across all of them (see
    `_base_per_unit_of`), because each is rounded on its own and reading
    whichever comes first makes the cost depend on split order. A CAD line
    converted at a different rate from its neighbours does move the result
    there; that is the aggregate of what the transaction did, and the fee
    belongs in its own transaction if it should not be part of it.

    A cost written on the split is consulted **last**, for the one shape whose
    transaction states none: every split in one foreign currency, with no
    base-currency figure to divide. Read first, it outranked the ledger — a
    split that paid 135.00 CAD for 100.00 USD reported whatever its KVP said,
    9.99 CAD/USD, and `fx-balances`, every realized gain and the cost every
    later sale must be valued at followed the copy rather than the money. A
    copy can be stale, hand-edited, or left behind by a correction; the
    transaction is what the book is.
    """
    derived = derived_cost_of(split)
    if derived is not None:
        return derived
    return stated_cost_of(split)


def derived_cost_of(split) -> Optional[Fraction]:
    """What the transaction itself says this split's currency cost, or None.

    None when it says nothing: a split with no amount to divide by, or a
    transaction in the record's own currency with no base-currency figure
    anywhere in it. A zero cost is None as well — 100.00 USD stated as worth
    nothing prices no currency, and a cross-currency posting GnuCash wrote with
    amount 0 is exactly that shape.
    """
    amount = _fraction(split.GetAmount())
    if amount == 0:
        return None
    transaction = split.GetParent()
    if transaction is None:
        return None
    tx_currency = transaction_currency(transaction)

    # `share_price` is value per unit, stated in the transaction's currency.
    per_unit = abs(_fraction(split.GetValue()) / amount)
    if tx_currency != BASE_CURRENCY:
        base_per_tx_currency = _base_per_unit_of(transaction, tx_currency)
        if base_per_tx_currency is None:
            return None
        per_unit *= base_per_tx_currency
    return per_unit or None


def _base_per_unit_of(transaction, tx_currency: str) -> Optional[Fraction]:
    """What one unit of the transaction's currency is worth in the book's.

    Taken from the splits on base-currency accounts, whose amount over value
    is that same rate the other way up — all of them together, as one sum over
    another, not whichever happens to be first.

    They are all converted at the one rate the transaction was entered at, but
    each is rounded to the cent on its own, so individually they disagree in
    the last digit: a taxed USD invoice at 1.4 books 46.66 CAD against 33.33
    USD and 4.66 against 3.33, which are 1.40006 and 1.39940. Reading one
    split answered with whichever of those it reached first — the tax line, on
    a book where the tax is listed before the income — and priced the whole
    basis at 1.3994. Summing cancels most of the rounding and cannot depend on
    order: 51.32 over 36.66 is 2566/1833, or 1.39989.

    Every base-currency split counts rather than some chosen subset. Where the
    transaction did convert at one rate — the ordinary case — a fee split
    changes the numerator and denominator together and cannot move the answer.
    Where its splits were converted at different rates, as
    `fx_two_base_splits_at_different_rates.txt` is, the fee does move it: a
    fee at 1.25 beside revenue at 1.4 pools to 25/18, or 1.3889. That is the
    aggregate of what the transaction actually did, which is the most any
    single figure can be for such a book, and it is the same figure however
    the splits are ordered. Choosing one split instead would answer with
    whichever came first.
    """
    if tx_currency == BASE_CURRENCY:
        return Fraction(1)
    base_total = Fraction(0)
    value_total = Fraction(0)
    for other in transaction.GetSplitList():
        if split_commodity(other) != BASE_CURRENCY:
            continue
        base_amount = _fraction(other.GetAmount())
        tx_value = _fraction(other.GetValue())
        if base_amount == 0 or tx_value == 0:
            continue
        base_total += abs(base_amount)
        value_total += abs(tx_value)
    if value_total == 0:
        return None
    return base_total / value_total


def cost_basis_guid_of(split) -> str:
    """The guid of the split whose cost basis this split picks, or ''."""
    value = get_custom_metadata(split).get(COST_BASIS_SPLIT_KEY, '')
    return str(value).replace('-', '').lower() if value else ''


def establishes_cost_basis(split) -> bool:
    """True when this split brings foreign currency into the book at a cost.

    An invoice's A/R split and currency bought or borrowed raise a debit-side
    balance; a bill's A/P split raises a credit-side one. Either way the book
    now carries that many units at a stated cost. A split that spends foreign
    currency establishes nothing, and neither does a split that picks another's
    cost basis — that one is the use, not the source.

    Currency only: shares are counted in units and priced, not converted, so a
    security establishes nothing however its account is typed. And a business
    account moved against its normal direction counts only when it is a
    prepayment — a lot with no invoice or bill against it — since the same shape is
    otherwise a settlement, money that has already gone.

    A business account can be raised on either side, but only one of them
    unconditionally. Its normal direction — a debit on a receivable, a credit
    on a payable — is what the record owes and always establishes a basis.
    The opposite direction is a prepayment *or* a settlement, which look
    identical as figures: a 200 USD payment against a 100 USD invoice leaves
    two A/R credits, one settling the invoice and one the customer's money
    held and owed back. Only the second is currency the book still has, and
    what separates them is the lot — a settlement belongs to the invoice it
    settles, a prepayment to nothing yet — so that side is gated on
    `_is_prepayment`. Counting only the normal direction opened a basis for
    100 USD of the 200 the bank held; counting both offered currency already
    sent.
    """
    commodity = split_commodity(split)
    if not commodity or commodity == BASE_CURRENCY:
        return False
    # Currency only. Shares are not foreign currency: they are counted in
    # units, priced rather than converted, and a book holding them has no FX
    # question to answer. Testing "not the book's currency" alone swept them
    # in — a plain stock purchase in a single-currency book grew a cost-basis
    # KVP, listed in `fx-balances` as `50 CAD/USTECH`, and could no longer be
    # corrected with `--strategy update`.
    # No null-account guard, for the reason `split_commodity` gives: a split
    # without an account cannot be in a book this reads at all — GnuCash 5.x
    # drops the whole transaction while loading and 4.x segfaults inside
    # `qof_session_load` (CLAUDE.md §12).
    account = split.GetAccount()
    if account.GetCommodity().get_namespace() != 'CURRENCY':
        return False
    if cost_basis_guid_of(split):
        return False
    if split.GetParent() is None:
        return False

    amount = _fraction(split.GetAmount())
    if amount == 0:
        return False
    # Which way the split moves is asked before what it cost, because reading
    # the cost can raise — a `cost_basis_cost` that does not parse is refused
    # rather than ignored — and a split that establishes nothing has no cost
    # worth refusing over. Asked first, a spend carrying such a line was
    # reported as an unreadable cost basis, listing and all.
    if not _raises_a_foreign_balance(split, account, amount):
        return False
    return cost_of(split) is not None


def _raises_a_foreign_balance(split, account, amount: Fraction) -> bool:
    """Whether this split's direction is one that brings currency in."""
    account_type = account.GetType()
    if account_type in (ACCT_TYPE_RECEIVABLE, ACCT_TYPE_PAYABLE):
        raises_the_balance = (amount > 0 if account_type == ACCT_TYPE_RECEIVABLE
                              else amount < 0)
        if not raises_the_balance:
            # The other side of a business account is currency held only when
            # it is a prepayment — a customer's overpayment, or one made to a
            # vendor — which sits in a lot of its own with no invoice or bill
            # against it. The same shape is otherwise a settlement: money that has
            # gone, which would open a basis for currency the book no longer
            # has.
            #
            # And only when nothing else in the transaction already brought
            # that currency in. A prepayment paid into a foreign bank writes
            # two splits for one lump of money: the bank holds it, and this
            # credit says it is owed back. Counting both listed 100.00 USD
            # twice and offered 200.00 for sale from a bank holding 100.
            return _is_prepayment(split) and not _currency_arrived_elsewhere(split)
        # The normal direction — what a customer owes on a receivable, what is
        # owed to a vendor on a payable — but not everything shaped like it.
        # A refund is a debit on a receivable too, and it sends the customer's
        # money back rather than bringing any in. The lot separates them: a
        # posting sits in the lot its own invoice owns, while a refund
        # settles an owner lot no invoice owns, exactly as on the opposite
        # side. Returning True for the shape alone offered a third 100.00 USD
        # for a prepayment that had already been refunded.
        return not _is_prepayment(split)
    if account_type in _CREDIT_TYPES:
        return amount < 0
    if account_type in _DEBIT_TYPES:
        return amount > 0
    return False


def _currency_arrived_elsewhere(split) -> bool:
    """Whether another split in this transaction already brings this currency
    in, at a cost of its own.

    Asked only of a business account moved against its normal direction, where
    the split records an obligation rather than a holding: a customer's
    overpayment paid into a USD bank is one lump of money written twice, and
    the account that took it is where it can be sold from. Where the money
    arrives converted, or in the record's own currency — a USD invoice overpaid
    from a USD bank, whose splits carry no base-currency figure and so no cost
    — nothing else brings it in, and this credit carries the basis.

    Business accounts are not consulted: the settling split beside an
    overpayment is on the same receivable, and is the invoice's money, not a
    second arrival. That also keeps this from asking about a split whose own
    answer would ask back.
    """
    transaction = split.GetParent()
    if transaction is None:
        return False
    commodity = split_commodity(split)
    this_one = split_guid(split)
    for other in transaction.GetSplitList():
        if split_guid(other) == this_one:
            continue
        if split_commodity(other) != commodity:
            continue
        account = other.GetAccount()
        if account is None:
            continue
        if account.GetType() in (ACCT_TYPE_RECEIVABLE, ACCT_TYPE_PAYABLE):
            continue
        # Which direction counts as an arrival is the account type's business,
        # and `establishes_cost_basis` already answers it: a positive amount
        # on a bank, a negative one on a credit line, whose balance rises as
        # it goes down. Filtering on the sign here first meant currency drawn
        # on a USD credit line was never seen to arrive, so a vendor
        # prepayment funded by it opened a second basis for the same lump.
        if establishes_cost_basis(other):
            return True
    return False


def _is_prepayment(split) -> bool:
    """Whether this split sits in a lot no invoice or bill owns.

    That is what tells a prepayment from a settlement: both move a business
    account against its normal direction, but a settlement belongs to the
    record it settles, and a prepayment belongs to nothing yet.

    Except where an unpost is what took that record away. That leaves a live
    lot naming nothing — the same three facts a prepayment has — and
    reading it as one had the FX layer offer an orphaned settlement as currency
    the book holds, listed as a basis at the rate of the day it settled, while
    every settlement path refused to call the same split a credit. Measured on
    a USD receivable paid out of a CAD bank: after `unpost-invoices` the orphan
    appeared as a 100.00 USD basis at 1.37, currency that had gone out rather
    than come in.

    Imported here rather than at the top: `gnucash_importer` reads this module
    for the cost-basis keys, so the other direction has to stay lazy.
    """
    from services.gnucash_importer import is_a_bank_paid_orphan
    if is_a_bank_paid_orphan(split):
        return False
    raw_lot = split.GetLot()
    if raw_lot is None:
        return False
    instance = raw_lot.instance if hasattr(raw_lot, 'instance') else raw_lot
    # Not wrapped in a catch-all: if the binding rejects this pointer on some
    # platform, that must surface. Swallowing it would turn every prepayment
    # into "not a basis" and under-report held currency with no error at all.
    return not _gc.gncInvoiceGetInvoiceFromLot(instance)


def cost_basis_balance_of(split) -> Optional[Fraction]:
    """What this cost basis has left, or None when no balance is recorded.

    The KVP is the record of it: a basis opens with everything it brought in,
    each sale lowers it, and giving a sale back — deleting it — raises it
    again.

    A split carrying no KVP has no balance recorded, which is not the same as
    having nothing left. Its balance was never written by this tool — the
    split may have been created in the GnuCash GUI, or predate this feature —
    and sales may already have been measured against it that nothing wrote
    down. Reading the split's amount as its balance would re-open currency
    that is possibly long gone. Stating `cost_basis_balance:` on the split in
    an import file is how a balance is given to one.
    """
    raw = _stored_cost_basis_balance(split)
    if raw is None or raw == '':
        return None
    try:
        return Fraction(str(raw))
    except (ValueError, ZeroDivisionError):
        # A balance that cannot be read is not a balance, so this basis has
        # none for every purpose that needs a number — refused as a sale's
        # basis, left out of the totals. It is not the *same* as never having
        # had one, though, and `verify_cost_bases` says so through
        # `malformed_cost_basis_balance_of`.
        return None


def malformed_cost_basis_balance_of(split) -> str:
    """The text of a balance KVP that will not parse, or `''`.

    Split from `cost_basis_balance_of` because the two answer different
    questions: what the basis has left (nothing, since no figure reads) and
    whether something is wrong (yes, and here it is).
    """
    raw = _stored_cost_basis_balance(split)
    if raw is None or str(raw) == '':
        return ''
    try:
        Fraction(str(raw))
    except (ValueError, ZeroDivisionError):
        return str(raw)
    return ''


def stated_cost_of(split) -> Optional[Fraction]:
    """The cost written on a split, or None when it carries none.

    Written with its direction — `1.4 CAD/USD`, base currency over the split's
    own — and refused without it. A bare `1.4` reads either way round, and the
    two readings are a factor of two apart at that rate: the same number that
    prices 100 USD at 140.00 CAD prices it at 71.43 if taken the other way. The
    listing states the direction for exactly this reason, and what a file
    states has to be as unambiguous as what it shows.
    """
    raw = get_custom_metadata(split).get(COST_BASIS_COST_KEY)
    if raw is None or str(raw).strip() == '':
        return None
    return parse_stated_cost(raw, split_commodity(split),
                             f'split {split_guid(split)}')


def parse_stated_cost(raw, currency: str, where: str) -> Fraction:
    """A stated cost, checked the one way.

    Both the file being read and the file being written go through here: an
    update is checked before anything is committed, and the same text is read
    back afterwards, where a refusal could no longer undo the edit. A second,
    looser check in front of this one let three of its four refusals through —
    a wrong direction, a non-number, a negative — and each landed a
    half-committed transaction.
    """
    text = str(raw).strip()
    parts = text.split()
    expected = f'{BASE_CURRENCY}/{currency}'
    if len(parts) != 2:
        raise Exception(
            f'{COST_BASIS_COST_KEY} on {where} reads '
            f'{text!r} — state which way round it goes, as in '
            f'`{COST_BASIS_COST_KEY}: "1.4 {expected}"`')
    figure, direction = parts
    if direction != expected:
        raise Exception(
            f'{COST_BASIS_COST_KEY} on {where} is stated in '
            f'{direction}, but that split holds {currency} and the book counts '
            f'in {BASE_CURRENCY} — state it as {expected}')
    try:
        cost = Fraction(figure)
    except (ValueError, ZeroDivisionError) as exc:
        raise Exception(
            f'{COST_BASIS_COST_KEY} on {where} is not a '
            f'number: {figure!r}') from exc
    if cost <= 0:
        raise Exception(
            f'{COST_BASIS_COST_KEY} on {where} must be '
            f'positive, got {figure}')
    return cost


def smallest_unit(split) -> int:
    """How finely the split's own currency divides: 100 for CAD, 1 for JPY.

    GnuCash keeps this on the commodity, which is the only place it can be
    read from — a yen has no hundredths, so an amount written 103.00 is not a
    yen amount at all.
    """
    account = split.GetAccount()
    commodity = account.GetCommodity() if account is not None else None
    return commodity.get_fraction() if commodity is not None else 1


def _format(value: Fraction, unit: int) -> str:
    """An amount as text at its own currency's decimals — 60.00 CAD, 103 JPY.

    Exact throughout: the figure reaches its currency's smallest unit through
    GnuCash's own conversion, and an amount that unit cannot express is written
    as the fraction it is rather than quietly rounded to something the currency
    can hold.
    """
    if not is_power_of_ten(unit) or (value * unit).denominator != 1:
        return str(value)
    return money_text(value, unit)




def write_cost_basis_balance(split, available: Fraction) -> None:
    """Record a split's basis balance in its KVP, keeping its other keys.

    The pre-rename key goes when the current one is written. Every *read*
    accepts either name, so a book from the shipped release keeps its
    balances — but a split carrying both would hold two figures that disagree,
    and which one answered would depend on which code path asked. The importer
    reads this metadata directly in a dozen places, so that is a dozen chances
    to read the pair the wrong way round; a split that never holds both cannot
    be read two ways.

    It also migrates a book by using it: any basis this tool writes comes out
    carrying one key, and the ones it has not touched still read correctly.
    """
    metadata = dict(get_custom_metadata(split))
    metadata.pop(LEGACY_COST_BASIS_BALANCE_KEY, None)
    metadata[COST_BASIS_BALANCE_KEY] = _format(available, smallest_unit(split))
    transaction = split.GetParent()
    reopen = transaction is not None and not transaction.IsOpen()
    if reopen:
        transaction.BeginEdit()
    set_custom_metadata(split, metadata)
    if reopen:
        transaction.CommitEdit()


# Guids of cost bases whose basis balance the file being imported stated
# outright. Such a balance is authoritative and already net of every sale in
# that file — an export carries `cost_basis_balance: "60.00"` on a basis
# alongside the 40 USD sale that lowered it, and applying the sale again would
# leave 20. Reset at the start of each import.
_stated_in_file = set()


def begin_import_run() -> None:
    """Forget which balances the previous file stated."""
    _stated_in_file.clear()


def note_stated_balance(split) -> None:
    """This basis arrived with its balance already written in the file."""
    _stated_in_file.add(split_guid(split))


def balance_came_from_file(split) -> bool:
    return split_guid(split) in _stated_in_file


def open_cost_basis_balance(split) -> Fraction:
    """Open a cost basis: none of what it brought in has been charged against
    yet, so all of it is still there to measure a disposal against."""
    opening = abs(_fraction(split.GetAmount()))
    write_cost_basis_balance(split, opening)
    return opening


def total_cost_basis_balance_in(account) -> Fraction:
    """What the book still offers for sale out of one account.

    The sum across that account's cost bases of what each has left. A basis
    with no balance recorded counts for nothing: its balance was never
    written, so there is no number to add — which is what a `None` from
    `cost_basis_balance_of` means, and the same answer `fx-balances` gives by
    leaving those out of its totals.

    That leaves a hole, and it is the same one the module docstring records
    for a bank fee: an account whose bases were all made in the GnuCash GUI
    offers nothing here, so a payment block spending it is not refused. What
    the guard catches is an account this tool has been keeping the balances
    of, which is every account it wrote.

    Asked before a settlement spends foreign cash, to tell an account whose
    bases still have something left (where the disposal has to be measured
    against a named basis) from one whose bases are spent.

    Reads the account's own splits rather than walking the book. Every other
    caller of `iter_splits` is a one-shot command; this one is asked once per
    payment block with a foreign bank, and `GetSplitList()` builds a fresh
    wrapper for every split it returns — so walking the tree here would cost
    the whole book once per payment to answer a question about one account.

    Not memoised, though it is asked once per payment block and the answer
    rarely changes between two of them: importing *n* payments against an
    account of *m* splits costs n·m KVP reads. Deliberately, because the
    answer does change — a settlement into a foreign bank opens a basis and a
    disposal lowers one — and while every *write* goes through
    `write_cost_basis_balance`, a removal does not: `_strip_a_settlements_
    basis` and the applied-credit paths replace a split's whole slot frame. A
    memo would need clearing at each of those, and the one that was missed
    would refuse a payment the book can afford or allow one it cannot. That is
    a bad trade against a walk of one account, and there is no measurement
    saying the walk hurts.
    """
    total = Fraction(0)
    # No currency argument and no per-split commodity test: every split here
    # is on `account`, so every one is denominated in that account's own
    # commodity. The test was the same answer each time round, and never the
    # skipping one.
    for split in account.GetSplitList():
        try:
            if not establishes_cost_basis(split):
                continue
            balance = cost_basis_balance_of(split)
        except Exception:
            # A basis this cannot read is not a figure anyone can measure
            # against, and `fx-balances` already lists it as malformed.
            # Adding it here would refuse a settlement over a number nothing
            # can state, with no way for the reader to get out of it.
            continue
        if balance is not None:
            total += balance
    return total


def lower_cost_basis_balance(split, amount: Fraction) -> Fraction:
    """Charge `amount` against a cost basis and record what is left."""
    current = cost_basis_balance_of(split)
    if current is None:
        raise Exception(
            f'cost basis {split_guid(split)} has no balance recorded')
    remaining = current - amount
    write_cost_basis_balance(split, remaining)
    return remaining


def raise_cost_basis_balance(split, amount: Fraction) -> Fraction:
    """Give `amount` back to a cost basis — a sale measured against it is gone.

    Capped at what the basis brought in, so it can never come to hold more
    than the currency the split actually carried.
    """
    if open_cost_basis_balance_if_none_is_stored(split) is not None:
        return cost_basis_balance_of(split) or Fraction(0)
    current = cost_basis_balance_of(split)
    if current is None:
        # A figure is stored and will not parse. Opening the basis at its full
        # amount would re-open currency that may have been sold and destroy
        # the text `--verify-costs` exists to report — the same reading
        # `_carry_basis_to_residue` refuses. Leave it as it is; the fault is
        # reported, and correcting the figure is what unblocks it.
        return Fraction(0)
    restored = min(current + amount, abs(_fraction(split.GetAmount())))
    write_cost_basis_balance(split, restored)
    return restored


#: What the balance key was called before it was renamed. Books on disk carry
#: it, and no save rewrites a key by itself, so every read goes through
#: `_stored_cost_basis_balance` rather than the current name alone.
LEGACY_COST_BASIS_BALANCE_KEY = 'cost_basis_available'


def _stored_cost_basis_balance(split):
    """The stored balance text, under either name it has been kept under.

    Read only under the current name, every basis in a book written before the
    rename looked like one no balance was ever written for — and that is the
    branch that *writes*: giving a sale back opens such a basis at everything
    it brought in. A book with 80.00 of 100.00 already sold would have been
    reset to 100.00 by deleting one of those sales, offering currency it had
    sold, with nothing able to notice: 100.00 is not above what the basis
    acquired, and the old key is read by nothing else.

    The current name wins where a split somehow carries both.
    """
    held = get_custom_metadata(split)
    raw = held.get(COST_BASIS_BALANCE_KEY)
    if raw is None or raw == '':
        return held.get(LEGACY_COST_BASIS_BALANCE_KEY)
    return raw


def cost_basis_metadata(split) -> Dict:
    """A split's custom keys, with the balance under its current name.

    For the readers that work on the metadata dict rather than asking for the
    balance — carrying a basis across an applied credit, dividing one,
    stripping a settlement's. Each tests the key by name, so on a book from
    before the rename each would answer as though the split had no balance:
    the applied part keeping the old figure while the carved remainder got
    none, which is the Q-035 defect — the 60.00 a customer had left accounted
    for by no basis at all — coming back for those books.

    Normalised on the way out rather than at each site, because there are a
    dozen sites and the one that is missed is the one that matters.
    """
    held = dict(get_custom_metadata(split))
    legacy = held.pop(LEGACY_COST_BASIS_BALANCE_KEY, None)
    if legacy is not None and not held.get(COST_BASIS_BALANCE_KEY):
        held[COST_BASIS_BALANCE_KEY] = legacy
    return held


def has_a_stored_cost_basis_balance(split) -> bool:
    """Whether a figure has been written on this basis, whatever it says.

    Distinct from what the basis has left. This asks about the book's record,
    and the callers that need it are the ones deciding whether to write.
    """
    raw = _stored_cost_basis_balance(split)
    return raw is not None and raw != ''


def open_cost_basis_balance_if_none_is_stored(split):
    """Open this basis's balance, unless the book already records one.

    The one place that decision is made. Four callers needed it — opening a
    transaction's bases, opening a borrowed one, opening what an edit turned
    into a basis, and giving a sale back — and each asked it themselves, which
    is how three of them came to ask it the new way and the fourth kept the
    old one. Asked in four places it can be answered three ways; asked here it
    cannot.

    Never a second time, and that is the whole point: a basis already carrying
    a figure has had disposals charged against it, and opening it again would
    put that currency back. A figure that will not parse counts as stored —
    something wrote it, and overwriting it would destroy what `--verify-costs`
    reports.

    Returns the opening balance when it opened one, or None when it left a
    stored figure alone.
    """
    if has_a_stored_cost_basis_balance(split):
        return None
    return open_cost_basis_balance(split)


def record_cost_bases(book, transaction) -> None:
    """Open every cost basis this transaction establishes: nothing has been
    charged against it yet, so all of what it brought in is still there."""
    for split in transaction.GetSplitList():
        if not establishes_cost_basis(split):
            continue
        open_cost_basis_balance_if_none_is_stored(split)


def record_borrowed_basis(split, cost: Fraction) -> None:
    """Open a basis for currency the book now holds and owes back, at a cost
    its own transaction cannot state.

    An overpaid invoice settled in its own currency is the case: 200.00 USD
    against a 100.00 USD invoice leaves the customer's money in the bank and a
    credit balance on the receivable, with no base-currency figure anywhere in
    that payment to price it by. The cost is the one the record was carried
    at, written on the split so it reads back like any other. Counting only
    the settling split opened a basis for 100.00 USD of the 200.00 the bank
    holds, and a sale of the rest was refused for exceeding a basis that was
    never opened.
    """
    if has_a_stored_cost_basis_balance(split):
        return
    if cost_of(split) is not None:
        # The transaction already says what it cost: a converting payment
        # values this credit at the rate it was received at. Writing a cost
        # beside it would state a second, different one — the record's — on a
        # split whose own figures contradict it.
        open_cost_basis_balance(split)
        return
    currency = split_commodity(split)

    # The cost that is stored is the one the money actually carries, not the
    # rate it was quoted at — the same way `share_price` comes back as the
    # value over the amount. 45.00 USD at 1.405 is 63.225 CAD, which reaches
    # the cent as 63.23, so the cost is 6323/4500 (1.405 + 1/9000). Storing
    # the quoted rate instead would price this basis at something no CAD
    # figure in the book equals, and every gain measured against it would be
    # out by the difference.
    units = abs(_fraction(split.GetAmount()))
    effective = cost
    if units != 0:
        account = split.GetAccount()
        book = account.get_book() if account is not None else None
        base = (book.get_table().lookup('CURRENCY', BASE_CURRENCY)
                if book is not None else None)
        if base is not None:
            base_value = numeric_to_fraction(to_money(units * cost, base.get_fraction()))
            effective = base_value / units

    metadata = dict(get_custom_metadata(split))
    metadata[COST_BASIS_COST_KEY] = f'{exact_text(effective)} {BASE_CURRENCY}/{currency}'
    transaction = split.GetParent()
    reopen = transaction is not None and not transaction.IsOpen()
    if reopen:
        transaction.BeginEdit()
    set_custom_metadata(split, metadata)
    if reopen:
        transaction.CommitEdit()
    open_cost_basis_balance(split)


def amounts_by_cost_basis(transaction) -> Dict[str, Fraction]:
    """How much this transaction takes from each cost basis it names.

    Read before the transaction is deleted, so the amounts can be given back
    afterwards — undoing a sale is how a user corrects one, and the balance has
    to follow it.
    """
    taken: Dict[str, Fraction] = {}
    for split in transaction.GetSplitList():
        guid = cost_basis_guid_of(split)
        if not guid:
            continue
        taken[guid] = taken.get(guid, Fraction(0)) + abs(_fraction(split.GetAmount()))
    return taken


def give_back_to_cost_bases(book, taken: Dict[str, Fraction]) -> None:
    """Raise each named basis's basis balance by what was taken from it."""
    for guid, amount in taken.items():
        basis = find_split_by_guid(book, guid)
        if basis is not None:
            raise_cost_basis_balance(basis, amount)


def find_split_by_guid(book, guid: str):
    """The split with this guid, or None."""
    wanted = guid.replace('-', '').lower()
    for split in iter_splits(book):
        if split_guid(split) == wanted:
            return split
    return None


def apply_cost_basis_picks(book, transaction) -> Dict[str, Fraction]:
    """Check everything this transaction picks, then lower those balances.

    Every check runs before any balance is written, so a sale that is refused
    leaves no basis half-lowered.

    Returns what was taken, keyed by basis guid, because the transaction can
    still be refused after this — everything read from it afterwards is
    checked too — and a drawdown that outlives its transaction is currency the
    book can no longer sell and no longer accounts for. The caller destroys
    the transaction and gives this back together (`give_back_to_cost_bases`).

    Amounts are summed per basis first: two splits naming the same basis for 60
    USD each pass individually against a 100 USD balance but together exceed
    it, so it is the total that is checked.
    """
    wanted: Dict[str, Fraction] = {}
    for split in transaction.GetSplitList():
        basis_guid = cost_basis_guid_of(split)
        if not basis_guid:
            continue
        basis = _validate_pick(book, split, basis_guid)
        if basis is None:                     # stated in the file; already net
            continue
        wanted[basis_guid] = wanted.get(basis_guid, Fraction(0)) + abs(
            _fraction(split.GetAmount()))

    checked = []
    for basis_guid, total in wanted.items():
        basis = find_split_by_guid(book, basis_guid)
        available = cost_basis_balance_of(basis)
        currency = split_commodity(basis)
        if available is None:
            raise Exception(
                f'cost basis {basis_guid} has no balance recorded — the split '
                f'was not written by this tool, so how much of its {currency} '
                f'is still unsold is not known and cannot be assumed to be all '
                f'of it. State `{COST_BASIS_BALANCE_KEY}:` on that split in an '
                f'import file to give it a balance.')
        if total > available:
            held = abs(_fraction(basis.GetAmount()))
            unit = smallest_unit(basis)
            raise Exception(
                f'{_format(total, unit)} {currency} against cost basis {basis_guid} '
                f'exceeds its basis balance by '
                f'{_format(total - available, unit)} {currency} (the basis brought '
                f'in {_format(held, unit)} {currency} and has '
                f'{_format(available, unit)} left)')
        checked.append((basis, total))

    # Lowering more than one basis is not atomic by itself, so it is made so
    # here: a failure part-way through gives back what this call already took
    # before it re-raises. Reporting the drawdown only on the way out would
    # hand the caller an empty dict for the very case it exists to undo.
    taken: Dict[str, Fraction] = {}
    try:
        for basis, total in checked:
            lower_cost_basis_balance(basis, total)
            taken[split_guid(basis)] = total
    except Exception:
        give_back_to_cost_bases(book, taken)
        raise
    return taken


def _validate_pick(book, selling_split, basis_guid: str):
    """Check one picking split, without writing anything.

    Returns the basis split, or None when the file stated that basis's balance
    — such a balance is already net of this sale and must not be lowered again.

    Raises when the basis cannot be found, is in another currency, is not a
    cost basis at all, has not been collected, or is valued at the wrong cost.
    """
    basis = find_split_by_guid(book, basis_guid)
    if basis is None:
        raise Exception(
            f'{COST_BASIS_SPLIT_KEY} {basis_guid!r} matches no split in the book')

    selling_currency = split_commodity(selling_split)
    basis_currency = split_commodity(basis)
    if selling_currency != basis_currency:
        raise Exception(
            f'{COST_BASIS_SPLIT_KEY} {basis_guid!r} is a {basis_currency} split '
            f'but this split sells {selling_currency}')

    if not establishes_cost_basis(basis):
        raise Exception(
            f'{COST_BASIS_SPLIT_KEY} {basis_guid!r} names a split that is no '
            f'{basis_currency} cost basis — a basis is a split that brought '
            f'{basis_currency} into the book (an invoice, a bill, a purchase or '
            f'a borrowing)')

    _require_basis_collected(selling_split, basis, basis_guid)
    _require_stated_cost(selling_split, basis, basis_guid)

    # The file stated this basis's balance, so it already accounts for this
    # sale — re-importing an export must not lower it a second time.
    if balance_came_from_file(basis):
        return None
    return basis


def _require_basis_collected(selling_split, basis, basis_guid: str) -> None:
    """A receivable that has not been collected holds no currency to sell.

    An invoice's A/R split states currency the customer owes, not currency the
    book has. Selling against it before the invoice is paid is selling money
    that has not arrived — this tool keeps books, it does not support trading a
    position it does not hold. The lot is the test: it closes when the record
    is settled.

    A payable is not restricted. Its lot is open precisely until the bill is
    paid, and settling it with foreign cash is the ordinary way that happens.

    `cost_basis_force: true` on the selling split overrides it, for the case
    where the user knows the money is in hand and the record simply has not
    been marked paid yet.

    It is read first, before any of the reasons below to return early. Read
    where it is *used*, a mistyped one on a split this function lets past —
    a settled lot, a payable, an overpayment — was never looked at, so the
    same typo was named on one sale and ignored on the next. A flag a file
    states is read wherever the file states it.
    """
    # Read as a word, like every other flag a ledger carries: compared
    # against a list of the truthy spellings, `cost_basis_force: treu` was
    # silently *not* forced, and the sale then failed with a message telling
    # its author to add the key they had already added.
    #
    # Imported here rather than at the top for the reason given above
    # `is_a_bank_paid_orphan`: `gnucash_importer` reads this module.
    from services.gnucash_importer import _a_yes_or_no

    forced = _a_yes_or_no(
        get_custom_metadata(selling_split).get(COST_BASIS_FORCE_KEY, 'false'),
        COST_BASIS_FORCE_KEY, 'a split')

    account = basis.GetAccount()
    if account is None or account.GetType() != ACCT_TYPE_RECEIVABLE:
        return

    # A split on the receivable itself is the collection, not a sale of what
    # has not been collected: it is the entry that settles the invoice, and
    # refusing it would forbid the very thing that makes the basis sellable.
    # Selling is a split somewhere else — a bank account paying the currency
    # out — measured against this basis.
    selling_account = selling_split.GetAccount()
    if (selling_account is not None
            and get_account_full_name(selling_account) == get_account_full_name(account)):
        return

    # A credit balance on the receivable is money already in hand — an
    # overpayment, held and owed back — so there is nothing uncollected about
    # it. Its lot stays open because the debt runs the other way now, which is
    # the opposite of an invoice waiting to be paid.
    if _fraction(basis.GetAmount()) < 0:
        return

    raw_lot = basis.GetLot()
    if raw_lot is None:
        return
    # `xaccSplitGetLot` hands back a raw pointer; a bare SwigPyObject has no
    # lot methods.
    lot = raw_lot if hasattr(raw_lot, 'get_balance') else GncLot(instance=raw_lot)
    balance = lot.get_balance()
    if Fraction(balance.num(), balance.denom()) == 0:      # settled
        return
    if forced:
        return
    currency = split_commodity(basis)
    raise Exception(
        f'cost basis {basis_guid} is an unpaid receivable — that '
        f'{currency} has not been collected, so there is none to sell. Record '
        f'the payment first, or add `{COST_BASIS_FORCE_KEY}: true` to this '
        f'split to measure against it anyway.')


def _require_stated_cost(selling_split, basis, basis_guid: str) -> None:
    """A sale must value what it sells at the cost of the basis it picks.

    That is what makes the residual split the realized gain or loss: the
    currency leaves at what it cost, the other splits state what it fetched,
    and the difference is what was made or lost on it. Valuing it at the sale
    rate instead balances the transaction with nothing left over, and the gain
    silently disappears.

    Only checked for a sale priced in the book's own currency; a transaction
    between two foreign currencies states its values in neither.
    """
    transaction = selling_split.GetParent()
    if transaction is None or transaction_currency(transaction) != BASE_CURRENCY:
        return
    basis_cost = cost_of(basis)
    if basis_cost is None:
        return
    sold = abs(_fraction(selling_split.GetAmount()))
    stated = abs(_fraction(selling_split.GetValue()))
    currency = split_commodity(selling_split)
    base_unit = transaction.GetCurrency().get_fraction()
    # Rounded the way the engine rounds before comparing, and then compared
    # exactly. `basis_cost × sold` is a rate times a quantity and lands
    # between cents; the value on the split is what GnuCash booked, which is
    # that figure rounded to the currency's smallest unit. Held apart by half
    # a cent instead — the width of one rounding — the check was an epsilon
    # standing in for arithmetic nobody had done, and it forgave a sale
    # valued half a cent off its basis on purpose as readily as one off by
    # accident.
    expected = numeric_to_fraction(to_money(basis_cost * sold, base_unit))
    if stated == expected:
        return
    raise Exception(
        f'this split sells {_format(sold, smallest_unit(selling_split))} '
        f'{currency} valued at '
        f'{_format(stated, base_unit)} {BASE_CURRENCY}, but cost basis {basis_guid} cost '
        f'{exact_text(basis_cost)} {BASE_CURRENCY} per {currency}, i.e. '
        f'{_format(expected, base_unit)} {BASE_CURRENCY} — value what is sold at the '
        f'basis it picks, so the {BASE_CURRENCY} the sale fetched and the '
        f'residual gain or loss stand apart')


def cost_basis_users(book, record) -> List[str]:
    """Descriptions of the transactions measured against this record's cost
    basis, or [] when it has none or nothing has picked it.

    Unposting destroys the posting transaction, and with it the split that *is*
    the cost basis. Anything already measured against it would then name a guid
    the book no longer holds, and re-posting mints a new split with the whole
    amount available again — so a sale of 40 of 100 USD silently becomes 100
    USD available, currency the book no longer has.
    """
    posting_txn = record.GetPostedTxn()
    posted_account = record.GetPostedAcc()
    if posting_txn is None or posted_account is None:
        return []
    posted_name = get_account_full_name(posted_account)

    basis = None
    for split in posting_txn.GetSplitList():
        if get_account_full_name(split.GetAccount()) == posted_name:
            basis = split
            break
    if basis is None or not establishes_cost_basis(basis):
        return []

    guid = split_guid(basis)
    users = []
    for split in iter_splits(book):
        if cost_basis_guid_of(split) != guid:
            continue
        transaction = split.GetParent()
        if transaction is None:
            continue
        label = transaction.GetDescription() or '(no description)'
        date = transaction.GetDate().strftime('%Y-%m-%d')
        users.append(f'{date} {label!r} '
                     f'({_format(abs(_fraction(split.GetAmount())), smallest_unit(split))} '
                     f'{split_commodity(split)})')
    return users


def transactions_measuring_against(book, transaction) -> List[str]:
    """Descriptions of what measures against any cost basis this transaction
    establishes — what would be orphaned if it were deleted."""
    basis_guids = {split_guid(split) for split in transaction.GetSplitList()
                   if establishes_cost_basis(split)}
    if not basis_guids:
        return []

    users = []
    for split in iter_splits(book):
        if cost_basis_guid_of(split) not in basis_guids:
            continue
        parent = split.GetParent()
        if parent is None or parent.GetGUID().to_string() == transaction.GetGUID().to_string():
            continue
        label = parent.GetDescription() or '(no description)'
        users.append(f"{parent.GetDate().strftime('%Y-%m-%d')} {label!r} "
                     f'({_format(abs(_fraction(split.GetAmount())), smallest_unit(split))} '
                     f'{split_commodity(split)})')
    return users


def require_no_cost_basis_dependents(book, transaction, label: str) -> None:
    """Refuse to delete a transaction whose cost basis something measures against.

    Deleting it destroys the split the basis lives on, leaving those
    transactions naming a guid the book no longer holds — the export then fails
    to re-import, and nothing gives them their currency back. The mirror of the
    unpost guard, for the other way a basis can be destroyed.
    """
    users = transactions_measuring_against(book, transaction)
    if not users:
        return
    listed = '; '.join(sorted(users))
    raise ValueError(
        f'{label} cannot be deleted: it establishes a cost basis that '
        f'{len(users)} transaction(s) measure against — {listed}. Deleting it '
        f'would leave them naming a split the book no longer holds. Delete '
        f'those first.')


def require_cost_basis_unused(book, record, kind: str, ident: str) -> None:
    """Refuse to unpost a record whose cost basis something is measured against."""
    users = cost_basis_users(book, record)
    if not users:
        return
    listed = '; '.join(sorted(users))
    raise Exception(
        f'{kind} {ident!r} cannot be unposted: its cost basis is what '
        f'{len(users)} transaction(s) measure against — {listed}. Unposting '
        f'destroys the split that basis lives on, and re-posting creates a new '
        f'one with the whole amount available again, so those transactions '
        f'would be measured against a cost basis the book no longer has. '
        f'Remove or re-point them first.')


def verify_cost_bases(book) -> Dict:
    """Check every cost basis against the ledger, and report what disagrees.

    Returns `{'checked': n, 'findings': [...]}` — how many bases were examined,
    which is the whole book regardless of what a listing filters to, and one
    entry per basis with something wrong with it.

    A cost is derived from the ledger, so it is only ever as right as the
    ledger is consistent. Two things can be checked, and each can fail:

    * **A basis balance is not above what its basis brought in, nor below
      zero.**
      Two exact comparisons against figures the book holds — zero, and the
      amount the split brought in — not a tolerance or a window. Balances move
      only by what a sale takes and what one gives back, so a balance above
      what arrived is currency offered that never did, and one below zero is a
      sale no ledger records.
    * **A stored `cost_basis_cost` agrees with the transaction, and parses.**
      Nothing writes one where the transaction states a cost, so finding both
      means a copy has drifted — and since the transaction is what is
      believed, the copy would otherwise sit unread and unnoticed.

    Both are exact questions about figures the ledger states. Two inexact ones
    were tried here and removed, because a check that reports correct books is
    worse than no check:

    * a split's `share_price` against its value. GnuCash stores no rate —
      `xaccSplitGetSharePrice` computes value over amount on demand — so the
      comparison was one number against itself and could not fail.
      (`SetSharePrice(1.405)` on 45.00 USD writes value 63.23 and reads the
      rate back as 6323/4500; set the value to 63.00 and it reads 6300/4500.)
    * whether a transaction's base-currency splits agree about its rate. Rates
      run **forward only**. A file states 1.405, 45.00 USD becomes 63.23 CAD,
      and the effective rate the ledger then carries is 6323/4500 — 1.405 plus
      1/9000. That is the rounding working, not a discrepancy, and asking
      whether 6323/4500 maps back to 1.405 is a question with no answer: many
      rates produce the same rounded figure, and the one the file stated is
      not among the things the ledger keeps. Every criterion tried in that
      backwards direction reported correct books — the splits' ratios against
      each other (every taxed foreign invoice), each against the pooled rate
      (a bill of 1.819 CAD for 1.30 USD beside 5.00 for 3.57, which 1.3992
      produces exactly), and the windows the rounding leaves. The pooled rate
      is still what a cost is derived from, because it is order-independent;
      it is simply not evidence about itself.

    Read-only, and reported rather than raised: this answers "is what the book
    says internally consistent", which is a question to ask of a book already
    written, not a reason to refuse to read it.
    """
    checked = 0
    found: List[Dict] = []
    for split in iter_splits(book):
        # Every split is checked and every finding kept: a book is verified to
        # learn everything wrong with it, so stopping at the first — or letting
        # one split's failure end the pass — would hide the rest behind it.
        try:
            if not establishes_cost_basis(split):
                continue
        except Exception:
            # Deciding whether this is a basis at all is what failed, so
            # nothing further about it can be said. It counts as one basis
            # examined, once.
            checked += 1
            found.append({
                'guid': split_guid(split),
                'account': get_account_full_name(split.GetAccount()),
                'date': '', 'description': '', 'tx_guid': '',
                'problems': ['this basis could not be read at all'],
                'traceback': traceback.format_exc(),
            })
            continue

        checked += 1
        try:
            row = cost_trace(split)
        except Exception:
            found.append({
                'guid': split_guid(split),
                'account': get_account_full_name(split.GetAccount()),
                'date': '', 'description': '', 'tx_guid': '',
                'problems': ['this basis could not be read at all'],
                'traceback': traceback.format_exc(),
            })
            continue

        problems = []

        if row['malformed_balance']:
            # Reported rather than silently read as an empty basis, which is
            # what a balance that will not parse otherwise becomes: the
            # listing would say nothing is left, about a split whose balance
            # something wrote and something has since broken. A stored *cost*
            # that will not parse has always been reported; this is the same
            # fault on the other key.
            problems.append(
                f"{COST_BASIS_BALANCE_KEY} reads "
                f"{row['malformed_balance']!r}, which is not a number — nothing "
                f"can be sold against this basis until it is corrected, and "
                f"it reads as empty meanwhile")

        available = row['balance']
        if available is not None and (available < 0 or available > row['amount']):
            # Written exactly, not through the currency's smallest unit: the
            # figure is being reported *because* it is past one of those two
            # bounds, and rounding it to the cent is how "100.001 against
            # 100.00" became a message saying 100.00 against 100.00.
            problems.append(
                f"basis balance is "
                f"{_format(available, row['unit'])} {row['currency']} "
                f"against the {_format(row['amount'], row['unit'])} this "
                f"basis brought in — a balance can only fall by what a sale "
                f"takes and rise by what one gives back")

        if row['stored_error']:
            problems.append(
                f"{row['stored_error']}. The transaction says "
                f"{exact_text(row['derived'])} "
                f"{BASE_CURRENCY}/{row['currency']}, which is what is used"
                if row['derived'] is not None else row['stored_error'])
        elif (row['stored'] is not None and row['derived'] is not None
                and row['stored'] != row['derived']):
            problems.append(
                f"{COST_BASIS_COST_KEY} says {exact_text(row['stored'])} "
                f"{BASE_CURRENCY}/{row['currency']}, but the transaction says "
                f"{exact_text(row['derived'])} — the transaction is what is used")

        if problems:
            found.append({**row, 'problems': problems, 'traceback': None})

    return {'checked': checked, 'findings': found,
            'currency_totals': currency_totals_that_disagree(book)}


def currency_totals_that_disagree(book) -> List[Dict]:
    """Per currency: what its bases hold between them against what the ledger
    says arrived and was sold. One entry per currency where the two differ.

    The book-wide question, which no per-basis check can answer. Every basis
    can pass on its own — a balance between zero and what it brought in — while
    the currency does not add up: take 80.00 off one basis of a book holding
    200.00 and record no sale, and each basis is still within its own bounds
    while 80.00 USD is accounted for by nothing.

    The two sides are written by different mechanisms, which is what makes the
    comparison worth anything. What the bases hold is a KVP on each split; what
    arrived and what was sold are the transactions themselves — a basis's own
    amount, and the amount of every split naming one. Neither is derived from
    the other, so they can disagree.

    A basis with no balance recorded is left out of both sides. Nothing knows
    how much of it is unsold — that is what `none recorded` means — so counting
    what it brought in would report every such book as short by exactly that.
    Nothing can be sold against one either, so no sale is dropped with it.

    Reported rather than refused: this says a book needs looking at, and the
    listing beside it is the thing to look at. What put the two out of step is
    not something the book records.
    """
    held: Dict[str, Fraction] = {}
    arrived: Dict[str, Fraction] = {}
    sold: Dict[str, Fraction] = {}
    units: Dict[str, int] = {}
    sales = []
    counted: set = set()
    for split in iter_splits(book):
        currency = split_commodity(split)
        if not currency or currency == BASE_CURRENCY:
            continue
        amount = abs(_fraction(split.GetAmount()))
        named = cost_basis_guid_of(split)
        if named:
            sales.append((currency, amount, named))
            continue
        try:
            if not establishes_cost_basis(split):
                continue
            balance = cost_basis_balance_of(split)
        except Exception:
            # A basis whose own figures cannot be read is reported by the
            # per-basis pass with its traceback. Counting it here would put
            # the totals out by whatever it holds and blame the currency.
            continue
        if balance is None:
            continue
        held[currency] = held.get(currency, Fraction(0)) + balance
        arrived[currency] = arrived.get(currency, Fraction(0)) + amount
        units.setdefault(currency, smallest_unit(split))
        counted.add(str(split_guid(split)).replace('-', '').lower())

    # A sale counts only where the basis it names is one of the bases counted
    # above. Counted unconditionally, a sale against a basis left out of the
    # other side — one with no balance recorded, or one whose figures do not
    # read — took the ledger figure down while nothing took the basis's own
    # arrival down with it, and the run warned that currency was accounted for
    # by no basis on a book that is perfectly consistent. Both sides skip the
    # same bases or neither does.
    for currency, amount, named in sales:
        if named in counted:
            sold[currency] = sold.get(currency, Fraction(0)) + amount

    out: List[Dict] = []
    for currency in sorted(set(held) | set(arrived)):
        ledger = (arrived.get(currency, Fraction(0))
                  - sold.get(currency, Fraction(0)))
        between_them = held.get(currency, Fraction(0))
        if between_them == ledger:
            continue
        out.append({
            'currency': currency,
            'unit': units.get(currency, 100),
            'held': between_them,
            'arrived': arrived.get(currency, Fraction(0)),
            'sold': sold.get(currency, Fraction(0)),
            'ledger': ledger,
            'difference': ledger - between_them,
        })
    return out


def cost_trace(split) -> Dict:
    """Every figure this split's cost is computed from, and what came out.

    The record a reader needs to judge a disagreement: the two guids to open
    the book at, the amount and value the ledger carries, each factor of the
    derivation, every rate the transaction's base-currency splits imply, and
    both answers — the one derived and the one stored — with which is used.
    """
    transaction = split.GetParent()
    currency = transaction.GetCurrency() if transaction is not None else None
    tx_currency = transaction_currency(transaction) if transaction is not None else ''
    tx_unit = currency.get_fraction() if currency is not None else 100
    amount = abs(_fraction(split.GetAmount()))
    value = abs(_fraction(split.GetValue()))

    # The factors the derivation actually multiplied, in order, and only
    # those. A transaction already in the book's currency needs no second
    # factor — its splits are valued in CAD, so `value / amount` is the whole
    # cost — and reporting a 1 there would be stating something the code never
    # computed. Where a second factor is needed and missing, it is listed as
    # missing rather than left out, because that is why no cost came of it.
    tx_rate = (_base_per_unit_of(transaction, tx_currency)
               if transaction is not None and tx_currency != BASE_CURRENCY
               else None)
    factors = []
    if amount != 0:
        factors.append(('value / amount', value / amount))
        if tx_currency != BASE_CURRENCY:
            factors.append((f'{BASE_CURRENCY} per {tx_currency}', tx_rate))
    derived = derived_cost_of(split)
    # `cost_of` never reaches a stored cost on a split the transaction prices,
    # so a malformed one there is inert to everything else — but this reads it
    # deliberately, and a basis that is otherwise entirely readable must not
    # become "could not be read at all" over a line nothing uses. What went
    # wrong is carried as a finding instead, on a row that still has the
    # derived cost, the amounts and the rate in it.
    stored, stored_error = None, ''
    try:
        stored = stated_cost_of(split)
    except Exception as exc:
        stored_error = str(exc)
    return {
        'guid': split_guid(split),
        'tx_guid': (transaction.GetGUID().to_string().replace('-', '').lower()
                    if transaction is not None else ''),
        'account': get_account_full_name(split.GetAccount()),
        'date': (transaction.GetDate().strftime('%Y-%m-%d')
                 if transaction is not None else ''),
        'description': (transaction.GetDescription()
                        if transaction is not None else ''),
        'currency': split_commodity(split),
        'unit': smallest_unit(split),
        'tx_currency': tx_currency,
        'tx_unit': tx_unit,
        'amount': amount,
        'value': value,
        'factors': factors,
        'tx_rate': tx_rate,
        'base_figures': _base_figures_of(transaction, tx_currency),
        'balance': cost_basis_balance_of(split),
        'malformed_balance': malformed_cost_basis_balance_of(split),
        'derived': derived,
        'stored': stored,
        'stored_error': stored_error,
        'used': derived if derived is not None else stored,
    }


def _base_figures_of(transaction, tx_currency: str) -> List:
    """Each base-currency split's own figures.

    `(account, its base-currency amount, the foreign value it is worth, the
    unit it is held to, the unit its currency has)` per split.

    Shown when a basis is reported, because the cost is derived from these and
    a reader looking at a finding wants to see what it came from. Not checked
    against each other: a rate runs forward into a figure, and the figure does
    not run back into the rate. 1.405 applied to 45.00 USD gives 63.23 CAD,
    whose effective rate is 6323/4500 — reading that back and asking whether
    it "is" 1.405 has no answer, since many rates give 63.23 and the stated
    one is not kept. Each of these figures is rounded to its own unit that
    way, so a taxed invoice's income and tax lines differ in the last digits
    though one rate produced both.

    Empty for a transaction in the book's own currency, which converts nothing.
    """
    if transaction is None or tx_currency == BASE_CURRENCY:
        return []
    figures = []
    for other in transaction.GetSplitList():
        if split_commodity(other) != BASE_CURRENCY:
            continue
        base_amount = abs(_fraction(other.GetAmount()))
        base_value = abs(_fraction(other.GetValue()))
        if base_amount == 0 or base_value == 0:
            continue
        # The account's own unit, not its currency's: an account can be kept
        # finer than the cent — fuel at 1.819 a litre — and its splits are
        # written at that unit, so printing one at the cent shows a figure the
        # ledger does not hold.
        account = other.GetAccount()
        unit = (account.GetCommoditySCU() if account is not None
                else smallest_unit(other))
        figures.append((get_account_full_name(other.GetAccount()),
                        base_amount, base_value, unit, smallest_unit(other)))
    return figures


def cost_bases(book) -> List[Dict]:
    """Every foreign-currency cost basis in the book with its cost and
    basis balance — what `fx-balances` lists.

    Listed as the book holds them, in no imposed order: a sale names the basis
    it measures against, so no basis is ahead of another and sorting by date
    would suggest an order of consumption that does not exist.

    A basis this cannot read — a `cost_basis_cost` that is not a cost, most
    likely written by hand — is listed as unreadable rather than ending the
    listing. One such split used to take the whole command down with it, so a
    book could not be inspected at exactly the moment there was something in
    it to inspect. `verify_cost_bases` says why, with the traceback.
    """
    rows: List[Dict] = []
    for split in iter_splits(book):
        try:
            if not establishes_cost_basis(split):
                continue
            row = {
                'currency': split_commodity(split),
                # The listing is rendered after the book is closed, so each row
                # carries how finely its currency divides rather than the
                # commodity it would have to read that from.
                'unit': smallest_unit(split),
                'cost': cost_of(split),
                'acquired': abs(_fraction(split.GetAmount())),
                'balance': cost_basis_balance_of(split),
                'malformed': False,
            }
        except Exception:
            row = {
                'currency': split_commodity(split),
                # From the commodity like any other row, not a hundredth
                # assumed: the amount is still printed, and a yen basis given
                # two invented decimals is wrong however unreadable the rest
                # of it is.
                'unit': smallest_unit(split),
                'cost': None,
                'acquired': abs(_fraction(split.GetAmount())),
                'balance': None,
                'malformed': True,
            }
        transaction = split.GetParent()
        rows.append({
            'guid': split_guid(split),
            'date': (transaction.GetDate().strftime('%Y-%m-%d')
                     if transaction is not None else ''),
            'description': (transaction.GetDescription()
                            if transaction is not None else ''),
            'account': get_account_full_name(split.GetAccount()),
            **row,
        })
    return rows
